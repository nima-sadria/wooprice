"""WooPrice Beta — CLI output utilities (Rich console).

Provides the [BETA ENVIRONMENT] banner, structured tables, status badges,
and error formatting. Uses Rich for all terminal output.

Implementation begins in B4.
"""


def print_banner(env_label: str = "BETA ENVIRONMENT") -> None:
    """Print the environment banner. Called on every CLI invocation.

    Implementation begins in B4.
    """
    raise NotImplementedError("Implementation begins in B4.")


def print_error(message: str, suggestion: str | None = None) -> None:
    """Print a formatted error message with optional recovery suggestion.

    Implementation begins in B4.
    """
    raise NotImplementedError("Implementation begins in B4.")


def print_success(message: str) -> None:
    """Print a formatted success message.

    Implementation begins in B4.
    """
    raise NotImplementedError("Implementation begins in B4.")
