"""Terminal reporting and output formatting using Rich."""

from __future__ import annotations

from rich.console import Console

from permlint import __version__
from permlint.models import GitIndexStatus, ScanResult, Severity


def render_report(result: ScanResult, console: Console | None = None) -> None:
    """Render the scan result to the terminal using Rich.

    Args:
        result: The ScanResult to render.
        console: Optional Rich Console instance (defaults to standard output console).
    """
    if console is None:
        console = Console()

    console.print(f"[bold]PermLint {__version__}[/bold]")
    console.print(f"Scanning: [cyan]{result.target_path}[/cyan]\n")

    if not result.has_findings:
        console.print(f"[green]✓[/green] {result.files_inspected} files inspected\n")
        console.print("[green]No issues found.[/green]")
        # Printed even on a clean run: "found nothing" and "could not look"
        # must not read the same.
        _render_diagnostics(result, console)
        return

    for finding in result.findings:
        if finding.severity == Severity.ERROR:
            tag = f"[bold red]{finding.check_id} ERROR[/bold red]"
        else:
            tag = f"[bold yellow]{finding.check_id} WARN [/bold yellow]"

        console.print(f"{tag}  [bold]{finding.path}[/bold]")
        console.print(f"             {finding.message}\n")

    console.print(f"Files inspected: {result.files_inspected}")
    if result.error_count > 0:
        console.print(f"[red]Errors: {result.error_count}[/red]")
    else:
        console.print(f"Errors: {result.error_count}")

    if result.warning_count > 0:
        console.print(f"[yellow]Warnings: {result.warning_count}[/yellow]")
    else:
        console.print(f"Warnings: {result.warning_count}")

    issues_word = "issue" if result.total_findings == 1 else "issues"
    console.print(f"\n[bold]{result.total_findings} {issues_word} found[/bold]")

    _render_diagnostics(result, console)


_GIT_INCOMPLETE_NOTES = {
    GitIndexStatus.GIT_UNAVAILABLE: "git executable not found",
    GitIndexStatus.ERROR: "git index could not be read",
}


def _render_diagnostics(result: ScanResult, console: Console) -> None:
    """Print what the scan could not look at, and what simply did not apply.

    These are kept apart on purpose. A directory that is not a Git repository
    has no index to compare against — that is an answer, and reporting it as an
    incomplete scan was a bug: `is_complete` said one thing and the report said
    another. Anything that genuinely went uninspected is listed separately and
    is what drives the non-zero exit code.
    """
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

    if incomplete:
        console.print()
        console.print("[bold yellow]Scan was incomplete:[/bold yellow]")
        for note in incomplete:
            console.print(f"  [yellow]•[/yellow] {note}")

    # Not a gap: there was nothing to compare against.
    if not diagnostics.git_is_applicable:
        console.print()
        console.print(
            "[dim]Not a Git repository: PL007 (executable-bit mismatch) does not apply.[/dim]"
        )
