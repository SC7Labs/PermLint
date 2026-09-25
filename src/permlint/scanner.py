"""Core scanner implementation for PermLint."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from permlint.checks import BaseCheck, get_default_checks
from permlint.config import Config, load_config
from permlint.filesystem import walk_repository
from permlint.git import get_git_index_snapshot
from permlint.models import Finding, ScanDiagnostics, ScanResult


class InvalidTargetError(ValueError):
    """The scan target is not a directory that can be scanned.

    Raised rather than returning an empty result: a caller cannot tell an empty
    `ScanResult` for a missing path from an empty one for a clean repository,
    and a library that answers "no problems found" about a path it never looked
    at is worse than one that refuses.
    """


class Scanner:
    """Orchestrates file discovery and check execution over a target directory."""

    def __init__(self, checks: list[BaseCheck] | None = None, config: Config | None = None) -> None:
        """Initialize Scanner with an optional list of checks.

        Args:
            checks: List of BaseCheck instances to execute. If None, uses default checks.
            config: Optional configuration. If absent, the scan loads the target's
                ``.permlint.toml`` when it exists.
        """
        self.checks: list[BaseCheck] = checks if checks is not None else get_default_checks()
        self.config = config

    def scan(self, target_path: Path) -> ScanResult:
        """Scan target repository path and evaluate all configured checks against regular files.

        Performs single-pass traversal over the filesystem while reusing pre-collected
        Git index metadata where applicable.

        Args:
            target_path: Root directory of the repository to scan.

        Returns:
            A ScanResult containing the target path, inspected file count,
            findings, and diagnostics describing anything the scan could not
            look at.

        Raises:
            InvalidTargetError: If the target does not exist, is not a
                directory, or cannot be opened.
        """
        resolved_path = self._validate_target(target_path)
        config = self.config if self.config is not None else load_config(resolved_path)
        git_snapshot = get_git_index_snapshot(resolved_path)

        files_inspected = 0
        unreadable = 0
        skipped = [0]
        directories_skipped = [0]
        findings: list[Finding] = []

        for file_info in walk_repository(
            resolved_path,
            git_index_modes=git_snapshot.modes,
            skipped=skipped,
            directories_skipped=directories_skipped,
            is_excluded=config.is_excluded,
        ):
            files_inspected += 1
            for check in self.checks:
                if check.check_id in config.disabled_rules:
                    continue
                finding = check.inspect(file_info)
                if finding is not None:
                    override = config.severity_overrides.get(check.check_id)
                    if override is not None:
                        finding = replace(finding, severity=override)
                    findings.append(finding)
            # Asked after the checks have run, so only files a check actually
            # needed to read are counted.
            if file_info.content_read_failed():
                unreadable += 1

        return ScanResult(
            target_path=resolved_path,
            files_inspected=files_inspected,
            findings=findings,
            policy_fail_on=config.fail_on,
            diagnostics=ScanDiagnostics(
                git_index_status=git_snapshot.status,
                entries_skipped=skipped[0],
                directories_skipped=directories_skipped[0],
                files_unreadable=unreadable,
                unmerged_index_paths=sum(
                    1
                    for rel_path in git_snapshot.unmerged_paths
                    if not config.is_excluded(rel_path)
                ),
            ),
        )

    @staticmethod
    def _validate_target(target_path: Path) -> Path:
        """Resolve the target and confirm it is a scannable directory."""
        try:
            resolved_path = target_path.resolve()
        except OSError as exc:
            raise InvalidTargetError(f"Path could not be resolved: {target_path}") from exc

        if not resolved_path.exists():
            raise InvalidTargetError(f"Path does not exist: {target_path}")
        if not resolved_path.is_dir():
            raise InvalidTargetError(f"Target is not a directory: {target_path}")
        try:
            os.scandir(resolved_path).close()
        except OSError as exc:
            raise InvalidTargetError(f"Directory cannot be read: {target_path}") from exc

        return resolved_path
