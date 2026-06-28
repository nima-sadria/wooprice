"""WooPrice Beta — Authentication and authorization.

JWT-based authentication for all /api/v2/ and /api/beta/ endpoints.

Design:
- Short-lived access tokens signed with BETA_JWT_SECRET (default TTL: 15 min)
- Long-lived refresh tokens rotated on use (default TTL: 7 days)
- Permission model: named permissions per BetaUser; admin users hold all permissions
- Feature flag gates applied per-endpoint after permission check
- Control Plane rule: local credential login is always available; no external
  identity provider may be required for admin access

Auth flow:
    Request
      → Auth Middleware (extract + validate JWT from Authorization: Bearer)
      → Permission Guard (per-endpoint named permission check)
      → Feature Flag Gate (per-endpoint flag check)
      → Handler

Implementation begins in B7 — Authentication Foundation.
"""

# Implementation begins in B7 — Authentication Foundation.
