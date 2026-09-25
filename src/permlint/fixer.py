"""Conservative, reviewable executable-bit repairs.

Planning is read-only. Applying a plan checks its filesystem and Git evidence
again, then changes only file execute bits and, when needed, the matching Git
index mode. It never stages file contents.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from permlint.checks.executable_data_file import DATA_EXTENSIONS
from permlint.models import Finding, GitIndexStatus, ScanResult
from permlint.staged_content import StagedContentError, read_staged_headers

if TYPE_CHECKING:
    from permlint.config import Config


_HEADER_SIZE = 1024
_GIT_TIMEOUT = 30
_FIXABLE_RULES = frozenset({"PL001", "PL003", "PL007"})
_UNSAFE_COMPANION_RULES = frozenset({"PL004", "PL005", "PL006", "PL008"})


@dataclass(frozen=True)
class FixAction:
    """One proposed change to a regular file and, possibly, its Git index mode.

    Modes contain POSIX permission bits, without the regular-file type bits.
    The private fields capture the evidence that must still hold at apply time.
    """

    rel_path: Path
    before_mode: int
    after_mode: int
    before_git_mode: str | None
    after_git_mode: str | None
    reason: str
    _dev: int = field(default=-1, repr=False)
    _ino: int = field(default=-1, repr=False)
    _size: int = field(default=-1, repr=False)
    _mtime_ns: int = field(default=-1, repr=False)
    _header_digest: str = field(default="", repr=False)
    _git_blob: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ManualReview:
    """A finding for which PermLint has no safe, deterministic repair."""

    rel_path: Path
    reason: str
    check_ids: tuple[str, ...] = ()


@dataclass
class FixPlan:
    """A scan's proposed repairs and findings left for manual review."""

    root: Path
    scan: ScanResult
    actions: list[FixAction] = field(default_factory=list)
    manual: list[ManualReview] = field(default_factory=list)
    _root_dev: int = field(default=-1, repr=False)
    _root_ino: int = field(default=-1, repr=False)
    _git_available: bool = field(default=False, repr=False)
    _git_prefix: Path = field(default=Path("."), repr=False)
    _git_index_path: Path | None = field(default=None, repr=False)


@dataclass(frozen=True)
class FixFailure:
    """A planned repair that was refused or failed during application."""

    rel_path: Path
    reason: str


@dataclass
class FixOutcome:
    """Repairs that finished and repairs that need the user's attention."""

    applied: list[FixAction] = field(default_factory=list)
    failures: list[FixFailure] = field(default_factory=list)


@dataclass(frozen=True)
class _IndexEntry:
    mode: str
    blob: str
    stage: int


class _UnsafeFixError(Exception):
    """An action's assumptions no longer hold, or a safe operation failed."""


