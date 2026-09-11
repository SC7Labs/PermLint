"""Safe, read-only Git index metadata retrieval."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from permlint.models import GitIndexStatus


def get_git_index_modes(repo_root: Path) -> tuple[dict[Path, str] | None, GitIndexStatus]:
    """Retrieve Git staged / index file modes for a repository directory.

    Runs `git ls-files --stage -z` once for the entire repository.
    Safe and read-only:
    - Never uses shell=True.
    - Explicit bounded timeout.
    - No modification to the Git repository or index.
    - Gracefully returns None if Git is missing, not a repo, or an error occurs.

    Args:
        repo_root: The root directory of the target repository.

    Returns:
        A pair of (index modes, status). The modes are None whenever the status
        is anything but AVAILABLE. The status matters: "Git had nothing to say"
        and "Git was never asked" are different answers, and a check that cannot
        run must not look like a check that passed.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "--stage", "-z"],
            cwd=str(repo_root),
            capture_output=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        # No `git` on PATH at all.
        return None, GitIndexStatus.GIT_UNAVAILABLE
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
        return None, GitIndexStatus.ERROR

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").lower()
        if "not a git repository" in stderr:
            return None, GitIndexStatus.NOT_A_REPOSITORY
        return None, GitIndexStatus.ERROR

    index_modes: dict[Path, str] = {}
    raw_entries = result.stdout.split(b"\x00")

    for entry_bytes in raw_entries:
        if not entry_bytes:
            continue

        try:
            # `os.fsdecode` (surrogateescape) rather than `errors="replace"`.
            # A POSIX filename is bytes, and replacement decoding destroys any
            # byte that is not valid UTF-8 — the resulting path would never
            # match the one traversal produced, so PL007 would silently skip the
            # file instead of comparing its mode.
            entry_str = os.fsdecode(entry_bytes)
            if "\t" not in entry_str:
                continue

            metadata, path_str = entry_str.split("\t", 1)
            mode = metadata.split()[0]

            # Only track regular blob modes
            if mode in ("100644", "100755"):
                index_modes[Path(path_str)] = mode
        except Exception:
            continue

    return index_modes, GitIndexStatus.AVAILABLE
