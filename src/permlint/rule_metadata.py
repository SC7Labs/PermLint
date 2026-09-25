"""Human-facing descriptions of PermLint's stable rule IDs."""

from __future__ import annotations

from dataclasses import dataclass

from permlint.models import Severity


@dataclass(frozen=True)
class RuleInfo:
    """Description used by `explain` and machine-readable reports."""

    rule_id: str
    name: str
    summary: str
    why: str
    trigger: str
    auto_fix: str
    caveat: str
    default_severity: Severity


RULES: dict[str, RuleInfo] = {
    "PL001": RuleInfo(
        "PL001",
        "Shebang but not executable",
        "A file with a valid shebang is not executable.",
        "Directly launching the script may fail, and Git may commit the wrong mode.",
        "A readable regular file starts with a valid shebang but its owner execute bit is clear.",
        "Yes, when script intent is clear; filesystem and Git index are updated together.",
        "A shebang can be documentation or intentionally sourced. Review unusual cases.",
        Severity.ERROR,
    ),
    "PL002": RuleInfo(
        "PL002",
        "Executable script without shebang",
        "A script-like text file is executable but has no shebang.",
        "Direct execution may use an unexpected shell or fail on another system.",
        "An executable, readable, nonbinary file with a script extension lacks a shebang.",
        "No. Choosing an interpreter or removing execution requires context.",
        "Some scripts run via an explicit interpreter; execution may be intentional.",
        Severity.WARNING,
    ),
    "PL003": RuleInfo(
        "PL003",
        "Executable data or document",
        "A data, configuration, or documentation file has an execute bit.",
        "The bit is usually accidental and creates noisy or misleading repository metadata.",
        "A regular file with a known non-executable extension has an execute bit.",
        "Yes, absent conflicting script evidence; filesystem and Git index are updated together.",
        "An unusual executable document or generated file may be intentional.",
        Severity.WARNING,
    ),
    "PL004": RuleInfo(
        "PL004",
        "World-writable file",
        "A regular file is writable by every local user.",
        "Other local users can modify it in a shared environment.",
        "The file's mode includes the other-write bit.",
        "No. The correct access policy depends on the environment.",
        "Shared workspaces can deliberately use broad permissions.",
        Severity.ERROR,
    ),
    "PL005": RuleInfo(
        "PL005",
        "Broad permissions on sensitive-looking file",
        "A private-key-like filename is accessible by group or other users.",
        "A sensitive file may be exposed to more local users than intended.",
        "A conservative private-key filename pattern has group or other access bits.",
        "No. The tool does not inspect secrets or know the required owner and group.",
        "The filename heuristic can match harmless test fixtures or public material.",
        Severity.WARNING,
    ),
    "PL006": RuleInfo(
        "PL006",
        "Malformed shebang",
        "A shebang-like first line cannot identify an interpreter.",
        "The file may fail when launched directly.",
        "A readable file starts with `#!` but has malformed interpreter syntax. "
        "Rust `#![...]` is excluded.",
        "No. Selecting or rewriting an interpreter is a manual decision.",
        "Some files intentionally contain a shebang-like first line as data.",
        Severity.ERROR,
    ),
    "PL007": RuleInfo(
        "PL007",
        "Git executable-bit mismatch",
        "The working tree's owner execute bit differs from the Git index mode.",
        "The permission developers see may differ from what Git will commit.",
        "A tracked regular file has filesystem and staged Git executable states that disagree.",
        "Only when other evidence makes the intended executable state clear.",
        "Git core.filemode, filesystem behavior, and deliberate staging can make this intentional.",
        Severity.WARNING,
    ),
    "PL008": RuleInfo(
        "PL008",
        "Unexpected privilege bits",
        "A regular file has a setuid or setgid bit.",
        "These bits can change execution privilege and deserve explicit review.",
        "The file mode includes setuid or setgid.",
        "No. Permission and ownership intent must be reviewed manually.",
        "Some deployed programs intentionally use privilege bits; Git does not record them.",
        Severity.ERROR,
    ),
}


def get_rule(rule_id: str) -> RuleInfo | None:
    """Look up a rule by its stable ID, ignoring case."""
    return RULES.get(rule_id.upper())
