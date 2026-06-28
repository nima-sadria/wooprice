"""Tests for app/beta/auth/jwt_service.py"""

from __future__ import annotations

import time
import pytest
import jwt as pyjwt

from app.beta.auth.jwt_service import create_access_token, decode_access_token


class TestCreateAccessToken:
    def test_returns_string(self):
        token = create_access_token(1, "alice", "admin")
        assert isinstance(token, str)

    def test_payload_fields(self):
        token = create_access_token(42, "bob", "viewer")
        payload = decode_access_token(token)
        assert payload["sub"] == "42"
        assert payload["username"] == "bob"
        assert payload["role"] == "viewer"
        assert payload["type"] == "access"

    def test_token_is_decodable(self):
        token = create_access_token(1, "alice", "admin")
        payload = decode_access_token(token)
        assert "exp" in payload
        assert "iat" in payload


class TestDecodeAccessToken:
    def test_raises_on_tampered_token(self):
        token = create_access_token(1, "alice", "admin")
        bad = token[:-4] + "XXXX"
        with pytest.raises(pyjwt.InvalidTokenError):
            decode_access_token(bad)

    def test_raises_on_wrong_type_claim(self, monkeypatch):
        import os, jwt
        secret = os.environ["BETA_JWT_SECRET"]
        bad_token = jwt.encode(
            {"sub": "1", "type": "refresh", "exp": 9999999999},
            secret,
            algorithm="HS256",
        )
        with pytest.raises(pyjwt.InvalidTokenError):
            decode_access_token(bad_token)

    def test_raises_on_wrong_secret(self):
        import jwt
        token = jwt.encode({"sub": "1", "type": "access", "exp": 9999999999}, "wrong-secret", algorithm="HS256")
        with pytest.raises(pyjwt.InvalidTokenError):
            decode_access_token(token)

    def test_missing_secret_raises_runtime_error(self, monkeypatch):
        monkeypatch.delenv("BETA_JWT_SECRET", raising=False)
        with pytest.raises(RuntimeError):
            create_access_token(1, "alice", "admin")
