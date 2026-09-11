"""Command-line interface for PermLint."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from permlint import __version__
from permlint.reporter import render_report
from permlint.scanner import InvalidTargetError, Scanner

app = typer.Typer(
    name="permlint",
    help="Catch permission mistakes before they ship.",
    add_completion=False,
)


def version_callback(value: bool) -> None:
    """Print the PermLint version and exit."""
    if value:
        Console().print(f"PermLint {__version__}")
        raise typer.Exit(code=0)


@app.command()
def scan(
    path: Annotated[
        Path | None,
        typer.Argument(
            help="Target repository directory to scan (defaults to current directory).",
            show_default=False,
        ),
    ] = None,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-V",
            "-v",
            help="Show the PermLint version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """Scan a repository for Unix file permission issues."""
    target_path = path if path is not None else Path(".")
    error_console = Console(stderr=True)

    # Target validation lives in Scanner.scan, so the library and the CLI cannot
    # disagree about what a valid target is. The CLI only maps the failure to an
    # exit code.
    try:
        scanner = Scanner()
        result = scanner.scan(target_path)
    except InvalidTargetError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=2) from exc
    except Exception as exc:
        error_console.print(f"[bold red]Error:[/bold red] Scanner encountered an error: {exc}")
        raise typer.Exit(code=2) from exc

    try:
        render_report(result)
        raise typer.Exit(code=result.exit_code)
    except typer.Exit:
        raise
    except Exception as exc:
        error_console.print(f"[bold red]Error:[/bold red] Failed to render report: {exc}")
        raise typer.Exit(code=2) from exc


def main() -> None:
    """Entry point for the permlint console script."""
    try:
        app()
    except SystemExit as exc:
        sys.exit(exc.code)


if __name__ == "__main__":
    main()
