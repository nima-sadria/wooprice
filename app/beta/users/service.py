"""WooPrice Beta — UserService.

Business logic for user management: create, authenticate, deactivate,
reset password, assign permissions.

Implementation begins in B10.
"""


class UserService:
    """Business logic for user management.

    Implementation begins in B10.
    """

    def create_user(self, *, email: str, password: str, is_admin: bool = False) -> "BetaUser":
        """Create a new user with hashed password.

        Implementation begins in B10.
        """
        raise NotImplementedError("Implementation begins in B10.")

    def authenticate(self, *, email: str, password: str) -> "BetaUser":
        """Verify credentials and return the user.

        Raises ValueError if credentials are invalid.

        Implementation begins in B10.
        """
        raise NotImplementedError("Implementation begins in B10.")

    def reset_password(self, user_id: str, new_password: str) -> None:
        """Reset a user's password (admin-initiated).

        Implementation begins in B10.
        """
        raise NotImplementedError("Implementation begins in B10.")
