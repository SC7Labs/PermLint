"""PL003: Check for executable data or documentation files."""

from __future__ import annotations

from permlint.checks.base import BaseCheck
from permlint.checks.intent import DATA_EXTENSIONS, expected_executable
from permlint.filesystem import FileInfo
from permlint.models import Finding, Severity


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
                filesystem_mode=file_info.mode,
                git_index_mode=file_info.git_index_mode,
                expected_executable=expected_executable(file_info),
                detail="Data or documentation file carries an executable bit.",
            )
        return None
