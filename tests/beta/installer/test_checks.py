"""Tests for installer prerequisite checks."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from installer.installer_core import (
    PrerequisiteResult,
    all_prerequisites_passed,
    check_prerequisites,
)


class TestPrerequisiteResult:
    def test_format_pass(self):
        r = PrerequisiteResult(name="test", passed=True, message="ok")
        assert "[PASS]" in r.format_line()
        assert "test" in r.format_line()
        assert "ok" in r.format_line()

    def test_format_fail_shows_fail(self):
        r = PrerequisiteResult(name="test", passed=False, message="not found", fix="install it")
        assert "[FAIL]" in r.format_line()

    def test_format_fail_includes_fix_when_provided(self):
        r = PrerequisiteResult(name="test", passed=False, message="missing", fix="apt install X")
        assert "apt install X" in r.format_line()

    def test_format_fail_no_fix_no_fix_line(self):
        r = PrerequisiteResult(name="test", passed=False, message="missing")
        assert "Fix:" not in r.format_line()

    def test_format_pass_no_fix_line(self):
        r = PrerequisiteResult(name="test", passed=True, message="ok", fix="never shown")
        assert "Fix:" not in r.format_line()


class TestCheckPrerequisites:
    def test_returns_list(self):
        results = check_prerequisites()
        assert isinstance(results, list)
        assert len(results) >= 1

    def test_python_check_present(self):
        results = check_prerequisites()
        names = [r.name for r in results]
        assert any("Python" in n for n in names)

    def test_python_check_passes_on_current_interpreter(self):
        results = check_prerequisites()
        python_check = next(r for r in results if "Python" in r.name)
        assert python_check.passed is True

    def test_python_check_message_contains_version(self):
        results = check_prerequisites()
        python_check = next(r for r in results if "Python" in r.name)
        version_str = f"{sys.version_info.major}.{sys.version_info.minor}"
        assert version_str in python_check.message

    def test_docker_check_present(self):
        results = check_prerequisites()
        assert any("docker" in r.name.lower() for r in results)

    def test_openssl_check_present(self):
        results = check_prerequisites()
        assert any("openssl" in r.name.lower() for r in results)

    def test_no_install_dir_means_no_write_permission_check(self):
        results = check_prerequisites(install_dir=None)
        assert not any("write permission" in r.name for r in results)

    def test_writable_dir_check_passes_for_tmp(self, tmp_path: Path):
        results = check_prerequisites(install_dir=tmp_path)
        perm_check = next((r for r in results if "write permission" in r.name), None)
        assert perm_check is not None
        assert perm_check.passed is True

    def test_writable_dir_check_for_nonexistent_subdir_uses_parent(self, tmp_path: Path):
        subdir = tmp_path / "new_install_dir"
        results = check_prerequisites(install_dir=subdir)
        perm_check = next((r for r in results if "write permission" in r.name), None)
        assert perm_check is not None
        assert perm_check.passed is True

    def test_no_docker_execution(self):
        # check_prerequisites must not call subprocess or os.system to run docker
        import subprocess
        with patch.object(subprocess, "run", side_effect=AssertionError("subprocess.run called")) as mock_run:
            with patch.object(subprocess, "check_output", side_effect=AssertionError("subprocess.check_output called")):
                # should not raise
                results = check_prerequisites()
        assert results  # still returns results

    def test_no_network_calls(self):
        import socket
        with patch.object(socket, "create_connection", side_effect=AssertionError("network call made")):
            results = check_prerequisites()
        assert results

    def test_prerequisite_result_has_all_fields(self):
        results = check_prerequisites()
        for r in results:
            assert hasattr(r, "name")
            assert hasattr(r, "passed")
            assert hasattr(r, "message")
            assert hasattr(r, "fix")

    def test_missing_docker_command_fails(self):
        import shutil
        original_which = shutil.which

        def mock_which(cmd):
            if cmd == "docker":
                return None
            return original_which(cmd)

        with patch("shutil.which", side_effect=mock_which):
            results = check_prerequisites()
        docker_result = next((r for r in results if r.name == "docker command"), None)
        assert docker_result is not None
        assert docker_result.passed is False

    def test_missing_openssl_command_fails(self):
        import shutil
        original_which = shutil.which

        def mock_which(cmd):
            if cmd == "openssl":
                return None
            return original_which(cmd)

        with patch("shutil.which", side_effect=mock_which):
            results = check_prerequisites()
        openssl_result = next((r for r in results if r.name == "openssl command"), None)
        assert openssl_result is not None
        assert openssl_result.passed is False
        assert openssl_result.fix  # has remediation instruction


class TestAllPrerequisitesPassed:
    def test_all_pass(self):
        results = [
            PrerequisiteResult("a", True, "ok"),
            PrerequisiteResult("b", True, "ok"),
        ]
        assert all_prerequisites_passed(results) is True

    def test_one_fail(self):
        results = [
            PrerequisiteResult("a", True, "ok"),
            PrerequisiteResult("b", False, "fail"),
        ]
        assert all_prerequisites_passed(results) is False

    def test_empty_list(self):
        assert all_prerequisites_passed([]) is True
