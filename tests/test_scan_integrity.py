"""Regression tests for scans that cannot see everything they report on.

Three bugs are pinned here, each reproduced before it was fixed:

1. `Scanner.scan()` returned a clean, empty `ScanResult` for a nonexistent path
   and for a file — indistinguishable from a clean empty directory.
2. A file whose contents could not be read was treated as a file with no
   shebang, which produced a *fabricated* PL002 finding about bytes that were
   never read.
3. An unavailable Git index looked exactly like a Git index with nothing to
   report, so PL007 silently did not run.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from permlint.models import GitIndexStatus
from permlint.reporter import render_report
from permlint.scanner import InvalidTargetError, Scanner


def _unreadable(path: Path) -> bool:
    """Whether the file really cannot be read (root ignores permission bits)."""
    try:
        with open(path, "rb"):
            return False
    except OSError:
        return True


# ---------------------------------------------------------------------------
# 1. Invalid targets
# ---------------------------------------------------------------------------


def test_scan_rejects_a_nonexistent_path(tmp_path: Path) -> None:
    with pytest.raises(InvalidTargetError, match="does not exist"):
        Scanner().scan(tmp_path / "definitely_not_here")


def test_scan_rejects_a_file(tmp_path: Path) -> None:
    target = tmp_path / "a_file.txt"
    target.write_text("content\n")
    with pytest.raises(InvalidTargetError, match="not a directory"):
        Scanner().scan(target)


def test_scan_accepts_a_valid_empty_directory(tmp_path: Path) -> None:
    result = Scanner().scan(tmp_path)
    assert result.files_inspected == 0
    assert result.findings == []
    # An empty directory is a complete scan of nothing, not an incomplete one.
    assert result.diagnostics.entries_skipped == 0
    assert result.diagnostics.files_unreadable == 0


def test_scan_rejects_an_unreadable_directory(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    os.chmod(locked, 0o000)
    try:
        readable = True
        try:
            os.scandir(locked).close()
        except OSError:
            readable = False
        if not readable:
            with pytest.raises(InvalidTargetError, match="cannot be read"):
                Scanner().scan(locked)
    finally:
        os.chmod(locked, 0o755)


# ---------------------------------------------------------------------------
# 2. Unreadable file contents
# ---------------------------------------------------------------------------


def test_unreadable_file_does_not_produce_a_fabricated_finding(tmp_path: Path) -> None:
    """The original bug: PL002 fired for a file whose bytes were never read."""
    script = tmp_path / "script.sh"
    script.write_text("#!/bin/sh\necho hi\n")
    os.chmod(script, 0o111)  # executable, not readable
    try:
        if not _unreadable(script):
            pytest.skip("permission bits are not enforced for this user")

        result = Scanner().scan(tmp_path)

        assert [f.check_id for f in result.findings] == [], (
            "content checks must not conclude anything about an unreadable file"
        )
        assert result.diagnostics.files_unreadable == 1
        assert not result.diagnostics.is_complete
    finally:
        os.chmod(script, 0o755)


def test_unreadable_file_is_reported_to_the_user(tmp_path: Path, capsys) -> None:
    script = tmp_path / "script.sh"
    script.write_text("#!/bin/sh\n")
    os.chmod(script, 0o111)
    try:
        if not _unreadable(script):
            pytest.skip("permission bits are not enforced for this user")

        render_report(Scanner().scan(tmp_path))
        output = capsys.readouterr().out

        assert "Scan was incomplete" in output
        assert "could not be read" in output
    finally:
        os.chmod(script, 0o755)


def test_readable_file_still_produces_its_finding(tmp_path: Path) -> None:
    """The guard must not suppress genuine findings."""
    script = tmp_path / "script.sh"
    script.write_text("no shebang here\n")
    os.chmod(script, 0o755)

    result = Scanner().scan(tmp_path)

    assert "PL002" in [f.check_id for f in result.findings]
    assert result.diagnostics.files_unreadable == 0


def test_shebang_and_binary_state_is_unknown_rather_than_false(tmp_path: Path) -> None:
    from permlint.filesystem import FileInfo

    target = tmp_path / "opaque.sh"
    target.write_text("#!/bin/sh\n")
    os.chmod(target, 0o111)
    try:
        if not _unreadable(target):
            pytest.skip("permission bits are not enforced for this user")

        info = FileInfo(
            path=target,
            rel_path=Path("opaque.sh"),
            mode=os.stat(target).st_mode,
        )
        assert info.content_readable is False
        assert info.shebang_info.readable is False
        assert info.is_binary() is None, "unreadable is not 'not binary'"
        assert info.has_shebang() is False
        assert info.content_read_failed() is True
    finally:
        os.chmod(target, 0o755)


def test_content_read_failure_is_not_counted_for_untouched_files(tmp_path: Path) -> None:
    """A file no content check needed is not an unreadable file."""
    data = tmp_path / "notes.txt"
    data.write_text("plain\n")
    data.chmod(0o644)

    result = Scanner().scan(tmp_path)
    assert result.diagnostics.files_unreadable == 0


# ---------------------------------------------------------------------------
# 3. Git index availability
# ---------------------------------------------------------------------------


def test_non_repository_reports_git_unavailable(tmp_path: Path) -> None:
    (tmp_path / "a.sh").write_text("#!/bin/sh\n")
    result = Scanner().scan(tmp_path)
    assert result.diagnostics.git_index_status is GitIndexStatus.NOT_A_REPOSITORY
    assert not result.diagnostics.git_comparison_available


def test_non_repository_says_so_without_calling_the_scan_incomplete(tmp_path: Path, capsys) -> None:
    """Regression: this used to print under "Scan was incomplete".

    `is_complete` said True while the report said incomplete. A directory that
    is not a repository has no index to compare against — that is an answer, not
    a gap, and the two must agree.
    """
    result = Scanner().scan(tmp_path)
    render_report(result)
    output = capsys.readouterr().out

    assert "Git index checks" in output
    assert "Not a Git repository" in output
    assert "do not apply" in output
    assert "Scan was incomplete" not in output
    assert result.diagnostics.is_complete
    assert result.exit_code == 0


def test_missing_git_executable_is_distinguished(tmp_path: Path, monkeypatch) -> None:
    """`git` absent from PATH is its own state, not 'nothing to report'."""
    from permlint import git as git_module

    def _no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(git_module.subprocess, "run", _no_git)
    _, status = git_module.get_git_index_modes(tmp_path)
    assert status is GitIndexStatus.GIT_UNAVAILABLE


def test_git_command_failure_is_an_error_state(tmp_path: Path, monkeypatch) -> None:
    from permlint import git as git_module

    def _boom(*args, **kwargs):
        raise subprocess.SubprocessError("exploded")

    monkeypatch.setattr(git_module.subprocess, "run", _boom)
    _, status = git_module.get_git_index_modes(tmp_path)
    assert status is GitIndexStatus.ERROR


def test_real_repository_reports_git_available(tmp_path: Path) -> None:
    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        pytest.skip("git unavailable")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.sh").write_text("#!/bin/sh\n")
    subprocess.run(["git", "add", "a.sh"], cwd=tmp_path, check=True)

    result = Scanner().scan(tmp_path)
    assert result.diagnostics.git_index_status is GitIndexStatus.AVAILABLE
    assert result.diagnostics.git_comparison_available
    assert result.diagnostics.is_complete


def test_available_git_index_is_not_flagged_as_incomplete(tmp_path: Path, capsys) -> None:
    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        pytest.skip("git unavailable")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("x\n")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)

    render_report(Scanner().scan(tmp_path))
    assert "Scan was incomplete" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Completeness semantics
# ---------------------------------------------------------------------------


def test_absent_git_index_is_not_counted_as_incomplete(tmp_path: Path) -> None:
    """A plain directory has no index to compare against; that is an answer."""
    (tmp_path / "a.txt").write_text("x\n")
    result = Scanner().scan(tmp_path)
    assert result.diagnostics.git_index_status is GitIndexStatus.NOT_A_REPOSITORY
    assert result.diagnostics.is_complete


def test_failed_git_invocation_is_counted_as_incomplete(tmp_path: Path) -> None:
    """A broken `git` means PL007 did not run, which is a gap."""
    from permlint.models import ScanDiagnostics

    assert not ScanDiagnostics(git_index_status=GitIndexStatus.ERROR).is_complete
    assert not ScanDiagnostics(git_index_status=GitIndexStatus.GIT_UNAVAILABLE).is_complete
    assert ScanDiagnostics(git_index_status=GitIndexStatus.AVAILABLE).is_complete
