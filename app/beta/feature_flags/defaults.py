"""WooPrice Beta — Feature flag boot-time defaults.

Used before the Beta database is initialized (first boot before migrations).
After first migration, flag state is read from beta_feature_flags table.

Implementation begins in B11.
"""

BOOT_DEFAULTS: dict[str, bool] = {
    "FEATURE_RULE_ENGINE": True,
    "FEATURE_SAFETY_ENGINE": True,
    "FEATURE_CHANGE_SETS": True,
    "FEATURE_DRY_RUN": True,
    "FEATURE_EXECUTION": True,
    "FEATURE_SCHEDULER": True,
    "FEATURE_AI": True,
    "FEATURE_MULTI_CHANNEL": False,
    "FEATURE_COMPETITOR_FEATURES": False,
    "FEATURE_PLUGIN_SYSTEM": True,
}
