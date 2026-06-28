"""Tests for app/beta/auth/password.py"""

from __future__ import annotations

import pytest
from app.beta.auth.password import hash_password, verify_password


class TestHashPassword:
    def test_returns_string(self):
        assert isinstance(hash_password("secret"), str)

    def test_hash_starts_with_argon2(self):
        assert hash_password("secret").startswith("$argon2")

    def test_different_hashes_for_same_password(self):
        # Argon2 uses random salts
        assert hash_password("secret") != hash_password("secret")

    def test_non_empty_output(self):
        assert len(hash_password("x")) > 20


class TestVerifyPassword:
    def test_correct_password_returns_true(self):
        hashed = hash_password("correct-password")
        assert verify_password("correct-password", hashed) is True

    def test_wrong_password_returns_false(self):
        hashed = hash_password("correct-password")
        assert verify_password("wrong-password", hashed) is False

    def test_empty_password_against_non_empty_hash_returns_false(self):
        hashed = hash_password("nonempty")
        assert verify_password("", hashed) is False

    def test_invalid_hash_string_returns_false(self):
        assert verify_password("password", "not-a-valid-hash") is False

    def test_unicode_password(self):
        pwd = "p@ssw0rd-üñíçödé"
        hashed = hash_password(pwd)
        assert verify_password(pwd, hashed) is True
        assert verify_password("wrong", hashed) is False
