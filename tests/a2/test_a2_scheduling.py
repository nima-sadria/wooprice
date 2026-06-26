"""
A2.8 — Scheduling Engine tests.

Covers:
  - Schedule creation: fields, initial state, max_attempts
  - Due schedule detection: SCHEDULED+due returns, PAUSED excluded, CANCELLED excluded
  - Lease acquisition: atomic claim, token mismatch fails, expired lease reclaim,
    heartbeat extends lease
  - Run state transitions: PENDING → CLAIMED on claim
  - Cancellation: schedule → CANCELLED, PENDING runs → CANCELLED
  - Retry/backoff: next_run_at set after failure, attempt_count incremented
  - Max attempts: schedule → FAILED when attempt_count >= max_attempts
  - Dispatch: calls A2.7 ExecutionService, never bypasses A2.7, records execution_id,
    records error on failure
  - Stale lease detection: find_expired_leases returns past-expired leases
  - State machine: invalid transitions raise, terminal states immutable
  - Migration a2_007: revision/down_revision, upgrade/downgrade, lineage from a2_006
  - Isolation: no WooCommerce, no Apply, no UI, no external cron/daemon, no A2.9 imports
"""
import importlib.util
import os

os.environ.setdefault("A2_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("NEXTCLOUD_URL", "http://example.invalid")
os.environ.setdefault("NEXTCLOUD_USER", "x")
os.environ.setdefault("NEXTCLOUD_PASSWORD", "x")
os.environ.setdefault("NEXTCLOUD_FILE_PATH", "/x.xlsx")
os.environ.setdefault("WC_URL", "http://example.invalid")
os.environ.setdefault("WC_KEY", "x")
os.environ.setdefault("WC_SECRET", "x")

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.a2.database import A2Base

# Register all models with A2Base metadata (order: A2.1 → A2.8)
import app.a2.models.canonical_product    # noqa: F401
import app.a2.models.source               # noqa: F401
import app.a2.models.snapshot             # noqa: F401
import app.a2.models.provenance           # noqa: F401
import app.a2.models.checkpoint           # noqa: F401
import app.a2.models.pricing_rule          # noqa: F401
import app.a2.models.pricing_rule_version  # noqa: F401
import app.a2.models.price_proposal        # noqa: F401
import app.a2.models.safety               # noqa: F401
import app.a2.models.change_set           # noqa: F401
import app.a2.models.dry_run              # noqa: F401
import app.a2.models.execution            # noqa: F401
import app.a2.models.schedule             # noqa: F401

from app.a2.models.schedule import Schedule, ScheduleLease, ScheduleRun
from app.a2.repositories.scheduler_repository import (
    InvalidScheduleStateTransitionError,
    LeaseAlreadyHeldError,
    LeaseTokenMismatchError,
    SchedulerRepository,
)
from app.a2.services.change_set_service import compute_change_set_digest
from app.a2.services.execution_service import (
    DummyExecutionAdapter,
    ExecutionItemInput,
    ExecutionService,
)
from app.a2.services.scheduler_service import SchedulerService


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    A2Base.metadata.create_all(eng)
    yield eng
    A2Base.metadata.drop_all(eng)


@pytest.fixture()
def db(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def repo(db):
    return SchedulerRepository(db)


@pytest.fixture()
def scheduler(db):
    return SchedulerService(db)


@pytest.fixture()
def execution_svc(db):
    return ExecutionService(db)


# ── Helpers ───────────────────────────────────────────────────────────────────


_CHANNEL = "WC"
_SCOPE = "all"
_SNAPSHOT = "snap-001"
_CS_ID = "cs-sched-001"
_REV_ID = "rev-sched-001"
_CONF_ID = "conf-sched-001"
_DR_ID = "dr-sched-001"


def _item(
    product_id: str = "SKU-001",
    proposal_id: str = "prop-001",
    proposal_hash: str = "a" * 64,
    safety_result_id: str = "safe-001",
    rule_version_id: str = "rv-001",
    proposed_price: Decimal = Decimal("9.99"),
) -> ExecutionItemInput:
    return ExecutionItemInput(
        product_id=product_id,
        proposal_id=proposal_id,
        proposal_hash=proposal_hash,
        safety_result_id=safety_result_id,
        rule_version_id=rule_version_id,
        proposed_price=proposed_price,
    )


def _digest(items=None, channel=_CHANNEL, scope=_SCOPE, snapshot=_SNAPSHOT) -> str:
    if items is None:
        items = [_item()]
    return compute_change_set_digest(items, channel, scope, snapshot)  # type: ignore[arg-type]


def _future() -> datetime:
    return datetime.now(tz=timezone.utc) + timedelta(hours=1)


def _past() -> datetime:
    return datetime.now(tz=timezone.utc) - timedelta(hours=1)


def _make_schedule(
    scheduler: SchedulerService,
    *,
    dry_run_result: str = "PASS",
    dry_run_digest_verified: bool = True,
    scheduled_at: datetime | None = None,
    max_attempts: int = 3,
    items=None,
    change_set_digest: str | None = None,
    confirmation_digest: str | None = None,
) -> Schedule:
    if items is None:
        items = [_item()]
    if change_set_digest is None:
        change_set_digest = _digest(items)
    if confirmation_digest is None:
        confirmation_digest = change_set_digest
    if scheduled_at is None:
        scheduled_at = _past()
    return scheduler.create_schedule(
        change_set_id=_CS_ID,
        change_set_revision_id=_REV_ID,
        change_set_digest=change_set_digest,
        confirmation_id=_CONF_ID,
        confirmation_digest=confirmation_digest,
        dry_run_id=_DR_ID,
        dry_run_result=dry_run_result,
        dry_run_digest_verified=dry_run_digest_verified,
        destination_channel=_CHANNEL,
        scope=_SCOPE,
        source_snapshot_id=_SNAPSHOT,
        scheduled_at=scheduled_at,
        max_attempts=max_attempts,
    )


# ── TestScheduleCreation ──────────────────────────────────────────────────────


class TestScheduleCreation:
    def test_create_schedule(self, scheduler):
        sched = _make_schedule(scheduler)
        assert sched.id is not None
        assert sched.status == "SCHEDULED"
        assert sched.change_set_id == _CS_ID
        assert sched.dry_run_result == "PASS"
        assert sched.dry_run_digest_verified is True
        assert sched.max_attempts == 3
        assert sched.attempt_count == 0
        assert sched.next_run_at is None


# ── TestDueScheduleDetection ──────────────────────────────────────────────────


class TestDueScheduleDetection:
    def test_due_schedule_detected(self, scheduler):
        sched = _make_schedule(scheduler, scheduled_at=_past())
        due = scheduler.list_due_schedules()
        assert any(s.id == sched.id for s in due)

    def test_paused_schedule_not_due(self, scheduler, repo):
        sched = _make_schedule(scheduler, scheduled_at=_past())
        repo.transition_schedule(sched.id, "PAUSED")
        due = scheduler.list_due_schedules()
        assert not any(s.id == sched.id for s in due)

    def test_cancelled_schedule_not_due(self, scheduler):
        sched = _make_schedule(scheduler, scheduled_at=_past())
        scheduler.cancel_schedule(sched.id)
        due = scheduler.list_due_schedules()
        assert not any(s.id == sched.id for s in due)

    def test_future_schedule_not_due(self, scheduler):
        sched = _make_schedule(scheduler, scheduled_at=_future())
        due = scheduler.list_due_schedules()
        assert not any(s.id == sched.id for s in due)

    def test_next_run_at_overrides_scheduled_at(self, scheduler, repo):
        sched = _make_schedule(scheduler, scheduled_at=_future())
        # Manually set next_run_at to the past (retry scenario)
        sched.next_run_at = _past()
        repo._db.flush()
        due = scheduler.list_due_schedules()
        assert any(s.id == sched.id for s in due)


# ── TestLeaseAcquisition ──────────────────────────────────────────────────────


class TestLeaseAcquisition:
    def test_atomic_lease_acquisition(self, scheduler):
        sched = _make_schedule(scheduler)
        run = scheduler.create_run(sched.id)
        lease = scheduler.claim_run(run.id, lease_owner="worker-1")
        assert lease is not None
        assert lease.lease_owner == "worker-1"
        assert lease.lease_token is not None
        # Second claim on the same run must fail
        with pytest.raises(LeaseAlreadyHeldError):
            scheduler.claim_run(run.id, lease_owner="worker-2")

    def test_lease_token_mismatch_fails(self, scheduler):
        sched = _make_schedule(scheduler)
        run = scheduler.create_run(sched.id)
        scheduler.claim_run(run.id, lease_owner="worker-1")
        with pytest.raises(LeaseTokenMismatchError):
            scheduler.heartbeat(run.id, lease_token="wrong-token-value")

    def test_expired_lease_reclaim(self, scheduler, db):
        sched = _make_schedule(scheduler)
        run = scheduler.create_run(sched.id)
        lease = scheduler.claim_run(run.id, lease_owner="worker-1")
        old_token = lease.lease_token
        # Expire the lease by backdating
        lease_row = db.query(ScheduleLease).filter(ScheduleLease.run_id == run.id).first()
        lease_row.lease_expires_at = datetime.now(tz=timezone.utc) - timedelta(seconds=1)
        db.flush()
        # Worker-2 reclaims the expired lease
        new_lease = scheduler.claim_run(run.id, lease_owner="worker-2")
        assert new_lease.lease_owner == "worker-2"
        assert new_lease.lease_token != old_token
        assert new_lease.lease_expires_at > datetime.now(tz=timezone.utc)

    def test_heartbeat_extends_lease(self, scheduler):
        sched = _make_schedule(scheduler)
        run = scheduler.create_run(sched.id)
        lease = scheduler.claim_run(run.id, lease_owner="worker-1", lease_duration_seconds=60)
        original_expires = lease.lease_expires_at
        updated = scheduler.heartbeat(
            run.id, lease_token=lease.lease_token, lease_duration_seconds=300
        )
        assert updated.lease_expires_at > original_expires
        assert updated.heartbeat_at >= original_expires - timedelta(seconds=60)


# ── TestRunStateTransitions ───────────────────────────────────────────────────


class TestRunStateTransitions:
    def test_run_claim_state_transition(self, scheduler, db):
        sched = _make_schedule(scheduler)
        run = scheduler.create_run(sched.id)
        assert run.status == "PENDING"
        scheduler.claim_run(run.id, lease_owner="worker-1")
        fresh_run = db.get(ScheduleRun, run.id)
        assert fresh_run.status == "CLAIMED"


# ── TestCancellation ──────────────────────────────────────────────────────────


class TestCancellation:
    def test_schedule_cancellation(self, scheduler, db):
        sched = _make_schedule(scheduler)
        scheduler.cancel_schedule(sched.id)
        fresh = db.get(Schedule, sched.id)
        assert fresh.status == "CANCELLED"

    def test_pending_run_cancellation(self, scheduler, db):
        sched = _make_schedule(scheduler)
        run = scheduler.create_run(sched.id)
        assert run.status == "PENDING"
        scheduler.cancel_schedule(sched.id)
        fresh_run = db.get(ScheduleRun, run.id)
        assert fresh_run.status == "CANCELLED"

    def test_cancel_does_not_modify_terminal_run(self, scheduler, db):
        sched = _make_schedule(scheduler)
        run = scheduler.create_run(sched.id)
        scheduler.claim_run(run.id, lease_owner="worker")
        # Manually transition run to SUCCEEDED (terminal)
        repo = SchedulerRepository(db)
        repo.transition_run(run.id, "DISPATCHED")
        repo.transition_run(run.id, "SUCCEEDED")
        # Cancelling the same schedule must not touch the already-SUCCEEDED run
        scheduler.cancel_schedule(sched.id)
        fresh_run = db.get(ScheduleRun, run.id)
        assert fresh_run.status == "SUCCEEDED"


# ── TestRetryBackoff ──────────────────────────────────────────────────────────


class TestRetryBackoff:
    def test_retry_backoff_calculation(self, scheduler, execution_svc, db):
        # BLOCK dry run → execution BLOCKED → dispatch FAILED → retry scheduled
        items = [_item()]
        sched = _make_schedule(
            scheduler, dry_run_result="BLOCK", dry_run_digest_verified=True,
            max_attempts=3, items=items,
        )
        run = scheduler.create_run(sched.id)
        lease = scheduler.claim_run(run.id, lease_owner="worker-1")
        scheduler.dispatch(
            run.id,
            lease_token=lease.lease_token,
            execution_service=execution_svc,
            adapter=DummyExecutionAdapter(),
            items=items,
        )
        fresh = db.get(Schedule, sched.id)
        # Schedule should still be SCHEDULED (retry pending) with next_run_at set
        assert fresh.status == "SCHEDULED"
        assert fresh.next_run_at is not None
        assert fresh.next_run_at > datetime.now(tz=timezone.utc)
        assert fresh.attempt_count == 1

    def test_max_attempts_failure(self, scheduler, execution_svc, db):
        # max_attempts=1 → first failure immediately fails the schedule
        items = [_item()]
        sched = _make_schedule(
            scheduler, dry_run_result="BLOCK", dry_run_digest_verified=True,
            max_attempts=1, items=items,
        )
        run = scheduler.create_run(sched.id)
        lease = scheduler.claim_run(run.id, lease_owner="worker-1")
        scheduler.dispatch(
            run.id,
            lease_token=lease.lease_token,
            execution_service=execution_svc,
            adapter=DummyExecutionAdapter(),
            items=items,
        )
        fresh = db.get(Schedule, sched.id)
        assert fresh.status == "FAILED"


# ── TestDispatch ──────────────────────────────────────────────────────────────


class TestDispatch:
    def test_dispatch_calls_execution_service(self, scheduler, execution_svc, db):
        # Dispatch with valid inputs → execution is called and run.execution_id is set
        items = [_item()]
        sched = _make_schedule(scheduler, items=items)
        run = scheduler.create_run(sched.id)
        lease = scheduler.claim_run(run.id, lease_owner="worker-1")
        result = scheduler.dispatch(
            run.id,
            lease_token=lease.lease_token,
            execution_service=execution_svc,
            adapter=DummyExecutionAdapter(),
            items=items,
        )
        # execution_id is set — proves execution_service.execute() was called
        assert result.execution_id is not None
        assert result.status == "SUCCEEDED"

    def test_dispatch_never_bypasses_a27(self, scheduler, execution_svc, db):
        # BLOCK dry run → A2.7 validates and returns BLOCKED → dispatch records FAILED
        # If scheduling bypassed A2.7, this would succeed — the FAILED proves A2.7 ran
        items = [_item()]
        sched = _make_schedule(
            scheduler, dry_run_result="BLOCK", items=items, max_attempts=3
        )
        run = scheduler.create_run(sched.id)
        lease = scheduler.claim_run(run.id, lease_owner="worker-1")
        result = scheduler.dispatch(
            run.id,
            lease_token=lease.lease_token,
            execution_service=execution_svc,
            adapter=DummyExecutionAdapter(),
            items=items,
        )
        # A2.7 blocked the execution — scheduling did not bypass it
        assert result.status == "FAILED"

    def test_dispatch_records_execution_id(self, scheduler, execution_svc, db):
        items = [_item()]
        sched = _make_schedule(scheduler, items=items)
        run = scheduler.create_run(sched.id)
        lease = scheduler.claim_run(run.id, lease_owner="worker-1")
        result = scheduler.dispatch(
            run.id,
            lease_token=lease.lease_token,
            execution_service=execution_svc,
            adapter=DummyExecutionAdapter(),
            items=items,
        )
        fresh_run = db.get(ScheduleRun, result.id)
        assert fresh_run.execution_id is not None
        assert len(fresh_run.execution_id) == 36  # UUID format

    def test_dispatch_failure_records_error(self, scheduler, execution_svc, db):
        # Use BLOCK dry run to force execution failure
        items = [_item()]
        sched = _make_schedule(
            scheduler, dry_run_result="BLOCK", items=items, max_attempts=3
        )
        run = scheduler.create_run(sched.id)
        lease = scheduler.claim_run(run.id, lease_owner="worker-1")
        result = scheduler.dispatch(
            run.id,
            lease_token=lease.lease_token,
            execution_service=execution_svc,
            adapter=DummyExecutionAdapter(),
            items=items,
        )
        fresh_run = db.get(ScheduleRun, result.id)
        assert fresh_run.error_message is not None
        assert len(fresh_run.error_message) > 0


# ── TestStaleLeaseDetection ───────────────────────────────────────────────────


class TestStaleLeaseDetection:
    def test_stale_lease_detected(self, scheduler, repo, db):
        sched = _make_schedule(scheduler)
        run = scheduler.create_run(sched.id)
        lease = scheduler.claim_run(run.id, lease_owner="worker-1")
        # Backdate lease expiry to the past
        lease_row = db.query(ScheduleLease).filter(ScheduleLease.run_id == run.id).first()
        lease_row.lease_expires_at = datetime.now(tz=timezone.utc) - timedelta(seconds=1)
        db.flush()
        expired = repo.find_expired_leases()
        assert any(le.run_id == run.id for le in expired)

    def test_fresh_lease_not_stale(self, scheduler, repo):
        sched = _make_schedule(scheduler)
        run = scheduler.create_run(sched.id)
        scheduler.claim_run(run.id, lease_owner="worker-1", lease_duration_seconds=300)
        expired = repo.find_expired_leases()
        assert not any(le.run_id == run.id for le in expired)

    def test_expire_stale_leases_transitions_runs(self, scheduler, db):
        sched = _make_schedule(scheduler)
        run = scheduler.create_run(sched.id)
        lease = scheduler.claim_run(run.id, lease_owner="worker-1")
        # Backdate lease
        lease_row = db.query(ScheduleLease).filter(ScheduleLease.run_id == run.id).first()
        lease_row.lease_expires_at = datetime.now(tz=timezone.utc) - timedelta(seconds=1)
        db.flush()
        expired_runs = scheduler.expire_stale_leases()
        assert any(r.id == run.id for r in expired_runs)
        fresh_run = db.get(ScheduleRun, run.id)
        assert fresh_run.status == "EXPIRED"


# ── TestStateMachine ──────────────────────────────────────────────────────────


class TestStateMachine:
    def test_invalid_schedule_transition_raises(self, scheduler, repo):
        sched = _make_schedule(scheduler)
        with pytest.raises(InvalidScheduleStateTransitionError):
            repo.transition_schedule(sched.id, "SUCCEEDED")  # not a valid schedule state

    def test_invalid_run_transition_raises(self, scheduler, repo):
        sched = _make_schedule(scheduler)
        run = scheduler.create_run(sched.id)
        with pytest.raises(InvalidScheduleStateTransitionError):
            repo.transition_run(run.id, "SUCCEEDED")  # PENDING → SUCCEEDED not allowed

    def test_terminal_schedule_states_immutable(self, scheduler, repo):
        sched = _make_schedule(scheduler)
        repo.transition_schedule(sched.id, "CANCELLED")
        with pytest.raises(InvalidScheduleStateTransitionError):
            repo.transition_schedule(sched.id, "SCHEDULED")

    def test_terminal_run_states_immutable(self, scheduler, repo):
        sched = _make_schedule(scheduler)
        run = scheduler.create_run(sched.id)
        scheduler.claim_run(run.id, lease_owner="worker")
        repo.transition_run(run.id, "DISPATCHED")
        repo.transition_run(run.id, "SUCCEEDED")
        with pytest.raises(InvalidScheduleStateTransitionError):
            repo.transition_run(run.id, "FAILED")

    def test_valid_run_transition_sequence(self, scheduler, repo):
        sched = _make_schedule(scheduler)
        run = scheduler.create_run(sched.id)
        scheduler.claim_run(run.id, lease_owner="worker")
        repo.transition_run(run.id, "DISPATCHED")
        repo.transition_run(run.id, "SUCCEEDED")
        assert repo.get_run(run.id).status == "SUCCEEDED"


# ── TestMigration ─────────────────────────────────────────────────────────────


class TestMigration:
    def test_a2_007_revision_and_down_revision(self):
        from alembic_a2.versions.a2_007_scheduling_engine import down_revision, revision
        assert revision == "a2_007"
        assert down_revision == "a2_006"

    def test_upgrade_to_head_creates_scheduling_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_007_up.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "head")
        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()
        assert "a2_schedules" in tables
        assert "a2_schedule_runs" in tables
        assert "a2_schedule_leases" in tables

    def test_downgrade_from_a2_007_removes_scheduling_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_007_down.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "head")
            command.downgrade(cfg, "a2_006")
        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()
        assert "a2_schedules" not in tables
        assert "a2_schedule_runs" not in tables
        assert "a2_schedule_leases" not in tables

    def test_a2_006_tables_survive_downgrade_from_a2_007(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_007_compat.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "head")
            command.downgrade(cfg, "a2_006")
        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()
        assert "a2_executions" in tables
        assert "a2_execution_items" in tables

    def test_a2_007_adds_exactly_three_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_007_count.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "a2_006")
        eng = create_engine(db_url)
        tables_before = set(inspect(eng).get_table_names())
        eng.dispose()

        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "a2_007")
        eng = create_engine(db_url)
        tables_after = set(inspect(eng).get_table_names())
        eng.dispose()

        new_tables = tables_after - tables_before
        assert new_tables == {"a2_schedules", "a2_schedule_runs", "a2_schedule_leases"}


