"""WooPrice Beta — UserRepository.

Persistence layer for BetaUser and Permission records.

Implementation begins in B10.
"""


class UserNotFoundError(Exception):
    """Raised when a user lookup finds no matching record."""
    pass


class UserRepository:
    """Persistence layer for BetaUser and Permission records.

    Implementation begins in B10.
    """

    def create(self, *, email: str, hashed_password: str, is_admin: bool = False) -> "BetaUser":
        """Create and persist a new user.

        Implementation begins in B10.
        """
        raise NotImplementedError("Implementation begins in B10.")

    def get_by_id(self, user_id: str) -> "BetaUser":
        """Return user by ID. Raises UserNotFoundError if absent.

        Implementation begins in B10.
        """
        raise NotImplementedError("Implementation begins in B10.")

    def get_by_email(self, email: str) -> "BetaUser":
        """Return user by email. Raises UserNotFoundError if absent.

        Implementation begins in B10.
        """
        raise NotImplementedError("Implementation begins in B10.")

    def list_all(self) -> list:
        """Return all users.

        Implementation begins in B10.
        """
        raise NotImplementedError("Implementation begins in B10.")

    def deactivate(self, user_id: str) -> None:
        """Set is_active=False for a user (non-destructive).

        Implementation begins in B10.
        """
        raise NotImplementedError("Implementation begins in B10.")

    def set_permissions(self, user_id: str, permissions: list[str]) -> None:
        """Replace the permission set for a user.

        Implementation begins in B10.
        """
        raise NotImplementedError("Implementation begins in B10.")
