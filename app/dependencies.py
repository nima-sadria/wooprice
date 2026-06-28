"""WooPrice Beta — FastAPI dependency injectors.

Provides injectable dependencies for all API route handlers.

Planned dependency functions:
    get_config()         — Yields the typed BetaConfig object from ConfigurationManager.
                           No route may read os.environ directly.
    get_db()             — Yields an async SQLAlchemy session scoped to the request.
                           Closes and rolls back on exception.
    get_current_user()   — Validates the JWT from Authorization header and returns
                           the authenticated BetaUser. Raises HTTP 401 if missing/invalid.
    get_admin_user()     — Like get_current_user() but additionally enforces is_admin.
                           Raises HTTP 403 for non-admin callers.
    get_feature_flags()  — Yields the FeatureFlagEvaluator bound to the current request
                           user scope.
    get_plugin_registry() — Yields the read-only PluginRegistry view.

Usage (placeholder shape):
    @router.get("/example")
    async def example(
        config: BetaConfig = Depends(get_config),
        user: BetaUser = Depends(get_current_user),
    ) -> dict:
        ...

Implementation begins in B7 — Authentication Foundation.
"""

# Implementation begins in B7 — Authentication Foundation.
