"""PL002: Check for executable script files that lack a shebang line."""

from __future__ import annotations

from permlint.checks.base import BaseCheck
from permlint.filesystem import FileInfo
from permlint.models import Finding, Severity

# Recognizable script/text file extensions
SCRIPT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".pl",
        ".rb",
        ".js",
        ".ts",
        ".mjs",
        ".cjs",
        ".pyw",
        ".ksh",
        ".csh",
    }
)


class ExecutableNoShebangCheck(BaseCheck):
    """Detects executable script-like files that lack a shebang line."""

    check_id = "PL002"
    name = "Executable script without shebang"
    default_severity = Severity.WARNING

    def inspect(self, file_info: FileInfo) -> Finding | None:
        """Inspect the file for PL002."""
        # Contents could not be read. An unknown file is not a clean file, so
        # this check declines to conclude anything; the scan counts it instead.
        if not file_info.content_readable:
            return None
        if (
            file_info.is_executable
            and file_info.suffix in SCRIPT_EXTENSIONS
            and not file_info.has_raw_shebang_prefix()
            and file_info.is_binary() is False
        ):
            return Finding(
                check_id=self.check_id,
                path=file_info.rel_path,
                severity=self.default_severity,
                message="Executable text file has no shebang",
            )
        return None
