"""Tests for PL008: Unexpected privilege bits."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from permlint.checks.privilege_bits import UnexpectedPrivilegeBitsCheck
from permlint.filesystem import FileInfo
from permlint.models import Severity


def test_clean_files_without_privilege_bits(tmp_path: Path) -> None:
    check = UnexpectedPrivilegeBitsCheck()

    f1 = tmp_path / "script.sh"
    f1.write_text("#!/bin/sh\n")
    f1.chmod(0o755)
    info1 = FileInfo(path=f1, rel_path=Path("script.sh"), mode=0o755)
    assert check.inspect(info1) is None

    f2 = tmp_path / "doc.txt"
    f2.write_text("doc\n")
    f2.chmod(0o644)
    info2 = FileInfo(path=f2, rel_path=Path("doc.txt"), mode=0o644)
    assert check.inspect(info2) is None


@pytest.mark.parametrize(
    ("mode", "mode_name"),
    [
        (0o4755, "setuid (04755)"),
        (0o2755, "setgid (02755)"),
        (0o6755, "setuid+setgid (06755)"),
        (0o4644, "setuid (04644)"),
        (0o2644, "setgid (02644)"),
    ],
)
def test_privilege_bits_trigger_pl008(tmp_path: Path, mode: int, mode_name: str) -> None:
    check = UnexpectedPrivilegeBitsCheck()
    f = tmp_path / f"priv_{mode:o}.bin"
    f.write_bytes(b"\x00")

    # Attempt real chmod on the filesystem
    try:
        f.chmod(mode)
        actual_st_mode = os.stat(f).st_mode
    except OSError:
        actual_st_mode = mode

    # Check using FileInfo with the requested mode
    info = FileInfo(path=f, rel_path=Path(f.name), mode=actual_st_mode)
    finding = check.inspect(info)

    assert finding is not None, f"Failed for {mode_name}"
    assert finding.check_id == "PL008"
    assert finding.severity == Severity.ERROR
    assert finding.message == "Regular file has setuid/setgid permission bits"
