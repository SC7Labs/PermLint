"""Tests for PL002: Executable script without shebang."""

from __future__ import annotations

from pathlib import Path

import pytest

from permlint.checks.executable_no_shebang import ExecutableNoShebangCheck
from permlint.filesystem import FileInfo
from permlint.models import Severity


def make_file_info(path: Path, mode: int) -> FileInfo:
    path.chmod(mode)
    return FileInfo(path=path, rel_path=Path(path.name), mode=mode)


def test_executable_python_with_shebang_clean(tmp_path: Path) -> None:
    file = tmp_path / "cli.py"
    file.write_text("#!/usr/bin/env python3\nprint('running')\n")
    info = make_file_info(file, 0o755)

    check = ExecutableNoShebangCheck()
    finding = check.inspect(info)
    assert finding is None


def test_executable_python_without_shebang_warns(tmp_path: Path) -> None:
    file = tmp_path / "migrate.py"
    file.write_text("import sys\nprint('migrating')\n")
    info = make_file_info(file, 0o755)

    check = ExecutableNoShebangCheck()
    finding = check.inspect(info)
    assert finding is not None
    assert finding.check_id == "PL002"
    assert finding.severity == Severity.WARNING
    assert finding.message == "Executable text file has no shebang"
    assert finding.path == Path("migrate.py")


def test_executable_shell_without_shebang_warns(tmp_path: Path) -> None:
    file = tmp_path / "build.sh"
    file.write_text("echo 'building'\n")
    info = make_file_info(file, 0o755)

    check = ExecutableNoShebangCheck()
    finding = check.inspect(info)
    assert finding is not None
    assert finding.check_id == "PL002"
    assert finding.severity == Severity.WARNING


@pytest.mark.parametrize(
    "ext",
    [".bash", ".zsh", ".fish", ".pl", ".rb", ".js", ".ts", ".mjs"],
)
def test_other_script_extensions_warn(tmp_path: Path, ext: str) -> None:
    file = tmp_path / f"script{ext}"
    file.write_text("console.log('test')\n")
    info = make_file_info(file, 0o755)

    check = ExecutableNoShebangCheck()
    finding = check.inspect(info)
    assert finding is not None
    assert finding.check_id == "PL002"


def test_non_executable_python_without_shebang_clean(tmp_path: Path) -> None:
    file = tmp_path / "utils.py"
    file.write_text("def helper():\n    return 42\n")
    info = make_file_info(file, 0o644)

    check = ExecutableNoShebangCheck()
    finding = check.inspect(info)
    assert finding is None


def test_executable_elf_binary_no_warn(tmp_path: Path) -> None:
    file = tmp_path / "app.py"  # Even if misnamed with script extension
    file.write_bytes(b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00")
    info = make_file_info(file, 0o755)

    check = ExecutableNoShebangCheck()
    finding = check.inspect(info)
    assert finding is None


def test_executable_null_byte_binary_no_warn(tmp_path: Path) -> None:
    file = tmp_path / "binary_data.sh"
    file.write_bytes(b"DATA\x00\xff\xfe\x00BINARY")
    info = make_file_info(file, 0o755)

    check = ExecutableNoShebangCheck()
    finding = check.inspect(info)
    assert finding is None


def test_executable_empty_and_short_files_no_crash(tmp_path: Path) -> None:
    check = ExecutableNoShebangCheck()

    empty_file = tmp_path / "empty.py"
    empty_file.write_bytes(b"")
    info_empty = make_file_info(empty_file, 0o755)
    # Empty python file marked 0755 has no shebang and is text
    finding = check.inspect(info_empty)
    assert finding is not None
    assert finding.check_id == "PL002"

    short_file = tmp_path / "short.py"
    short_file.write_text("x\n")
    info_short = make_file_info(short_file, 0o755)
    finding = check.inspect(info_short)
    assert finding is not None
    assert finding.check_id == "PL002"


def test_executable_non_script_extension_no_warn(tmp_path: Path) -> None:
    file = tmp_path / "binary_runner"
    file.write_bytes(b"\x7fELF\x02\x01\x01")
    info = make_file_info(file, 0o755)

    check = ExecutableNoShebangCheck()
    finding = check.inspect(info)
    assert finding is None
