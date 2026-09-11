"""Check definitions and registry for PermLint."""

from __future__ import annotations

from permlint.checks.base import BaseCheck
from permlint.checks.executable_data_file import ExecutableDataFileCheck
from permlint.checks.executable_no_shebang import ExecutableNoShebangCheck
from permlint.checks.git_mode_mismatch import GitModeMismatchCheck
from permlint.checks.malformed_shebang import MalformedShebangCheck
from permlint.checks.privilege_bits import UnexpectedPrivilegeBitsCheck
from permlint.checks.sensitive_permissions import SensitiveFilePermissionsCheck
from permlint.checks.shebang_executable import ShebangExecutableCheck
from permlint.checks.world_writable import WorldWritableCheck


def get_default_checks() -> list[BaseCheck]:
    """Return an instantiated list of all default PermLint checks in stable order (PL001..PL008)."""
    return [
        ShebangExecutableCheck(),
        ExecutableNoShebangCheck(),
        ExecutableDataFileCheck(),
        WorldWritableCheck(),
        SensitiveFilePermissionsCheck(),
        MalformedShebangCheck(),
        GitModeMismatchCheck(),
        UnexpectedPrivilegeBitsCheck(),
    ]


__all__ = [
    "BaseCheck",
    "ExecutableDataFileCheck",
    "ExecutableNoShebangCheck",
    "GitModeMismatchCheck",
    "MalformedShebangCheck",
    "SensitiveFilePermissionsCheck",
    "ShebangExecutableCheck",
    "UnexpectedPrivilegeBitsCheck",
    "WorldWritableCheck",
    "get_default_checks",
]