# ── TestIsolation ─────────────────────────────────────────────────────────────


class TestIsolation:
    @staticmethod
    def _source(module_name: str) -> str:
        spec = importlib.util.find_spec(module_name)
        assert spec is not None and spec.origin is not None
        with open(spec.origin, encoding="utf-8") as f:
            return f.read()

    def _service_src(self) -> str:
        return self._source("app.a2.services.scheduler_service")

    def _model_src(self) -> str:
        return self._source("app.a2.models.schedule")

    def _repo_src(self) -> str:
        return self._source("app.a2.repositories.scheduler_repository")

    def test_no_woocommerce_imports(self):
        for src in [self._service_src(), self._model_src(), self._repo_src()]:
            for forbidden in ["import woocommerce", "from woocommerce", "wc_api", "wcapi"]:
                assert forbidden not in src.lower(), (
                    f"Found {forbidden!r} — real WooCommerce imports prohibited in A2.8"
                )

    def test_no_apply_imports(self):
        for src in [self._service_src(), self._model_src(), self._repo_src()]:
            for forbidden in ["apply_workflow", "workspace_apply", "ApplyWorkflow", "do_apply"]:
                assert forbidden not in src, (
                    f"Found {forbidden!r} — Apply Workflow must not be modified in A2.8"
                )

    def test_no_ui_imports(self):
        for src in [self._service_src(), self._model_src(), self._repo_src()]:
            for forbidden in ["from app.ui", "from app.frontend", "import React", "import Vue"]:
                assert forbidden not in src, (
                    f"Found {forbidden!r} — UI imports prohibited in A2.8"
                )

    def test_no_external_cron_or_background_daemon(self):
        for src in [self._service_src(), self._model_src(), self._repo_src()]:
            for forbidden in [
                "import schedule",
                "APScheduler",
                "import celery",
                "import rq",
                "import dramatiq",
                "import cron",
                "BackgroundScheduler",
                "threading.Thread",
                "asyncio.create_task",
            ]:
                assert forbidden not in src, (
                    f"Found {forbidden!r} — external cron/daemon prohibited in A2.8"
                )

    def test_no_a29_imports(self):
        for src in [self._service_src(), self._model_src(), self._repo_src()]:
            for forbidden in [
                "from app.a2.services.ai",
                "from app.a2.models.ai",
                "from ..services.ai",
                "from ..models.ai",
                "a2_9",
                "a2.9",
            ]:
                assert forbidden not in src, (
                    f"Found {forbidden!r} — A2.9 imports prohibited in A2.8"
                )
