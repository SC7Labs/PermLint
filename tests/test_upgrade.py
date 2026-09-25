"""Tests for safe PermLint self-update command."""

from __future__ import annotations

import io
import subprocess
import urllib.error
from unittest.mock import ANY, MagicMock, patch

import pytest
from rich.console import Console
from typer.testing import CliRunner

from permlint.cli import app
from permlint.upgrade import (
    OFFICIAL_REPO,
    UpgradeError,
    fetch_latest_release,
    get_release_tag_and_version,
    install_release,
    parse_semver,
    perform_upgrade,
    verify_installed_version,
)

runner = CliRunner()


def test_parse_semver_valid() -> None:
    assert parse_semver("0.2.0") == (0, 2, 0)
    assert parse_semver("v0.2.0") == (0, 2, 0)
    assert parse_semver("1.10.3") == (1, 10, 3)
    assert parse_semver("v2.0.0") == (2, 0, 0)


def test_parse_semver_malformed() -> None:
    for invalid in [
        "",
        "invalid",
        "v1",
        "1.0",
        "01.2.3",
        "v0.2.0-rc1",
        "v0.2.0+build",
        "v0.2.0; rm -rf /",
        "../v0.2.0",
        "main",
    ]:
        with pytest.raises(ValueError):
            parse_semver(invalid)


def test_upgrade_already_current_same_version() -> None:
    output = io.StringIO()
    console = Console(file=output, color_system=None)

    release_payload = {
        "tag_name": "v0.2.0",
        "draft": False,
        "prerelease": False,
    }

    with (
        patch("permlint.upgrade.fetch_latest_release", return_value=release_payload),
        patch("permlint.upgrade.install_release") as mock_install,
    ):
        perform_upgrade(current_version="0.2.0", console=console)

    mock_install.assert_not_called()
    assert "PermLint is already up to date (0.2.0)." in output.getvalue()


def test_upgrade_already_current_newer_than_release() -> None:
    output = io.StringIO()
    console = Console(file=output, color_system=None)

    release_payload = {
        "tag_name": "v0.1.0",
        "draft": False,
        "prerelease": False,
    }

    with (
        patch("permlint.upgrade.fetch_latest_release", return_value=release_payload),
        patch("permlint.upgrade.install_release") as mock_install,
    ):
        perform_upgrade(current_version="0.2.0", console=console)

    mock_install.assert_not_called()
    assert "PermLint is already up to date (0.2.0)." in output.getvalue()


def test_upgrade_newer_version_available_shows_details() -> None:
    output = io.StringIO()
    console = Console(file=output, color_system=None)

    release_payload = {
        "tag_name": "v0.3.0",
        "draft": False,
        "prerelease": False,
    }

    with (
        patch("permlint.upgrade.fetch_latest_release", return_value=release_payload),
        patch("permlint.upgrade.install_release") as mock_install,
        patch("permlint.upgrade.verify_installed_version", return_value="0.3.0"),
    ):
        perform_upgrade(current_version="0.2.0", console=console)

    mock_install.assert_called_once_with(
        source_url=f"git+https://github.com/{OFFICIAL_REPO}.git@v0.3.0",
        python_bin=ANY,
    )
    result_text = output.getvalue()
    assert "Current version: 0.2.0" in result_text
    assert "Latest version:  0.3.0" in result_text
    assert f"Source:          git+https://github.com/{OFFICIAL_REPO}.git@v0.3.0" in result_text
    assert "Successfully upgraded PermLint to 0.3.0." in result_text


def test_upgrade_malformed_release_tag() -> None:
    release_payload = {
        "tag_name": "not-a-valid-tag",
        "draft": False,
        "prerelease": False,
    }

    with (
        patch("permlint.upgrade.fetch_latest_release", return_value=release_payload),
        patch("permlint.upgrade.install_release") as mock_install,
    ):
        with pytest.raises(UpgradeError, match="Malformed release tag 'not-a-valid-tag'"):
            perform_upgrade(current_version="0.2.0")

    mock_install.assert_not_called()


def test_upgrade_missing_release_tag() -> None:
    release_payload = {
        "draft": False,
        "prerelease": False,
    }
    with pytest.raises(UpgradeError, match="missing 'tag_name'"):
        get_release_tag_and_version(release_payload)


def test_upgrade_draft_or_prerelease_rejected() -> None:
    draft_payload = {"tag_name": "v0.3.0", "draft": True, "prerelease": False}
    with pytest.raises(UpgradeError, match="draft"):
        get_release_tag_and_version(draft_payload)

    prerelease_payload = {"tag_name": "v0.3.0", "draft": False, "prerelease": True}
    with pytest.raises(UpgradeError, match="prerelease"):
        get_release_tag_and_version(prerelease_payload)


def test_upgrade_github_network_error_urlerror() -> None:
    with patch(
        "urllib.request.OpenerDirector.open",
        side_effect=urllib.error.URLError("Connection refused"),
    ):
        with pytest.raises(UpgradeError, match="Network error querying GitHub Releases"):
            fetch_latest_release()


