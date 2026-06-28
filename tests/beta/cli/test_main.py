"""Tests for cli/main.py — registration, help, and command groups."""

from typer.testing import CliRunner
from cli.main import app

runner = CliRunner()


class TestMainHelp:
    def test_help_exits_zero(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    def test_help_contains_wooprice(self):
        result = runner.invoke(app, ["--help"])
        assert "wooprice" in result.output.lower() or "WooPrice" in result.output

    def test_help_shows_install(self):
        result = runner.invoke(app, ["--help"])
        assert "install" in result.output

    def test_help_shows_configure(self):
        result = runner.invoke(app, ["--help"])
        assert "configure" in result.output

    def test_help_shows_status(self):
        result = runner.invoke(app, ["--help"])
        assert "status" in result.output

    def test_help_shows_health(self):
        result = runner.invoke(app, ["--help"])
        assert "health" in result.output

    def test_help_shows_diagnostics(self):
        result = runner.invoke(app, ["--help"])
        assert "diagnostics" in result.output

    def test_help_shows_migrate(self):
        result = runner.invoke(app, ["--help"])
        assert "migrate" in result.output

    def test_help_shows_backup(self):
        result = runner.invoke(app, ["--help"])
        assert "backup" in result.output

    def test_all_sub_commands_accessible(self):
        groups = [
            "install", "configure", "status", "health", "diagnostics",
            "migrate", "backup", "logs", "update", "adapters",
            "channels", "sources", "users", "scheduler", "ai",
        ]
        for group in groups:
            result = runner.invoke(app, [group, "--help"])
            assert result.exit_code == 0, (
                f"'{group} --help' exited with {result.exit_code}: {result.output}"
            )


class TestMainRegistration:
    def test_install_registered(self):
        from cli.main import app as main_app
        names = [g.name for g in main_app.registered_groups]
        assert "install" in names

    def test_configure_registered(self):
        from cli.main import app as main_app
        names = [g.name for g in main_app.registered_groups]
        assert "configure" in names

    def test_seventeen_command_groups_registered(self):
        from cli.main import app as main_app
        # 17 groups: install, configure, status, health, diagnostics, integrations (CP1.3),
        # migrate, backup, logs, update, adapters, channels, sources, users, scheduler, ai,
        # create-admin (BU2)
        assert len(main_app.registered_groups) == 17

    def test_integrations_registered(self):
        from cli.main import app as main_app
        names = [g.name for g in main_app.registered_groups]
        assert "integrations" in names
