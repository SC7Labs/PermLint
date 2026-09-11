"""Unix file permission semantics and helpers.

In Unix / POSIX filesystems, permissions are controlled by mode bits:
- S_IXUSR, S_IXGRP, S_IXOTH: User, group, other execute bits
- S_IWOTH: Others / world write bit
- S_IRWXG, S_IRWXO: Group and other read/write/execute bits
- S_ISUID, S_ISGID: Set-user-ID and set-group-ID privilege bits

For PermLint v0.1:
- A file is executable if ANY execute bit (user, group, or other) is set.
- A file is world-writable if the other-write bit (S_IWOTH, 0o002) is set.
- A file has group/other access if any group or other bit (0o077) is set.
- A file has privilege bits if setuid (0o4000) or setgid (0o2000) is set.
"""

from __future__ import annotations

import stat

# Mask representing any execute bit set (user, group, or others)
EXECUTABLE_MASK = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH

# Mask representing any group or other access (read, write, or execute)
GROUP_OTHER_ACCESS_MASK = stat.S_IRWXG | stat.S_IRWXO

# Mask representing special privilege bits (setuid or setgid)
PRIVILEGE_BITS_MASK = stat.S_ISUID | stat.S_ISGID


def is_executable(mode: int) -> bool:
    """Check if any Unix executable bit is set on the mode.

    Args:
        mode: The integer file mode (e.g., from os.stat().st_mode).

    Returns:
        True if any of user, group, or other execute bits are set, False otherwise.
    """
    return bool(mode & EXECUTABLE_MASK)


def is_world_writable(mode: int) -> bool:
    """Check if the world/other write bit (S_IWOTH) is set on the mode.

    Args:
        mode: The integer file mode.

    Returns:
        True if world-writable, False otherwise.
    """
    return bool(mode & stat.S_IWOTH)


def is_group_or_other_accessible(mode: int) -> bool:
    """Check if any group or other permission bit (read, write, execute) is set.

    Args:
        mode: The integer file mode.

    Returns:
        True if accessible to group or others, False if owner-only access.
    """
    return bool(mode & GROUP_OTHER_ACCESS_MASK)


def has_privilege_bits(mode: int) -> bool:
    """Check if setuid (S_ISUID) or setgid (S_ISGID) bits are set on the mode.

    Args:
        mode: The integer file mode.

    Returns:
        True if setuid or setgid bits are set, False otherwise.
    """
    return bool(mode & PRIVILEGE_BITS_MASK)


def is_regular_file(mode: int) -> bool:
    """Check if the mode represents a regular file.

    Args:
        mode: The integer file mode.

    Returns:
        True if the mode represents a standard regular file, False otherwise.
    """
    return stat.S_ISREG(mode)


def format_mode(mode: int) -> str:
    """Format file permission bits as a 4-digit octal string (e.g. '0755').

    Args:
        mode: The integer file mode.

    Returns:
        A string representing the permission bits in octal.
    """
    return f"{stat.S_IMODE(mode):04o}"
