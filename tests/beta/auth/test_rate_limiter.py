"""Tests for app/beta/auth/rate_limiter.py"""

from __future__ import annotations

import pytest
from app.beta.auth.rate_limiter import check_rate_limit, clear_all, record_attempt


@pytest.fixture(autouse=True)
def reset_limiter():
    clear_all()
    yield
    clear_all()


class TestRateLimiter:
    def test_first_request_allowed(self):
        assert check_rate_limit("1.2.3.4") is True

    def test_five_attempts_still_allowed(self):
        for _ in range(5):
            record_attempt("1.2.3.4")
        # 6th check: 5 recorded, window allows < 5 more... wait, limit is 5 attempts
        # After 5 recorded, the 6th check should fail
        assert check_rate_limit("1.2.3.4") is False

    def test_four_attempts_still_allowed(self):
        for _ in range(4):
            record_attempt("1.2.3.4")
        assert check_rate_limit("1.2.3.4") is True

    def test_different_ips_are_independent(self):
        for _ in range(5):
            record_attempt("1.2.3.4")
        assert check_rate_limit("1.2.3.4") is False
        assert check_rate_limit("5.6.7.8") is True

    def test_clear_all_resets_state(self):
        for _ in range(5):
            record_attempt("1.2.3.4")
        assert check_rate_limit("1.2.3.4") is False
        clear_all()
        assert check_rate_limit("1.2.3.4") is True
