"""Regression tests: an incomplete scan must never look like a clean one.

Four bugs are pinned here. The shared theme is the same as the rest of PermLint:
"I could not look" and "I looked and it was fine" must not produce the same
signal — least of all the same exit code, which is the only thing CI reads.

Fault injection is used in preference to `chmod`, because permission bits are
not enforced for root and several sandboxes run tests as root.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from permlint import filesystem as fs_module
from permlint import git as git_module
from permlint.cli import app
from permlint.models import GitIndexStatus, ScanDiagnostics, ScanResult
from permlint.reporter import render_report
from permlint.scanner import Scanner

runner = CliRunner()


def _git_available() -> bool:
    try:
        return subprocess.run(["git", "--version"], capture_output=True).returncode == 0
    except OSError:
        return False


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


# ---------------------------------------------------------------------------
# 1. Exit codes come from one place and account for completeness
# ---------------------------------------------------------------------------


def _result(**diagnostics) -> ScanResult:
    return ScanResult(
        target_path=Path("/tmp/x"),
        files_inspected=1,
        diagnostics=ScanDiagnostics(**diagnostics),
    )


def test_complete_clean_scan_exits_zero() -> None:
    assert _result(git_index_status=GitIndexStatus.AVAILABLE).exit_code == 0


def test_non_git_directory_still_exits_zero() -> None:
    """Nothing to compare against is not an incomplete scan."""
    assert _result(git_index_status=GitIndexStatus.NOT_A_REPOSITORY).exit_code == 0


def test_git_unavailable_exits_two() -> None:
    """Regression: this printed "Scan was incomplete" and still exited 0."""
    assert _result(git_index_status=GitIndexStatus.GIT_UNAVAILABLE).exit_code == 2


def test_git_error_exits_two() -> None:
    assert _result(git_index_status=GitIndexStatus.ERROR).exit_code == 2


def test_skipped_directory_exits_two() -> None:
    assert _result(git_index_status=GitIndexStatus.AVAILABLE, directories_skipped=1).exit_code == 2


def test_unreadable_file_exits_two() -> None:
    assert _result(git_index_status=GitIndexStatus.AVAILABLE, files_unreadable=1).exit_code == 2


def test_skipped_entry_exits_two() -> None:
    assert _result(git_index_status=GitIndexStatus.AVAILABLE, entries_skipped=1).exit_code == 2


def test_findings_exit_one_even_when_complete(tmp_path: Path) -> None:
    target = tmp_path / "world.txt"
    target.write_text("x\n")
    target.chmod(0o666)
    assert Scanner().scan(tmp_path).exit_code == 1


def test_cli_exit_codes_come_from_the_result(tmp_path: Path, monkeypatch) -> None:
    """The CLI must not re-derive status; it maps `result.exit_code`."""
    monkeypatch.setattr(
        git_module.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError())
    )
    (tmp_path / "a.txt").write_text("x\n")
    (tmp_path / "a.txt").chmod(0o644)

    result = runner.invoke(app, [str(tmp_path)])
    assert result.exit_code == 2, "git unavailable is an incomplete scan"


def test_cli_invalid_target_exits_two(tmp_path: Path) -> None:
    assert runner.invoke(app, [str(tmp_path / "nope")]).exit_code == 2
    target = tmp_path / "f.txt"
    target.write_text("x\n")
    assert runner.invoke(app, [str(target)]).exit_code == 2


# ---------------------------------------------------------------------------
# 2. Reporter and is_complete must agree
# ---------------------------------------------------------------------------


def test_non_git_directory_is_not_called_incomplete(tmp_path: Path, capsys) -> None:
    (tmp_path / "a.txt").write_text("x\n")
    (tmp_path / "a.txt").chmod(0o644)

    result = Scanner().scan(tmp_path)
    render_report(result)
    output = capsys.readouterr().out

    assert result.diagnostics.is_complete
    assert "Scan was incomplete" not in output
    assert "do not apply" in output


def test_missing_git_is_called_incomplete(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        git_module.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError())
    )
    result = Scanner().scan(tmp_path)
    render_report(result)
    output = capsys.readouterr().out

    assert not result.diagnostics.is_complete
    assert "Scan was incomplete" in output
    assert "git executable not found" in output


# ---------------------------------------------------------------------------
# 3. Unreadable subtrees
# ---------------------------------------------------------------------------


def test_unreadable_directory_makes_the_scan_incomplete(tmp_path: Path, monkeypatch) -> None:
    """Regression: `os.walk` swallowed the error and the subtree vanished.

    Injected rather than chmod-ed, so the test behaves the same as root.
    """
    (tmp_path / "visible.txt").write_text("x\n")
    (tmp_path / "visible.txt").chmod(0o644)
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    (blocked / "hidden.txt").write_text("y\n")

    real_walk = os.walk

    def _walk(top, topdown=True, onerror=None, followlinks=False):
        for dirpath, dirnames, filenames in real_walk(
            top, topdown=topdown, onerror=onerror, followlinks=followlinks
        ):
            if Path(dirpath).name == "blocked":
                if onerror is not None:
                    onerror(PermissionError(13, "Permission denied", dirpath))
                dirnames[:] = []
                continue
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(fs_module.os, "walk", _walk)
    result = Scanner().scan(tmp_path)

    assert result.diagnostics.directories_skipped == 1
    assert not result.diagnostics.is_complete
    assert result.exit_code == 2
    # And nothing was invented about the files it never saw.
    assert all("hidden" not in str(f.path) for f in result.findings)


def test_skipped_directory_is_reported_distinctly(tmp_path: Path, capsys) -> None:
    render_report(
        ScanResult(
            target_path=tmp_path,
            files_inspected=3,
            diagnostics=ScanDiagnostics(
                git_index_status=GitIndexStatus.AVAILABLE, directories_skipped=2
            ),
        )
    )
    output = capsys.readouterr().out
    assert "Scan was incomplete" in output
    assert "could not be entered" in output


def test_a_complete_traversal_reports_no_skipped_directories(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.txt").write_text("x\n")
    (tmp_path / "sub" / "a.txt").chmod(0o644)

    result = Scanner().scan(tmp_path)
    assert result.diagnostics.directories_skipped == 0
    assert result.diagnostics.is_complete


# ---------------------------------------------------------------------------
# 4. Non-UTF-8 filenames in the Git index
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _git_available(), reason="git unavailable")
@pytest.mark.skipif(os.name != "posix", reason="POSIX filename semantics required")
def test_pl007_sees_a_file_whose_name_is_not_valid_utf8(tmp_path: Path) -> None:
    """Regression: replacement decoding destroyed the name, so PL007 skipped it.

    The file is staged at 100644 and then made executable in the working tree,
    which is exactly the mismatch PL007 exists to catch.
    """
    _init_repo(tmp_path)

    raw_name = b"weird-\xff\xfe-name.sh"
    try:
        target = tmp_path / os.fsdecode(raw_name)
        target.write_bytes(b"#!/bin/sh\n")
    except (OSError, UnicodeError):
        pytest.skip("filesystem rejects non-UTF-8 names")

    target.chmod(0o644)
    subprocess.run(["git", "add", "--", os.fsdecode(raw_name)], cwd=tmp_path, check=True)
    target.chmod(0o755)  # now differs from the staged 100644

    result = Scanner().scan(tmp_path)

    assert result.diagnostics.git_index_status is GitIndexStatus.AVAILABLE
    assert "PL007" in [f.check_id for f in result.findings], (
        "the mismatch was missed: the filename lost its identity in decoding"
    )
    assert result.diagnostics.is_complete


@pytest.mark.skipif(not _git_available(), reason="git unavailable")
def test_ordinary_filenames_still_match(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    target = tmp_path / "plain.sh"
    target.write_bytes(b"#!/bin/sh\n")
    target.chmod(0o644)
    subprocess.run(["git", "add", "plain.sh"], cwd=tmp_path, check=True)
    target.chmod(0o755)

    result = Scanner().scan(tmp_path)
    assert "PL007" in [f.check_id for f in result.findings]


@pytest.mark.skipif(not _git_available(), reason="git unavailable")
def test_matching_modes_produce_no_pl007(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    target = tmp_path / "plain.sh"
    target.write_bytes(b"#!/bin/sh\n")
    target.chmod(0o644)
    subprocess.run(["git", "add", "plain.sh"], cwd=tmp_path, check=True)

    result = Scanner().scan(tmp_path)
    assert "PL007" not in [f.check_id for f in result.findings]
