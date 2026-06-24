"""
Isolation tests — verify that A2.2 does not import into or affect production code.

These tests inspect module import graphs without executing any application logic.
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
import sys


def _get_source(module_name: str) -> str:
    """Return the source code of a module as a string."""
    spec = importlib.util.find_spec(module_name)
    if spec is None or spec.origin is None:
        return ""
    with open(spec.origin, encoding="utf-8") as f:
        return f.read()


def test_app_main_does_not_import_a2_sources():
    src = _get_source("app.main")
    assert "app.a2.sources" not in src, (
        "app.main must not import from app.a2.sources"
    )
    assert "a2.sources" not in src


def test_app_main_does_not_import_a2_at_all():
    src = _get_source("app.main")
    assert "from app.a2" not in src
    assert "import app.a2" not in src


def test_production_database_module_not_imported_by_a2():
    import app.a2.database as a2db  # noqa: F401
    src = _get_source("app.a2.database")
    assert "from app.database" not in src
    assert "from ..database import" not in src or "app.database" not in src


def test_a2_models_do_not_reference_production_models():
    for module_name in (
        "app.a2.models.source",
        "app.a2.models.snapshot",
        "app.a2.models.provenance",
        "app.a2.models.checkpoint",
    ):
        src = _get_source(module_name)
        assert "from app.models" not in src, f"{module_name} imports app.models"
        assert "import app.models" not in src, f"{module_name} imports app.models"


def test_nextcloud_adapter_does_not_import_production_nextcloud_service():
    src = _get_source("app.a2.sources.adapters.nextcloud")
    assert "from app.services.nextcloud" not in src, (
        "A2 nextcloud adapter must not import from app.services.nextcloud"
    )
    assert "app.services.nextcloud" not in src


def test_nextcloud_adapter_does_not_implement_change_logic():
    src = _get_source("app.a2.sources.adapters.nextcloud")
    forbidden = [
        "change_set", "changeset", "diff", "mutation", "proposal",
        "rule_engine", "safety_engine", "dry_run", "apply",
        "price_calc", "cost_calc", "execute", "schedule",
    ]
    for term in forbidden:
        assert term not in src.lower(), (
            f"Forbidden term '{term}' found in nextcloud adapter — "
            "A2.2 must not implement change detection or execution logic."
        )


def test_a2_sources_do_not_import_woocommerce_service():
    for module_name in (
        "app.a2.sources.base",
        "app.a2.sources.registry",
        "app.a2.sources.adapters.nextcloud",
    ):
        src = _get_source(module_name)
        assert "woocommerce" not in src.lower(), (
            f"{module_name} must not reference WooCommerce service"
        )


def test_a2_package_is_importable_in_isolation():
    import app.a2.sources.base  # noqa: F401
    import app.a2.sources.capabilities  # noqa: F401
    import app.a2.sources.snapshot  # noqa: F401
    import app.a2.sources.provenance  # noqa: F401
    import app.a2.sources.checkpoint  # noqa: F401
    import app.a2.sources.registry  # noqa: F401
    import app.a2.sources.adapters.nextcloud  # noqa: F401