def test_upgrade_github_network_error_httperror_404() -> None:
    err = urllib.error.HTTPError(
        url="https://api.github.com/...", code=404, msg="Not Found", hdrs={}, fp=None
    )
    with patch("urllib.request.OpenerDirector.open", side_effect=err):
        with pytest.raises(UpgradeError, match=f"No releases found for {OFFICIAL_REPO}"):
            fetch_latest_release()


def test_upgrade_github_network_error_httperror_500() -> None:
    err = urllib.error.HTTPError(
        url="https://api.github.com/...",
        code=500,
        msg="Internal Server Error",
        hdrs={},
        fp=None,
    )
    with patch("urllib.request.OpenerDirector.open", side_effect=err):
        with pytest.raises(UpgradeError, match="HTTP 500"):
            fetch_latest_release()


def test_upgrade_github_timeout() -> None:
    with patch("urllib.request.OpenerDirector.open", side_effect=TimeoutError()):
        with pytest.raises(UpgradeError, match="timed out"):
            fetch_latest_release()


def test_upgrade_github_invalid_json() -> None:
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = b"<html>not json</html>"
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.OpenerDirector.open", return_value=mock_resp):
        with pytest.raises(UpgradeError, match="Failed to parse GitHub Releases API response"):
            fetch_latest_release()


def test_upgrade_install_failure() -> None:
    source = f"git+https://github.com/{OFFICIAL_REPO}.git@v0.3.0"
    failed_proc = subprocess.CompletedProcess(
        args=["pip"],
        returncode=1,
        stdout="",
        stderr="error: could not build wheel",
    )

    with patch("subprocess.run", return_value=failed_proc):
        with pytest.raises(UpgradeError, match="pip install failed"):
            install_release(source_url=source)


def test_upgrade_install_permission_failure() -> None:
    source = f"git+https://github.com/{OFFICIAL_REPO}.git@v0.3.0"
    failed_proc = subprocess.CompletedProcess(
        args=["pip"],
        returncode=1,
        stdout="",
        stderr="[Errno 13] Permission denied: '/usr/local/lib/python3.13/site-packages'",
    )

    with patch("subprocess.run", return_value=failed_proc):
        with pytest.raises(UpgradeError, match="insufficient permissions"):
            install_release(source_url=source)


def test_upgrade_install_unauthorized_source() -> None:
    with pytest.raises(UpgradeError, match="Refusing to install from unauthorized source"):
        install_release(source_url="git+https://github.com/attacker/malicious.git@v1.0.0")


def test_upgrade_verification_mismatch() -> None:
    # Subprocess claims to run python and print version 0.2.0 (mismatch when expecting 0.3.0)
    verify_proc = subprocess.CompletedProcess(
        args=["python"],
        returncode=0,
        stdout="0.2.0\n",
        stderr="",
    )

    with patch("subprocess.run", return_value=verify_proc):
        with pytest.raises(UpgradeError, match="Post-upgrade verification mismatch"):
            verify_installed_version(expected_version="0.3.0")


def test_upgrade_verification_failure_exit_code() -> None:
    verify_proc = subprocess.CompletedProcess(
        args=["python"],
        returncode=1,
        stdout="",
        stderr="ModuleNotFoundError: No module named permlint",
    )

    with patch("subprocess.run", return_value=verify_proc):
        with pytest.raises(UpgradeError, match="Post-upgrade verification failed"):
            verify_installed_version(expected_version="0.3.0")


def test_upgrade_security_non_https_api_rejected() -> None:
    with pytest.raises(UpgradeError, match="Refusing to query non-official or non-HTTPS"):
        fetch_latest_release(api_url="http://api.github.com/repos/SC7Labs/PermLint/releases/latest")


def test_upgrade_cli_already_current_exit_0() -> None:
    release_payload = {
        "tag_name": "v0.2.0",
        "draft": False,
        "prerelease": False,
    }
    with patch("permlint.upgrade.fetch_latest_release", return_value=release_payload):
        result = runner.invoke(app, ["upgrade"])
        assert result.exit_code == 0
        assert "PermLint is already up to date (0.2.0)." in result.output


def test_upgrade_cli_newer_release_success_exit_0() -> None:
    release_payload = {
        "tag_name": "v0.3.0",
        "draft": False,
        "prerelease": False,
    }
    with (
        patch("permlint.upgrade.fetch_latest_release", return_value=release_payload),
        patch("permlint.upgrade.install_release"),
        patch("permlint.upgrade.verify_installed_version", return_value="0.3.0"),
    ):
        result = runner.invoke(app, ["upgrade"])
        assert result.exit_code == 0
        assert "Current version: 0.2.0" in result.output
        assert "Latest version:  0.3.0" in result.output
        expected_src = f"Source:          git+https://github.com/{OFFICIAL_REPO}.git@v0.3.0"
        assert expected_src in result.output
        assert "Successfully upgraded PermLint to 0.3.0." in result.output


def test_upgrade_cli_error_exits_2() -> None:
    with patch(
        "permlint.upgrade.fetch_latest_release",
        side_effect=UpgradeError("Network error querying GitHub Releases: Name resolution failure"),
    ):
        result = runner.invoke(app, ["upgrade"])
        assert result.exit_code == 2
        assert "Error:" in result.output
        assert "Network error querying GitHub Releases" in result.output