def _git_env() -> dict[str, str]:
    """Bind Git commands to the repository at ``root``, not caller overrides."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env["LC_ALL"] = "C"
    return env


def _git_run(
    root: Path,
    args: list[str],
    input_data: bytes | None = None,
    *,
    index_file: Path | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        env = _git_env()
        if index_file is not None:
            env["GIT_INDEX_FILE"] = os.fspath(index_file)
        result = subprocess.run(
            ["git", "--literal-pathspecs", *args],
            cwd=root,
            env=env,
            capture_output=True,
            input=input_data,
            check=False,
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _UnsafeFixError(f"Git command failed: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise _UnsafeFixError(f"Git command failed: {detail or f'exit {result.returncode}'}")
    return result


def _parse_index_records(data: bytes) -> dict[Path, list[_IndexEntry]]:
    entries: dict[Path, list[_IndexEntry]] = {}
    if data and not data.endswith(b"\0"):
        raise _UnsafeFixError("Git returned a truncated index listing")
    for record in data.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            raw_mode, raw_blob, raw_stage = metadata.split()
            mode = raw_mode.decode("ascii")
            blob = raw_blob.decode("ascii")
            stage = int(raw_stage)
            path = Path(os.fsdecode(raw_path))
            if not _safe_rel_path(path) or not blob or stage not in (0, 1, 2, 3):
                raise ValueError("invalid index entry")
        except (UnicodeError, ValueError) as exc:
            raise _UnsafeFixError("Git returned a malformed index entry") from exc
        entries.setdefault(path, []).append(_IndexEntry(mode, blob, stage))
    return entries


def _read_index(
    root: Path, rel_path: Path | None = None, *, index_file: Path | None = None
) -> dict[Path, list[_IndexEntry]]:
    args = ["ls-files", "--stage", "-z"]
    if rel_path is not None:
        args.extend(["--", os.fspath(rel_path)])
    return _parse_index_records(_git_run(root, args, index_file=index_file).stdout)


def _read_git_prefix(root: Path) -> Path:
    """Path from repository top level to the requested scan root.

    `ls-files` reports paths relative to the current directory, while
    `update-index --index-info` consumes paths relative to the repository top
    level. A nested scan must translate between those two namespaces.
    """
    output = _git_run(root, ["rev-parse", "--show-prefix"]).stdout
    if not output.endswith(b"\n") or b"\0" in output:
        raise _UnsafeFixError("Git returned an invalid repository prefix")
    raw = output[:-1]
    if not raw:
        return Path(".")
    if not raw.endswith(b"/"):
        raise _UnsafeFixError("Git returned an invalid repository prefix")
    prefix = Path(os.fsdecode(raw))
    if not _safe_rel_path(prefix):
        raise _UnsafeFixError("Git repository prefix is unsafe")
    return prefix


def _git_index_path(root: Path) -> Path:
    """Locate the active index, including a linked worktree's private index."""
    output = _git_run(root, ["rev-parse", "--git-path", "index"]).stdout
    if not output.endswith(b"\n") or b"\0" in output:
        raise _UnsafeFixError("Git returned an invalid index path")
    raw = output[:-1]
    if not raw:
        raise _UnsafeFixError("Git returned an empty index path")
    path = Path(os.fsdecode(raw))
    return path if path.is_absolute() else root / path


@contextmanager
def _locked_index(plan: FixPlan) -> Iterator[tuple[Path, os.stat_result | None]]:
    """Hold Git's standard index lock across recheck, update, and replacement.

    Git writers acquire this same `<index>.lock` path. A competing writer that
    wins first makes us refuse the repair; a writer arriving later cannot
    replace the index until this transaction finishes.
    """
    index_path = _git_index_path(plan.root)
    if index_path != plan._git_index_path:
        raise _UnsafeFixError("Git index location changed since planning")
    lock_path = Path(os.fspath(index_path) + ".lock")
    try:
        lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    except FileExistsError as exc:
        raise _UnsafeFixError("Git index is locked by another process; try again") from exc
    except OSError as exc:
        raise _UnsafeFixError(f"Cannot lock Git index: {exc}") from exc
    lock_info = os.fstat(lock_fd)
    os.close(lock_fd)
    try:
        try:
            index_info = os.stat(index_path, follow_symlinks=False)
        except FileNotFoundError:
            # Git need not create an index until the first file is staged.
            # Its lock still serializes an untracked filesystem-only repair.
            index_info = None
        except OSError as exc:
            raise _UnsafeFixError(f"Cannot inspect Git index: {exc}") from exc
        if index_info is not None and (
            not stat.S_ISREG(index_info.st_mode) or index_info.st_nlink != 1
        ):
            raise _UnsafeFixError("Git index is not an ordinary single-link file")
        yield index_path, index_info
    finally:
        # Only unlink the lock inode we created. A rogue process that replaced
        # the pathname must not have its own lock removed by this cleanup.
        try:
            current = os.stat(lock_path, follow_symlinks=False)
            if (current.st_dev, current.st_ino) == (lock_info.st_dev, lock_info.st_ino):
                os.unlink(lock_path)
        except FileNotFoundError:
            pass


