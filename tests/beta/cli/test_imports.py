"""CLI module import tests — verifies all modules are importable."""

import importlib


_CLI_MODULES = [
    "cli.main",
    "cli.install",
    "cli.configure",
    "cli.status",
    "cli.health",
    "cli.diagnostics",
    "cli.migrate",
    "cli.backup",
    "cli.logs",
    "cli.update",
    "cli.adapters",
    "cli.channels",
    "cli.sources",
    "cli.users",
    "cli.scheduler",
    "cli.ai",
    "cli.shared.output",
    "cli.shared.env_guard",
    "cli.shared.config_reader",
    "cli.shared.api_client",
]


class TestCliImports:
    def test_all_cli_modules_importable(self):
        for mod in _CLI_MODULES:
            imported = importlib.import_module(mod)
            assert imported is not None, f"Failed to import {mod}"

    def test_main_app_is_typer(self):
        import typer
        from cli.main import app
        assert isinstance(app, typer.Typer)

    def test_all_sub_apps_are_typer(self):
        import typer
        from cli.install import app as install_app
        from cli.configure import app as configure_app
        from cli.status import app as status_app
        from cli.health import app as health_app
        from cli.diagnostics import app as diagnostics_app
        from cli.migrate import app as migrate_app
        from cli.backup import app as backup_app
        from cli.logs import app as logs_app
        from cli.update import app as update_app
        from cli.adapters import app as adapters_app
        from cli.channels import app as channels_app
        from cli.sources import app as sources_app
        from cli.users import app as users_app
        from cli.scheduler import app as scheduler_app
        from cli.ai import app as ai_app

        for sub_app in [
            install_app, configure_app, status_app, health_app,
            diagnostics_app, migrate_app, backup_app, logs_app,
            update_app, adapters_app, channels_app, sources_app,
            users_app, scheduler_app, ai_app,
        ]:
            assert isinstance(sub_app, typer.Typer)

    def test_output_module_has_console(self):
        from cli.shared.output import console
        from rich.console import Console
        assert isinstance(console, Console)

    def test_env_guard_module_has_exception(self):
        from cli.shared.env_guard import ProductionResourceError
        assert issubclass(ProductionResourceError, Exception)

    def test_config_reader_importable(self):
        from cli.shared.config_reader import load_config, validate_env_file, redact_env_dict
        assert callable(load_config)
        assert callable(validate_env_file)
        assert callable(redact_env_dict)
