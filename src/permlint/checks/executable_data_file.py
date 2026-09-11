"""PL003: Check for executable data or documentation files."""

from __future__ import annotations

from permlint.checks.base import BaseCheck
from permlint.filesystem import FileInfo
from permlint.models import Finding, Severity

# Obvious non-executable data, configuration, and documentation file extensions
DATA_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".md",
        ".txt",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".csv",
        ".xml",
        ".tsv",
        ".rst",
    }
)


class ExecutableDataFileCheck(BaseCheck):
    """Detects data and documentation files that unexpectedly have executable permission bits."""

    check_id = "PL003"
    name = "Unexpected executable data/document file"
    default_severity = Severity.WARNING

    def inspect(self, file_info: FileInfo) -> Finding | None:
        """Inspect the file for PL003."""
        if file_info.is_executable and file_info.suffix in DATA_EXTENSIONS:
            return Finding(
                check_id=self.check_id,
                path=file_info.rel_path,
                severity=self.default_severity,
                message="File type normally should not be executable",
            )
        return None