def _same_index_file(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )


def _read_index_flags(
    root: Path, rel_path: Path | None = None, *, index_file: Path | None = None
) -> dict[Path, list[bytes]]:
    """Read all Git cache-entry flags, including intent-to-add.

    `ls-files -v` exposes assume-unchanged and skip-worktree, but labels an
    intent-to-add entry as ordinary `H`. `--debug` exposes its extended flags.
    The debug format puts a NUL after each filename and five metadata lines
    after it. Reject unknown output rather than assuming the flags are clear.
    """
    args = ["ls-files", "--debug", "-z"]
    if rel_path is not None:
        args.extend(["--", os.fspath(rel_path)])
    output = _git_run(root, args, index_file=index_file).stdout
    flags_by_path: dict[Path, list[bytes]] = {}
    offset = 0
    while offset < len(output):
        end = output.find(b"\0", offset)
        if end < 0:
            raise _UnsafeFixError("Git returned malformed index flags")
        path = Path(os.fsdecode(output[offset:end]))
        if not _safe_rel_path(path):
            raise _UnsafeFixError("Git returned an unsafe index path")
        offset = end + 1
        lines: list[bytes] = []
        for _ in range(5):
            end = output.find(b"\n", offset)
            if end < 0:
                raise _UnsafeFixError("Git returned incomplete index flags")
            lines.append(output[offset:end])
            offset = end + 1
        if not lines[4].lstrip().startswith(b"size:") or b"flags:" not in lines[4]:
            raise _UnsafeFixError("Git returned unrecognized index flags")
        flags = lines[4].rsplit(b"flags:", 1)[1].strip()
        if not flags:
            raise _UnsafeFixError("Git returned empty index flags")
        flags_by_path.setdefault(path, []).append(flags)
    return flags_by_path


def _single_regular_entry(
    entries: dict[Path, list[_IndexEntry]], rel_path: Path
) -> _IndexEntry | None:
    path_entries = entries.get(rel_path, [])
    if not path_entries:
        return None
    if len(path_entries) != 1 or path_entries[0].stage != 0:
        raise _UnsafeFixError("Unmerged or duplicate Git index entries require manual review")
    entry = path_entries[0]
    if entry.mode not in ("100644", "100755"):
        raise _UnsafeFixError("Git index entry is not a regular file")
    return entry


def _require_plain_index_flags(
    flags_by_path: dict[Path, list[bytes]], rel_path: Path, tracked: bool
) -> None:
    flags = flags_by_path.get(rel_path, [])
    if tracked and flags != [b"0"]:
        raise _UnsafeFixError(
            "Git index has nonstandard flags (such as intent-to-add, skip-worktree, or "
            "assume-unchanged); manual review required"
        )
    if not tracked and flags:
        raise _UnsafeFixError("Git index tracking changed; scan again")


def _safe_rel_path(path: Path) -> bool:
    return (
        not path.is_absolute()
        and bool(path.parts)
        and all(part not in ("", ".", "..") for part in path.parts)
    )


def _selected_prefixes(
    root: Path, root_fd: int, selected_paths: list[Path] | None
) -> list[Path] | None:
    if selected_paths is None:
        return None
    selections: list[Path] = []
    for raw in selected_paths:
        path = Path(raw)
        if path.is_absolute():
            try:
                path = path.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"Selected path is outside scan root: {raw}") from exc
        if path != Path(".") and not _safe_rel_path(path):
            raise ValueError(f"Selected path is unsafe: {raw}")
        if path != Path("."):
            # Validate every component with O_NOFOLLOW. Even a selection with
            # no findings must not quietly succeed if it was mistyped.
            fd = os.dup(root_fd)
            try:
                for index, part in enumerate(path.parts):
                    is_last = index == len(path.parts) - 1
                    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
                    if not is_last:
                        flags |= os.O_DIRECTORY
                    next_fd = os.open(part, flags, dir_fd=fd)
                    os.close(fd)
                    fd = next_fd
                info = os.fstat(fd)
                if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                    raise ValueError(f"Selected path is not a regular file or directory: {raw}")
            except OSError as exc:
                raise ValueError(f"Selected path cannot be opened safely: {raw}: {exc}") from exc
            finally:
                os.close(fd)
        selections.append(path)
    return selections


