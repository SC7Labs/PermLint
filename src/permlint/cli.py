"""Command-line interface for Git-aware permission auditing and repair."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from typer.core import TyperGroup

from permlint import __version__
from permlint.formats import render_machine
from permlint.reporter import (
    render_diagnostics,
    render_fix_plan,
    render_report,
    render_summary,
    safe_markup,
)
from permlint.rule_metadata import RULES, get_rule
from permlint.scanner import InvalidTargetError, Scanner


class LegacyPathGroup(TyperGroup):
    """Dispatch an unknown first positional word as the legacy scan path."""

    def resolve_command(self, ctx: typer.Context, args: list[str]):
        if args and args[0] not in self.commands and not args[0].startswith("-"):
            return "scan", self.get_command(ctx, "scan"), args
        return super().resolve_command(ctx, args)


app = typer.Typer(
    name="permlint",
    cls=LegacyPathGroup,
    help="Git-aware Unix permission auditor and safe repair tool.",
    epilog=(
        "Common use: permlint [PATH] · permlint fix --dry-run · permlint fix · "
        "permlint explain PL001. Configuration: .permlint.toml or --config FILE. "
        "Formats: text, json, sarif. Use --summary for large text scans. "
        "Exit 0: clean; 1: policy findings; "
        "2: incomplete scan or operational error."
    ),
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def version_callback(value: bool) -> None:
    """Print the installed version and exit."""
    if value:
        Console().print(f"PermLint {__version__}")
        raise typer.Exit(code=0)


def _error(message: str) -> int:
    Console(stderr=True).print(f"[bold red]Error:[/bold red] {safe_markup(message)}")
    return 2


def _format(value: str) -> str:
    normalized = value.lower()
    if normalized not in {"text", "json", "sarif"}:
        raise ValueError("--format must be text, json, or sarif")
    return normalized


def _scan_target(path: Path, config_path: Path | None):
    """Use one validation and configuration path for scans and repairs."""
    from permlint.config import load_config

    root = Scanner._validate_target(path)
    config = load_config(root, explicit=config_path)
    result = Scanner(config=config).scan(root)
    return result, config


def _run_scan(
    path: Path,
    output_format: str,
    config_path: Path | None,
    *,
    summary_only: bool = False,
) -> int:
    try:
        from permlint.fixer import plan_fixes

        selected_format = _format(output_format)
        if summary_only and selected_format != "text":
            raise ValueError("--summary is available only with --format text")
        result, config = _scan_target(path, config_path)
        plan = plan_fixes(result, config=config)
        if selected_format == "text":
            if summary_only:
                render_summary(result, plan=plan)
            else:
                render_report(result, plan=plan)
        else:
            sys.stdout.write(render_machine(result, selected_format, plan))
        return result.exit_code
    except (InvalidTargetError, ValueError, OSError) as exc:
        return _error(str(exc))
    except Exception as exc:
        return _error(f"Scan failed: {exc}")


@app.callback(invoke_without_command=True)
def entry(
    ctx: typer.Context,
    output_format: Annotated[
        str,
        typer.Option("--format", help="Scan output: text, json, or sarif."),
    ] = "text",
    config_path: Annotated[
        Path | None,
        typer.Option("--config", help="Use an explicit .permlint.toml file."),
    ] = None,
    summary: Annotated[
        bool,
        typer.Option("--summary", help="Show totals and counts by rule, without file details."),
    ] = False,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-V",
            "-v",
            help="Show the installed version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """Scan the current directory when no command is supplied."""
    ctx.obj = {"format": output_format, "config": config_path, "summary": summary}
    if ctx.invoked_subcommand is None:
        raise typer.Exit(
            code=_run_scan(Path("."), output_format, config_path, summary_only=summary)
        )


@app.command()
def scan(
    ctx: typer.Context,
    path: Annotated[
        Path | None,
        typer.Argument(help="Directory to scan (default: current directory)."),
    ] = None,
    output_format: Annotated[
        str | None,
        typer.Option("--format", help="Scan output: text, json, or sarif."),
    ] = None,
    config_path: Annotated[
        Path | None,
        typer.Option("--config", help="Use an explicit .permlint.toml file."),
    ] = None,
    summary: Annotated[
        bool,
        typer.Option("--summary", help="Show totals and counts by rule, without file details."),
    ] = False,
) -> None:
    """Audit filesystem and Git index executable state."""
    inherited = ctx.obj or {}
    selected_format = output_format or inherited.get("format", "text")
    selected_config = config_path or inherited.get("config")
    selected_summary = summary or inherited.get("summary", False)
    raise typer.Exit(
        code=_run_scan(
            path or Path("."), selected_format, selected_config, summary_only=selected_summary
        )
    )


def _fix_target(paths: list[Path]) -> tuple[Path, list[Path] | None]:
    if not paths:
        return Path("."), None
    if paths[0].is_dir():
        return paths[0], paths[1:] or None
    return Path("."), paths


@app.command()
def fix(
    ctx: typer.Context,
    paths: Annotated[
        list[Path] | None,
        typer.Argument(help="Optional repository directory, then files to repair."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview safe changes without modifying files or Git."),
    ] = False,
    config_path: Annotated[
        Path | None,
        typer.Option("--config", help="Use an explicit .permlint.toml file."),
    ] = None,
) -> None:
    """Preview or apply only safe executable-bit repairs."""
    try:
        from permlint.fixer import apply_fixes, plan_fixes

        root, selected = _fix_target(paths or [])
        inherited = ctx.obj or {}
        result, config = _scan_target(root, config_path or inherited.get("config"))
        plan = plan_fixes(result, config=config, selected_paths=selected)
        if dry_run:
            render_fix_plan(plan, dry_run=True)
            if not result.diagnostics.is_complete:
                render_diagnostics(result)
                Console().print("Fixes cannot be applied until the scan completes.")
            raise typer.Exit(code=result.exit_code)
        if not result.diagnostics.is_complete:
            render_report(result, plan=plan)
            Console(stderr=True).print("No changes made: scan was incomplete.")
            raise typer.Exit(code=2)

        outcome = apply_fixes(plan)
        render_fix_plan(plan, dry_run=False, outcome=outcome)
        if outcome.failures:
            raise typer.Exit(code=2)
        remaining, _ = _scan_target(root, config_path or inherited.get("config"))
        if not remaining.diagnostics.is_complete:
            Console().print(
                "After repair: verification incomplete; "
                f"{remaining.error_count} errors and {remaining.warning_count} warnings "
                "in inspected files."
            )
            render_diagnostics(remaining)
            raise typer.Exit(code=2)
        Console().print(
            f"After repair: {remaining.error_count} errors, {remaining.warning_count} warnings."
        )
        raise typer.Exit(code=remaining.exit_code)
    except typer.Exit:
        raise
    except (InvalidTargetError, ValueError, OSError) as exc:
        raise typer.Exit(code=_error(str(exc))) from exc
    except Exception as exc:
        raise typer.Exit(code=_error(f"Fix failed: {exc}")) from exc


@app.command()
def explain(rule_id: Annotated[str, typer.Argument(help="Rule ID, for example PL001.")]) -> None:
    """Explain a rule, its evidence, repair policy, and edge cases."""
    rule = get_rule(rule_id)
    if rule is None:
        known = ", ".join(RULES)
        raise typer.Exit(code=_error(f"Unknown rule {rule_id!r}. Known rules: {known}"))
    console = Console()
    console.print(f"[bold]{rule.rule_id} — {rule.name}[/bold]")
    console.print(f"Severity: {rule.default_severity.label}")
    console.print(f"Meaning: {rule.summary}")
    console.print(f"Why it matters: {rule.why}")
    console.print(f"Triggers: {rule.trigger}")
    console.print(f"Auto-fix: {rule.auto_fix}")
    console.print(f"Edge cases: {rule.caveat}")


@app.command()
def upgrade() -> None:
    """Upgrade PermLint to the latest stable release from GitHub Releases."""
    from permlint.upgrade import UpgradeError, perform_upgrade

    try:
        perform_upgrade()
    except UpgradeError as exc:
        raise typer.Exit(code=_error(str(exc))) from exc
    except Exception as exc:
        raise typer.Exit(code=_error(f"Upgrade failed: {exc}")) from exc


def main() -> None:
    """Entry point for the permlint console script."""
    app()


if __name__ == "__main__":
    main()
