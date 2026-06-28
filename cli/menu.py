"""WooPrice Beta — interactive management menu (BU1).

Displayed when `wooprice` is launched with no arguments.
Each option dispatches to an existing CLI command or shows a placeholder
for features not yet implemented.
"""

from __future__ import annotations

from typing import Callable

_MENU_TEXT = """\

--------------------------------------------------------
  WooPrice Beta  [BETA ENVIRONMENT]
--------------------------------------------------------

  1. Status
  2. Health
  3. Configure
  4. Diagnostics
  5. Logs
  6. Restart Services
  7. Exit

--------------------------------------------------------"""

_PROMPT = "  Enter choice [1-7]: "
_COMING_SOON = "  Coming in future phase."


def _run_subcommand(*args: str) -> None:
    """Invoke an existing wooprice CLI subcommand in-process via the Typer app.

    Deferred import breaks the cli.main → cli.menu → cli.main circular chain.
    SystemExit(0) is swallowed; non-zero exits are also suppressed so a failing
    subcommand returns the user to the menu rather than killing the process.
    """
    from cli.main import app  # deferred: cli.main is fully loaded by call time
    try:
        app(args=list(args), standalone_mode=True)
    except SystemExit:
        pass


def _menu_status() -> None:
    _run_subcommand("status")


def _menu_health() -> None:
    _run_subcommand("health")


def _menu_configure() -> None:
    _run_subcommand("configure", "show")


def _menu_diagnostics() -> None:
    _run_subcommand("diagnostics")


def _menu_logs() -> None:
    print(_COMING_SOON)


def _menu_restart() -> None:
    print(_COMING_SOON)


_DISPATCH: dict[str, Callable[[], None]] = {
    "1": _menu_status,
    "2": _menu_health,
    "3": _menu_configure,
    "4": _menu_diagnostics,
    "5": _menu_logs,
    "6": _menu_restart,
}


def show_menu(_input_fn: Callable[[], str] | None = None) -> None:
    """Display and drive the interactive management menu loop.

    _input_fn: optional callable that returns the next input string.  Used by
    tests to supply pre-programmed responses without touching stdin.
    In production, stdin is read via the builtin input().
    """
    interactive = _input_fn is None

    def _read() -> str:
        if interactive:
            return input(_PROMPT)
        return _input_fn()  # type: ignore[misc]

    while True:
        print(_MENU_TEXT)
        try:
            choice = _read().strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Exiting.")
            return

        if choice in ("7", "exit", "q", "quit", ""):
            print("  Exiting.")
            return

        handler = _DISPATCH.get(choice)
        if handler is None:
            print(f"\n  Invalid choice '{choice}'. Enter a number from 1 to 7.\n")
            continue

        print()
        try:
            handler()
        except KeyboardInterrupt:
            print("\n  (interrupted)")

        if interactive:
            try:
                input("\n  Press Enter to return to menu...")
            except (EOFError, KeyboardInterrupt):
                return
