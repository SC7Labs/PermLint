"""Small, explicit project configuration for PermLint."""

from __future__ import annotations

import fnmatch
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from permlint.models import Severity


class ConfigError(ValueError):
    """A PermLint configuration file is missing or invalid."""


@dataclass(frozen=True)
class Config:
    """Options that affect scanning, policy, and safe Git repairs."""

    exclude: tuple[str, ...] = ()
    disabled_rules: frozenset[str] = frozenset()
    severity_overrides: dict[str, Severity] = field(default_factory=dict)
    fix_git_index: bool = True
    fail_on: Literal["warning", "error"] = "warning"

    def is_excluded(self, rel_path: Path) -> bool:
        """Match a repository-relative file or directory against explicit patterns.

        A bare name matches that name at any depth. A pattern containing ``/``
        matches from the scan root. Matching every ancestor lets ``vendor``
        exclude its whole subtree, and lets traversal prune it early.
        """
        if not self.exclude:
            return False
        parts = rel_path.parts
        if not parts:
            return False
        ancestors = ["/".join(parts[:end]) for end in range(1, len(parts) + 1)]
        for pattern in self.exclude:
            if "/" in pattern:
                if any(fnmatch.fnmatchcase(candidate, pattern) for candidate in ancestors):
                    return True
                if pattern.endswith("/**") and pattern[:-3] in ancestors:
                    return True
            elif any(fnmatch.fnmatchcase(part, pattern) for part in parts):
                return True
        return False


_TOP_LEVEL_KEYS = frozenset(
    {"exclude", "disabled_rules", "severity_overrides", "fix_git_index", "fail_on"}
)


def load_config(root: Path, explicit: Path | None = None) -> Config:
    """Read ``.permlint.toml`` from *root*, or an explicitly named file.

    No file means defaults only for implicit discovery. An explicitly selected
    missing file is an error so a mistyped CI configuration cannot go unnoticed.
    """
    root = root.resolve()
    config_path = explicit if explicit is not None else root / ".permlint.toml"
    if not config_path.is_absolute():
        config_path = root / config_path
    try:
        contents = config_path.read_bytes()
    except FileNotFoundError as exc:
        if explicit is None:
            return Config()
        raise ConfigError(f"Configuration file does not exist: {config_path}") from exc
    except OSError as exc:
        raise ConfigError(f"Cannot read configuration file {config_path}: {exc}") from exc

    try:
        data = tomllib.loads(contents.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"Invalid TOML in {config_path}: {exc}") from exc

    unknown = data.keys() - _TOP_LEVEL_KEYS
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ConfigError(f"Unknown configuration option(s) in {config_path}: {names}")

    rule_ids = _known_rule_ids()
    exclude = _string_tuple(data.get("exclude", []), "exclude", config_path)
    for pattern in exclude:
        if not pattern or pattern.startswith("/") or ".." in Path(pattern).parts:
            raise ConfigError(f"Invalid relative exclusion pattern in {config_path}: {pattern!r}")

    disabled = frozenset(
        _string_tuple(data.get("disabled_rules", []), "disabled_rules", config_path)
    )
    _validate_rule_ids(disabled, rule_ids, "disabled_rules", config_path)

    raw_severity = data.get("severity_overrides", {})
    if not isinstance(raw_severity, dict):
        raise ConfigError(f"severity_overrides must be a table in {config_path}")
    _validate_rule_ids(raw_severity.keys(), rule_ids, "severity_overrides", config_path)
    severity_overrides: dict[str, Severity] = {}
    for rule_id, value in raw_severity.items():
        try:
            severity_overrides[rule_id] = Severity(value)
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                f"severity_overrides.{rule_id} must be 'error' or 'warning' in {config_path}"
            ) from exc

    fix_git_index = data.get("fix_git_index", True)
    if not isinstance(fix_git_index, bool):
        raise ConfigError(f"fix_git_index must be a boolean in {config_path}")

    fail_on = data.get("fail_on", "warning")
    if fail_on not in ("warning", "error"):
        raise ConfigError(f"fail_on must be 'warning' or 'error' in {config_path}")

    return Config(
        exclude=exclude,
        disabled_rules=disabled,
        severity_overrides=severity_overrides,
        fix_git_index=fix_git_index,
        fail_on=fail_on,
    )


def _string_tuple(value: object, name: str, config_path: Path) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ConfigError(f"{name} must be a list of strings in {config_path}")
    return tuple(value)


def _known_rule_ids() -> frozenset[str]:
    # Import lazily: checks depend on FileInfo and models, while config is used
    # by Scanner after the check registry has already been imported.
    from permlint.checks import get_default_checks

    return frozenset(check.check_id for check in get_default_checks())


def _validate_rule_ids(values: object, known: frozenset[str], name: str, config_path: Path) -> None:
    unknown = set(values) - known
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ConfigError(f"Unknown rule ID(s) in {name} ({config_path}): {names}")
