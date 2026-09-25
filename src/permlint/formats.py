"""Deterministic JSON and SARIF 2.1.0 scan output."""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote_from_bytes

from permlint import __version__
from permlint.models import Finding, ScanResult, Severity
from permlint.rule_metadata import RULES

if TYPE_CHECKING:
    from permlint.fixer import FixPlan


def _sorted_findings(result: ScanResult) -> list[Finding]:
    return sorted(
        result.findings,
        key=lambda finding: (
            finding.path.as_posix(),
            finding.check_id,
            finding.severity.value,
            finding.message,
        ),
    )


def _relative_path(path: Path, root: Path) -> Path:
    """Return a path relative to the scan root without resolving symlinks."""
    return path.relative_to(root) if path.is_absolute() else path


def _fixable_paths(plan: FixPlan | None) -> set[Path]:
    return {action.rel_path for action in plan.actions} if plan is not None else set()


def _is_fixable(finding: Finding, fixable_paths: set[Path]) -> bool:
    return finding.path in fixable_paths and finding.check_id in {"PL001", "PL003", "PL007"}


def _mode(mode: int | None) -> str | None:
    return f"{mode & 0o7777:04o}" if mode is not None else None


def suggested_fix_command(path: Path) -> str:
    """Return a shell-safe command for a repository-relative selection."""
    name = path.as_posix()
    option_end = "-- " if name.startswith("-") else ""
    return f"permlint fix {option_end}{shlex.quote(name)}"


def _summary(result: ScanResult, plan: FixPlan | None) -> dict[str, Any]:
    return {
        "auto_fixable": len(plan.actions) if plan is not None else None,
        "complete": result.diagnostics.is_complete,
        "errors": result.error_count,
        "exit_code": result.exit_code,
        "files_scanned": result.files_inspected,
        "manual_review": len(plan.manual) if plan is not None else None,
        "warnings": result.warning_count,
    }


def scan_to_json(result: ScanResult, plan: FixPlan | None = None) -> dict[str, Any]:
    """Return the versioned, stable JSON representation of a scan."""
    fixable_paths = _fixable_paths(plan)
    diagnostics = result.diagnostics
    findings = []
    for finding in _sorted_findings(result):
        rel_path = _relative_path(finding.path, result.target_path)
        fixable = _is_fixable(finding, fixable_paths)
        findings.append(
            {
                "auto_fixable": fixable,
                "detail": getattr(finding, "detail", None),
                "expected_executable": getattr(finding, "expected_executable", None),
                "filesystem_mode": _mode(getattr(finding, "filesystem_mode", None)),
                "git_index_mode": getattr(finding, "git_index_mode", None),
                "message": finding.message,
                "path": rel_path.as_posix(),
                "rule_id": finding.check_id,
                "severity": finding.severity.value,
                "suggested_fix": suggested_fix_command(rel_path) if fixable else None,
            }
        )
    return {
        "schema_version": 1,
        "tool": {"name": "PermLint", "version": __version__},
        "target": str(result.target_path),
        "summary": _summary(result, plan),
        "diagnostics": {
            "directories_skipped": diagnostics.directories_skipped,
            "entries_skipped": diagnostics.entries_skipped,
            "files_unreadable": diagnostics.files_unreadable,
            "git_index_status": diagnostics.git_index_status.value,
            "unmerged_index_paths": diagnostics.unmerged_index_paths,
        },
        "findings": findings,
    }


def _uri(path: Path) -> str:
    """Encode POSIX path bytes as a URI, including non-UTF-8 filenames."""
    return quote_from_bytes(os.fsencode(path.as_posix()), safe="/")


def _root_uri(root: Path) -> str:
    path = _uri(root)
    return f"file://{path.rstrip('/')}/"


def scan_to_sarif(result: ScanResult, plan: FixPlan | None = None) -> dict[str, Any]:
    """Return SARIF 2.1.0 with file-level locations for permission metadata.

    Permission bits belong to files, not source lines, so results deliberately
    omit a fabricated `region.startLine`.
    """
    fixable_paths = _fixable_paths(plan)
    rules = []
    for rule in RULES.values():
        rules.append(
            {
                "id": rule.rule_id,
                "name": rule.name,
                "shortDescription": {"text": rule.summary},
                "fullDescription": {"text": rule.why},
                "help": {"text": f"{rule.trigger} Auto-fix: {rule.auto_fix} Caveat: {rule.caveat}"},
                "defaultConfiguration": {
                    "level": "error" if rule.default_severity is Severity.ERROR else "warning"
                },
            }
        )

    sarif_results = []
    for finding in _sorted_findings(result):
        rel_path = _relative_path(finding.path, result.target_path)
        properties: dict[str, Any] = {
            "autoFixable": _is_fixable(finding, fixable_paths),
        }
        filesystem_mode = _mode(getattr(finding, "filesystem_mode", None))
        git_index_mode = getattr(finding, "git_index_mode", None)
        expected_executable = getattr(finding, "expected_executable", None)
        detail = getattr(finding, "detail", None)
        if filesystem_mode is not None:
            properties["filesystemMode"] = filesystem_mode
        if git_index_mode is not None:
            properties["gitIndexMode"] = git_index_mode
        if expected_executable is not None:
            properties["expectedExecutable"] = expected_executable
        if detail is not None:
            properties["detail"] = detail

        state: list[str] = []
        if filesystem_mode is not None:
            state.append(f"filesystem {filesystem_mode}")
        if git_index_mode is not None:
            state.append(f"Git index {git_index_mode}")
        if expected_executable is not None:
            state.append(
                "expected executable" if expected_executable else "expected non-executable"
            )
        message = finding.message
        if state:
            message += f" ({', '.join(state)})"

        sarif_results.append(
            {
                "ruleId": finding.check_id,
                "level": "error" if finding.severity is Severity.ERROR else "warning",
                "message": {"text": message},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": _uri(rel_path),
                                "uriBaseId": "%SRCROOT%",
                            }
                        }
                    }
                ],
                "properties": properties,
            }
        )

    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "PermLint",
                        "informationUri": "https://github.com/SC7Labs/PermLint",
                        "version": __version__,
                        "rules": rules,
                    }
                },
                "originalUriBaseIds": {"%SRCROOT%": {"uri": _root_uri(result.target_path)}},
                "results": sarif_results,
                "properties": {"permlint": {"summary": _summary(result, plan)}},
            }
        ],
    }


def render_machine(result: ScanResult, output_format: str, plan: FixPlan | None = None) -> str:
    """Serialize one complete machine-readable document with a trailing newline."""
    if output_format == "json":
        document = scan_to_json(result, plan)
    elif output_format == "sarif":
        document = scan_to_sarif(result, plan)
    else:
        raise ValueError(f"Unknown output format: {output_format}")
    return json.dumps(document, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
