"""Tests for cli/create_admin.py (BU2)."""

from __future__ import annotations

import os
import pytest
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock

from cli.main import app

runner = CliRunner()


class TestCreateAdminHelp:
    def test_help_is_accessible(self):
        result = runner.invoke(app, ["create-admin", "--help"])
        assert result.exit_code == 0
        assert "admin" in result.output.lower()


class TestCreateAdminMissingEnv:
    def test_exits_1_when_no_db_url(self, monkeypatch):
        monkeypatch.delenv("BETA_DATABASE_URL", raising=False)
        result = runner.invoke(
            app,
            ["create-admin", "--username", "admin", "--password", "pass", "--no-confirmation-prompt"],
            input="pass\npass\n",
            catch_exceptions=False,
        )
        # Should fail with clear error
        assert result.exit_code != 0 or "ERROR" in result.output


class TestCreateAdminSuccess:
    def test_creates_user_in_db(self, tmp_path):
        db_url = f"sqlite:///{tmp_path}/test.db"
        os.environ["BETA_DATABASE_URL"] = db_url
        os.environ["BETA_JWT_SECRET"] = "test-secret-create-admin"

        # Create tables
        from sqlalchemy import create_engine
        from app.beta.database import BetaBase, _get_engine
        from app.beta.auth import models  # noqa: F401

        _get_engine.cache_clear()
        engine = create_engine(db_url, connect_args={"check_same_thread": False})
        BetaBase.metadata.create_all(engine)

        result = runner.invoke(
            app,
            ["create-admin", "--username", "myadmin", "--password", "hunter2", "--env-file", str(tmp_path / ".env.beta")],
            input="myadmin\nhunter2\nhunter2\n",
        )

        assert "myadmin" in result.output or result.exit_code == 0

        from sqlalchemy.orm import sessionmaker
        from app.beta.auth.repository import get_user_by_username

        Session = sessionmaker(bind=engine)
        db = Session()
        user = get_user_by_username(db, "myadmin")
        db.close()
        engine.dispose()
        _get_engine.cache_clear()

        assert user is not None
        assert user.role == "admin"
        assert user.is_active is True

    def test_duplicate_username_exits_with_error(self, tmp_path):
        db_url = f"sqlite:///{tmp_path}/test2.db"
        os.environ["BETA_DATABASE_URL"] = db_url

        from sqlalchemy import create_engine
        from app.beta.database import BetaBase, _get_engine
        from app.beta.auth import models  # noqa: F401
        from app.beta.auth.password import hash_password
        from app.beta.auth.repository import create_user
        from sqlalchemy.orm import sessionmaker

        _get_engine.cache_clear()
        engine = create_engine(db_url, connect_args={"check_same_thread": False})
        BetaBase.metadata.create_all(engine)

        Session = sessionmaker(bind=engine)
        db = Session()
        create_user(db, username="existing", hashed_password=hash_password("pass"), role="admin")
        db.close()

        result = runner.invoke(
            app,
            ["create-admin", "--username", "existing", "--password", "hunter2", "--env-file", str(tmp_path / ".env.beta")],
            input="existing\nhunter2\nhunter2\n",
        )
        assert result.exit_code != 0
        engine.dispose()
        _get_engine.cache_clear()
