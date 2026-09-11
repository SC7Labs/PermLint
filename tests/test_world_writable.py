"""Tests for PL004: World-writable file."""

from __future__ import annotations

from pathlib import Path

from permlint.checks.executable_data_file import ExecutableDataFileCheck
from permlint.checks.world_writable import WorldWritableCheck
from permlint.filesystem import FileInfo
from permlint.models import Severity


def make_file_info(path: Path, mode: int) -> FileInfo:
    path.chmod(mode)
    return FileInfo(path=path, rel_path=Path(path.name), mode=mode)


def test_clean_modes_not_world_writable(tmp_path: Path) -> None:
    check = WorldWritableCheck()

    f1 = tmp_path / "normal.txt"
    f1.write_text("content\n")
    assert check.inspect(make_file_info(f1, 0o644)) is None

    f2 = tmp_path / "script.sh"
    f2.write_text("#!/bin/sh\n")
    assert check.inspect(make_file_info(f2, 0o755)) is None

    f3 = tmp_path / "private.txt"
    f3.write_text("secret\n")
    assert check.inspect(make_file_info(f3, 0o600)) is None


def test_world_writable_modes_trigger_pl004(tmp_path: Path) -> None:
    check = WorldWritableCheck()

    f1 = tmp_path / "public.txt"
    f1.write_text("hello\n")
    info1 = make_file_info(f1, 0o666)
    finding1 = check.inspect(info1)
    assert finding1 is not None
    assert finding1.check_id == "PL004"
    assert finding1.severity == Severity.ERROR
    assert finding1.message == "File is writable by all users"
    assert finding1.path == Path("public.txt")

    f2 = tmp_path / "odd.bin"
    f2.write_bytes(b"\x00")
    info2 = make_file_info(f2, 0o602)
    finding2 = check.inspect(info2)
    assert finding2 is not None
    assert finding2.check_id == "PL004"

    f3 = tmp_path / "all_access.sh"
    f3.write_text("#!/bin/sh\n")
    info3 = make_file_info(f3, 0o777)
    finding3 = check.inspect(info3)
    assert finding3 is not None
    assert finding3.check_id == "PL004"


def test_coexistence_with_pl003(tmp_path: Path) -> None:
    # config.yaml with mode 0777 should trigger both PL003 and PL004
    f = tmp_path / "config.yaml"
    f.write_text("setting: true\n")
    info = make_file_info(f, 0o777)

    pl003 = ExecutableDataFileCheck().inspect(info)
    pl004 = WorldWritableCheck().inspect(info)

    assert pl003 is not None
    assert pl003.check_id == "PL003"
    assert pl003.severity == Severity.WARNING

    assert pl004 is not None
    assert pl004.check_id == "PL004"
    assert pl004.severity == Severity.ERROR
