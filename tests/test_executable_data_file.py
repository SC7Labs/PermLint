"""Tests for PL003: Unexpected executable data/document file."""

from __future__ import annotations

from pathlib import Path

import pytest

from permlint.checks.executable_data_file import ExecutableDataFileCheck
from permlint.filesystem import FileInfo
from permlint.models import Severity


def make_file_info(path: Path, mode: int) -> FileInfo:
    path.chmod(mode)
    return FileInfo(path=path, rel_path=Path(path.name), mode=mode)


def test_data_file_non_executable_clean(tmp_path: Path) -> None:
    file = tmp_path / "README.md"
    file.write_text("# Project\n")
    info = make_file_info(file, 0o644)

    check = ExecutableDataFileCheck()
    finding = check.inspect(info)
    assert finding is None


def test_readme_executable_warns(tmp_path: Path) -> None:
    file = tmp_path / "README.md"
    file.write_text("# Project\n")
    info = make_file_info(file, 0o755)

    check = ExecutableDataFileCheck()
    finding = check.inspect(info)
    assert finding is not None
    assert finding.check_id == "PL003"
    assert finding.severity == Severity.WARNING
    assert finding.message == "File type normally should not be executable"
    assert finding.path == Path("README.md")


@pytest.mark.parametrize(
    "filename",
    [
        "config.json",
        "settings.yaml",
        "ci.yml",
        "pyproject.toml",
        "setup.cfg",
        "app.ini",
        "records.csv",
        "data.xml",
        "notes.txt",
        "table.tsv",
        "doc.rst",
    ],
)
def test_various_data_files_executable_warn(tmp_path: Path, filename: str) -> None:
    file = tmp_path / filename
    file.write_text("sample content\n")
    info = make_file_info(file, 0o755)

    check = ExecutableDataFileCheck()
    finding = check.inspect(info)
    assert finding is not None
    assert finding.check_id == "PL003"


def test_scripts_executable_do_not_trigger_pl003(tmp_path: Path) -> None:
    check = ExecutableDataFileCheck()

    sh_file = tmp_path / "deploy.sh"
    sh_file.write_text("#!/bin/sh\n")
    sh_info = make_file_info(sh_file, 0o755)
    assert check.inspect(sh_info) is None

    py_file = tmp_path / "script.py"
    py_file.write_text("#!/usr/bin/env python3\n")
    py_info = make_file_info(py_file, 0o755)
    assert check.inspect(py_info) is None
