"""PL006: Check for files with malformed or unusable shebang lines."""

from __future__ import annotations

from permlint.checks.base import BaseCheck
from permlint.filesystem import FileInfo
from permlint.models import Finding, Severity


class MalformedShebangCheck(BaseCheck):
    """Detects files beginning with '#!' where the shebang line is structurally unusable."""

    check_id = "PL006"
    name = "Malformed shebang"
    default_severity = Severity.ERROR

    def inspect(self, file_info: FileInfo) -> Finding | None:
        """Inspect the file for PL006."""
        # Contents could not be read. An unknown file is not a clean file, so
        # this check declines to conclude anything; the scan counts it instead.
        if not file_info.content_readable:
            return None
        if file_info.is_shebang_malformed():
            return Finding(
                check_id=self.check_id,
                path=file_info.rel_path,
                severity=self.default_severity,
                message="Malformed shebang",
            )
        return None
