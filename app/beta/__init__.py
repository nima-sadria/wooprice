"""WooPrice Beta — Beta-specific extensions package.

Builds on the frozen A2 Platform Core (app/a2/) without modifying it.
All Beta-only functionality lives in this package.

One-way dependency rule: app/a2/ must never import from app/beta/.

Implementation of individual modules begins in later B phases.
"""
