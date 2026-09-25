"""Safe, read-only Git index metadata retrieval."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from permlint.models import GitIndexStatus


@dataclass(frozen=True)
class GitIndexSnapshot:
    """A bulk view of Git's staged executable bits and unresolved paths."""

    modes: dict[Path, str] | None
    status: GitIndexStatus
    unmerged_paths: frozenset[Path] = frozenset()


def _git_env() -> dict[str, str]:
    """Bind Git to the requested root and keep status errors locale-stable."""
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment["LC_ALL"] = "C"
    return environment


def get_git_index_snapshot(repo_root: Path) -> GitIndexSnapshot:
    """Retrieve Git staged/index file modes for a repository directory.

    Runs `git ls-files --stage -z` once for the entire repository.
    Safe and read-only:
    - Never uses shell=True.
    - Explicit bounded timeout.
    - No modification to the Git repository or index.
    - Reports an explicit status if Git is missing, this is not a repository,
      or the index cannot be read.

    Args:
        repo_root: The root directory of the target repository.

    Unmerged index entries have stages 1-3, with no single staged mode. Their
    paths are returned separately and never represented as a normal mode.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "--stage", "-z"],
            cwd=str(repo_root),
            env=_git_env(),
            capture_output=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        # No `git` on PATH at all.
        return GitIndexSnapshot(None, GitIndexStatus.GIT_UNAVAILABLE)
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
        return GitIndexSnapshot(None, GitIndexStatus.ERROR)

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").lower()
        if "not a git repository" in stderr:
            return GitIndexSnapshot(None, GitIndexStatus.NOT_A_REPOSITORY)
        return GitIndexSnapshot(None, GitIndexStatus.ERROR)

    if result.stdout and not result.stdout.endswith(b"\x00"):
        return GitIndexSnapshot(None, GitIndexStatus.ERROR)

    index_modes: dict[Path, str] = {}
    unmerged_paths: set[Path] = set()
    raw_entries = result.stdout.split(b"\x00")

    for entry_bytes in raw_entries:
        if not entry_bytes:
            continue

        # `os.fsdecode` uses surrogateescape on POSIX. Replacement decoding
        # would destroy a non-UTF-8 name's identity and silently miss it.
        entry_str = os.fsdecode(entry_bytes)
        if "\t" not in entry_str:
            return GitIndexSnapshot(None, GitIndexStatus.ERROR)

        metadata, path_str = entry_str.split("\t", 1)
        fields = metadata.split()
        if len(fields) != 3 or fields[2] not in {"0", "1", "2", "3"}:
            return GitIndexSnapshot(None, GitIndexStatus.ERROR)
        mode, _object_id, stage = fields
        rel_path = Path(path_str)
        if stage != "0":
            unmerged_paths.add(rel_path)
        elif mode in ("100644", "100755"):
            index_modes[rel_path] = mode

    for rel_path in unmerged_paths:
        index_modes.pop(rel_path, None)

    return GitIndexSnapshot(index_modes, GitIndexStatus.AVAILABLE, frozenset(unmerged_paths))


def get_git_index_modes(repo_root: Path) -> tuple[dict[Path, str] | None, GitIndexStatus]:
    """Compatibility wrapper for callers needing only index modes and status."""
    snapshot = get_git_index_snapshot(repo_root)
    return snapshot.modes, snapshot.status
