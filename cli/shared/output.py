"""WooPrice Beta — CLI output utilities (Rich console)."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich import box

from app.beta.config import ConfigProfile

console = Console()
err_console = Console(stderr=True)

_BANNER_STYLES: dict[ConfigProfile, str] = {
    ConfigProfile.DEV: "bold yellow",
    ConfigProfile.BETA: "bold cyan",
    ConfigProfile.PRODUCTION: "bold red",
}


def print_banner(profile: ConfigProfile | None = None) -> None:
    """Print the environment banner. Called on every CLI invocation."""
    label = profile.banner() if profile else "[BETA ENVIRONMENT]"
    style = _BANNER_STYLES.get(profile, "bold cyan") if profile else "bold cyan"
    console.print(f"\n  WooPrice  {label}\n", style=style)


def print_production_warning() -> None:
    """Print strong PRODUCTION warning block."""
    console.print("\n[bold red]" + "━" * 56 + "[/bold red]")
    console.print("[bold red]  ⚠  PRODUCTION PROFILE DETECTED  ⚠[/bold red]")
    console.print("[bold red]" + "━" * 56 + "[/bold red]")
    console.print("[red]  Write operations are BLOCKED in the PRODUCTION profile.")
    console.print("  Only read-only diagnostics are permitted.[/red]\n")


def print_error(message: str, suggestion: str | None = None) -> None:
    """Print a formatted error message with optional recovery suggestion."""
    err_console.print(f"[bold red]✗ Error:[/bold red] {message}")
    if suggestion:
        err_console.print(f"  [dim]{suggestion}[/dim]")


def print_success(message: str) -> None:
    """Print a formatted success message."""
    console.print(f"[bold green]✓[/bold green] {message}")


def print_warning(message: str) -> None:
    """Print a formatted warning."""
    console.print(f"[bold yellow]⚠[/bold yellow]  {message}")


def print_info(message: str) -> None:
    """Print an informational message."""
    console.print(f"  {message}")


def print_section(title: str) -> None:
    """Print a section divider."""
    console.print(f"\n[bold]{title}[/bold]")
    console.print("  " + "─" * (len(title) + 2))


def make_table(title: str | None = None) -> Table:
    """Create a styled Rich table."""
    return Table(
        title=title,
        box=box.SIMPLE,
        show_header=True,
        header_style="bold",
        padding=(0, 1),
    )
