"""Tests for Unix file permission semantics."""

from __future__ import annotations

import stat

from permlint.permissions import (
    format_mode,
    has_privilege_bits,
    is_executable,
    is_group_or_other_accessible,
    is_regular_file,
    is_world_writable,
)


def test_is_executable_various_modes() -> None:
    # No execute bits set
    assert not is_executable(0o644)
    assert not is_executable(0o600)
    assert not is_executable(0o400)
    assert not is_executable(0o666)

    # User execute only
    assert is_executable(0o700)
    assert is_executable(0o500)
    assert is_executable(0o100)

    # Group execute only
    assert is_executable(0o010)
    assert is_executable(0o050)
    assert is_executable(0o654)

    # Other execute only
    assert is_executable(0o001)
    assert is_executable(0o005)
    assert is_executable(0o645)

    # Standard combinations
    assert is_executable(0o755)
    assert is_executable(0o777)
    assert is_executable(0o750)


def test_is_world_writable() -> None:
    assert not is_world_writable(0o644)
    assert not is_world_writable(0o755)
    assert not is_world_writable(0o600)
    assert not is_world_writable(0o750)

    assert is_world_writable(0o666)
    assert is_world_writable(0o777)
    assert is_world_writable(0o602)
    assert is_world_writable(0o767)


def test_is_group_or_other_accessible() -> None:
    # Owner only (clean for sensitive files)
    assert not is_group_or_other_accessible(0o600)
    assert not is_group_or_other_accessible(0o400)
    assert not is_group_or_other_accessible(0o700)
    assert not is_group_or_other_accessible(0o000)

    # Group or other access
    assert is_group_or_other_accessible(0o644)
    assert is_group_or_other_accessible(0o664)
    assert is_group_or_other_accessible(0o755)
    assert is_group_or_other_accessible(0o640)
    assert is_group_or_other_accessible(0o604)
    assert is_group_or_other_accessible(0o777)


def test_has_privilege_bits() -> None:
    assert not has_privilege_bits(0o755)
    assert not has_privilege_bits(0o644)
    assert not has_privilege_bits(0o777)

    # setuid (0o4000)
    assert has_privilege_bits(0o4755)
    assert has_privilege_bits(0o4644)

    # setgid (0o2000)
    assert has_privilege_bits(0o2755)
    assert has_privilege_bits(0o2644)

    # both (0o6000)
    assert has_privilege_bits(0o6755)


def test_is_regular_file() -> None:
    assert is_regular_file(stat.S_IFREG | 0o644)
    assert is_regular_file(stat.S_IFREG | 0o755)
    assert not is_regular_file(stat.S_IFDIR | 0o755)
    assert not is_regular_file(stat.S_IFLNK | 0o777)
    assert not is_regular_file(stat.S_IFIFO | 0o644)


def test_format_mode() -> None:
    assert format_mode(0o755) == "0755"
    assert format_mode(0o644) == "0644"
    assert format_mode(0o600) == "0600"
    assert format_mode(0o4755) == "4755"
    assert format_mode(stat.S_IFREG | 0o755) == "0755"
