"""PL004: Check for world-writable repository files."""

from __future__ import annotations

from permlint.checks.base import BaseCheck
from permlint.filesystem import FileInfo
from permlint.models import Finding, Severity


class WorldWritableCheck(BaseCheck):
    """Detects repository files that have the world/other write bit set."""

    check_id = "PL004"
    name = "World-writable file"
    default_severity = Severity.ERROR

    def inspect(self, file_info: FileInfo) -> Finding | None:
        """Inspect the file for PL004."""
        if file_info.is_world_writable:
            return Finding(
                check_id=self.check_id,
                path=file_info.rel_path,
                severity=self.default_severity,
                message="File is writable by all users",
            )
        return None
