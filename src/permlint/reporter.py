"""Concise terminal reporting for scans and safe repair plans."""

from __future__ import annotations

import stat
from collections import Counter
from typing import TYPE_CHECKING

from rich.console import Console
from rich.markup import escape

from permlint import __version__
from permlint.formats import suggested_fix_command
from permlint.models import GitIndexStatus, ScanResult, Severity
from permlint.rule_metadata import RULES

if TYPE_CHECKING:
    from permlint.fixer import FixAction, FixOutcome, FixPlan


def _mode(mode: int) -> str:
    return f"{mode & 0o7777:04o}"


def safe_markup(value: object) -> str:
    """Make untrusted text printable and safe inside Rich markup.

    Filenames may contain terminal controls or undecodable POSIX bytes. Show
    those as visible escapes so reports cannot alter the terminal or fail to
    encode, while ordinary Unicode names remain readable.
    """
    visible: list[str] = []
    for character in str(value):
        if character.isprintable():
            visible.append(character)
        else:
            codepoint = ord(character)
            if codepoint <= 0xFF:
                visible.append(f"\\x{codepoint:02x}")
            elif codepoint <= 0xFFFF:
                visible.append(f"\\u{codepoint:04x}")
            else:
                visible.append(f"\\U{codepoint:08x}")
    return escape("".join(visible))


def _has_unprintable(value: object) -> bool:
    return any(not character.isprintable() for character in str(value))


def render_report(
    result: ScanResult,
    console: Console | None = None,
    plan: FixPlan | None = None,
) -> None:
    """Render findings, relevant permission evidence, and a compact summary."""
    if console is None:
        console = Console()

    console.print(f"[bold]PermLint {__version__}[/bold]")
    console.print(f"Scanning: [cyan]{safe_markup(result.target_path)}[/cyan]\n")

    fixable_paths = {action.rel_path for action in plan.actions} if plan is not None else set()
    if result.findings:
        for finding in sorted(
            result.findings,
            key=lambda item: (item.path.as_posix(), item.check_id, item.message),
        ):
            color = "red" if finding.severity is Severity.ERROR else "yellow"
            console.print(
                f"[bold {color}]{safe_markup(finding.check_id)} "
                f"{finding.severity.label:<5}[/bold {color}]  "
                f"[bold]{safe_markup(finding.path)}[/bold]"
            )
            console.print(f"  {safe_markup(finding.message)}")
            detail = getattr(finding, "detail", None)
            if detail:
                console.print(f"  {safe_markup(detail)}")
            filesystem_mode = getattr(finding, "filesystem_mode", None)
            git_mode = getattr(finding, "git_index_mode", None)
            expected_executable = getattr(finding, "expected_executable", None)
            if filesystem_mode is not None:
                console.print(f"  Filesystem: {_mode(filesystem_mode)}")
            if git_mode is not None:
                console.print(f"  Git index:  {safe_markup(git_mode)}")
            if expected_executable is not None:
                expected = "executable" if expected_executable else "non-executable"
                console.print(f"  Expected:   {expected}")
            if finding.path in fixable_paths and finding.check_id in {"PL001", "PL003", "PL007"}:
                if _has_unprintable(finding.path):
                    console.print(
                        "  Suggested fix: run permlint fix from the scan root; "
                        "targeted paths need shell escaping."
                    )
                else:
                    command = suggested_fix_command(finding.path)
                    console.print(f"  Suggested fix: {safe_markup(command)}")
            console.print()
    else:
        noun = "file" if result.files_inspected == 1 else "files"
        console.print(f"[green]✓[/green] {result.files_inspected} {noun} inspected\n")
        if result.diagnostics.is_complete:
            console.print("[green]No issues found.[/green]")
        else:
            console.print("No findings in inspected files.")

    if result.findings:
        console.print(f"Files inspected: {result.files_inspected}")
        console.print(f"Errors: {result.error_count}")
        console.print(f"Warnings: {result.warning_count}")
        if plan is not None:
            console.print(f"Auto-fixable: {len(plan.actions)}")
            console.print(f"Manual review: {len(plan.manual)}")
        issues_word = "issue" if result.total_findings == 1 else "issues"
        console.print(f"\n[bold]{result.total_findings} {issues_word} found[/bold]")

    render_diagnostics(result, console)


