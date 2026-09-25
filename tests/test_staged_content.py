"""Real Git and malformed-output tests for bounded bulk staged-header reads."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from permlint import staged_content
from permlint.staged_content import StagedContentError, read_staged_headers

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git unavailable")


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True).stdout


def _stage_blob(root: Path, path: str) -> str:
    record = _git(root, "ls-files", "--stage", "-z", "--", path).rstrip(b"\0")
    return record.split(b"\t", 1)[0].split()[1].decode("ascii")


def test_small_staged_blobs_use_two_bulk_git_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git(tmp_path, "init", "-q")
    expected: dict[str, bytes] = {}
    for number in range(24):
        path = tmp_path / f"tool-{number:02}.sh"
        data = f"#!/bin/sh\necho {number}\n".encode()
        path.write_bytes(data)
        path.chmod(0o644)
    _git(tmp_path, "add", "-A")
    for number in range(24):
        name = f"tool-{number:02}.sh"
        expected[_stage_blob(tmp_path, name)] = (tmp_path / name).read_bytes()

    original_popen = subprocess.Popen
    commands: list[list[str]] = []

    def _counted_popen(*args, **kwargs):
        commands.append(args[0])
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", _counted_popen)
    headers = read_staged_headers(tmp_path, set(expected))

    assert headers == expected
    assert [command[1:] for command in commands] == [
        ["cat-file", "--batch-check"],
        ["cat-file", "--batch"],
    ]


def test_large_blob_reads_only_header_and_ignores_caller_git_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    intended = tmp_path / "intended"
    other = tmp_path / "other"
    intended.mkdir()
    other.mkdir()
    _git(intended, "init", "-q")
    _git(other, "init", "-q")

    data = b"#!/bin/sh\n" + b"x" * (1024 * 1024 + 100)
    (intended / "large.sh").write_bytes(data)
    _git(intended, "add", "--", "large.sh")
    blob = _stage_blob(intended, "large.sh")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))

    headers = read_staged_headers(intended, {blob})
    assert headers == {blob: data[:1024]}


def test_invalid_blob_id_rejected_before_running_git(tmp_path: Path) -> None:
    with pytest.raises(StagedContentError, match="invalid staged blob ID"):
        read_staged_headers(tmp_path, {"../../outside"})


def test_truncated_batch_content_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blob = "a" * 40
    responses = iter(
        [
            f"{blob} blob 4\n".encode(),
            f"{blob} blob 4\n".encode() + b"abc",
        ]
    )
    monkeypatch.setattr(staged_content, "_run_bounded", lambda *args: next(responses))
    with pytest.raises(StagedContentError, match="truncated staged blob"):
        read_staged_headers(tmp_path, {blob})


def test_nonblob_staged_object_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blob = "a" * 40
    monkeypatch.setattr(
        staged_content,
        "_run_bounded",
        lambda *args: f"{blob} tree 4\n".encode(),
    )
    with pytest.raises(StagedContentError, match="unexpected staged object"):
        read_staged_headers(tmp_path, {blob})