def _is_selected(path: Path, selections: list[Path] | None) -> bool:
    if selections is None:
        return True
    return any(
        selection == Path(".") or path == selection or selection in path.parents
        for selection in selections
    )


def _open_root(root: Path, expected: tuple[int, int] | None = None) -> tuple[int, os.stat_result]:
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise _UnsafeFixError("Safe no-symlink file operations are unavailable on this platform")
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        info = os.fstat(fd)
    except OSError as exc:
        raise _UnsafeFixError(f"Cannot open scan root safely: {exc}") from exc
    if expected is not None and (info.st_dev, info.st_ino) != expected:
        os.close(fd)
        raise _UnsafeFixError("Scan root changed since the repair was planned")
    return fd, info


def _open_regular(root_fd: int, rel_path: Path) -> tuple[int, os.stat_result]:
    if not _safe_rel_path(rel_path):
        raise _UnsafeFixError("Path is outside the scan root or is not a regular relative path")
    parent_fd = os.dup(root_fd)
    try:
        for part in rel_path.parts[:-1]:
            next_fd = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent_fd,
            )
            os.close(parent_fd)
            parent_fd = next_fd
        fd = os.open(
            rel_path.parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=parent_fd,
        )
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            os.close(fd)
            raise _UnsafeFixError("Target is no longer a regular file")
        return fd, info
    except OSError as exc:
        raise _UnsafeFixError(f"Cannot open target without following symlinks: {exc}") from exc
    finally:
        os.close(parent_fd)