def render_summary(
    result: ScanResult,
    console: Console | None = None,
    plan: FixPlan | None = None,
) -> None:
    """Render scan totals and a per-rule breakdown without individual paths."""
    if console is None:
        console = Console()

    console.print(f"[bold]PermLint {__version__}[/bold]")
    console.print(f"Scanning: [cyan]{safe_markup(result.target_path)}[/cyan]\n")
    console.print(f"Files inspected: {result.files_inspected}")
    console.print(f"Errors: {result.error_count}")
    console.print(f"Warnings: {result.warning_count}")
    if plan is not None:
        console.print(f"Auto-fixable: {len(plan.actions)}")
        console.print(f"Manual review: {len(plan.manual)}")
    console.print(f"Total findings: {result.total_findings}")

    if result.findings:
        counts = Counter((finding.check_id, finding.severity) for finding in result.findings)
        console.print("\n[bold]Findings by rule:[/bold]")
        for (rule_id, severity), count in sorted(
            counts.items(), key=lambda item: (item[0][0], item[0][1].value)
        ):
            name = RULES[rule_id].name if rule_id in RULES else "Other rule"
            console.print(
                f"  {safe_markup(rule_id)} {severity.label:<5} {count:>6}  {safe_markup(name)}"
            )
    elif result.diagnostics.is_complete:
        console.print("\n[green]No issues found.[/green]")
    else:
        console.print("\nNo findings in inspected files.")

    render_diagnostics(result, console)


def _action_label(action: FixAction) -> str:
    before_x = bool(action.before_mode & stat.S_IXUSR)
    after_x = bool(action.after_mode & stat.S_IXUSR)
    if before_x != after_x:
        return "+x" if after_x else "-x"
    if action.before_git_mode != action.after_git_mode:
        return "git +x" if action.after_git_mode == "100755" else "git -x"
    return "mode"


def _render_action(action: FixAction, console: Console) -> None:
    console.print(f"{_action_label(action)} [bold]{safe_markup(action.rel_path)}[/bold]")
    if action.before_mode != action.after_mode:
        console.print(f"   filesystem: {_mode(action.before_mode)} -> {_mode(action.after_mode)}")
    if action.before_git_mode != action.after_git_mode:
        before = action.before_git_mode or "untracked"
        after = action.after_git_mode or "untracked"
        console.print(f"   git index:  {before} -> {after}")
    console.print(f"   {safe_markup(action.reason)}")


def render_fix_plan(
    plan: FixPlan,
    *,
    dry_run: bool,
    outcome: FixOutcome | None = None,
    console: Console | None = None,
) -> None:
    """Describe exactly which safe metadata changes are planned or applied."""
    if console is None:
        console = Console()

    if dry_run:
        count = len(plan.actions)
        console.print(f"{count} safe fix{'es' if count != 1 else ''} available")
        actions = plan.actions
    else:
        actions = outcome.applied if outcome is not None else []
        count = len(actions)
        console.print(f"Applied {count} safe fix{'es' if count != 1 else ''}")

    if actions:
        console.print()
        for action in actions:
            _render_action(action, console)
            console.print()

    if plan.manual:
        count = len(plan.manual)
        console.print(f"{count} need{'s' if count == 1 else ''} manual review:")
        for item in plan.manual:
            rules = ", ".join(item.check_ids)
            console.print(
                f"  {safe_markup(item.rel_path)} ({safe_markup(rules)}): {safe_markup(item.reason)}"
            )
        console.print()

    if outcome is not None and outcome.failures:
        console.print(f"[bold red]{len(outcome.failures)} fix failures:[/bold red]")
        for failure in outcome.failures:
            console.print(f"  {safe_markup(failure.rel_path)}: {safe_markup(failure.reason)}")
        console.print()

    if dry_run:
        console.print("No files changed.")


_GIT_INCOMPLETE_NOTES = {
    GitIndexStatus.GIT_UNAVAILABLE: "git executable not found",
    GitIndexStatus.ERROR: "git index could not be read",
}


def render_diagnostics(result: ScanResult, console: Console | None = None) -> None:
    """Report coverage gaps without repeating the entire finding list."""
    if console is None:
        console = Console()
    diagnostics = result.diagnostics
    incomplete: list[str] = []

    if diagnostics.git_is_applicable and not diagnostics.git_comparison_available:
        reason = _GIT_INCOMPLETE_NOTES.get(diagnostics.git_index_status, "unavailable")
        incomplete.append(f"Git index comparison (PL007) did not run: {reason}")
    if diagnostics.directories_skipped:
        count = diagnostics.directories_skipped
        incomplete.append(
            f"{count} director{'y' if count == 1 else 'ies'} could not be entered; "
            "everything inside was not scanned"
        )
    if diagnostics.entries_skipped:
        count = diagnostics.entries_skipped
        incomplete.append(f"{count} file{'' if count == 1 else 's'} could not be inspected")
    if diagnostics.files_unreadable:
        count = diagnostics.files_unreadable
        incomplete.append(
            f"{count} file{'' if count == 1 else 's'} could not be read; "
            "content checks were skipped for them"
        )
    if diagnostics.unmerged_index_paths:
        count = diagnostics.unmerged_index_paths
        incomplete.append(
            f"{count} unmerged Git index path{'' if count == 1 else 's'} could not be compared"
        )

    if incomplete:
        console.print()
        console.print("[bold yellow]Scan was incomplete:[/bold yellow]")
        for note in incomplete:
            console.print(f"  [yellow]•[/yellow] {note}")

    if not diagnostics.git_is_applicable:
        console.print()
        console.print("[dim]Not a Git repository: Git index checks do not apply.[/dim]")
