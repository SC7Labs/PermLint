"""Comprehensive cross-rule integration test covering all eight rules."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

from rich.console import Console

from permlint.models import Severity
from permlint.reporter import render_report
from permlint.scanner import Scanner


def test_eight_rules_comprehensive_repository(tmp_path: Path) -> None:
    # 1. Initialize git repo so PL007 can function
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    # 1. PL001: Shebang but not executable (0644 + valid shebang)
    f_pl001 = tmp_path / "deploy.sh"
    f_pl001.write_text("#!/bin/bash\necho deploy\n")
    f_pl001.chmod(0o644)

    # 2. PL002: Executable script without shebang (0755 + no shebang)
    f_pl002 = tmp_path / "worker.py"
    f_pl002.write_text("import sys\nprint('working')\n")
    f_pl002.chmod(0o755)

    # 3. PL003: Unexpected executable data file (0755)
    f_pl003 = tmp_path / "config.yaml"
    f_pl003.write_text("version: 1\n")
    f_pl003.chmod(0o755)

    # 4. PL004: World-writable file (0666)
    f_pl004 = tmp_path / "public.txt"
    f_pl004.write_text("hello public\n")
    f_pl004.chmod(0o666)

    # 5. PL005: Sensitive-looking file with broad permissions (0644)
    f_pl005 = tmp_path / "id_ed25519"
    f_pl005.write_text("fake private key data\n")
    f_pl005.chmod(0o644)

    # 6. PL006: Malformed shebang (0755 + "#!")
    f_pl006 = tmp_path / "broken.sh"
    f_pl006.write_text("#!\necho broken\n")
    f_pl006.chmod(0o755)

    # 7. PL007: Git executable-bit mismatch (staged 100644, disk 0755)
    f_pl007 = tmp_path / "tracked.sh"
    f_pl007.write_text("#!/bin/sh\necho tracked\n")
    f_pl007.chmod(0o644)
    subprocess.run(["git", "add", "tracked.sh"], cwd=str(tmp_path), capture_output=True, check=True)
    f_pl007.chmod(0o755)

    # 8. PL008: Unexpected privilege bits (4755)
    f_pl008 = tmp_path / "privileged.bin"
    f_pl008.write_bytes(b"\x00")
    try:
        f_pl008.chmod(0o4755)
    except OSError:
        pass

    scanner = Scanner()
    result = scanner.scan(tmp_path)

    # Verify all 8 checks triggered
    check_ids = {f.check_id for f in result.findings}
    expected_ids = {"PL001", "PL002", "PL003", "PL004", "PL005", "PL006", "PL007", "PL008"}
    assert expected_ids.issubset(check_ids)

    assert result.has_findings
    assert result.exit_code == 1
    assert result.error_count == 4  # PL001, PL004, PL006, PL008
    assert result.warning_count == 4  # PL002, PL003, PL005, PL007
    assert result.total_findings == 8

    # Verify severity classification
    finding_map = {f.check_id: f for f in result.findings}
    assert finding_map["PL001"].severity == Severity.ERROR
    assert finding_map["PL002"].severity == Severity.WARNING
    assert finding_map["PL003"].severity == Severity.WARNING
    assert finding_map["PL004"].severity == Severity.ERROR
    assert finding_map["PL005"].severity == Severity.WARNING
    assert finding_map["PL006"].severity == Severity.ERROR
    assert finding_map["PL007"].severity == Severity.WARNING
    assert finding_map["PL008"].severity == Severity.ERROR

    # Verify Rich rendering
    output = io.StringIO()
    console = Console(file=output, color_system=None, width=120)
    render_report(result, console=console)
    rendered = output.getvalue()

    for check_id in ["PL001", "PL002", "PL003", "PL004", "PL005", "PL006", "PL007", "PL008"]:
        assert check_id in rendered

    assert "Errors: 4" in rendered
    assert "Warnings: 4" in rendered
    assert "8 issues found" in rendered
