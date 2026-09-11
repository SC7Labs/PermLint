"""Tests for the Scanner orchestration."""

from __future__ import annotations

from pathlib import Path

from permlint.models import Severity
from permlint.scanner import Scanner


def test_scanner_clean_repo(tmp_path: Path) -> None:
    f1 = tmp_path / "README.md"
    f1.write_text("# PermLint\n")
    f1.chmod(0o644)

    f2 = tmp_path / "script.sh"
    f2.write_text("#!/bin/sh\necho ok\n")
    f2.chmod(0o755)

    scanner = Scanner()
    result = scanner.scan(tmp_path)

    assert result.files_inspected == 2
    assert not result.has_findings
    assert result.exit_code == 0


def test_scanner_deterministic_ordering(tmp_path: Path) -> None:
    # Create files in non-alphabetical order
    f_z = tmp_path / "z_deploy.sh"
    f_z.write_text("#!/bin/bash\n")
    f_z.chmod(0o644)

    f_a = tmp_path / "a_config.yaml"
    f_a.write_text("key: value\n")
    f_a.chmod(0o755)

    f_m = tmp_path / "m_worker.py"
    f_m.write_text("print('work')\n")
    f_m.chmod(0o755)

    scanner = Scanner()
    result = scanner.scan(tmp_path)

    paths = [f.path for f in result.findings]
    assert paths == [
        Path("a_config.yaml"),
        Path("m_worker.py"),
        Path("z_deploy.sh"),
    ]


def test_scanner_with_all_checks_triggered(tmp_path: Path) -> None:
    # PL001: shebang but not executable
    f1 = tmp_path / "deploy.sh"
    f1.write_text("#!/bin/bash\necho deploy\n")
    f1.chmod(0o644)

    # PL002: executable script without shebang
    f2 = tmp_path / "worker.py"
    f2.write_text("print('working')\n")
    f2.chmod(0o755)

    # PL003: executable data file
    f3 = tmp_path / "config.yaml"
    f3.write_text("key: value\n")
    f3.chmod(0o755)

    scanner = Scanner()
    result = scanner.scan(tmp_path)

    assert result.files_inspected == 3
    assert result.has_findings
    assert result.total_findings == 3
    assert result.error_count == 1
    assert result.warning_count == 2
    assert result.exit_code == 1

    check_ids = {f.check_id for f in result.findings}
    assert check_ids == {"PL001", "PL002", "PL003"}

    pl001 = next(f for f in result.findings if f.check_id == "PL001")
    assert pl001.severity == Severity.ERROR
    assert pl001.message == "Has a shebang but is not executable"

    pl002 = next(f for f in result.findings if f.check_id == "PL002")
    assert pl002.severity == Severity.WARNING
    assert pl002.message == "Executable text file has no shebang"

    pl003 = next(f for f in result.findings if f.check_id == "PL003")
    assert pl003.severity == Severity.WARNING
    assert pl003.message == "File type normally should not be executable"


def test_scanner_rust_inner_attribute_clean(tmp_path: Path) -> None:
    f = tmp_path / "main.rs"
    f.write_text("#![allow(dead_code)]\n\nfn main() {}\n")
    f.chmod(0o644)

    scanner = Scanner()
    result = scanner.scan(tmp_path)

    assert result.files_inspected == 1
    assert not result.has_findings
    assert result.exit_code == 0
