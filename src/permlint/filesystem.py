"""Filesystem traversal and file inspection utilities for PermLint.

Provides safe, bounded, single-pass traversal of software repositories,
excluding version-control internals and symlink loops. Other exclusions are
explicit project configuration, so large source trees remain scannable.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from permlint.permissions import (
    has_privilege_bits,
    is_executable,
    is_group_or_other_accessible,
    is_regular_file,
    is_world_writable,
)

# Version-control metadata is never source material. Everything else, including
# dependencies and generated trees, is scanned unless explicitly excluded.
DEFAULT_IGNORE_DIRS: frozenset[str] = frozenset({".git", ".hg", ".svn"})


@dataclass(frozen=True)
class ShebangInfo:
    """Parsed shebang metadata from a bounded file read."""

    present: bool
    valid: bool
    raw_header: str
    interpreter: str
    readable: bool = True
    """False when the bytes could not be read at all.

    The other fields are then meaningless and must not be read as facts about
    the file: `present=False` would otherwise be indistinguishable from a file
    that genuinely has no shebang.
    """


@dataclass
class FileInfo:
    """Represents a discovered repository file with lazily-evaluated properties."""

    path: Path
    rel_path: Path
    mode: int
    git_index_mode: str | None = None

    _shebang_info: ShebangInfo | None = None
    _is_binary: bool | None = None
    _content_read_failed: bool = False

    @property
    def suffix(self) -> str:
        """Return lowercase file extension with leading dot (e.g. '.py')."""
        return self.path.suffix.lower()

    @property
    def name(self) -> str:
        """Return the file name."""
        return self.path.name

    @property
    def is_regular_file(self) -> bool:
        """Check whether the mode represents a regular file."""
        return is_regular_file(self.mode)

    @property
    def is_executable(self) -> bool:
        """Check whether any Unix executable bit (user, group, or other) is set."""
        return is_executable(self.mode)

    @property
    def is_owner_executable(self) -> bool:
        """Git's executable bit corresponds to the working-tree owner bit."""
        return bool(self.mode & stat.S_IXUSR)

    @property
    def is_world_writable(self) -> bool:
        """Check whether the world/other write bit (S_IWOTH) is set."""
        return is_world_writable(self.mode)

    @property
    def is_group_or_other_accessible(self) -> bool:
        """Check whether group or other users have read, write, or execute access."""
        return is_group_or_other_accessible(self.mode)

    @property
    def has_privilege_bits(self) -> bool:
        """Check whether setuid or setgid privilege bits are set."""
        return has_privilege_bits(self.mode)

    @property
    def shebang_info(self) -> ShebangInfo:
        """Parse and return cached shebang information from a bounded read."""
        if self._shebang_info is not None:
            return self._shebang_info

        try:
            with open(self.path, "rb") as f:
                header = f.read(512)
        except OSError:
            # Not "no shebang" — "unknown". Content checks refuse to conclude
            # anything from this, and the scan counts the file as unreadable.
            self._shebang_info = ShebangInfo(
                present=False, valid=False, raw_header="", interpreter="", readable=False
            )
            return self._shebang_info

        # Lines beginning with '#![' are Rust inner attributes, not shebangs
        if not header.startswith(b"#!") or header.startswith(b"#!["):
            self._shebang_info = ShebangInfo(
                present=False, valid=False, raw_header="", interpreter=""
            )
            return self._shebang_info

        first_line_bytes = header.split(b"\n", 1)[0]
        if b"\x00" in first_line_bytes:
            # Binary file with #! header is considered malformed
            self._shebang_info = ShebangInfo(
                present=True, valid=False, raw_header="", interpreter=""
            )
            return self._shebang_info

        first_line_str = first_line_bytes.decode("utf-8", errors="replace").strip()
        after_hashbang = first_line_str[2:].strip()

        if not after_hashbang:
            # Empty shebang like "#!" or "#!   "
            self._shebang_info = ShebangInfo(
                present=True, valid=False, raw_header=first_line_str, interpreter=""
            )
            return self._shebang_info

        interp_path = after_hashbang.split()[0]
        is_valid = interp_path.startswith("/")

        self._shebang_info = ShebangInfo(
            present=True,
            valid=is_valid,
            raw_header=first_line_str,
            interpreter=interp_path,
        )
        return self._shebang_info

    def has_shebang(self) -> bool:
        """Check if the file has a structurally valid Unix shebang."""
        info = self.shebang_info
        return info.readable and info.present and info.valid

    def has_raw_shebang_prefix(self) -> bool:
        """Check if the file begins with '#!' regardless of validity."""
        info = self.shebang_info
        return info.readable and info.present

    def is_shebang_malformed(self) -> bool:
        """Check if the file begins with '#!' but has an invalid structure."""
        info = self.shebang_info
        return info.readable and info.present and not info.valid

    def is_binary(self) -> bool | None:
        """Check if the file appears to be binary by inspecting the first chunk.

        Returns None when the contents could not be read. "Unreadable" is not
        "not binary".
        """
        if self._is_binary is not None:
            return self._is_binary

        try:
            with open(self.path, "rb") as f:
                chunk = f.read(1024)
        except OSError:
            self._content_read_failed = True
            return None

        # Null bytes indicate binary data (e.g. ELF, images, archives)
        self._is_binary = b"\x00" in chunk
        return self._is_binary

    @property
    def content_readable(self) -> bool:
        """Whether the file's contents can be read.

        Reads the header, so callers that do not otherwise need content should
        prefer `content_read_failed`.
        """
        return self.shebang_info.readable

    def content_read_failed(self) -> bool:
        """Whether a content read was attempted for this file and failed.

        Deliberately does not trigger a read: files no content check looked at
        are not counted as unreadable.
        """
        if self._content_read_failed:
            return True
        return self._shebang_info is not None and not self._shebang_info.readable


