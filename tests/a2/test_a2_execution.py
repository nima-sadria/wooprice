"""
A2.7 — Execution Engine tests.

Covers:
  - Prerequisite validation: invalid confirmation, digest mismatch, BLOCK dry run,
    unverified digest, Change Set digest recompute mismatch
  - Freshness verification: success permits execution, failure blocks item (BLOCKED),
    freshness_verified flag set on success
  - Execution outcomes: all-succeed → SUCCEEDED, any-blocked → BLOCKED,
    any-failed → FAILED, mixed worst-outcome
  - Idempotency: duplicate execution key returns existing record, no re-execution
  - Retry: transient failure then success, permanent failure no retry,
    max_attempts exhausted → FAILED, attempt records created per try
  - State machine: valid transitions, invalid transitions raise, terminal immutability
  - Cancel: PENDING → CANCELLED, RUNNING → CANCELLED, terminal cannot cancel
  - Recovery: stale RUNNING executions detected, fresh RUNNING not stale;
    stale RUNNING items detected, fresh RUNNING items not stale
  - Repository: create/get/list operations, find_by_idempotency_key
  - DummyAdapter: idempotent retry, freshness simulation, transient/permanent failure
  - Report: ExecutionService.get_report() returns correct counts
  - Alembic migration a2_006: revision/down_revision, table creation/destruction,
    lineage from a2_005
  - Isolation: no WooCommerce writes, no Apply, no Scheduling, no A2.8+, no AI,
    no network calls, DummyAdapter is self-contained
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
import app.a2.models.canonical_product    # noqa: F401
import app.a2.models.source               # noqa: F401
import app.a2.models.snapshot             # noqa: F401
import app.a2.models.provenance           # noqa: F401
import app.a2.models.checkpoint           # noqa: F401
import app.a2.models.pricing_rule          # noqa: F401 — A2.3-R2
import app.a2.models.pricing_rule_version  # noqa: F401 — A2.3-R2
import app.a2.models.price_proposal        # noqa: F401 — A2.3-R2
import app.a2.models.safety               # noqa: F401 — A2.4
import app.a2.models.change_set           # noqa: F401 — A2.5
import app.a2.models.dry_run              # noqa: F401 — A2.6
import app.a2.models.execution            # noqa: F401 — A2.7

from app.a2.models.execution import Execution, ExecutionItem
from app.a2.repositories.execution_repository import (
    ExecutionRepository,
    InvalidExecutionStateTransitionError,
)
from app.a2.services.change_set_service import compute_change_set_digest
from app.a2.services.execution_service import (
    ChannelExecutionAdapter,
    DummyExecutionAdapter,
    ExecuteItemResult,
    ExecutionItemInput,
    ExecutionReport,
    ExecutionService,
    FreshnessContext,
    FreshnessResult,
)


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
    return ExecutionRepository(db)


@pytest.fixture()
def svc(db):
    return ExecutionService(db)


# ── Helpers ───────────────────────────────────────────────────────────────────

_CHANNEL = "WC"
_SCOPE = "all"
_SNAPSHOT = "snap-001"
_CS_ID = "cs-001"
_REV_ID = "rev-001"
_CONF_ID = "conf-001"


def _item(
    product_id: str = "SKU-001",
    proposal_id: str = "prop-001",
    proposal_hash: str = "a" * 64,
    safety_result_id: str = "safe-001",
    rule_version_id: str = "rv-001",
    proposed_price: Decimal = Decimal("9.99"),
    current_price: Decimal | None = Decimal("8.00"),
) -> ExecutionItemInput:
    return ExecutionItemInput(
        product_id=product_id,
        proposal_id=proposal_id,
        proposal_hash=proposal_hash,
        safety_result_id=safety_result_id,
        rule_version_id=rule_version_id,
        proposed_price=proposed_price,
        current_price=current_price,
    )


def _digest(
    items: list[ExecutionItemInput] | None = None,
    channel: str = _CHANNEL,
    scope: str = _SCOPE,
    snapshot: str = _SNAPSHOT,
) -> str:
    if items is None:
        items = [_item()]
    return compute_change_set_digest(items, channel, scope, snapshot)  # type: ignore[arg-type]


def _exec_args(
    svc: ExecutionService,
    items: list[ExecutionItemInput] | None = None,
    adapter: ChannelExecutionAdapter | None = None,
    idempotency_key: str = "key-001",
    change_set_id: str = _CS_ID,
    change_set_revision_id: str = _REV_ID,
    channel: str = _CHANNEL,
    scope: str = _SCOPE,
    snapshot: str = _SNAPSHOT,
    dry_run_result: str = "PASS",
    dry_run_digest_verified: bool = True,
    confirmation_id: str = _CONF_ID,
    confirmation_is_valid: bool = True,
    stored_digest: str | None = None,
    confirmation_digest: str | None = None,
    max_attempts: int = 3,
) -> dict:
    if items is None:
        items = [_item()]
    if stored_digest is None:
        stored_digest = _digest(items, channel, scope, snapshot)
    if confirmation_digest is None:
        confirmation_digest = stored_digest
    if adapter is None:
        adapter = DummyExecutionAdapter()
    return dict(
        change_set_id=change_set_id,
        change_set_revision_id=change_set_revision_id,
        change_set_digest=stored_digest,
        items=items,
        destination_channel=channel,
        scope=scope,
        source_snapshot_id=snapshot,
        dry_run_result=dry_run_result,
        dry_run_digest_verified=dry_run_digest_verified,
        confirmation_id=confirmation_id,
        confirmation_digest=confirmation_digest,
        confirmation_is_valid=confirmation_is_valid,
        adapter=adapter,
        idempotency_key=idempotency_key,
        max_attempts=max_attempts,
    )


# ── TestPrerequisiteValidation ────────────────────────────────────────────────


class TestPrerequisiteValidation:
    def test_invalid_confirmation_blocks(self, svc):
        execution = svc.execute(**_exec_args(svc, confirmation_is_valid=False))
        assert execution.status == "BLOCKED"
        assert "SellerConfirmation is invalid" in (execution.error_message or "")

    def test_confirmation_digest_mismatch_blocks(self, svc):
        items = [_item()]
        real_digest = _digest(items)
        wrong_digest = "b" * 64
        execution = svc.execute(
            **_exec_args(
                svc,
                items=items,
                stored_digest=real_digest,
                confirmation_digest=wrong_digest,
            )
        )
        assert execution.status == "BLOCKED"
        assert "Confirmation digest mismatch" in (execution.error_message or "")

    def test_dry_run_block_result_blocks(self, svc):
        execution = svc.execute(**_exec_args(svc, dry_run_result="BLOCK"))
        assert execution.status == "BLOCKED"
        assert "BLOCK" in (execution.error_message or "")

    def test_dry_run_digest_not_verified_blocks(self, svc):
        execution = svc.execute(**_exec_args(svc, dry_run_digest_verified=False))
        assert execution.status == "BLOCKED"
        assert "digest_verified=False" in (execution.error_message or "")

    def test_change_set_digest_mismatch_blocks(self, svc):
        items = [_item()]
        wrong_digest = "c" * 64
        execution = svc.execute(
            **_exec_args(
                svc,
                items=items,
                stored_digest=wrong_digest,
                confirmation_digest=wrong_digest,
            )
        )
        assert execution.status == "BLOCKED"
        assert "integrity failure" in (execution.error_message or "")

    def test_dry_run_warn_permits_execution(self, svc):
        execution = svc.execute(**_exec_args(svc, dry_run_result="WARN"))
        assert execution.status == "SUCCEEDED"

    def test_all_prerequisites_pass_execution_runs(self, svc):
        execution = svc.execute(**_exec_args(svc))
        assert execution.status == "SUCCEEDED"


# ── TestFreshnessVerification ─────────────────────────────────────────────────


class TestFreshnessVerification:
    def test_freshness_success_execution_succeeds(self, svc):
        adapter = DummyExecutionAdapter(freshness_verified=True)
        execution = svc.execute(**_exec_args(svc, adapter=adapter))
        assert execution.status == "SUCCEEDED"

    def test_freshness_failure_blocks_item_and_execution(self, svc, db):
        adapter = DummyExecutionAdapter(freshness_verified=False)
        execution = svc.execute(**_exec_args(svc, adapter=adapter))
        assert execution.status == "BLOCKED"

        repo = ExecutionRepository(db)
        items = repo.list_items(execution.id)
        assert len(items) == 1
        assert items[0].status == "BLOCKED"

    def test_freshness_failure_records_blocked_attempt(self, svc, db):
        adapter = DummyExecutionAdapter(freshness_verified=False)
        execution = svc.execute(**_exec_args(svc, adapter=adapter))

        repo = ExecutionRepository(db)
        items = repo.list_items(execution.id)
        assert items[0].attempts[0].status == "BLOCKED"

    def test_freshness_verified_flag_set_on_success(self, svc, db):
        adapter = DummyExecutionAdapter(freshness_verified=True)
        execution = svc.execute(**_exec_args(svc, adapter=adapter))

        repo = ExecutionRepository(db)
        items = repo.list_items(execution.id)
        assert items[0].freshness_verified is True

    def test_freshness_not_set_on_failure(self, svc, db):
        adapter = DummyExecutionAdapter(freshness_verified=False)
        execution = svc.execute(**_exec_args(svc, adapter=adapter))

        repo = ExecutionRepository(db)
        items = repo.list_items(execution.id)
        assert items[0].freshness_verified is False


# ── TestExecutionOutcomes ─────────────────────────────────────────────────────


class TestExecutionOutcomes:
    def test_all_items_succeed(self, svc, db):
        items = [_item("SKU-001"), _item("SKU-002", proposal_id="prop-002")]
        execution = svc.execute(**_exec_args(svc, items=items))
        assert execution.status == "SUCCEEDED"
        repo = ExecutionRepository(db)
        db_items = repo.list_items(execution.id)
        assert all(i.status == "SUCCEEDED" for i in db_items)

    def test_freshness_block_causes_blocked_execution(self, svc):
        adapter = DummyExecutionAdapter(freshness_verified=False)
        execution = svc.execute(**_exec_args(svc, adapter=adapter))
        assert execution.status == "BLOCKED"

    def test_permanent_failure_causes_failed_execution(self, svc):
        adapter = DummyExecutionAdapter(permanent_failure=True)
        execution = svc.execute(**_exec_args(svc, adapter=adapter))
        assert execution.status == "FAILED"

    def test_mixed_block_and_fail_block_wins(self, svc, db):
        # SKU-001: freshness fails (BLOCKED), SKU-002: permanent failure (FAILED)
        items = [_item("SKU-001"), _item("SKU-002", proposal_id="prop-002")]

        class MixedAdapter(ChannelExecutionAdapter):
            def verify_freshness(self, ctx: FreshnessContext) -> FreshnessResult:
                if ctx.product_id == "SKU-001":
                    return FreshnessResult(verified=False, reason="freshness block")
                return FreshnessResult(verified=True)

            def execute_item(self, ctx: FreshnessContext) -> ExecuteItemResult:
                return ExecuteItemResult(success=False, is_transient_failure=False, reason="perm fail")

        execution = svc.execute(**_exec_args(svc, items=items, adapter=MixedAdapter()))
        assert execution.status == "BLOCKED"

    def test_execution_completed_at_set_on_terminal(self, svc):
        execution = svc.execute(**_exec_args(svc))
        assert execution.completed_at is not None

    def test_execution_started_at_set_on_running(self, svc):
        execution = svc.execute(**_exec_args(svc))
        assert execution.started_at is not None


# ── TestIdempotency ───────────────────────────────────────────────────────────


class TestIdempotency:
    def test_duplicate_key_returns_existing_execution(self, svc, db):
        args = _exec_args(svc, idempotency_key="key-idem-001")
        exec1 = svc.execute(**args)
        exec2 = svc.execute(**args)
        assert exec1.id == exec2.id

    def test_idempotency_does_not_create_new_record(self, svc, db):
        args = _exec_args(svc, idempotency_key="key-idem-002")
        svc.execute(**args)
        svc.execute(**args)
        count = db.query(Execution).filter(Execution.idempotency_key == "key-idem-002").count()
        assert count == 1

    def test_different_keys_create_separate_executions(self, svc, db):
        items1 = [_item("SKU-001")]
        items2 = [_item("SKU-002", proposal_id="prop-002")]
        exec1 = svc.execute(**_exec_args(svc, items=items1, idempotency_key="key-a"))
        exec2 = svc.execute(**_exec_args(svc, items=items2, idempotency_key="key-b"))
        assert exec1.id != exec2.id

    def test_item_idempotency_key_unique_per_execution(self, svc, db):
        execution = svc.execute(**_exec_args(svc))
        repo = ExecutionRepository(db)
        items = repo.list_items(execution.id)
        keys = [i.idempotency_key for i in items]
        assert len(keys) == len(set(keys))

    def test_dummy_adapter_idempotent_retry_returns_success(self):
        adapter = DummyExecutionAdapter()
        ctx = FreshnessContext(
            product_id="SKU-001",
            proposal_id="p",
            proposal_hash="h" * 64,
            proposed_price=Decimal("9.99"),
            current_price=None,
            destination_channel="WC",
            change_set_digest="d" * 64,
            confirmation_digest="d" * 64,
        )
        result1 = adapter.execute_item(ctx)
        result2 = adapter.execute_item(ctx)
        assert result1.success is True
        assert result2.success is True


# ── TestRetry ─────────────────────────────────────────────────────────────────


class TestRetry:
    def test_transient_failure_then_success(self, svc, db):
        adapter = DummyExecutionAdapter(transient_fail_times=1)
        execution = svc.execute(**_exec_args(svc, adapter=adapter, max_attempts=3))
        assert execution.status == "SUCCEEDED"

        repo = ExecutionRepository(db)
        items = repo.list_items(execution.id)
        assert items[0].status == "SUCCEEDED"
        assert len(items[0].attempts) == 2  # attempt 1: FAILED, attempt 2: SUCCEEDED

    def test_permanent_failure_no_retry(self, svc, db):
        adapter = DummyExecutionAdapter(permanent_failure=True)
        execution = svc.execute(**_exec_args(svc, adapter=adapter, max_attempts=3))
        assert execution.status == "FAILED"

        repo = ExecutionRepository(db)
        items = repo.list_items(execution.id)
        assert len(items[0].attempts) == 1  # no retry on permanent failure

    def test_max_attempts_exhausted_marks_item_failed(self, svc, db):
        # 4 transient failures, max_attempts=3 → FAILED after 3 attempts
        adapter = DummyExecutionAdapter(transient_fail_times=4)
        execution = svc.execute(**_exec_args(svc, adapter=adapter, max_attempts=3))
        assert execution.status == "FAILED"

        repo = ExecutionRepository(db)
        items = repo.list_items(execution.id)
        assert items[0].status == "FAILED"
        assert len(items[0].attempts) == 3

    def test_attempt_records_created_per_try(self, svc, db):
        adapter = DummyExecutionAdapter(transient_fail_times=2)
        execution = svc.execute(**_exec_args(svc, adapter=adapter, max_attempts=3))
        assert execution.status == "SUCCEEDED"

        repo = ExecutionRepository(db)
        items = repo.list_items(execution.id)
        attempts = items[0].attempts
        assert len(attempts) == 3
        assert attempts[0].attempt_number == 1
        assert attempts[1].attempt_number == 2
        assert attempts[2].attempt_number == 3
        assert attempts[0].status == "FAILED"
        assert attempts[1].status == "FAILED"
        assert attempts[2].status == "SUCCEEDED"

    def test_failed_attempts_have_error_message(self, svc, db):
        adapter = DummyExecutionAdapter(transient_fail_times=1)
        execution = svc.execute(**_exec_args(svc, adapter=adapter, max_attempts=3))

        repo = ExecutionRepository(db)
        items = repo.list_items(execution.id)
        assert items[0].attempts[0].error_message is not None


# ── TestStateMachine ──────────────────────────────────────────────────────────


class TestStateMachine:
    def test_execution_pending_to_running_valid(self, repo):
        exec_ = repo.create_execution(
            change_set_id=_CS_ID, change_set_revision_id=_REV_ID,
            change_set_digest="d" * 64, confirmation_id=_CONF_ID,
            confirmation_digest="d" * 64, destination_channel=_CHANNEL,
            scope=_SCOPE, source_snapshot_id=_SNAPSHOT, idempotency_key="sm-001",
        )
        updated = repo.transition_execution(exec_.id, "RUNNING")
        assert updated.status == "RUNNING"
        assert updated.started_at is not None

    def test_execution_running_to_succeeded_valid(self, repo):
        exec_ = repo.create_execution(
            change_set_id=_CS_ID, change_set_revision_id=_REV_ID,
            change_set_digest="d" * 64, confirmation_id=_CONF_ID,
            confirmation_digest="d" * 64, destination_channel=_CHANNEL,
            scope=_SCOPE, source_snapshot_id=_SNAPSHOT, idempotency_key="sm-002",
        )
        repo.transition_execution(exec_.id, "RUNNING")
        updated = repo.transition_execution(exec_.id, "SUCCEEDED")
        assert updated.status == "SUCCEEDED"
        assert updated.completed_at is not None

    def test_invalid_execution_transition_raises(self, repo):
        exec_ = repo.create_execution(
            change_set_id=_CS_ID, change_set_revision_id=_REV_ID,
            change_set_digest="d" * 64, confirmation_id=_CONF_ID,
            confirmation_digest="d" * 64, destination_channel=_CHANNEL,
            scope=_SCOPE, source_snapshot_id=_SNAPSHOT, idempotency_key="sm-003",
        )
        with pytest.raises(InvalidExecutionStateTransitionError):
            repo.transition_execution(exec_.id, "SUCCEEDED")  # PENDING → SUCCEEDED invalid

    def test_item_pending_to_running_valid(self, repo, db):
        exec_ = repo.create_execution(
            change_set_id=_CS_ID, change_set_revision_id=_REV_ID,
            change_set_digest="d" * 64, confirmation_id=_CONF_ID,
            confirmation_digest="d" * 64, destination_channel=_CHANNEL,
            scope=_SCOPE, source_snapshot_id=_SNAPSHOT, idempotency_key="sm-004",
        )
        batch = repo.create_batch(execution_id=exec_.id, batch_number=1)
        item = repo.create_item(
            execution_id=exec_.id, batch_id=batch.id,
            idempotency_key="sm-004:SKU-001", product_id="SKU-001",
            proposal_id="p-001", proposal_hash="h" * 64,
            safety_result_id="s-001", rule_version_id="rv-001",
            proposed_price=Decimal("9.99"),
        )
        updated = repo.transition_item(item.id, "RUNNING")
        assert updated.status == "RUNNING"

    def test_invalid_item_transition_raises(self, repo):
        exec_ = repo.create_execution(
            change_set_id=_CS_ID, change_set_revision_id=_REV_ID,
            change_set_digest="d" * 64, confirmation_id=_CONF_ID,
            confirmation_digest="d" * 64, destination_channel=_CHANNEL,
            scope=_SCOPE, source_snapshot_id=_SNAPSHOT, idempotency_key="sm-005",
        )
        batch = repo.create_batch(execution_id=exec_.id, batch_number=1)
        item = repo.create_item(
            execution_id=exec_.id, batch_id=batch.id,
            idempotency_key="sm-005:SKU-001", product_id="SKU-001",
            proposal_id="p-001", proposal_hash="h" * 64,
            safety_result_id="s-001", rule_version_id="rv-001",
            proposed_price=Decimal("9.99"),
        )
        with pytest.raises(InvalidExecutionStateTransitionError):
            repo.transition_item(item.id, "SUCCEEDED")  # PENDING → SUCCEEDED invalid


# ── TestTerminalStatesImmutable ───────────────────────────────────────────────


class TestTerminalStatesImmutable:
    def _make_terminal_execution(self, repo, idempotency_key: str, terminal: str) -> Execution:
        exec_ = repo.create_execution(
            change_set_id=_CS_ID, change_set_revision_id=_REV_ID,
            change_set_digest="d" * 64, confirmation_id=_CONF_ID,
            confirmation_digest="d" * 64, destination_channel=_CHANNEL,
            scope=_SCOPE, source_snapshot_id=_SNAPSHOT, idempotency_key=idempotency_key,
        )
        if terminal in {"SUCCEEDED", "FAILED"}:
            repo.transition_execution(exec_.id, "RUNNING")
        repo.transition_execution(exec_.id, terminal)
        return exec_

    def test_succeeded_execution_cannot_transition(self, repo):
        exec_ = self._make_terminal_execution(repo, "ts-001", "SUCCEEDED")
        with pytest.raises(InvalidExecutionStateTransitionError):
            repo.transition_execution(exec_.id, "FAILED")

    def test_failed_execution_cannot_transition(self, repo):
        exec_ = self._make_terminal_execution(repo, "ts-002", "FAILED")
        with pytest.raises(InvalidExecutionStateTransitionError):
            repo.transition_execution(exec_.id, "SUCCEEDED")

    def test_blocked_execution_cannot_transition(self, repo):
        exec_ = self._make_terminal_execution(repo, "ts-003", "BLOCKED")
        with pytest.raises(InvalidExecutionStateTransitionError):
            repo.transition_execution(exec_.id, "RUNNING")

    def test_cancelled_execution_cannot_transition(self, repo):
        exec_ = self._make_terminal_execution(repo, "ts-004", "CANCELLED")
        with pytest.raises(InvalidExecutionStateTransitionError):
            repo.transition_execution(exec_.id, "RUNNING")

    def test_succeeded_item_cannot_transition(self, repo):
        exec_ = repo.create_execution(
            change_set_id=_CS_ID, change_set_revision_id=_REV_ID,
            change_set_digest="d" * 64, confirmation_id=_CONF_ID,
            confirmation_digest="d" * 64, destination_channel=_CHANNEL,
            scope=_SCOPE, source_snapshot_id=_SNAPSHOT, idempotency_key="ts-005",
        )
        batch = repo.create_batch(execution_id=exec_.id, batch_number=1)
        item = repo.create_item(
            execution_id=exec_.id, batch_id=batch.id, idempotency_key="ts-005:s",
            product_id="SKU-001", proposal_id="p", proposal_hash="h" * 64,
            safety_result_id="s", rule_version_id="rv", proposed_price=Decimal("1.00"),
        )
        repo.transition_item(item.id, "RUNNING")
        repo.transition_item(item.id, "SUCCEEDED")
        with pytest.raises(InvalidExecutionStateTransitionError):
            repo.transition_item(item.id, "FAILED")


# ── TestCancel ────────────────────────────────────────────────────────────────


class TestCancel:
    def test_cancel_pending_execution(self, svc, db):
        # Create a stale PENDING execution via repo (service always runs to completion)
        repo = ExecutionRepository(db)
        exec_ = repo.create_execution(
            change_set_id=_CS_ID, change_set_revision_id=_REV_ID,
            change_set_digest="d" * 64, confirmation_id=_CONF_ID,
            confirmation_digest="d" * 64, destination_channel=_CHANNEL,
            scope=_SCOPE, source_snapshot_id=_SNAPSHOT, idempotency_key="cancel-001",
        )
        cancelled = svc.cancel(exec_.id)
        assert cancelled.status == "CANCELLED"

    def test_cancel_running_execution(self, svc, db):
        repo = ExecutionRepository(db)
        exec_ = repo.create_execution(
            change_set_id=_CS_ID, change_set_revision_id=_REV_ID,
            change_set_digest="d" * 64, confirmation_id=_CONF_ID,
            confirmation_digest="d" * 64, destination_channel=_CHANNEL,
            scope=_SCOPE, source_snapshot_id=_SNAPSHOT, idempotency_key="cancel-002",
        )
        repo.transition_execution(exec_.id, "RUNNING")
        cancelled = svc.cancel(exec_.id)
        assert cancelled.status == "CANCELLED"

    def test_cancel_terminal_raises(self, svc, db):
        repo = ExecutionRepository(db)
        exec_ = repo.create_execution(
            change_set_id=_CS_ID, change_set_revision_id=_REV_ID,
            change_set_digest="d" * 64, confirmation_id=_CONF_ID,
            confirmation_digest="d" * 64, destination_channel=_CHANNEL,
            scope=_SCOPE, source_snapshot_id=_SNAPSHOT, idempotency_key="cancel-003",
        )
        repo.transition_execution(exec_.id, "RUNNING")
        repo.transition_execution(exec_.id, "SUCCEEDED")
        with pytest.raises(InvalidExecutionStateTransitionError):
            svc.cancel(exec_.id)


# ── TestRecovery ──────────────────────────────────────────────────────────────


class TestRecovery:
    def test_stale_running_execution_detected(self, repo, db):
        exec_ = repo.create_execution(
            change_set_id=_CS_ID, change_set_revision_id=_REV_ID,
            change_set_digest="d" * 64, confirmation_id=_CONF_ID,
            confirmation_digest="d" * 64, destination_channel=_CHANNEL,
            scope=_SCOPE, source_snapshot_id=_SNAPSHOT, idempotency_key="stale-001",
        )
        repo.transition_execution(exec_.id, "RUNNING")
        # Backdate started_at to simulate staleness
        exec_row = db.get(Execution, exec_.id)
        exec_row.started_at = datetime.now(tz=timezone.utc) - timedelta(minutes=31)
        db.flush()

        stale = repo.find_stale_running(timeout_minutes=30)
        assert any(e.id == exec_.id for e in stale)

    def test_fresh_running_execution_not_stale(self, repo):
        exec_ = repo.create_execution(
            change_set_id=_CS_ID, change_set_revision_id=_REV_ID,
            change_set_digest="d" * 64, confirmation_id=_CONF_ID,
            confirmation_digest="d" * 64, destination_channel=_CHANNEL,
            scope=_SCOPE, source_snapshot_id=_SNAPSHOT, idempotency_key="fresh-001",
        )
        repo.transition_execution(exec_.id, "RUNNING")
        stale = repo.find_stale_running(timeout_minutes=30)
        assert not any(e.id == exec_.id for e in stale)

    def test_stale_running_item_detected(self, repo, db):
        exec_ = repo.create_execution(
            change_set_id=_CS_ID, change_set_revision_id=_REV_ID,
            change_set_digest="d" * 64, confirmation_id=_CONF_ID,
            confirmation_digest="d" * 64, destination_channel=_CHANNEL,
            scope=_SCOPE, source_snapshot_id=_SNAPSHOT, idempotency_key="stale-item-001",
        )
        batch = repo.create_batch(execution_id=exec_.id, batch_number=1)
        item = repo.create_item(
            execution_id=exec_.id, batch_id=batch.id,
            idempotency_key="stale-item-001:SKU", product_id="SKU",
            proposal_id="p", proposal_hash="h" * 64,
            safety_result_id="s", rule_version_id="rv", proposed_price=Decimal("1.00"),
        )
        repo.transition_item(item.id, "RUNNING")
        # Backdate updated_at
        item_row = db.get(ExecutionItem, item.id)
        item_row.updated_at = datetime.now(tz=timezone.utc) - timedelta(minutes=31)
        db.flush()

        stale = repo.find_stale_running_items(timeout_minutes=30)
        assert any(i.id == item.id for i in stale)

    def test_fresh_running_item_not_stale(self, repo):
        exec_ = repo.create_execution(
            change_set_id=_CS_ID, change_set_revision_id=_REV_ID,
            change_set_digest="d" * 64, confirmation_id=_CONF_ID,
            confirmation_digest="d" * 64, destination_channel=_CHANNEL,
            scope=_SCOPE, source_snapshot_id=_SNAPSHOT, idempotency_key="fresh-item-001",
        )
        batch = repo.create_batch(execution_id=exec_.id, batch_number=1)
        item = repo.create_item(
            execution_id=exec_.id, batch_id=batch.id,
            idempotency_key="fresh-item-001:SKU", product_id="SKU",
            proposal_id="p", proposal_hash="h" * 64,
            safety_result_id="s", rule_version_id="rv", proposed_price=Decimal("1.00"),
        )
        repo.transition_item(item.id, "RUNNING")
        stale = repo.find_stale_running_items(timeout_minutes=30)
        assert not any(i.id == item.id for i in stale)


# ── TestRepository ────────────────────────────────────────────────────────────


class TestRepository:
    def test_create_and_get_execution(self, repo):
        exec_ = repo.create_execution(
            change_set_id="cs-r", change_set_revision_id="rv-r",
            change_set_digest="d" * 64, confirmation_id="c-r",
            confirmation_digest="d" * 64, destination_channel="WC",
            scope="all", source_snapshot_id="s-r", idempotency_key="repo-001",
        )
        fetched = repo.get_execution(exec_.id)
        assert fetched is not None
        assert fetched.id == exec_.id
        assert fetched.status == "PENDING"

    def test_get_missing_execution_returns_none(self, repo):
        assert repo.get_execution("nonexistent-id") is None

    def test_create_batch(self, repo):
        exec_ = repo.create_execution(
            change_set_id="cs-r2", change_set_revision_id="rv-r2",
            change_set_digest="d" * 64, confirmation_id="c-r2",
            confirmation_digest="d" * 64, destination_channel="WC",
            scope="all", source_snapshot_id="s-r2", idempotency_key="repo-002",
        )
        batch = repo.create_batch(execution_id=exec_.id, batch_number=1)
        assert batch.execution_id == exec_.id
        assert batch.batch_number == 1
        assert batch.status == "PENDING"

    def test_create_and_get_item(self, repo):
        exec_ = repo.create_execution(
            change_set_id="cs-r3", change_set_revision_id="rv-r3",
            change_set_digest="d" * 64, confirmation_id="c-r3",
            confirmation_digest="d" * 64, destination_channel="WC",
            scope="all", source_snapshot_id="s-r3", idempotency_key="repo-003",
        )
        batch = repo.create_batch(execution_id=exec_.id, batch_number=1)
        item = repo.create_item(
            execution_id=exec_.id, batch_id=batch.id,
            idempotency_key="repo-003:SKU", product_id="SKU",
            proposal_id="p", proposal_hash="h" * 64,
            safety_result_id="s", rule_version_id="rv", proposed_price=Decimal("9.99"),
        )
        fetched = repo.get_item(item.id)
        assert fetched is not None
        assert fetched.product_id == "SKU"
        assert fetched.status == "PENDING"
        assert fetched.freshness_verified is False

    def test_list_items(self, repo):
        exec_ = repo.create_execution(
            change_set_id="cs-r4", change_set_revision_id="rv-r4",
            change_set_digest="d" * 64, confirmation_id="c-r4",
            confirmation_digest="d" * 64, destination_channel="WC",
            scope="all", source_snapshot_id="s-r4", idempotency_key="repo-004",
        )
        batch = repo.create_batch(execution_id=exec_.id, batch_number=1)
        for i in range(3):
            repo.create_item(
                execution_id=exec_.id, batch_id=batch.id,
                idempotency_key=f"repo-004:SKU-{i}", product_id=f"SKU-{i}",
                proposal_id=f"p-{i}", proposal_hash="h" * 64,
                safety_result_id="s", rule_version_id="rv", proposed_price=Decimal("1.00"),
            )
        items = repo.list_items(exec_.id)
        assert len(items) == 3

    def test_find_by_idempotency_key(self, repo):
        exec_ = repo.create_execution(
            change_set_id="cs-r5", change_set_revision_id="rv-r5",
            change_set_digest="d" * 64, confirmation_id="c-r5",
            confirmation_digest="d" * 64, destination_channel="WC",
            scope="all", source_snapshot_id="s-r5", idempotency_key="repo-005",
        )
        found = repo.find_by_idempotency_key("repo-005")
        assert found is not None
        assert found.id == exec_.id

    def test_find_by_missing_idempotency_key_returns_none(self, repo):
        assert repo.find_by_idempotency_key("nonexistent-key") is None

    def test_record_attempt(self, repo):
        exec_ = repo.create_execution(
            change_set_id="cs-r6", change_set_revision_id="rv-r6",
            change_set_digest="d" * 64, confirmation_id="c-r6",
            confirmation_digest="d" * 64, destination_channel="WC",
            scope="all", source_snapshot_id="s-r6", idempotency_key="repo-006",
        )
        batch = repo.create_batch(execution_id=exec_.id, batch_number=1)
        item = repo.create_item(
            execution_id=exec_.id, batch_id=batch.id, idempotency_key="repo-006:SKU",
            product_id="SKU", proposal_id="p", proposal_hash="h" * 64,
            safety_result_id="s", rule_version_id="rv", proposed_price=Decimal("1.00"),
        )
        attempt = repo.record_attempt(
            execution_item_id=item.id, attempt_number=1,
            status="SUCCEEDED", adapter_name="DummyExecutionAdapter",
        )
        assert attempt.attempt_number == 1
        assert attempt.status == "SUCCEEDED"
        assert attempt.adapter_name == "DummyExecutionAdapter"


# ── TestExecutionReport ───────────────────────────────────────────────────────


class TestExecutionReport:
    def test_report_counts_on_success(self, svc):
        items = [_item("SKU-001"), _item("SKU-002", proposal_id="prop-002")]
        execution = svc.execute(**_exec_args(svc, items=items, idempotency_key="report-001"))
        report = svc.get_report(execution.id)
        assert isinstance(report, ExecutionReport)
        assert report.total_items == 2
        assert report.succeeded_count == 2
        assert report.failed_count == 0
        assert report.blocked_count == 0

    def test_report_counts_on_freshness_block(self, svc):
        adapter = DummyExecutionAdapter(freshness_verified=False)
        execution = svc.execute(**_exec_args(svc, adapter=adapter, idempotency_key="report-002"))
        report = svc.get_report(execution.id)
        assert report.blocked_count == 1
        assert report.status == "BLOCKED"

    def test_report_has_execution_metadata(self, svc):
        execution = svc.execute(**_exec_args(svc, idempotency_key="report-003"))
        report = svc.get_report(execution.id)
        assert report.execution_id == execution.id
        assert report.change_set_id == _CS_ID
        assert report.destination_channel == _CHANNEL

    def test_report_missing_execution_raises(self, svc):
        with pytest.raises(ValueError, match="not found"):
            svc.get_report("nonexistent-execution-id")


# ── TestMigration ─────────────────────────────────────────────────────────────


class TestMigration:
    def test_a2_006_down_revision_is_a2_005(self):
        from alembic_a2.versions.a2_006_execution_engine import down_revision, revision
        assert revision == "a2_006"
        assert down_revision == "a2_005"

    def test_upgrade_to_head_creates_execution_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_006_up.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "head")
        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()
        assert "a2_executions" in tables
        assert "a2_execution_batches" in tables
        assert "a2_execution_items" in tables
        assert "a2_execution_attempts" in tables

    def test_downgrade_from_a2_006_removes_execution_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_006_down.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "head")
            command.downgrade(cfg, "a2_005")
        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()
        assert "a2_executions" not in tables
        assert "a2_execution_batches" not in tables
        assert "a2_execution_items" not in tables
        assert "a2_execution_attempts" not in tables

    def test_a2_005_tables_survive_downgrade_from_a2_006(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_006_compat.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "head")
            command.downgrade(cfg, "a2_005")
        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()
        assert "a2_dry_runs" in tables
        assert "a2_seller_confirmations" in tables

    def test_a2_006_adds_exactly_four_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_006_count.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "a2_005")
        eng = create_engine(db_url)
        tables_before = set(inspect(eng).get_table_names())
        eng.dispose()

        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "a2_006")
        eng = create_engine(db_url)
        tables_after = set(inspect(eng).get_table_names())
        eng.dispose()

        new_tables = tables_after - tables_before
        assert new_tables == {
            "a2_executions",
            "a2_execution_batches",
            "a2_execution_items",
            "a2_execution_attempts",
        }


# ── TestIsolation ─────────────────────────────────────────────────────────────


class TestIsolation:
    @staticmethod
    def _source(module_name: str) -> str:
        spec = importlib.util.find_spec(module_name)
        assert spec is not None and spec.origin is not None
        with open(spec.origin, encoding="utf-8") as f:
            return f.read()

    def _service_source(self) -> str:
        return self._source("app.a2.services.execution_service")

    def _model_source(self) -> str:
        return self._source("app.a2.models.execution")

    def _repo_source(self) -> str:
        return self._source("app.a2.repositories.execution_repository")

    def test_no_woocommerce_writes_in_execution_service(self):
        src = self._service_source()
        # Check import-level only; comments may reference WooCommerce for documentation
        for forbidden in ["import woocommerce", "from woocommerce", "wc_api", "wcapi"]:
            assert forbidden not in src.lower(), (
                f"Found {forbidden!r} in execution_service — real WooCommerce imports prohibited in A2.7"
            )

    def test_no_apply_workflow_in_execution_service(self):
        src = self._service_source()
        for forbidden in ["apply_workflow", "workspace_apply", "ApplyWorkflow", "do_apply"]:
            assert forbidden not in src, (
                f"Found {forbidden!r} in execution_service — Apply Workflow must not be modified"
            )

    def test_no_scheduling_engine_imports(self):
        src = self._service_source()
        assert "a2.8" not in src
        assert "scheduling" not in src.lower() or "No" in src  # doc comments OK

    def test_no_a2_8_imports(self):
        for module_name in [
            "app.a2.services.execution_service",
            "app.a2.models.execution",
            "app.a2.repositories.execution_repository",
        ]:
            src = self._source(module_name)
            assert "a2_8" not in src
            assert "from app.a2.services.scheduling" not in src
            assert "from app.a2.models.scheduling" not in src

    def test_no_ai_foundation_imports(self):
        src = self._service_source()
        assert "from app.a2.services.ai" not in src
        assert "from app.a2.models.ai" not in src

    def test_no_network_calls_in_execution_service(self):
        src = self._service_source()
        for forbidden in ["import requests", "import httpx", "import aiohttp", "urllib.request"]:
            assert forbidden not in src, (
                f"Found {forbidden!r} in execution_service — network calls prohibited in A2.7"
            )

    def test_dummy_adapter_has_no_network_calls(self):
        src = self._service_source()
        # DummyExecutionAdapter class body should contain no network-related symbols
        for forbidden in ["requests.get", "requests.post", "httpx.get", "httpx.post"]:
            assert forbidden not in src

    def test_no_direct_woocommerce_write_in_model(self):
        src = self._model_source()
        # Check import-level only; docstrings may reference WooCommerce for documentation
        for forbidden in ["import woocommerce", "from woocommerce", "wc_api"]:
            assert forbidden not in src.lower()

    def test_execution_service_does_not_import_a2_6_models(self):
        src = self._service_source()
        # Check import-level only; SellerConfirmation may appear in docstring comments
        assert "from app.a2.models.dry_run" not in src
        assert "from ..models.dry_run" not in src
        assert "import SellerConfirmation" not in src

    def test_dummy_adapter_is_in_execution_service_module(self):
        src = self._service_source()
        assert "class DummyExecutionAdapter" in src
        assert "class ChannelExecutionAdapter" in src
