"""Tests for all stub commands — must exit safely with 'Not implemented' message."""

import pytest
from typer.testing import CliRunner
from cli.main import app

runner = CliRunner()

_STUB_COMMANDS = [
    ["migrate", "status"],
    ["migrate", "up"],
    ["migrate", "history"],
    ["backup", "create"],
    ["backup", "list"],
    ["backup", "restore"],
    ["logs", "tail"],
    ["logs", "show"],
    ["logs", "export"],
    ["update", "check"],
    ["update", "apply"],
    ["adapters", "list"],
    ["adapters", "install"],
    ["adapters", "enable"],
    ["adapters", "disable"],
    ["adapters", "remove"],
    ["channels", "list"],
    ["channels", "add"],
    ["channels", "test"],
    ["channels", "remove"],
    ["sources", "list"],
    ["sources", "add"],
    ["sources", "test"],
    ["sources", "remove"],
    ["users", "list"],
    ["users", "create"],
    ["users", "set-role"],
    ["users", "deactivate"],
    ["users", "reset-pw"],
    ["scheduler", "list"],
    ["scheduler", "pause"],
    ["scheduler", "resume"],
    ["scheduler", "cancel"],
    ["ai", "status"],
    ["ai", "insights"],
    ["ai", "toggle"],
]


class TestStubCommandsSafeExit:
    @pytest.mark.parametrize("cmd", _STUB_COMMANDS, ids=[" ".join(c) for c in _STUB_COMMANDS])
    def test_stub_exits_zero(self, cmd: list[str]):
        result = runner.invoke(app, cmd)
        assert result.exit_code == 0, (
            f"'{' '.join(cmd)}' exited with {result.exit_code}: {result.output}"
        )

    @pytest.mark.parametrize("cmd", _STUB_COMMANDS, ids=[" ".join(c) for c in _STUB_COMMANDS])
    def test_stub_prints_not_implemented(self, cmd: list[str]):
        result = runner.invoke(app, cmd)
        assert "Not implemented" in result.output, (
            f"'{' '.join(cmd)}' did not print 'Not implemented': {result.output!r}"
        )


class TestStubGroupHelp:
    @pytest.mark.parametrize("group", [
        "migrate", "backup", "logs", "update", "adapters",
        "channels", "sources", "users", "scheduler", "ai",
    ])
    def test_stub_group_help_exits_zero(self, group: str):
        result = runner.invoke(app, [group, "--help"])
        assert result.exit_code == 0
