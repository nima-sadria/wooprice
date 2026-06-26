"""WooPrice Beta — Environment safety guard.

Checks BETA_ENV before every write operation. Refuses to proceed if
a production resource (database URL, WooCommerce URL) is detected.

Implementation begins in B4.
"""


class ProductionResourceError(Exception):
    """Raised when a production resource is detected in Beta configuration."""
    pass


def check_environment() -> None:
    """Verify the current environment is not production before write operations.

    Raises ProductionResourceError if production resources are detected.

    Implementation begins in B4.
    """
    raise NotImplementedError("Implementation begins in B4.")


def require_beta_env() -> None:
    """Assert BETA_ENV == 'beta' or raise with clear error.

    Implementation begins in B4.
    """
    raise NotImplementedError("Implementation begins in B4.")
