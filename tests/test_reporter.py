"""Tests for the terminal reporter."""

from __future__ import annotations

import io
from pathlib import Path

from rich.console import Console

from permlint.models import Finding, ScanResult, Severity
from permlint.reporter import render_report


def test_render_clean_report() -> None:
    result = ScanResult(
        target_path=Path("/path/to/project"),
        files_inspected=42,
        findings=[],
    )

    output = io.StringIO()
    console = Console(file=output, color_system=None, width=120)
    render_report(result, console=console)

    rendered = output.getvalue()
    assert "PermLint 0.1.1" in rendered
    assert "Scanning: /path/to/project" in rendered
    assert "42 files inspected" in rendered
    assert "No issues found." in rendered


def test_render_report_with_findings() -> None:
    findings = [
        Finding(
            check_id="PL001",
            path=Path("scripts/deploy.sh"),
            severity=Severity.ERROR,
            message="Has a shebang but is not executable",
        ),
        Finding(
            check_id="PL003",
            path=Path("config/settings.yaml"),
            severity=Severity.WARNING,
            message="File type normally should not be executable",
        ),
    ]
    result = ScanResult(
        target_path=Path("/path/to/project"),
        files_inspected=132,
        findings=findings,
    )

    output = io.StringIO()
    console = Console(file=output, color_system=None, width=120)
    render_report(result, console=console)

    rendered = output.getvalue()
    assert "PermLint 0.1.1" in rendered
    assert "Scanning: /path/to/project" in rendered
    assert "PL001 ERROR" in rendered
    assert "scripts/deploy.sh" in rendered
    assert "Has a shebang but is not executable" in rendered
    assert "PL003 WARN" in rendered
    assert "config/settings.yaml" in rendered
    assert "File type normally should not be executable" in rendered
    assert "Files inspected: 132" in rendered
    assert "Errors: 1" in rendered
    assert "Warnings: 1" in rendered
    assert "2 issues found" in rendered
