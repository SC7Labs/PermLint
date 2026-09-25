"""Safe self-update implementation for PermLint using GitHub Releases."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

from rich.console import Console

from permlint import __version__

OFFICIAL_REPO = "SC7Labs/PermLint"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{OFFICIAL_REPO}/releases/latest"
SOURCE_URL_TEMPLATE = f"git+https://github.com/{OFFICIAL_REPO}.git@{{tag}}"

SEMVER_PATTERN = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$"
)


class UpgradeError(Exception):
    """Raised when an upgrade operation fails."""


class StrictHttpsRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse any redirects to non-HTTPS schemes or untrusted hosts."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        parsed = urlsplit(newurl)
        if parsed.scheme != "https":
            raise UpgradeError(f"Refusing insecure HTTP redirect to {newurl!r}")
        if parsed.netloc != "api.github.com" and not parsed.netloc.endswith(".github.com"):
            raise UpgradeError(f"Refusing redirect outside GitHub to {newurl!r}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def parse_semver(version_str: str) -> tuple[int, int, int]:
    """Parse and validate a semantic version string.

    Accepts 'X.Y.Z' or 'vX.Y.Z'.
    Raises:
        ValueError: If version_str is not a valid stable semantic version.
    """
    if not isinstance(version_str, str):
        raise ValueError(f"Version must be a string, got {type(version_str).__name__}")
    match = SEMVER_PATTERN.match(version_str.strip())
    if not match:
        raise ValueError(f"Invalid semantic version: {version_str!r}")
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )


def fetch_latest_release(
    api_url: str = LATEST_RELEASE_URL,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Fetch latest release metadata from GitHub Releases API over HTTPS."""
    parsed = urlsplit(api_url)
    if parsed.scheme != "https" or parsed.netloc != "api.github.com":
        raise UpgradeError("Refusing to query non-official or non-HTTPS GitHub API URL.")

    opener = urllib.request.build_opener(StrictHttpsRedirectHandler())
    req = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "PermLint-Upgrade",
        },
    )
    try:
        with opener.open(req, timeout=timeout) as response:
            if response.status != 200:
                raise UpgradeError(f"GitHub API returned HTTP {response.status}")
            raw = response.read().decode("utf-8")
            data = json.loads(raw)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpgradeError(f"No releases found for {OFFICIAL_REPO}.") from exc
        raise UpgradeError(f"GitHub release API error: HTTP {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise UpgradeError(f"Network error querying GitHub Releases: {exc.reason}") from exc
    except TimeoutError as exc:
        raise UpgradeError("Connection to GitHub Releases timed out.") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise UpgradeError("Failed to parse GitHub Releases API response as JSON.") from exc
    except OSError as exc:
        raise UpgradeError(f"Operating system error communicating with GitHub: {exc}") from exc

    if not isinstance(data, dict):
        raise UpgradeError("Invalid GitHub Releases API response: expected JSON object.")

    return data


def get_release_tag_and_version(
    release_data: dict[str, Any],
) -> tuple[str, str, tuple[int, int, int]]:
    """Validate release metadata and return (tag_name, normalized_version, semver_tuple)."""
    if release_data.get("draft"):
        raise UpgradeError("Latest GitHub release is a draft; no stable release found.")
    if release_data.get("prerelease"):
        raise UpgradeError("Latest GitHub release is a prerelease; no stable release found.")

    tag = release_data.get("tag_name")
    if not tag or not isinstance(tag, str):
        raise UpgradeError("Malformed GitHub release: missing 'tag_name'.")

    try:
        semver = parse_semver(tag)
    except ValueError as exc:
        raise UpgradeError(
            f"Malformed release tag {tag!r}: expected stable semantic version (e.g. v0.2.0)."
        ) from exc

    normalized_version = f"{semver[0]}.{semver[1]}.{semver[2]}"
    return tag, normalized_version, semver


def install_release(
    source_url: str,
    python_bin: str = sys.executable,
    timeout: float = 300.0,
) -> None:
    """Install the specified release via pip in the target Python environment."""
    expected_prefix = f"git+https://github.com/{OFFICIAL_REPO}.git@"
    if not source_url.startswith(expected_prefix):
        raise UpgradeError(f"Refusing to install from unauthorized source: {source_url!r}")

    cmd = [python_bin, "-m", "pip", "install", "--upgrade", source_url]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise UpgradeError("pip installation timed out.") from exc
    except (FileNotFoundError, OSError) as exc:
        raise UpgradeError(f"Failed to execute pip ({python_bin}): {exc}") from exc

    if proc.returncode != 0:
        output = (proc.stderr or proc.stdout or "").strip()
        lowered = output.lower()
        if "permission denied" in lowered or "errno 13" in lowered or "permissionerror" in lowered:
            raise UpgradeError(
                "Failed to upgrade PermLint due to insufficient permissions.\n"
                f"{output}\n\n"
                "Please run with appropriate permissions or within an active virtual environment."
            )
        if "externally-managed-environment" in lowered:
            raise UpgradeError(
                "Failed to upgrade PermLint: Python environment is externally managed.\n"
                f"{output}\n\n"
                "Please run in a virtual environment or pass appropriate pip flags."
            )
        raise UpgradeError(f"pip install failed (exit code {proc.returncode}):\n{output}")


def verify_installed_version(
    expected_version: str,
    python_bin: str = sys.executable,
    timeout: float = 15.0,
) -> str:
    """Verify that the target Python environment now runs the expected version."""
    expected_semver = parse_semver(expected_version)
    cmd = [python_bin, "-c", "import permlint; print(permlint.__version__)"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise UpgradeError("Post-upgrade verification timed out.") from exc
    except (FileNotFoundError, OSError) as exc:
        raise UpgradeError(f"Failed to execute verification command ({python_bin}): {exc}") from exc

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise UpgradeError(
            f"Post-upgrade verification failed (command exited with code {proc.returncode}):\n{err}"
        )

    reported_version = proc.stdout.strip()
    try:
        reported_semver = parse_semver(reported_version)
    except ValueError as exc:
        raise UpgradeError(
            f"Post-upgrade verification returned invalid version string: {reported_version!r}"
        ) from exc

    if reported_semver != expected_semver:
        raise UpgradeError(
            f"Post-upgrade verification mismatch: expected {expected_version}, "
            f"but found {reported_version}."
        )

    return reported_version


def perform_upgrade(
    *,
    current_version: str = __version__,
    api_url: str = LATEST_RELEASE_URL,
    python_bin: str = sys.executable,
    console: Console | None = None,
) -> None:
    """Query GitHub Releases and upgrade PermLint if a newer version exists."""
    if console is None:
        console = Console()

    current_semver = parse_semver(current_version)
    current_str = f"{current_semver[0]}.{current_semver[1]}.{current_semver[2]}"

    release_data = fetch_latest_release(api_url=api_url)
    tag, latest_str, latest_semver = get_release_tag_and_version(release_data)

    if latest_semver <= current_semver:
        console.print(f"PermLint is already up to date ({current_str}).")
        return

    source_url = SOURCE_URL_TEMPLATE.format(tag=tag)

    console.print(f"Current version: {current_str}")
    console.print(f"Latest version:  {latest_str}")
    console.print(f"Source:          {source_url}")
    console.print()
    console.print(f"Upgrading PermLint to {latest_str}...")

    install_release(source_url=source_url, python_bin=python_bin)

    verified = verify_installed_version(expected_version=latest_str, python_bin=python_bin)
    console.print(f"Successfully upgraded PermLint to {verified}.")
