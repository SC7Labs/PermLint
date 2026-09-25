"""Bounded, bulk reads of the content Git has staged for tracked files."""

from __future__ import annotations

import os
import select
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path


class StagedContentError(RuntimeError):
    """Git staged content could not be read and validated safely."""


HEADER_SIZE = 1024
_TIMEOUT_SECONDS = 30
_QUERY_BATCH_SIZE = 512
_MAX_BATCH_OUTPUT = 8 * 1024 * 1024
_MAX_INLINE_BLOB = 1024 * 1024
_MAX_TOTAL_HEADERS = 64 * 1024 * 1024


def _git_env() -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment["LC_ALL"] = "C"
    return environment


def _batches(values: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _queries(blobs: list[str]) -> bytes:
    return b"".join(blob.encode("ascii") + b"\n" for blob in blobs)


def _run_bounded(root: Path, args: list[str], query: bytes, output_limit: int) -> bytes:
    """Run Git with bounded pipes, output, and time; never buffer whole blobs."""
    try:
        process = subprocess.Popen(
            ["git", *args],
            cwd=root,
            env=_git_env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
    except OSError as exc:
        raise StagedContentError(f"Cannot start Git staged-content read: {exc}") from exc

    assert process.stdin is not None
    assert process.stdout is not None
    input_fd = process.stdin.fileno()
    output_fd = process.stdout.fileno()
    os.set_blocking(input_fd, False)
    os.set_blocking(output_fd, False)
    output = bytearray()
    sent = 0
    stdin_open = True
    deadline = time.monotonic() + _TIMEOUT_SECONDS
    try:
        while True:
            if stdin_open and sent == len(query):
                process.stdin.close()
                stdin_open = False

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise StagedContentError("Git staged-content read timed out")
            readable, writable, _ = select.select(
                [output_fd], [input_fd] if stdin_open else [], [], remaining
            )
            if input_fd in writable:
                try:
                    sent += os.write(input_fd, query[sent : sent + 65536])
                except BrokenPipeError as exc:
                    raise StagedContentError("Git closed the staged-content query early") from exc
            if output_fd in readable:
                chunk = os.read(output_fd, min(65536, output_limit - len(output) + 1))
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > output_limit:
                    raise StagedContentError("Git staged-content response exceeded its size limit")

        if stdin_open:
            process.stdin.close()
            stdin_open = False
        remaining = max(0, deadline - time.monotonic())
        if process.wait(timeout=remaining) != 0:
            raise StagedContentError("Git could not read staged content")
        if sent != len(query):
            raise StagedContentError("Git did not accept the complete staged-content query")
        return bytes(output)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StagedContentError(f"Git staged-content read failed: {exc}") from exc
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if stdin_open:
            process.stdin.close()
        process.stdout.close()


def _validate_blobs(blobs: set[str]) -> list[str]:
    if len(blobs) * HEADER_SIZE > _MAX_TOTAL_HEADERS:
        raise StagedContentError("Too many staged headers to inspect within the memory limit")
    for blob in blobs:
        if len(blob) not in (40, 64) or any(char not in "0123456789abcdef" for char in blob):
            raise StagedContentError("Git index contains an invalid staged blob ID")
    return sorted(blobs)


def _blob_sizes(root: Path, blobs: list[str]) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for batch in _batches(blobs, _QUERY_BATCH_SIZE):
        response = _run_bounded(
            root, ["cat-file", "--batch-check"], _queries(batch), 128 * len(batch)
        )
        if not response.endswith(b"\n"):
            raise StagedContentError("Git returned a truncated staged-object listing")
        lines = response.splitlines()
        if len(lines) != len(batch):
            raise StagedContentError("Git returned the wrong number of staged objects")
        for blob, line in zip(batch, lines, strict=True):
            fields = line.split()
            if len(fields) != 3 or fields[0] != blob.encode("ascii") or fields[1] != b"blob":
                raise StagedContentError("Git returned an unexpected staged object")
            if not fields[2].isascii() or not fields[2].isdigit():
                raise StagedContentError("Git returned an invalid staged blob size")
            sizes[blob] = int(fields[2])
    return sizes


def _content_batches(blobs: list[str], sizes: dict[str, int]) -> Iterator[list[str]]:
    batch: list[str] = []
    bytes_expected = 0
    for blob in blobs:
        size_with_framing = sizes[blob] + 128
        if batch and (
            len(batch) == _QUERY_BATCH_SIZE
            or bytes_expected + size_with_framing > _MAX_BATCH_OUTPUT
        ):
            yield batch
            batch = []
            bytes_expected = 0
        batch.append(blob)
        bytes_expected += size_with_framing
    if batch:
        yield batch


def _read_inline_batch(root: Path, batch: list[str], sizes: dict[str, int]) -> dict[str, bytes]:
    output_limit = sum(sizes[blob] + 128 for blob in batch)
    response = _run_bounded(root, ["cat-file", "--batch"], _queries(batch), output_limit)
    headers: dict[str, bytes] = {}
    offset = 0
    for blob in batch:
        line_end = response.find(b"\n", offset)
        if line_end < 0:
            raise StagedContentError("Git returned a truncated staged-blob header")
        expected_line = f"{blob} blob {sizes[blob]}".encode("ascii")
        if response[offset:line_end] != expected_line:
            raise StagedContentError("Git returned the wrong staged blob or size")
        content_start = line_end + 1
        content_end = content_start + sizes[blob]
        if content_end >= len(response) or response[content_end : content_end + 1] != b"\n":
            raise StagedContentError("Git returned a truncated staged blob")
        headers[blob] = response[content_start : min(content_end, content_start + HEADER_SIZE)]
        offset = content_end + 1
    if offset != len(response):
        raise StagedContentError("Git returned extra staged-content bytes")
    return headers


def _read_large_header(root: Path, blob: str) -> bytes:
    """Read only a prefix when a blob is too large for the bounded batch."""
    try:
        process = subprocess.Popen(
            ["git", "cat-file", "blob", blob],
            cwd=root,
            env=_git_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
    except OSError as exc:
        raise StagedContentError(f"Cannot start Git staged-blob read: {exc}") from exc
    assert process.stdout is not None
    data = bytearray()
    deadline = time.monotonic() + _TIMEOUT_SECONDS
    try:
        while len(data) < HEADER_SIZE:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise StagedContentError("Large staged-blob read timed out")
            readable, _, _ = select.select([process.stdout], [], [], remaining)
            if not readable:
                raise StagedContentError("Large staged-blob read timed out")
            chunk = os.read(process.stdout.fileno(), HEADER_SIZE - len(data))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) != HEADER_SIZE:
            raise StagedContentError("Large staged blob ended before its expected header")
        return bytes(data)
    except OSError as exc:
        raise StagedContentError(f"Large staged-blob read failed: {exc}") from exc
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()


def read_staged_headers(root: Path, blobs: set[str]) -> dict[str, bytes]:
    """Read at most 1024 bytes per staged blob with few Git processes.

    Ordinary small blobs are fetched through size-capped bulk requests. Blobs
    over 1 MiB use a per-object prefix read, so a large staged data file never
    has to be drained merely to inspect its executable intent. Any invalid Git
    response fails closed with ``StagedContentError``.
    """
    ordered = _validate_blobs(blobs)
    if not ordered:
        return {}
    sizes = _blob_sizes(root, ordered)
    inline = [blob for blob in ordered if sizes[blob] <= _MAX_INLINE_BLOB]
    large = [blob for blob in ordered if sizes[blob] > _MAX_INLINE_BLOB]
    headers: dict[str, bytes] = {}
    for batch in _content_batches(inline, sizes):
        headers.update(_read_inline_batch(root, batch, sizes))
    for blob in large:
        headers[blob] = _read_large_header(root, blob)
    return headers
