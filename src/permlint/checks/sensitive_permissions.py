"""PL005: Check for sensitive-looking files with overly broad permissions."""

from __future__ import annotations

from permlint.checks.base import BaseCheck
from permlint.filesystem import FileInfo
from permlint.models import Finding, Severity

# Standard exact filenames associated with private keys
SENSITIVE_EXACT_NAMES: frozenset[str] = frozenset(
    {
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
    }
)


def is_sensitive_filename(name: str) -> bool:
    """Check if a filename matches conservative private-key / sensitive patterns.

    Args:
        name: The base filename to test.

    Returns:
        True if the filename looks like a private key, False otherwise.
    """
    name_lower = name.lower()

    # Never flag public keys
    if name_lower.endswith(".pub"):
        return False

    # Exact standard private key names
    if name_lower in SENSITIVE_EXACT_NAMES:
        return True

    # .key extension
    if name_lower.endswith(".key"):
        return True

    # .key.pem compound extension (e.g. server.key.pem)
    if name_lower.endswith(".key.pem"):
        return True

    # .pem files indicating a private key (e.g. server-private.pem, privkey.pem)
    if name_lower.endswith(".pem") and ("private" in name_lower or "privkey" in name_lower):
        return True

    return False


class SensitiveFilePermissionsCheck(BaseCheck):
    """Detects private-key-like files accessible by group or other users."""

    check_id = "PL005"
    name = "Sensitive-looking file has broad permissions"
    default_severity = Severity.WARNING

    def inspect(self, file_info: FileInfo) -> Finding | None:
        """Inspect the file for PL005."""
        if is_sensitive_filename(file_info.name) and file_info.is_group_or_other_accessible:
            return Finding(
                check_id=self.check_id,
                path=file_info.rel_path,
                severity=self.default_severity,
                message="Sensitive-looking file is accessible by group or other users",
            )
        return None