def _reject_nested_git_boundary(root_fd: int, rel_path: Path) -> None:
    """Do not treat files in an inner repository as outer-repo untracked files."""
    if not _safe_rel_path(rel_path):
        raise _UnsafeFixError("Path is unsafe")
    directory_fd = os.dup(root_fd)
    try:
        for part in rel_path.parts[:-1]:
            next_fd = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
            try:
                os.stat(".git", dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise _UnsafeFixError(f"Cannot verify nested Git boundary: {exc}") from exc
            else:
                raise _UnsafeFixError("Path belongs to a nested Git repository; scan it directly")
    except OSError as exc:
        raise _UnsafeFixError(f"Cannot inspect parent directory safely: {exc}") from exc
    finally:
        os.close(directory_fd)


def _header(fd: int) -> bytes:
    try:
        return os.pread(fd, _HEADER_SIZE, 0)
    except OSError as exc:
        raise _UnsafeFixError(f"Cannot read file evidence: {exc}") from exc


def _valid_shebang(header: bytes) -> bool:
    # Match scanner semantics, including the Rust #![...] exclusion.
    if not header.startswith(b"#!") or header.startswith(b"#!["):
        return False
    first_line = header[:512].split(b"\n", 1)[0]
    if b"\0" in first_line:
        return False
    text = first_line.decode("utf-8", errors="replace").strip()
    words = text[2:].strip().split()
    return bool(words) and words[0].startswith("/")


def _intent(path: Path, header: bytes) -> tuple[bool | None, str]:
    shebang = _valid_shebang(header)
    data_type = path.suffix.lower() in DATA_EXTENSIONS
    if shebang and data_type:
        return None, "Shebang and data-file extension give conflicting executable intent"
    if shebang:
        return True, "Valid shebang indicates an executable script"
    if data_type and b"\0" not in header and not header.startswith(b"#!"):
        return False, "Readable, nonbinary data/document file has no shebang"
    return None, "Executable intent is ambiguous; no safe automatic repair"


def _manual(path: Path, ids: tuple[str, ...], reason: str) -> ManualReview:
    return ManualReview(rel_path=path, reason=reason, check_ids=ids)


def plan_fixes(
    scan: ScanResult,
    config: Config | None = None,
    selected_paths: list[Path] | None = None,
) -> FixPlan:
    """Build a read-only plan from a scan, using current file and Git evidence.

    A valid shebang supports adding only the owner execute bit. An obvious
    data/document file supports removing all execute bits. A Git mismatch by
    itself says nothing about which side is right and stays manual.
    """
    root = scan.target_path
    root_fd, root_info = _open_root(root)
    plan = FixPlan(
        root=root,
        scan=scan,
        _root_dev=root_info.st_dev,
        _root_ino=root_info.st_ino,
        _git_available=scan.diagnostics.git_index_status is GitIndexStatus.AVAILABLE,
    )
    try:
        selections = _selected_prefixes(root, root_fd, selected_paths)
        findings_by_path: dict[Path, list[Finding]] = {}
        for finding in scan.findings:
            if _is_selected(finding.path, selections):
                findings_by_path.setdefault(finding.path, []).append(finding)

        index_entries: dict[Path, list[_IndexEntry]] = {}
        index_flags: dict[Path, list[bytes]] = {}
        index_problem: str | None = None
        if plan._git_available:
            try:
                index_entries = _read_index(root)
                index_flags = _read_index_flags(root)
                plan._git_prefix = _read_git_prefix(root)
                plan._git_index_path = _git_index_path(root)
            except _UnsafeFixError as exc:
                index_problem = str(exc)
        elif scan.diagnostics.git_index_status is not GitIndexStatus.NOT_A_REPOSITORY:
            index_problem = "Git index was unavailable; tracked status cannot be verified"

        staged_headers: dict[str, bytes] = {}
        staged_problem: str | None = None
        if plan._git_available and index_problem is None:
            candidate_blobs: set[str] = set()
            for rel_path, findings in findings_by_path.items():
                ids = {finding.check_id for finding in findings}
                if (
                    not _safe_rel_path(rel_path)
                    or not _FIXABLE_RULES.intersection(ids)
                    or _UNSAFE_COMPANION_RULES.intersection(ids)
                ):
                    continue
                try:
                    entry = _single_regular_entry(index_entries, rel_path)
                except _UnsafeFixError:
                    continue
                if entry is not None:
                    candidate_blobs.add(entry.blob)
            try:
                staged_headers = read_staged_headers(root, candidate_blobs)
            except StagedContentError as exc:
                staged_problem = f"Cannot inspect staged Git content: {exc}"

        fix_git_index = bool(getattr(config, "fix_git_index", True))
        for rel_path, findings in sorted(
            findings_by_path.items(), key=lambda item: os.fspath(item[0])
        ):
            ids = tuple(sorted({finding.check_id for finding in findings}))
            if not _safe_rel_path(rel_path):
                plan.manual.append(_manual(rel_path, ids, "Finding path is unsafe"))
                continue
            if index_problem:
                plan.manual.append(_manual(rel_path, ids, index_problem))
                continue
            if not _FIXABLE_RULES.intersection(ids):
                plan.manual.append(
                    _manual(
                        rel_path,
                        ids,
                        "No deterministic executable-bit repair exists for these rules",
                    )
                )
                continue
            if _UNSAFE_COMPANION_RULES.intersection(ids):
                plan.manual.append(
                    _manual(
                        rel_path,
                        ids,
                        "Other permission findings require manual review before repair",
                    )
                )
                continue

            try:
                _reject_nested_git_boundary(root_fd, rel_path)
                fd, info = _open_regular(root_fd, rel_path)
                try:
                    if info.st_nlink != 1:
                        raise _UnsafeFixError(
                            "File has multiple hard links; mode change could affect an outside path"
                        )
                    header = _header(fd)
                finally:
                    os.close(fd)
                mode = stat.S_IMODE(info.st_mode)
                if mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX | stat.S_IWOTH):
                    raise _UnsafeFixError(
                        "World-writable or special permission bits require manual review"
                    )
                expected_exec, reason = _intent(rel_path, header)
                if expected_exec is None:
                    raise _UnsafeFixError(reason)
                entry = _single_regular_entry(index_entries, rel_path)
                if plan._git_available:
                    _require_plain_index_flags(index_flags, rel_path, entry is not None)
                if entry is not None:
                    if staged_problem is not None:
                        raise _UnsafeFixError(staged_problem)
                    staged_header = staged_headers.get(entry.blob)
                    if staged_header is None:
                        raise _UnsafeFixError("Git staged header was unavailable")
                    staged_intent, _ = _intent(rel_path, staged_header)
                    if staged_intent is not expected_exec:
                        raise _UnsafeFixError(
                            "Staged Git content does not support the working-tree executable intent"
                        )
                before_git_mode = entry.mode if entry else None
                desired_git_mode = ("100755" if expected_exec else "100644") if entry else None
                if entry and desired_git_mode != before_git_mode and not fix_git_index:
                    raise _UnsafeFixError("Git index repair is disabled by configuration")
                after_mode = (mode | stat.S_IXUSR) if expected_exec else (mode & ~0o111)
                if after_mode == mode and desired_git_mode == before_git_mode:
                    # The file changed since scanning, and the finding is stale.
                    raise _UnsafeFixError("Finding is no longer present; scan again")
                plan.actions.append(
                    FixAction(
                        rel_path=rel_path,
                        before_mode=mode,
                        after_mode=after_mode,
                        before_git_mode=before_git_mode,
                        after_git_mode=desired_git_mode,
                        reason=reason,
                        _dev=info.st_dev,
                        _ino=info.st_ino,
                        _size=info.st_size,
                        _mtime_ns=info.st_mtime_ns,
                        _header_digest=hashlib.sha256(header).hexdigest(),
                        _git_blob=entry.blob if entry else None,
                    )
                )
            except _UnsafeFixError as exc:
                plan.manual.append(_manual(rel_path, ids, str(exc)))
    finally:
        os.close(root_fd)
    return plan


