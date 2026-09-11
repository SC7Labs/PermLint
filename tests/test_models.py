"""Tests for PermLint data models."""

from __future__ import annotations

from pathlib import Path

from permlint.models import Finding, GitIndexStatus, ScanDiagnostics, ScanResult, Severity


def test_severity_labels() -> None:
    assert Severity.ERROR.label == "ERROR"
    assert Severity.WARNING.label == "WARN"
    assert Severity.ERROR == "error"
    assert Severity.WARNING == "warning"


def test_finding_creation() -> None:
    finding = Finding(
        check_id="PL001",
        path=Path("scripts/deploy.sh"),
        severity=Severity.ERROR,
        message="Has a shebang but is not executable",
    )
    assert finding.check_id == "PL001"
    assert finding.path == Path("scripts/deploy.sh")
    assert finding.severity == Severity.ERROR
    assert finding.message == "Has a shebang but is not executable"


def test_scan_result_empty() -> None:
    # Diagnostics are explicit: the default is deliberately pessimistic, so a
    # result built without them counts as incomplete.
    result = ScanResult(
        target_path=Path("/tmp/repo"),
        files_inspected=10,
        diagnostics=ScanDiagnostics(git_index_status=GitIndexStatus.AVAILABLE),
    )
    assert not result.has_findings
    assert result.total_findings == 0
    assert result.error_count == 0
    assert result.warning_count == 0
    assert result.exit_code == 0


def test_scan_result_with_findings() -> None:
    findings = [
        Finding(
            check_id="PL001",
            path=Path("scripts/deploy.sh"),
            severity=Severity.ERROR,
            message="Has a shebang but is not executable",
        ),
        Finding(
            check_id="PL003",
            path=Path("config/app.yaml"),
            severity=Severity.WARNING,
            message="File type normally should not be executable",
        ),
    ]
    result = ScanResult(target_path=Path("/tmp/repo"), files_inspected=10, findings=findings)
    assert result.has_findings
    assert result.total_findings == 2
    assert result.error_count == 1
    assert result.warning_count == 1
    assert result.exit_code == 1
