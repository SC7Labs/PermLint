"""Integration tests for the PermLint CLI."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from permlint.cli import app

runner = CliRunner()


def test_cli_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "PermLint 0.1.0" in result.output

    result_short = runner.invoke(app, ["-V"])
    assert result_short.exit_code == 0
    assert "PermLint 0.1.0" in result_short.output


def test_cli_clean_repository(tmp_path: Path) -> None:
    # Setup clean files
    readme = tmp_path / "README.md"
    readme.write_text("# Test Repo\n")
    readme.chmod(0o644)

    script = tmp_path / "run.sh"
    script.write_text("#!/bin/sh\necho test\n")
    script.chmod(0o755)

    result = runner.invoke(app, [str(tmp_path)])
    assert result.exit_code == 0
    assert "2 files inspected" in result.output
    assert "No issues found." in result.output


def test_cli_repository_with_findings(tmp_path: Path) -> None:
    # Setup files with issues
    deploy = tmp_path / "deploy.sh"
    deploy.write_text("#!/bin/bash\necho deploy\n")
    deploy.chmod(0o644)

    config = tmp_path / "config.yaml"
    config.write_text("env: prod\n")
    config.chmod(0o755)

    result = runner.invoke(app, [str(tmp_path)])
    assert result.exit_code == 1
    assert "PL001 ERROR" in result.output
    assert "PL003 WARN" in result.output
    assert "2 issues found" in result.output


def test_cli_nonexistent_path(tmp_path: Path) -> None:
    nonexistent = tmp_path / "does_not_exist"
    result = runner.invoke(app, [str(nonexistent)])
    assert result.exit_code == 2
    combined_output = result.output + (result.stderr or "")
    assert "Path does not exist" in combined_output


def test_cli_file_target_rejected(tmp_path: Path) -> None:
    file = tmp_path / "file.txt"
    file.write_text("content\n")
    file.chmod(0o644)

    result = runner.invoke(app, [str(file)])
    assert result.exit_code == 2
    combined_output = result.output + (result.stderr or "")
    assert "Target is not a directory" in combined_output
