"""Tests for the terminal reporter."""

from __future__ import annotations

import io
from pathlib import Path

from rich.console import Console

from permlint.fixer import FixAction, FixFailure, FixOutcome, FixPlan, ManualReview
from permlint.models import Finding, GitIndexStatus, ScanDiagnostics, ScanResult, Severity
from permlint.reporter import render_fix_plan, render_report, render_summary


def test_render_clean_report() -> None:
    result = ScanResult(
        target_path=Path("/path/to/project"),
        files_inspected=42,
        findings=[],
        diagnostics=ScanDiagnostics(git_index_status=GitIndexStatus.NOT_A_REPOSITORY),
    )

    output = io.StringIO()
    console = Console(file=output, color_system=None, width=120)
    render_report(result, console=console)

    rendered = output.getvalue()
    assert "PermLint 0.2.0" in rendered
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
        diagnostics=ScanDiagnostics(git_index_status=GitIndexStatus.NOT_A_REPOSITORY),
    )

    output = io.StringIO()
    console = Console(file=output, color_system=None, width=120)
    render_report(result, console=console)

    rendered = output.getvalue()
    assert "PermLint 0.2.0" in rendered
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


def test_render_git_evidence_and_safe_fix_suggestion() -> None:
    finding = Finding(
        check_id="PL001",
        path=Path("scripts/deploy.sh"),
        severity=Severity.ERROR,
        message="Has a shebang but is not executable",
        filesystem_mode=0o644,
        git_index_mode="100644",
        expected_executable=True,
    )
    result = ScanResult(
        target_path=Path("/path/to/project"),
        files_inspected=1,
        findings=[finding],
        diagnostics=ScanDiagnostics(git_index_status=GitIndexStatus.AVAILABLE),
    )
    action = FixAction(
        rel_path=Path("scripts/deploy.sh"),
        before_mode=0o644,
        after_mode=0o755,
        before_git_mode="100644",
        after_git_mode="100755",
        reason="Valid shebang",
    )
    plan = FixPlan(root=result.target_path, scan=result, actions=[action])
    output = io.StringIO()
    render_report(result, Console(file=output, color_system=None), plan=plan)
    rendered = output.getvalue()
    assert "Filesystem: 0644" in rendered
    assert "Git index:  100644" in rendered
    assert "Expected:   executable" in rendered
    assert "permlint fix scripts/deploy.sh" in rendered
    assert "Auto-fixable: 1" in rendered


def test_render_fix_preview_shows_exact_changes_and_manual_review() -> None:
    result = ScanResult(target_path=Path("/path/to/project"))
    action = FixAction(
        rel_path=Path("scripts/deploy.sh"),
        before_mode=0o644,
        after_mode=0o755,
        before_git_mode="100644",
        after_git_mode="100755",
        reason="Valid shebang",
    )
    plan = FixPlan(
        root=result.target_path,
        scan=result,
        actions=[action],
        manual=[ManualReview(Path("odd.sh"), "No clear intent", ("PL007",))],
    )
    output = io.StringIO()
    render_fix_plan(plan, dry_run=True, console=Console(file=output, color_system=None))
    rendered = output.getvalue()
    assert "1 safe fix available" in rendered
    assert "+x scripts/deploy.sh" in rendered
    assert "filesystem: 0644 -> 0755" in rendered
    assert "git index:  100644 -> 100755" in rendered
    assert "odd.sh (PL007): No clear intent" in rendered
    assert "No files changed." in rendered


def test_render_summary_keeps_incomplete_scan_diagnostics() -> None:
    result = ScanResult(
        target_path=Path("/path/to/project"),
        files_inspected=2,
        diagnostics=ScanDiagnostics(
            git_index_status=GitIndexStatus.NOT_A_REPOSITORY,
            files_unreadable=1,
        ),
    )
    output = io.StringIO()
    render_summary(result, Console(file=output, color_system=None))
    rendered = output.getvalue()
    assert "Files inspected: 2" in rendered
    assert "Total findings: 0" in rendered
    assert "No findings in inspected files." in rendered
    assert "Scan was incomplete:" in rendered
    assert "1 file could not be read" in rendered


def test_untrusted_filename_is_visible_without_terminal_controls_or_surrogates() -> None:
    path = Path("bad\x1b[31m\udcff.md")
    finding = Finding(
        check_id="PL003",
        path=path,
        severity=Severity.WARNING,
        message="File type normally should not be executable",
    )
    result = ScanResult(
        target_path=Path("/path/to/project"),
        files_inspected=1,
        findings=[finding],
        diagnostics=ScanDiagnostics(git_index_status=GitIndexStatus.NOT_A_REPOSITORY),
    )
    action = FixAction(path, 0o755, 0o644, None, None, "Non-executable data file")
    plan = FixPlan(root=result.target_path, scan=result, actions=[action])
    output = io.StringIO()
    console = Console(file=output, color_system=None, width=160)
    render_report(result, console=console, plan=plan)
    rendered = output.getvalue()
    assert "\\x1b" in rendered
    assert "\\udcff" in rendered
    assert "\x1b" not in rendered
    assert "\udcff" not in rendered
    assert "targeted paths need shell escaping" in rendered


def test_fix_report_escapes_untrusted_paths_and_failure_reasons() -> None:
    path = Path("bad\x1b[31m\udcff.md")
    scan = ScanResult(target_path=Path("/path/to/project"))
    action = FixAction(path, 0o755, 0o644, None, None, "Reason\x1b[31m")
    plan = FixPlan(
        root=scan.target_path,
        scan=scan,
        actions=[action],
        manual=[ManualReview(path, "Review\x1b[31m", ("PL003",))],
    )
    outcome = FixOutcome(applied=[action], failures=[FixFailure(path, "Failure\x1b[31m")])
    output = io.StringIO()
    render_fix_plan(
        plan,
        dry_run=False,
        outcome=outcome,
        console=Console(file=output, color_system=None, width=160),
    )
    rendered = output.getvalue()
    assert "bad\\x1b[31m\\udcff.md" in rendered
    assert "Reason\\x1b[31m" in rendered
    assert "Review\\x1b[31m" in rendered
    assert "Failure\\x1b[31m" in rendered
    assert "\x1b" not in rendered
    assert "\udcff" not in rendered
