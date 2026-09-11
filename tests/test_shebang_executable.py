"""Tests for PL001: Shebang but not executable."""

from __future__ import annotations

from pathlib import Path

from permlint.checks.shebang_executable import ShebangExecutableCheck
from permlint.filesystem import FileInfo
from permlint.models import Severity


def make_file_info(path: Path, mode: int) -> FileInfo:
    path.chmod(mode)
    return FileInfo(path=path, rel_path=Path(path.name), mode=mode)


def test_shebang_executable_clean(tmp_path: Path) -> None:
    file = tmp_path / "script.sh"
    file.write_text("#!/bin/bash\necho 'hello'\n")
    info = make_file_info(file, 0o755)

    check = ShebangExecutableCheck()
    finding = check.inspect(info)
    assert finding is None


def test_shebang_not_executable_error(tmp_path: Path) -> None:
    file = tmp_path / "deploy.sh"
    file.write_text("#!/bin/bash\necho 'deploying'\n")
    info = make_file_info(file, 0o644)

    check = ShebangExecutableCheck()
    finding = check.inspect(info)
    assert finding is not None
    assert finding.check_id == "PL001"
    assert finding.severity == Severity.ERROR
    assert finding.message == "Has a shebang but is not executable"
    assert finding.path == Path("deploy.sh")


def test_python_env_shebang_not_executable(tmp_path: Path) -> None:
    file = tmp_path / "tool.py"
    file.write_text("#!/usr/bin/env python3\nprint('hello')\n")
    info = make_file_info(file, 0o644)

    check = ShebangExecutableCheck()
    finding = check.inspect(info)
    assert finding is not None
    assert finding.check_id == "PL001"
    assert finding.severity == Severity.ERROR


def test_empty_file_no_crash(tmp_path: Path) -> None:
    file = tmp_path / "empty.sh"
    file.write_bytes(b"")
    info = make_file_info(file, 0o644)

    check = ShebangExecutableCheck()
    finding = check.inspect(info)
    assert finding is None


def test_binary_file_no_false_positive(tmp_path: Path) -> None:
    file = tmp_path / "binary_app"
    file.write_bytes(b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00")
    info = make_file_info(file, 0o644)

    check = ShebangExecutableCheck()
    finding = check.inspect(info)
    assert finding is None


def test_binary_with_shebang_bytes_no_false_positive(tmp_path: Path) -> None:
    file = tmp_path / "corrupted.bin"
    file.write_bytes(b"#!\x00\x01\x02\x03\x04\x05binarypayload")
    info = make_file_info(file, 0o644)

    check = ShebangExecutableCheck()
    finding = check.inspect(info)
    assert finding is None


def test_regular_text_no_shebang_clean(tmp_path: Path) -> None:
    file = tmp_path / "module.py"
    file.write_text("def run():\n    pass\n")
    info = make_file_info(file, 0o644)

    check = ShebangExecutableCheck()
    finding = check.inspect(info)
    assert finding is None
