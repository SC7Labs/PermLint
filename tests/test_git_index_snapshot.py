"""Real Git index tests for staged modes, intent evidence, and conflicts."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from permlint import git as git_module
from permlint.git import get_git_index_snapshot
from permlint.models import GitIndexStatus
from permlint.scanner import Scanner

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git unavailable")


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=check)


def test_findings_carry_real_filesystem_and_index_modes(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    script = tmp_path / "run.sh"
    script.write_text("#!/bin/sh\necho run\n")
    script.chmod(0o644)
    _git(tmp_path, "add", "--", "run.sh")

    result = Scanner().scan(tmp_path)
    pl001 = next(finding for finding in result.findings if finding.check_id == "PL001")
    assert pl001.filesystem_mode is not None
    assert pl001.filesystem_mode & 0o777 == 0o644
    assert pl001.git_index_mode == "100644"
    assert pl001.expected_executable is True

    script.chmod(0o755)
    result = Scanner().scan(tmp_path)
    pl007 = next(finding for finding in result.findings if finding.check_id == "PL007")
    assert pl007.filesystem_mode is not None
    assert pl007.filesystem_mode & 0o777 == 0o755
    assert pl007.git_index_mode == "100644"
    assert pl007.expected_executable is True

    _git(tmp_path, "update-index", "--chmod=+x", "--", "run.sh")
    result = Scanner().scan(tmp_path)
    assert "PL007" not in {finding.check_id for finding in result.findings}
    assert result.diagnostics.git_index_status is GitIndexStatus.AVAILABLE


def test_unmerged_index_is_reported_without_guessing_a_mode(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "PermLint Test")
    conflict = tmp_path / "conflict.txt"
    conflict.write_text("base\n")
    _git(tmp_path, "add", "--", "conflict.txt")
    _git(tmp_path, "commit", "-qm", "base")

    _git(tmp_path, "checkout", "-qb", "feature")
    conflict.write_text("feature\n")
    _git(tmp_path, "commit", "-qam", "feature")

    _git(tmp_path, "checkout", "-qb", "alternate", "HEAD~1")
    conflict.write_text("alternate\n")
    _git(tmp_path, "commit", "-qam", "alternate")

    merge = _git(tmp_path, "merge", "feature", check=False)
    assert merge.returncode == 1

    snapshot = get_git_index_snapshot(tmp_path)
    assert snapshot.status is GitIndexStatus.AVAILABLE
    assert Path("conflict.txt") in snapshot.unmerged_paths
    assert snapshot.modes is not None
    assert Path("conflict.txt") not in snapshot.modes

    result = Scanner().scan(tmp_path)
    assert result.diagnostics.unmerged_index_paths == 1
    assert result.exit_code == 2
    assert not any(finding.check_id == "PL007" for finding in result.findings)


def test_git_environment_cannot_redirect_scan_to_another_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    intended = tmp_path / "intended"
    other = tmp_path / "other"
    intended.mkdir()
    other.mkdir()
    for root, mode in ((intended, 0o644), (other, 0o755)):
        _git(root, "init", "-q")
        script = root / "tool.sh"
        script.write_text("#!/bin/sh\n")
        script.chmod(mode)
        _git(root, "add", "--", "tool.sh")

    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    monkeypatch.setenv("GIT_INDEX_FILE", str(other / ".git" / "index"))

    snapshot = get_git_index_snapshot(intended)
    assert snapshot.status is GitIndexStatus.AVAILABLE
    assert snapshot.modes == {Path("tool.sh"): "100644"}


def test_truncated_git_index_listing_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    truncated = b"100644 " + b"a" * 40 + b" 0\ttool.sh"

    def _truncated(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout=truncated, stderr=b"")

    monkeypatch.setattr(git_module.subprocess, "run", _truncated)
    snapshot = get_git_index_snapshot(tmp_path)
    assert snapshot.status is GitIndexStatus.ERROR
    assert snapshot.modes is None


def test_git_error_classification_uses_c_locale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LC_ALL", "fr_FR.UTF-8")
    seen_environment: dict[str, str] = {}

    def _not_a_repo(*args, **kwargs):
        seen_environment.update(kwargs["env"])
        return subprocess.CompletedProcess(
            args[0], 128, stdout=b"", stderr=b"fatal: not a git repository"
        )

    monkeypatch.setattr(git_module.subprocess, "run", _not_a_repo)
    snapshot = get_git_index_snapshot(tmp_path)
    assert seen_environment["LC_ALL"] == "C"
    assert snapshot.status is GitIndexStatus.NOT_A_REPOSITORY
