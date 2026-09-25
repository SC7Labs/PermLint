"""PL001: Check for shebang scripts without owner execute permission."""

from __future__ import annotations

from permlint.checks.base import BaseCheck
from permlint.checks.intent import expected_executable
from permlint.filesystem import FileInfo
from permlint.models import Finding, Severity


class ShebangExecutableCheck(BaseCheck):
    """Detects shebang scripts whose owner execute bit is clear."""

    check_id = "PL001"
    name = "Shebang but not executable"
    default_severity = Severity.ERROR

    def inspect(self, file_info: FileInfo) -> Finding | None:
        """Inspect the file for PL001."""
        # Contents could not be read. An unknown file is not a clean file, so
        # this check declines to conclude anything; the scan counts it instead.
        if not file_info.content_readable:
            return None
        if not file_info.is_owner_executable and file_info.has_shebang():
            return Finding(
                check_id=self.check_id,
                path=file_info.rel_path,
                severity=self.default_severity,
                message="Has a shebang but is not executable",
                filesystem_mode=file_info.mode,
                git_index_mode=file_info.git_index_mode,
                expected_executable=expected_executable(file_info),
                detail="The file has a valid interpreter line but its owner execute bit is clear.",
            )
        return None
