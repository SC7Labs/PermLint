"""Tests for PL006: Malformed shebang and interactions with PL001/PL002."""

from __future__ import annotations

from pathlib import Path

import pytest

from permlint.checks.executable_no_shebang import ExecutableNoShebangCheck
from permlint.checks.malformed_shebang import MalformedShebangCheck
from permlint.checks.shebang_executable import ShebangExecutableCheck
from permlint.filesystem import FileInfo
from permlint.models import Severity


def make_file_info(path: Path, mode: int) -> FileInfo:
    path.chmod(mode)
    return FileInfo(path=path, rel_path=Path(path.name), mode=mode)


@pytest.mark.parametrize(
    "header",
    [
        "#!/bin/sh\n",
        "#!/bin/bash\n",
        "#!/usr/bin/env python3\n",
        "#!/usr/bin/python3\n",
        "#! /bin/bash -e\n",
        "#!/bin/sh\r\n",
        "#!/bin/sh",  # no trailing newline
    ],
)
def test_valid_shebangs_are_clean(tmp_path: Path, header: str) -> None:
    check = MalformedShebangCheck()
    f = tmp_path / "valid.sh"
    f.write_text(f"{header}echo ok\n")
    info = make_file_info(f, 0o755)
    assert check.inspect(info) is None


@pytest.mark.parametrize(
    "header",
    [
        "#!\n",
        "#!   \n",
        "#!\r\n",
        "#!   \r\n",
        "#!",
        "#!python3\n",
        "#!bash\n",
        "#!env python3\n",
    ],
)
def test_malformed_shebangs_trigger_pl006(tmp_path: Path, header: str) -> None:
    check = MalformedShebangCheck()
    f = tmp_path / "broken.sh"
    f.write_text(f"{header}echo test\n")
    info = make_file_info(f, 0o755)

    finding = check.inspect(info)
    assert finding is not None
    assert finding.check_id == "PL006"
    assert finding.severity == Severity.ERROR
    assert finding.message == "Malformed shebang"


def test_invalid_utf8_in_shebang_handled_gracefully(tmp_path: Path) -> None:
    check = MalformedShebangCheck()
    f = tmp_path / "corrupt.sh"
    f.write_bytes(b"#!\xff\xfe/bin/sh\necho test\n")
    info = make_file_info(f, 0o755)
    # The invalid bytes do not start with '/' so it is marked malformed rather than crashing
    finding = check.inspect(info)
    assert finding is not None
    assert finding.check_id == "PL006"


def test_interaction_malformed_shebang_non_executable_only_pl006(tmp_path: Path) -> None:
    # A malformed shebang file with 0644 must trigger PL006 and NOT PL001
    f = tmp_path / "broken_mode.sh"
    f.write_text("#!python3\nprint('hello')\n")
    info = make_file_info(f, 0o644)

    pl001 = ShebangExecutableCheck().inspect(info)
    pl006 = MalformedShebangCheck().inspect(info)

    assert pl006 is not None
    assert pl006.check_id == "PL006"
    assert pl001 is None


def test_interaction_valid_shebang_non_executable_triggers_pl001(tmp_path: Path) -> None:
    # A valid shebang with 0644 triggers PL001 and NOT PL006
    f = tmp_path / "deploy.sh"
    f.write_text("#!/bin/bash\necho deploy\n")
    info = make_file_info(f, 0o644)

    pl001 = ShebangExecutableCheck().inspect(info)
    pl006 = MalformedShebangCheck().inspect(info)

    assert pl001 is not None
    assert pl001.check_id == "PL001"
    assert pl006 is None


def test_interaction_malformed_shebang_executable_only_pl006(tmp_path: Path) -> None:
    # A script with malformed shebang and 0755 triggers PL006 and NOT PL002
    f = tmp_path / "broken.sh"
    f.write_text("#!\necho broken\n")
    info = make_file_info(f, 0o755)

    pl002 = ExecutableNoShebangCheck().inspect(info)
    pl006 = MalformedShebangCheck().inspect(info)

    assert pl006 is not None
    assert pl006.check_id == "PL006"
    assert pl002 is None


@pytest.mark.parametrize(
    "header",
    [
        "#![allow(dead_code)]\n",
        '#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]\n',
        "#![feature(box_syntax)]\n",
        "#![no_std]\n",
    ],
)
def test_rust_inner_attributes_produce_no_pl006(tmp_path: Path, header: str) -> None:
    check = MalformedShebangCheck()
    f = tmp_path / "main.rs"
    f.write_text(f"{header}fn main() {{}}\n")
    info = make_file_info(f, 0o644)

    assert check.inspect(info) is None
    assert not info.has_shebang()
    assert not info.has_raw_shebang_prefix()
    assert not info.is_shebang_malformed()


def test_rust_file_with_malformed_shebang_still_triggers_pl006(tmp_path: Path) -> None:
    # A .rs file with an actual malformed shebang must still trigger PL006
    check = MalformedShebangCheck()
    f = tmp_path / "script.rs"
    f.write_text("#!rust-script\nfn main() {}\n")
    info = make_file_info(f, 0o755)

    finding = check.inspect(info)
    assert finding is not None
    assert finding.check_id == "PL006"
    assert info.is_shebang_malformed()


def test_rust_file_with_valid_shebang_retains_behavior(tmp_path: Path) -> None:
    # A .rs file with a valid shebang is clean under PL006 when executable
    check = MalformedShebangCheck()
    f = tmp_path / "script.rs"
    f.write_text("#!/usr/bin/env rust-script\nfn main() {}\n")
    info = make_file_info(f, 0o755)

    assert check.inspect(info) is None
    assert info.has_shebang()
    assert not info.is_shebang_malformed()

    # When not executable, a valid shebang triggers PL001 and not PL006
    info_non_exec = make_file_info(f, 0o644)
    assert check.inspect(info_non_exec) is None
    pl001 = ShebangExecutableCheck().inspect(info_non_exec)
    assert pl001 is not None
    assert pl001.check_id == "PL001"
