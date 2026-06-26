"""
Isolation tests — verify A2.3-R2 rule engine does not import forbidden modules.

Tests inspect module source code without executing application logic.
"""
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

import importlib
import re


def _source(module_name: str) -> str:
    spec = importlib.util.find_spec(module_name)
    if spec is None or spec.origin is None:
        return ""
    with open(spec.origin, encoding="utf-8") as f:
        return f.read()


def _has_import(source: str, pattern: str) -> bool:
    """Return True if source contains a real import line matching pattern."""
    return bool(re.search(
        rf"^(?:from|import)\s+.*{re.escape(pattern)}",
        source,
        re.MULTILINE,
    ))


_RULE_MODULES = [
    "app.a2.rules.formula",
    "app.a2.rules.base",
    "app.a2.rules.engine",
    "app.a2.rules.proposal",
    "app.a2.repositories.rule_repository",
    "app.a2.repositories.proposal_repository",
]


# ── No WooCommerce / external service imports ─────────────────────────────────

def test_rule_modules_do_not_import_woocommerce():
    for module_name in _RULE_MODULES:
        src = _source(module_name)
        assert not _has_import(src, "app.services.woo"), (
            f"{module_name} must not import WooCommerce service"
        )
        assert "import woocommerce" not in src.lower(), (
            f"{module_name} must not import WooCommerce"
        )


# ── No Apply / Execute / DryRun imports ───────────────────────────────────────

def test_rule_modules_do_not_import_apply():
    for module_name in _RULE_MODULES:
        src = _source(module_name)
        assert not _has_import(src, "app.a2.apply"), (
            f"{module_name} must not import from apply module"
        )
        assert not _has_import(src, "app.a2.dry_run"), (
            f"{module_name} must not import from dry_run module"
        )
        assert not _has_import(src, "app.a2.execution"), (
            f"{module_name} must not import from execution module"
        )


# ── No Safety Engine imports ──────────────────────────────────────────────────

def test_rule_modules_do_not_import_safety():
    for module_name in _RULE_MODULES:
        src = _source(module_name)
        assert not _has_import(src, "app.a2.safety"), (
            f"{module_name} must not import from safety module"
        )
        assert not _has_import(src, "app.a2.engines.safety"), (
            f"{module_name} must not import from safety engine"
        )


# ── No Change Set imports ─────────────────────────────────────────────────────

def test_rule_modules_do_not_import_change_set():
    for module_name in _RULE_MODULES:
        src = _source(module_name)
        assert not _has_import(src, "app.a2.change_set"), (
            f"{module_name} must not import change_set"
        )
        assert not _has_import(src, "app.a2.changeset"), (
            f"{module_name} must not import changeset"
        )


# ── No production app imports ─────────────────────────────────────────────────

def test_rule_modules_do_not_import_production_models():
    for module_name in _RULE_MODULES:
        src = _source(module_name)
        assert not _has_import(src, "app.models"), (
            f"{module_name} must not import app.models (production)"
        )


def test_rule_modules_do_not_import_production_database():
    for module_name in _RULE_MODULES:
        src = _source(module_name)
        assert not _has_import(src, "app.database"), (
            f"{module_name} must not import app.database (production)"
        )


# ── No eval() or exec() calls in formula module ───────────────────────────────

def test_formula_module_does_not_use_eval():
    src = _source("app.a2.rules.formula")
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        assert "eval(" not in line, f"formula.py must not call eval(): {line!r}"


def test_formula_module_does_not_use_exec():
    src = _source("app.a2.rules.formula")
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        assert "exec(" not in line, f"formula.py must not call exec(): {line!r}"


# ── Importable in isolation ────────────────────────────────────────────────────

def test_rule_engine_importable():
    import app.a2.rules.formula    # noqa: F401
    import app.a2.rules.base       # noqa: F401
    import app.a2.rules.engine     # noqa: F401
    import app.a2.rules.proposal   # noqa: F401


def test_repositories_importable():
    import app.a2.repositories.rule_repository      # noqa: F401
    import app.a2.repositories.proposal_repository  # noqa: F401


# ── Engine does not call external APIs ────────────────────────────────────────

def test_engine_does_not_call_nextcloud():
    src = _source("app.a2.rules.engine")
    assert not _has_import(src, "app.a2.sources.adapters.nextcloud"), (
        "RuleEngine must not import Nextcloud adapter"
    )


def test_engine_does_not_import_httpx():
    src = _source("app.a2.rules.engine")
    assert "import httpx" not in src, "RuleEngine must not make network calls (httpx detected)"


def test_engine_does_not_use_random():
    src = _source("app.a2.rules.engine")
    assert "import random" not in src, "RuleEngine must be deterministic (no random module)"


# ── A2.3 must not reach forward into A2.4+ ───────────────────────────────────

def test_rule_modules_do_not_import_safety_models():
    for module_name in _RULE_MODULES:
        src = _source(module_name)
        assert not _has_import(src, "app.a2.models.safety"), (
            f"{module_name} must not import A2.4 safety models"
        )


def test_rule_modules_do_not_import_scheduling():
    for module_name in _RULE_MODULES:
        src = _source(module_name)
        assert not _has_import(src, "app.a2.scheduling"), (
            f"{module_name} must not import scheduling module"
        )


def test_rule_modules_do_not_import_ai():
    for module_name in _RULE_MODULES:
        src = _source(module_name)
        assert not _has_import(src, "app.a2.ai"), (
            f"{module_name} must not import AI module"
        )
