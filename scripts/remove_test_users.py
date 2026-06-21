#!/usr/bin/env python3
"""One-shot cleanup: remove test-fixture accounts from the production database.

These usernames were seeded by unit-test helpers in tests/test_project71.py and
should never exist in the production app_users table.

Run inside the container:
    docker exec -it wooprice python scripts/remove_test_users.py

Or locally (point DATABASE_URL at the real database):
    DATABASE_URL=sqlite:////app/data/wooprice.db python scripts/remove_test_users.py

Nextcloud accounts (dbadmin71, dbadmin72, etc.) must be removed separately by
a Nextcloud administrator — this script only removes WooPrice permission records.
"""
import os
import sys

# Minimal env so Settings() doesn't error on required fields before we import.
for _k, _v in [
    ("NEXTCLOUD_URL", "http://placeholder"),
    ("NEXTCLOUD_USER", "placeholder"),
    ("NEXTCLOUD_PASSWORD", "placeholder"),
    ("NEXTCLOUD_FILE_PATH", "/placeholder"),
    ("WC_URL", "http://placeholder"),
    ("WC_KEY", "placeholder"),
    ("WC_SECRET", "placeholder"),
]:
    os.environ.setdefault(_k, _v)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_USERNAMES = [
    "dbadmin71",
    "dbadmin72",
    "permtest71",
    "permtest72",
    "listtest71",
    "normaluser71",
]


def main() -> None:
    from app.database import SessionLocal
    from app.models import AppUser

    db = SessionLocal()
    try:
        removed: list[str] = []
        not_found: list[str] = []
        for username in TEST_USERNAMES:
            row = db.query(AppUser).filter(AppUser.username == username).first()
            if row:
                db.delete(row)
                removed.append(username)
            else:
                not_found.append(username)

        if removed:
            db.commit()
            print(f"Removed {len(removed)} test user(s): {', '.join(removed)}")
        else:
            print("No test users found — database is already clean.")

        if not_found:
            print(f"Not present (skipped): {', '.join(not_found)}")

        remaining = db.query(AppUser).order_by(AppUser.username).all()
        admins = [u.username for u in remaining if u.is_admin and u.is_active]
        active_users = [u.username for u in remaining if u.is_active and not u.is_admin]
        inactive = [u.username for u in remaining if not u.is_active]

        print(f"\nPost-cleanup state:")
        print(f"  Active admins  ({len(admins)}): {', '.join(admins) or '—'}")
        print(f"  Active users   ({len(active_users)}): {', '.join(active_users) or '—'}")
        print(f"  Inactive users ({len(inactive)}): {', '.join(inactive) or '—'}")
        print("\nNextcloud accounts must be removed separately by a Nextcloud administrator.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