def walk_repository(
    root_path: Path,
    ignore_dirs: frozenset[str] = DEFAULT_IGNORE_DIRS,
    git_index_modes: dict[Path, str] | None = None,
    skipped: list[int] | None = None,
    directories_skipped: list[int] | None = None,
    is_excluded: Callable[[Path], bool] | None = None,
) -> Iterator[FileInfo]:
    """Safely traverse a repository directory and yield FileInfo for regular files.

    Guarantees:
    - Does not follow directory symlinks.
    - Does not follow file symlinks.
    - Prunes VCS internals and explicitly excluded directories immediately.
    - Ignores special files (FIFOs, sockets, devices).
    - Handles permission and filesystem errors gracefully.

    Args:
        root_path: The directory path to scan.
        ignore_dirs: Set of directory names to skip.
        git_index_modes: Optional mapping of relative Paths to Git index mode strings.
        skipped: Optional single-element list used as an out-parameter; incremented
            for every file that could not be stat-ed, so the caller can report an
            incomplete traversal rather than presenting it as a complete one.
        directories_skipped: Optional single-element out-parameter; incremented for
            every directory `os.walk` could not enter. Each one hides an entire
            subtree, so this is tracked separately from individual files.
        is_excluded: Optional predicate for explicitly excluded relative paths.

    Yields:
        FileInfo objects for each discovered regular file.
    """
    resolved_root = root_path.resolve()

    def _on_walk_error(_error: OSError) -> None:
        """Record a directory `os.walk` could not read.

        Without this, `os.walk` swallows the error and simply yields nothing for
        that subtree — every file inside it silently disappears from the scan
        while the result still looks complete.
        """
        if directories_skipped is not None:
            directories_skipped[0] += 1

    for dirpath_str, dirnames, filenames in os.walk(
        resolved_root, followlinks=False, onerror=_on_walk_error
    ):
        dirpath = Path(dirpath_str)

        # In-place filter dirnames to prune ignored dirs and directory symlinks
        dirnames[:] = [
            d
            for d in dirnames
            if d not in ignore_dirs
            and not (dirpath / d).is_symlink()
            and not (
                is_excluded is not None and is_excluded((dirpath / d).relative_to(resolved_root))
            )
        ]

        # Sort for deterministic traversal order
        dirnames.sort()
        filenames.sort()

        for filename in filenames:
            file_path = dirpath / filename

            rel_path = file_path.relative_to(resolved_root)
            if is_excluded is not None and is_excluded(rel_path):
                continue

            # Skip symlinks
            if file_path.is_symlink():
                continue

            try:
                stat_result = os.stat(file_path, follow_symlinks=False)
            except OSError:
                # Inaccessible entry. Counted rather than silently dropped: a
                # scan that could not look at something is not a clean scan.
                if skipped is not None:
                    skipped[0] += 1
                continue

            if not is_regular_file(stat_result.st_mode):
                continue

            git_mode = git_index_modes.get(rel_path) if git_index_modes is not None else None

            yield FileInfo(
                path=file_path,
                rel_path=rel_path,
                mode=stat_result.st_mode,
                git_index_mode=git_mode,
            )
