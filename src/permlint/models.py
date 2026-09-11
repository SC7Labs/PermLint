"""Data models for PermLint findings and scan results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class Severity(StrEnum):
    """Severity level of a finding."""

    ERROR = "error"
    WARNING = "warning"

    @property
    def label(self) -> str:
        """Return a formatted uppercase label."""
        if self == Severity.ERROR:
            return "ERROR"
        return "WARN"


@dataclass(frozen=True)
class Finding:
    """Represents a discovered permission issue."""

    check_id: str
    path: Path
    severity: Severity
    message: str


class GitIndexStatus(StrEnum):
    """Whether the Git index was available to compare working-tree modes against.

    PL007 compares the executable bit on disk with the mode Git has staged. When
    the index cannot be read there is nothing to compare, and that is a
    different answer from "compared, and they matched".
    """

    AVAILABLE = "available"
    NOT_A_REPOSITORY = "not_a_repository"
    GIT_UNAVAILABLE = "git_unavailable"
    ERROR = "error"


@dataclass
class ScanDiagnostics:
    """What the scan could and could not look at.

    PermLint reports on the filesystem, and the filesystem does not always
    cooperate. Rather than let an unreadable file quietly become a clean one,
    the parts of the scan that did not happen are counted here and shown to the
    user.
    """

    git_index_status: GitIndexStatus = GitIndexStatus.GIT_UNAVAILABLE
    entries_skipped: int = 0
    """Files that could not be stat-ed during traversal."""
    directories_skipped: int = 0
    """Directories that could not be entered. Each one hides a whole subtree."""
    files_unreadable: int = 0
    """Files whose contents a check needed but could not read."""

    @property
    def git_is_applicable(self) -> bool:
        """Whether a Git index comparison was possible in principle.

        A directory that is not a repository has no index to compare against.
        That is an answer, not a gap, so it does not make a scan incomplete —
        and the report must not say it did.
        """
        return self.git_index_status is not GitIndexStatus.NOT_A_REPOSITORY

    @property
    def is_complete(self) -> bool:
        """True when nothing was left out for an environmental reason.

        `NOT_A_REPOSITORY` does not count: there is no index to compare against.
        A missing `git` executable or a failed `git` invocation do count — in
        both cases PL007 could not run somewhere it should have.
        """
        if self.entries_skipped or self.directories_skipped or self.files_unreadable:
            return False
        return self.git_index_status in (
            GitIndexStatus.AVAILABLE,
            GitIndexStatus.NOT_A_REPOSITORY,
        )

    @property
    def git_comparison_available(self) -> bool:
        """True when working-tree modes could be compared against the index."""
        return self.git_index_status is GitIndexStatus.AVAILABLE


@dataclass
class ScanResult:
    """Represents the outcome of a repository scan."""

    target_path: Path
    files_inspected: int = 0
    findings: list[Finding] = field(default_factory=list)
    diagnostics: ScanDiagnostics = field(default_factory=ScanDiagnostics)

    @property
    def error_count(self) -> int:
        """Number of error-level findings."""
        return sum(1 for f in self.findings if f.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        """Number of warning-level findings."""
        return sum(1 for f in self.findings if f.severity == Severity.WARNING)

    @property
    def total_findings(self) -> int:
        """Total number of findings."""
        return len(self.findings)

    @property
    def has_findings(self) -> bool:
        """Whether any findings were discovered."""
        return bool(self.findings)

    @property
    def exit_code(self) -> int:
        """Process exit code for this scan. The single source of truth.

        * ``0`` — the scan completed and found nothing.
        * ``1`` — findings exist, **or** the scan was incomplete.
        * ``2`` — invalid target; raised as `InvalidTargetError` before a
          `ScanResult` exists, and mapped by the CLI.

        An incomplete scan exits non-zero deliberately. In CI, "I found no
        problems" and "I could not look" must not be the same signal: a broken
        `git` or an unreadable subtree would otherwise turn into a green build.
        """
        if self.has_findings or not self.diagnostics.is_complete:
            return 1
        return 0
