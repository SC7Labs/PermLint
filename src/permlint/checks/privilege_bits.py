"""PL008: Check for unexpected setuid or setgid privilege bits on repository files."""

from __future__ import annotations

from permlint.checks.base import BaseCheck
from permlint.filesystem import FileInfo
from permlint.models import Finding, Severity


class UnexpectedPrivilegeBitsCheck(BaseCheck):
    """Detects regular files with setuid (S_ISUID) or setgid (S_ISGID) bits set."""

    check_id = "PL008"
    name = "Unexpected privilege bits"
    default_severity = Severity.ERROR

    def inspect(self, file_info: FileInfo) -> Finding | None:
        """Inspect the file for PL008."""
        if file_info.has_privilege_bits:
            return Finding(
                check_id=self.check_id,
                path=file_info.rel_path,
                severity=self.default_severity,
                message="Regular file has setuid/setgid permission bits",
            )
        return None
