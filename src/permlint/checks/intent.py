"""Conservative evidence of whether a file should carry an executable bit."""

from __future__ import annotations

from permlint.filesystem import FileInfo

# Extensions whose content is normally documentation, configuration, or data.
# A valid shebang on one of these is contradictory evidence, so it needs review.
DATA_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".md",
        ".txt",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".csv",
        ".xml",
        ".tsv",
        ".rst",
    }
)


def expected_executable(file_info: FileInfo) -> bool | None:
    """Return intent only when evidence is strong and not contradictory.

    A shebang is stronger evidence than a script extension alone. Data and
    document extensions suggest the opposite, unless there is a shebang.
    Unreadable content and conflicting signals stay unknown.
    """
    if file_info.suffix in DATA_EXTENSIONS:
        info = file_info.shebang_info
        if not info.readable or info.present:
            return None
        return False
    if file_info.has_shebang():
        return True
    return None