def _check_index_snapshot(plan: FixPlan, action: FixAction) -> None:
    if not plan._git_available:
        return
    current = _single_regular_entry(_read_index(plan.root, action.rel_path), action.rel_path)
    flags = _read_index_flags(plan.root, action.rel_path)
    _require_plain_index_flags(flags, action.rel_path, current is not None)
    if action.before_git_mode is None:
        if current is not None:
            raise _UnsafeFixError("File became tracked after planning; scan again")
    elif (
        current is None
        or current.mode != action.before_git_mode
        or current.blob != action._git_blob
    ):
        raise _UnsafeFixError("Git index mode or staged content changed since planning")


def _check_file_snapshot(action: FixAction, info: os.stat_result, header: bytes) -> None:
    if info.st_nlink != 1:
        raise _UnsafeFixError(
            "File gained another hard link; mode change could affect an outside path"
        )
    if (
        (info.st_dev, info.st_ino) != (action._dev, action._ino)
        or stat.S_IMODE(info.st_mode) != action.before_mode
        or info.st_size != action._size
        or info.st_mtime_ns != action._mtime_ns
        or hashlib.sha256(header).hexdigest() != action._header_digest
    ):
        raise _UnsafeFixError("File identity, mode, or content changed since planning")
    expected_exec, _ = _intent(action.rel_path, header)
    if expected_exec is None or ((action.after_mode & stat.S_IXUSR) != 0) is not expected_exec:
        raise _UnsafeFixError("Executable intent changed since planning")


