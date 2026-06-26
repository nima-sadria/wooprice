"""WooPrice Beta — BetaUser and Permission ORM models.

Defines beta_users and beta_permissions tables in the Beta database.

Implementation begins in B10 (migration: beta_001).
"""


class BetaUser:
    """ORM model for the beta_users table.

    Fields: id, email, hashed_password, is_admin, is_active,
    created_at, last_login_at.

    Implementation begins in B10.
    """
    pass


class Permission:
    """ORM model for the beta_user_permissions table.

    Fields: user_id (FK → beta_users.id), permission (named string).

    Implementation begins in B10.
    """
    pass
