"""WooPrice Beta — FeatureFlag ORM model.

Defines the beta_feature_flags table in the Beta database.

Implementation begins in B11 (migration: beta_001).
"""


class FeatureFlag:
    """ORM model for the beta_feature_flags table.

    Fields: id (flag name), is_enabled, description, admin_only,
    locked, updated_at, updated_by.

    Implementation begins in B11.
    """
    pass