def _replace_index_mode_under_lock(
    plan: FixPlan,
    root_fd: int,
    action: FixAction,
    index_path: Path,
    index_info: os.stat_result,
) -> None:
    """Write a verified alternate index, then atomically install it under lock."""
    assert action.after_git_mode is not None
    assert action._git_blob is not None

    original_entries = _read_index(plan.root)
    original_flags = _read_index_flags(plan.root)
    current = _single_regular_entry(original_entries, action.rel_path)
    _require_plain_index_flags(original_flags, action.rel_path, tracked=True)
    if (
        current is None
        or current.mode != action.before_git_mode
        or current.blob != action._git_blob
    ):
        raise _UnsafeFixError("Git index changed while acquiring its lock")

    expected_entries = {path: list(entries) for path, entries in original_entries.items()}
    expected_entries[action.rel_path] = [_IndexEntry(action.after_git_mode, action._git_blob, 0)]
    temp_path: Path | None = None
    try:
        temp_fd, temp_name = tempfile.mkstemp(prefix=".permlint-index-", dir=index_path.parent)
        temp_path = Path(temp_name)
        with os.fdopen(temp_fd, "wb") as destination, open(index_path, "rb") as source:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
            destination.flush()
            os.fsync(destination.fileno())

        index_record = (
            action.after_git_mode.encode("ascii")
            + b" "
            + action._git_blob.encode("ascii")
            + b"\t"
            + os.fsencode(plan._git_prefix / action.rel_path)
            + b"\0"
        )
        _git_run(
            plan.root,
            ["update-index", "-z", "--index-info"],
            index_record,
            index_file=temp_path,
        )
        alternate_entries = _read_index(plan.root, index_file=temp_path)
        alternate_flags = _read_index_flags(plan.root, index_file=temp_path)
        if alternate_entries != expected_entries or alternate_flags != original_flags:
            raise _UnsafeFixError(
                "Alternate Git index changed content, flags, or unrelated entries"
            )

        # `update-index` replaces its alternate file. Restore the original
        # index's ownership and permissions before installing it.
        alternate_fd = os.open(temp_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            alternate_info = os.fstat(alternate_fd)
            if not stat.S_ISREG(alternate_info.st_mode) or alternate_info.st_nlink != 1:
                raise _UnsafeFixError("Alternate Git index is not an ordinary file")
            if (alternate_info.st_uid, alternate_info.st_gid) != (
                index_info.st_uid,
                index_info.st_gid,
            ):
                os.fchown(alternate_fd, index_info.st_uid, index_info.st_gid)
            os.fchmod(alternate_fd, stat.S_IMODE(index_info.st_mode))
            os.fsync(alternate_fd)
        finally:
            os.close(alternate_fd)

        if not _same_index_file(index_info, os.stat(index_path, follow_symlinks=False)):
            raise _UnsafeFixError("Git index changed despite its lock; no index replacement made")
        # A file can be renamed while its fd remains open. Check its path once
        # more immediately before committing the index change by pathname.
        _reject_nested_git_boundary(root_fd, action.rel_path)
        path_fd, path_info = _open_regular(root_fd, action.rel_path)
        os.close(path_fd)
        if (
            (path_info.st_dev, path_info.st_ino) != (action._dev, action._ino)
            or stat.S_IMODE(path_info.st_mode) != action.after_mode
            or path_info.st_nlink != 1
        ):
            raise _UnsafeFixError("File pathname or mode changed before Git index replacement")
        current_root_fd, _ = _open_root(plan.root, (plan._root_dev, plan._root_ino))
        os.close(current_root_fd)
        os.replace(temp_path, index_path)
        temp_path = None
    except OSError as exc:
        raise _UnsafeFixError(f"Cannot safely replace Git index: {exc}") from exc
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass
            try:
                os.unlink(Path(os.fspath(temp_path) + ".lock"))
            except FileNotFoundError:
                pass


def _apply_one(plan: FixPlan, root_fd: int, action: FixAction) -> None:
    _reject_nested_git_boundary(root_fd, action.rel_path)
    fd, info = _open_regular(root_fd, action.rel_path)
    changed_fs = False
    needs_index_change = action.after_git_mode != action.before_git_mode
    # Even a filesystem-only repair must not race a Git writer that makes an
    # untracked file tracked or changes a tracked file's staged content.
    index_context = _locked_index(plan) if plan._git_available else nullcontext(None)
    try:
        with index_context as index_state:
            try:
                _check_file_snapshot(action, info, _header(fd))
                _check_index_snapshot(plan, action)
                if action.after_mode != action.before_mode:
                    if os.fstat(fd).st_nlink != 1:
                        raise _UnsafeFixError(
                            "File gained another hard link; its mode may affect an outside path"
                        )
                    try:
                        os.fchmod(fd, action.after_mode)
                    except OSError as exc:
                        raise _UnsafeFixError(f"Cannot change filesystem mode: {exc}") from exc
                    changed_fs = True

                if needs_index_change:
                    assert index_state is not None
                    index_path, index_info = index_state
                    if index_info is None:
                        raise _UnsafeFixError("Git index disappeared before its mode repair")
                    _replace_index_mode_under_lock(plan, root_fd, action, index_path, index_info)
                current_info = os.fstat(fd)
                if stat.S_IMODE(current_info.st_mode) != action.after_mode:
                    raise _UnsafeFixError("Filesystem mode changed unexpectedly during repair")
            except _UnsafeFixError as exc:
                if changed_fs and needs_index_change:
                    # Restore only while still holding the index lock, and
                    # only if the inode/path, index entry, and mode still match
                    # what this action wrote. Never clobber another chmod.
                    rollback_safe = False
                    try:
                        current = _single_regular_entry(
                            _read_index(plan.root, action.rel_path), action.rel_path
                        )
                        path_fd, path_info = _open_regular(root_fd, action.rel_path)
                        os.close(path_fd)
                        file_info = os.fstat(fd)
                        rollback_safe = (
                            current is not None
                            and current.mode == action.before_git_mode
                            and current.blob == action._git_blob
                            and (path_info.st_dev, path_info.st_ino) == (action._dev, action._ino)
                            and stat.S_IMODE(file_info.st_mode) == action.after_mode
                            and file_info.st_nlink == 1
                        )
                    except (_UnsafeFixError, OSError):
                        pass
                    if rollback_safe:
                        try:
                            os.fchmod(fd, action.before_mode)
                        except OSError as rollback_exc:
                            raise _UnsafeFixError(
                                f"{exc}; filesystem rollback failed: {rollback_exc}"
                            ) from rollback_exc
                    else:
                        raise _UnsafeFixError(
                            f"{exc}; repair may be partial, inspect filesystem and Git index"
                        ) from exc
                raise
    finally:
        os.close(fd)


def apply_fixes(plan: FixPlan) -> FixOutcome:
    """Apply eligible actions, refusing anything that changed since planning."""
    outcome = FixOutcome()
    if not plan.scan.diagnostics.is_complete:
        outcome.failures.extend(
            FixFailure(action.rel_path, "Scan was incomplete; no repairs were applied")
            for action in plan.actions
        )
        return outcome
    try:
        root_fd, _ = _open_root(plan.root, (plan._root_dev, plan._root_ino))
    except _UnsafeFixError as exc:
        outcome.failures.extend(FixFailure(action.rel_path, str(exc)) for action in plan.actions)
        return outcome
    try:
        if plan._git_available:
            if _read_git_prefix(plan.root) != plan._git_prefix:
                raise _UnsafeFixError("Git repository location changed since planning")
            if _git_index_path(plan.root) != plan._git_index_path:
                raise _UnsafeFixError("Git index location changed since planning")
    except _UnsafeFixError as exc:
        outcome.failures.extend(FixFailure(action.rel_path, str(exc)) for action in plan.actions)
        os.close(root_fd)
        return outcome
    try:
        for action in plan.actions:
            try:
                _apply_one(plan, root_fd, action)
            except _UnsafeFixError as exc:
                outcome.failures.append(FixFailure(action.rel_path, str(exc)))
            else:
                outcome.applied.append(action)
    finally:
        os.close(root_fd)
    return outcome
