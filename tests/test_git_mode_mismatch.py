"""Tests for PL007: Git executable-bit mismatch."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from permlint.checks.git_mode_mismatch import GitModeMismatchCheck
from permlint.filesystem import FileInfo
from permlint.models import Severity
from permlint.scanner import Scanner

HAS_GIT = shutil.which("git") is not None


@pytest.mark.skipif(not HAS_GIT, reason="git executable not found")
def test_git_mismatch_clean_modes(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    # 1. Tracked non-executable file with 0644 on disk
    f1 = tmp_path / "doc.txt"
    f1.write_text("doc\n")
    f1.chmod(0o644)
    subprocess.run(["git", "add", "doc.txt"], cwd=str(tmp_path), capture_output=True, check=True)

    # 2. Tracked executable file with 0755 on disk
    f2 = tmp_path / "run.sh"
    f2.write_text("#!/bin/sh\necho ok\n")
    f2.chmod(0o755)
    subprocess.run(["git", "add", "run.sh"], cwd=str(tmp_path), capture_output=True, check=True)

    scanner = Scanner()
    result = scanner.scan(tmp_path)

    pl007_findings = [f for f in result.findings if f.check_id == "PL007"]
    assert len(pl007_findings) == 0


@pytest.mark.skipif(not HAS_GIT, reason="git executable not found")
def test_git_mismatch_index_non_executable_disk_executable(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    # File staged as 100644, then chmod +x on working tree
    f = tmp_path / "tool.sh"
    f.write_text("#!/bin/sh\necho tool\n")
    f.chmod(0o644)
    subprocess.run(["git", "add", "tool.sh"], cwd=str(tmp_path), capture_output=True, check=True)

    # Now make it executable on disk without staging
    f.chmod(0o755)

    scanner = Scanner()
    result = scanner.scan(tmp_path)

    pl007 = next((finding for finding in result.findings if finding.check_id == "PL007"), None)
    assert pl007 is not None
    assert pl007.severity == Severity.WARNING
    assert pl007.message == "Working tree executable bit does not match Git index"
    assert pl007.path == Path("tool.sh")


@pytest.mark.skipif(not HAS_GIT, reason="git executable not found")
def test_git_mismatch_index_executable_disk_non_executable(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    # File staged as 100755, then chmod -x on working tree
    f = tmp_path / "deploy.sh"
    f.write_text("#!/bin/bash\necho deploy\n")
    f.chmod(0o755)
    subprocess.run(["git", "add", "deploy.sh"], cwd=str(tmp_path), capture_output=True, check=True)

    # Now remove execute bits on disk
    f.chmod(0o644)

    scanner = Scanner()
    result = scanner.scan(tmp_path)

    pl007 = next((finding for finding in result.findings if finding.check_id == "PL007"), None)
    assert pl007 is not None
    assert pl007.severity == Severity.WARNING
    assert pl007.message == "Working tree executable bit does not match Git index"


@pytest.mark.skipif(not HAS_GIT, reason="git executable not found")
def test_git_untracked_file_no_pl007(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    # Untracked file on disk
    f = tmp_path / "untracked.py"
    f.write_text("#!/usr/bin/env python3\nprint('untracked')\n")
    f.chmod(0o755)

    scanner = Scanner()
    result = scanner.scan(tmp_path)

    pl007_findings = [f for f in result.findings if f.check_id == "PL007"]
    assert len(pl007_findings) == 0


def test_non_git_directory_no_pl007(tmp_path: Path) -> None:
    # Directory without git init
    f = tmp_path / "script.sh"
    f.write_text("#!/bin/sh\necho test\n")
    f.chmod(0o755)

    scanner = Scanner()
    result = scanner.scan(tmp_path)

    pl007_findings = [f for f in result.findings if f.check_id == "PL007"]
    assert len(pl007_findings) == 0


@pytest.mark.skipif(not HAS_GIT, reason="git executable not found")
def test_git_file_with_spaces_in_name(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    file_with_spaces = tmp_path / "script with space.sh"
    file_with_spaces.write_text("#!/bin/sh\necho space\n")
    file_with_spaces.chmod(0o644)
    subprocess.run(
        ["git", "add", "script with space.sh"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )

    # Make executable on disk
    file_with_spaces.chmod(0o755)

    scanner = Scanner()
    result = scanner.scan(tmp_path)

    pl007 = next((finding for finding in result.findings if finding.check_id == "PL007"), None)
    assert pl007 is not None
    assert pl007.path == Path("script with space.sh")


@pytest.mark.skipif(not HAS_GIT, reason="git executable not found")
def test_git_unicode_filename(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    unicode_file = tmp_path / "скрипт_тест.sh"
    unicode_file.write_text("#!/bin/sh\necho test\n")
    unicode_file.chmod(0o644)
    subprocess.run(
        ["git", "add", str(unicode_file.name)],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )

    unicode_file.chmod(0o755)

    scanner = Scanner()
    result = scanner.scan(tmp_path)

    pl007 = next((finding for finding in result.findings if finding.check_id == "PL007"), None)
    assert pl007 is not None
    assert pl007.path == Path("скрипт_тест.sh")


@pytest.mark.skipif(not HAS_GIT, reason="git executable not found")
def test_git_symlink_ignored_in_index(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    target = tmp_path / "real.sh"
    target.write_text("#!/bin/sh\necho real\n")
    target.chmod(0o755)

    link = tmp_path / "link.sh"
    link.symlink_to(target)

    subprocess.run(
        ["git", "add", "real.sh", "link.sh"], cwd=str(tmp_path), capture_output=True, check=True
    )

    scanner = Scanner()
    result = scanner.scan(tmp_path)

    # Symlink is not a regular file and mode 120000 is ignored
    pl007_findings = [f for f in result.findings if f.check_id == "PL007"]
    assert len(pl007_findings) == 0


def test_direct_check_inspection_without_git_mode() -> None:
    check = GitModeMismatchCheck()
    info = FileInfo(
        path=Path("/tmp/foo.sh"), rel_path=Path("foo.sh"), mode=0o755, git_index_mode=None
    )
    assert check.inspect(info) is None
