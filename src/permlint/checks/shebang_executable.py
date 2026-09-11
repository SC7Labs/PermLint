"""PL001: Check for script files with a shebang that lack executable permission bits."""

from __future__ import annotations

from permlint.checks.base import BaseCheck
from permlint.filesystem import FileInfo
from permlint.models import Finding, Severity


class ShebangExecutableCheck(BaseCheck):
    """Detects script files beginning with a shebang (#!), but missing executable bits."""

    check_id = "PL001"
    name = "Shebang but not executable"
    default_severity = Severity.ERROR

    def inspect(self, file_info: FileInfo) -> Finding | None:
        """Inspect the file for PL001."""
        # Contents could not be read. An unknown file is not a clean file, so
        # this check declines to conclude anything; the scan counts it instead.
        if not file_info.content_readable:
            return None
        if not file_info.is_executable and file_info.has_shebang():
            return Finding(
                check_id=self.check_id,
                path=file_info.rel_path,
                severity=self.default_severity,
                message="Has a shebang but is not executable",
            )
        return None
