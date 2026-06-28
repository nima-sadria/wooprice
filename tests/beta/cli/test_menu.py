"""Tests for cli/menu.py — interactive management menu (BU1)."""

from __future__ import annotations

from io import StringIO
from unittest.mock import MagicMock, call, patch

import pytest

from cli.menu import (
    _COMING_SOON,
    _DISPATCH,
    _menu_configure,
    _menu_diagnostics,
    _menu_health,
    _menu_logs,
    _menu_restart,
    _menu_status,
    show_menu,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _input_sequence(*responses: str):
    """Return an _input_fn that yields each response in order, then raises EOFError."""
    it = iter(responses)

    def _fn() -> str:
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    return _fn


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------


class TestDispatchTable:
    def test_seven_choices_registered(self):
        assert len(_DISPATCH) == 6  # 1-6; "7" is Exit handled directly

    def test_all_handlers_callable(self):
        for key, fn in _DISPATCH.items():
            assert callable(fn), f"handler for choice {key!r} is not callable"

    def test_choices_one_through_six(self):
        for i in range(1, 7):
            assert str(i) in _DISPATCH


# ---------------------------------------------------------------------------
# Exit paths
# ---------------------------------------------------------------------------


class TestMenuExit:
    def test_choice_7_exits(self, capsys):
        show_menu(_input_fn=_input_sequence("7"))
        out = capsys.readouterr().out
        assert "Exiting" in out

    def test_eof_exits_gracefully(self, capsys):
        def _eof():
            raise EOFError

        show_menu(_input_fn=_eof)
        out = capsys.readouterr().out
        assert "Exiting" in out

    def test_keyboard_interrupt_exits_gracefully(self, capsys):
        def _interrupt():
            raise KeyboardInterrupt

        show_menu(_input_fn=_interrupt)
        out = capsys.readouterr().out
        assert "Exiting" in out

    def test_empty_string_exits(self, capsys):
        show_menu(_input_fn=_input_sequence(""))
        out = capsys.readouterr().out
        assert "Exiting" in out

    def test_q_exits(self, capsys):
        show_menu(_input_fn=_input_sequence("q"))
        out = capsys.readouterr().out
        assert "Exiting" in out


# ---------------------------------------------------------------------------
# Invalid input
# ---------------------------------------------------------------------------


class TestMenuInvalidInput:
    def test_invalid_choice_shows_error_then_exits(self, capsys):
        show_menu(_input_fn=_input_sequence("99", "7"))
        out = capsys.readouterr().out
        assert "Invalid" in out or "invalid" in out

    def test_letter_shows_error_then_exits(self, capsys):
        show_menu(_input_fn=_input_sequence("z", "7"))
        out = capsys.readouterr().out
        assert "Invalid" in out or "invalid" in out


# ---------------------------------------------------------------------------
# Placeholder choices (5 and 6)
# ---------------------------------------------------------------------------


class TestMenuComingSoon:
    def test_logs_shows_coming_soon(self, capsys):
        _menu_logs()
        out = capsys.readouterr().out
        assert "Coming in future phase" in out

    def test_restart_shows_coming_soon(self, capsys):
        _menu_restart()
        out = capsys.readouterr().out
        assert "Coming in future phase" in out

    def test_choice_5_displays_coming_soon(self, capsys):
        show_menu(_input_fn=_input_sequence("5", "7"))
        out = capsys.readouterr().out
        assert "Coming in future phase" in out

    def test_choice_6_displays_coming_soon(self, capsys):
        show_menu(_input_fn=_input_sequence("6", "7"))
        out = capsys.readouterr().out
        assert "Coming in future phase" in out


# ---------------------------------------------------------------------------
# Dispatch to CLI subcommands
# ---------------------------------------------------------------------------


class TestMenuDispatch:
    """Verify that each menu choice invokes its registered handler.

    _DISPATCH holds function references set at module load time; patching the
    name after import does not update those references.  Use patch.dict to
    replace the dict entries directly, which is what show_menu actually reads.
    """

    def test_choice_1_calls_handler(self):
        mock = MagicMock()
        with patch.dict("cli.menu._DISPATCH", {"1": mock}):
            show_menu(_input_fn=_input_sequence("1", "7"))
        mock.assert_called_once()

    def test_choice_2_calls_handler(self):
        mock = MagicMock()
        with patch.dict("cli.menu._DISPATCH", {"2": mock}):
            show_menu(_input_fn=_input_sequence("2", "7"))
        mock.assert_called_once()

    def test_choice_3_calls_handler(self):
        mock = MagicMock()
        with patch.dict("cli.menu._DISPATCH", {"3": mock}):
            show_menu(_input_fn=_input_sequence("3", "7"))
        mock.assert_called_once()

    def test_choice_4_calls_handler(self):
        mock = MagicMock()
        with patch.dict("cli.menu._DISPATCH", {"4": mock}):
            show_menu(_input_fn=_input_sequence("4", "7"))
        mock.assert_called_once()


class TestDispatchMapping:
    """Verify that the dispatch table entries point to the correct functions."""

    def test_choice_1_maps_to_menu_status(self):
        assert _DISPATCH["1"] is _menu_status

    def test_choice_2_maps_to_menu_health(self):
        assert _DISPATCH["2"] is _menu_health

    def test_choice_3_maps_to_menu_configure(self):
        assert _DISPATCH["3"] is _menu_configure

    def test_choice_4_maps_to_menu_diagnostics(self):
        assert _DISPATCH["4"] is _menu_diagnostics

    def test_choice_5_maps_to_menu_logs(self):
        assert _DISPATCH["5"] is _menu_logs

    def test_choice_6_maps_to_menu_restart(self):
        assert _DISPATCH["6"] is _menu_restart


# ---------------------------------------------------------------------------
# Subprocess dispatch
# ---------------------------------------------------------------------------


class TestSubprocessDispatch:
    """Verify each handler calls the Typer app with the correct subcommand args.

    _run_subcommand uses a deferred `from cli.main import app` to avoid a
    circular import.  Patching cli.main.app replaces the module attribute so the
    deferred import inside _run_subcommand picks up the mock.
    """

    def test_menu_status_runs_status_subcommand(self):
        with patch("cli.main.app") as mock_app:
            _menu_status()
        mock_app.assert_called_once()
        _, kwargs = mock_app.call_args
        assert kwargs["args"] == ["status"]
        assert kwargs["standalone_mode"] is True

    def test_menu_health_runs_health_subcommand(self):
        with patch("cli.main.app") as mock_app:
            _menu_health()
        mock_app.assert_called_once()
        _, kwargs = mock_app.call_args
        assert kwargs["args"] == ["health"]

    def test_menu_configure_runs_configure_show(self):
        with patch("cli.main.app") as mock_app:
            _menu_configure()
        mock_app.assert_called_once()
        _, kwargs = mock_app.call_args
        assert kwargs["args"] == ["configure", "show"]

    def test_menu_diagnostics_runs_diagnostics_subcommand(self):
        with patch("cli.main.app") as mock_app:
            _menu_diagnostics()
        mock_app.assert_called_once()
        _, kwargs = mock_app.call_args
        assert kwargs["args"] == ["diagnostics"]

    def test_system_exit_from_app_is_suppressed(self):
        with patch("cli.main.app", side_effect=SystemExit(0)):
            _menu_status()  # must not propagate


# ---------------------------------------------------------------------------
# Menu text content
# ---------------------------------------------------------------------------


class TestMenuText:
    def test_menu_shows_all_seven_options(self, capsys):
        show_menu(_input_fn=_input_sequence("7"))
        out = capsys.readouterr().out
        for i in range(1, 8):
            assert str(i) in out

    def test_menu_shows_wooprice_beta(self, capsys):
        show_menu(_input_fn=_input_sequence("7"))
        out = capsys.readouterr().out
        assert "WooPrice Beta" in out

    def test_menu_shows_status_option(self, capsys):
        show_menu(_input_fn=_input_sequence("7"))
        out = capsys.readouterr().out
        assert "Status" in out

    def test_menu_shows_health_option(self, capsys):
        show_menu(_input_fn=_input_sequence("7"))
        out = capsys.readouterr().out
        assert "Health" in out

    def test_menu_shows_exit_option(self, capsys):
        show_menu(_input_fn=_input_sequence("7"))
        out = capsys.readouterr().out
        assert "Exit" in out


# ---------------------------------------------------------------------------
# cli/main.py integration — no-args invokes menu (not help)
# ---------------------------------------------------------------------------


class TestMainNoArgsInvokesMenu:
    def test_no_args_calls_show_menu(self):
        from typer.testing import CliRunner
        from cli.main import app

        runner = CliRunner()
        with patch("cli.menu.show_menu") as mock_menu:
            result = runner.invoke(app, [])
        mock_menu.assert_called_once()

    def test_help_still_works(self):
        from typer.testing import CliRunner
        from cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
