"""PL007: Check for discrepancies between working tree permissions and the Git index."""

from __future__ import annotations

import stat

from permlint.checks.base import BaseCheck
from permlint.filesystem import FileInfo
from permlint.models import Finding, Severity


class GitModeMismatchCheck(BaseCheck):
    """Detects when working tree executable status differs from the Git staged mode."""

    check_id = "PL007"
    name = "Git executable-bit mismatch"
    default_severity = Severity.WARNING

    def inspect(self, file_info: FileInfo) -> Finding | None:
        """Inspect the file for PL007."""
        if file_info.git_index_mode is None:
            return None

        git_is_executable = file_info.git_index_mode == "100755"
        # Git's 100755/100644 distinction follows the owner execute bit.
        working_is_executable = bool(file_info.mode & stat.S_IXUSR)

        if git_is_executable != working_is_executable:
            return Finding(
                check_id=self.check_id,
                path=file_info.rel_path,
                severity=self.default_severity,
                message="Working tree executable bit does not match Git index",
            )
        return None
