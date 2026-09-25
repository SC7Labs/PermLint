"""CLI compatibility, machine output, and repair command integration."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from permlint.cli import app
from permlint.config import Config
from permlint.models import GitIndexStatus, ScanDiagnostics, ScanResult

runner = CliRunner()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _repo_with_nonexecutable_script(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "core.filemode", "true")
    script = repo / "deploy script.sh"
    script.write_text("#!/bin/sh\necho ready\n")
    script.chmod(0o644)
    _git(repo, "add", "--", script.name)
    return repo, script


def test_help_aliases_and_explain() -> None:
    for flag in ("-h", "--help"):
        result = runner.invoke(app, [flag])
        assert result.exit_code == 0
        assert "Git-aware Unix permission auditor" in result.output
        assert "fix" in result.output
        assert "json" in result.output
        assert "Exit 0" in result.output

    explained = runner.invoke(app, ["explain", "PL007"])
    assert explained.exit_code == 0
    assert "Git executable-bit mismatch" in explained.output
    assert "Auto-fix" in explained.output
    assert "Edge cases" in explained.output
    assert runner.invoke(app, ["explain", "PL999"]).exit_code == 2


def test_bare_permlint_remains_a_scan(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "README.md").write_text("# Clean\n")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "1 file inspected" in result.output
    assert "No issues found." in result.output


def test_json_output_is_deterministic_and_contains_git_evidence(tmp_path: Path) -> None:
    repo, _ = _repo_with_nonexecutable_script(tmp_path)
    explicit = runner.invoke(app, ["scan", str(repo), "--format", "json"])
    legacy = runner.invoke(app, ["--format", "json", str(repo)])
    assert explicit.exit_code == 1
    assert legacy.exit_code == 1
    assert explicit.output == legacy.output

    payload = json.loads(explicit.output)
    assert payload["schema_version"] == 1
    assert payload["tool"] == {"name": "PermLint", "version": "0.2.0"}
    assert payload["summary"]["files_scanned"] == 1
    assert payload["summary"]["errors"] == 1
    assert payload["summary"]["exit_code"] == 1
    assert payload["summary"]["auto_fixable"] == 1
    assert payload["diagnostics"]["git_index_status"] == "available"
    assert payload["diagnostics"]["unmerged_index_paths"] == 0
    finding = payload["findings"][0]
    assert finding["rule_id"] == "PL001"
    assert finding["path"] == "deploy script.sh"
    assert finding["filesystem_mode"] == "0644"
    assert finding["git_index_mode"] == "100644"
    assert finding["expected_executable"] is True
    assert finding["auto_fixable"] is True
    assert finding["suggested_fix"] == "permlint fix 'deploy script.sh'"


def test_summary_is_explicit_and_lists_counts_without_file_details(tmp_path: Path) -> None:
    repo, script = _repo_with_nonexecutable_script(tmp_path)
    full = runner.invoke(app, [str(repo)])
    legacy_summary = runner.invoke(app, ["--summary", str(repo)])
    scan_summary = runner.invoke(app, ["scan", str(repo), "--summary"])
    assert full.exit_code == legacy_summary.exit_code == scan_summary.exit_code == 1
    assert script.name in full.output
    assert legacy_summary.output == scan_summary.output
    assert "Files inspected: 1" in scan_summary.output
    assert "Errors: 1" in scan_summary.output
    assert "Auto-fixable: 1" in scan_summary.output
    assert "Total findings: 1" in scan_summary.output
    assert "Findings by rule:" in scan_summary.output
    assert "PL001 ERROR" in scan_summary.output
    assert script.name not in scan_summary.output
    assert "Filesystem: 0644" not in scan_summary.output


def test_summary_rejects_machine_format(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(tmp_path), "--summary", "--format", "json"])
    assert result.exit_code == 2
    assert "--summary is available only with --format text" in result.output


def test_sarif_output_has_file_level_location_and_rule_metadata(tmp_path: Path) -> None:
    repo, _ = _repo_with_nonexecutable_script(tmp_path)
    result = runner.invoke(app, ["scan", str(repo), "--format", "sarif"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["version"] == "2.1.0"
    run = payload["runs"][0]
    assert run["tool"]["driver"]["name"] == "PermLint"
    assert any(rule["id"] == "PL001" for rule in run["tool"]["driver"]["rules"])
    assert run["originalUriBaseIds"]["%SRCROOT%"]["uri"].startswith("file:///")
    finding = run["results"][0]
    assert finding["ruleId"] == "PL001"
    assert finding["level"] == "error"
    assert "filesystem 0644" in finding["message"]["text"]
    assert "Git index 100644" in finding["message"]["text"]
    location = finding["locations"][0]["physicalLocation"]
    assert location["artifactLocation"] == {
        "uri": "deploy%20script.sh",
        "uriBaseId": "%SRCROOT%",
    }
    assert "region" not in location


def test_fix_command_preview_then_apply_updates_filesystem_and_git(
    tmp_path: Path, monkeypatch
) -> None:
    repo, script = _repo_with_nonexecutable_script(tmp_path)
    monkeypatch.chdir(repo)
    before_index = _git(repo, "ls-files", "--stage")
    preview = runner.invoke(app, ["fix", script.name, "--dry-run"])
    assert preview.exit_code == 1
    assert "1 safe fix available" in preview.output
    assert "filesystem: 0644 -> 0744" in preview.output
    assert "git index:  100644 -> 100755" in preview.output
    assert "No files changed." in preview.output
    assert stat.S_IMODE(script.stat().st_mode) == 0o644
    assert _git(repo, "ls-files", "--stage") == before_index

    applied = runner.invoke(app, ["fix", script.name])
    assert applied.exit_code == 0
    assert "Applied 1 safe fix" in applied.output
    assert "After repair: 0 errors, 0 warnings." in applied.output
    assert stat.S_IMODE(script.stat().st_mode) & stat.S_IXUSR
    assert _git(repo, "ls-files", "--stage").startswith("100755 ")


def test_bad_config_and_format_are_operational_errors(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n")
    (repo / ".permlint.toml").write_text("not [valid\n")
    malformed = runner.invoke(app, ["scan", str(repo), "--format", "json"])
    assert malformed.exit_code == 2
    assert "Invalid TOML" in malformed.output
    assert not malformed.output.lstrip().startswith("{")

    (repo / ".permlint.toml").unlink()
    bad_format = runner.invoke(app, ["scan", str(repo), "--format", "yaml"])
    assert bad_format.exit_code == 2
    assert "--format must be text, json, or sarif" in bad_format.output


def test_fail_on_error_allows_warning_only_scan(tmp_path: Path) -> None:
    (tmp_path / ".permlint.toml").write_text('fail_on = "error"\n')
    document = tmp_path / "README.md"
    document.write_text("# Example\n")
    document.chmod(0o755)
    result = runner.invoke(app, ["scan", str(tmp_path), "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["summary"]["warnings"] == 1
    assert payload["summary"]["exit_code"] == 0


def test_upgrade_cli_already_current(monkeypatch) -> None:
    monkeypatch.setattr(
        "permlint.upgrade.fetch_latest_release",
        lambda **_kwargs: {"tag_name": "v0.2.0", "draft": False, "prerelease": False},
    )
    result = runner.invoke(app, ["upgrade"])
    assert result.exit_code == 0
    assert "already up to date" in result.output


def test_fix_preview_explains_incomplete_scan(tmp_path: Path, monkeypatch) -> None:
    incomplete = ScanResult(
        target_path=tmp_path,
        diagnostics=ScanDiagnostics(
            git_index_status=GitIndexStatus.NOT_A_REPOSITORY,
            files_unreadable=1,
        ),
    )
    monkeypatch.setattr("permlint.cli._scan_target", lambda _path, _config: (incomplete, Config()))
    result = runner.invoke(app, ["fix", str(tmp_path), "--dry-run"])
    assert result.exit_code == 2
    assert "No files changed." in result.output
    assert "Scan was incomplete:" in result.output
    assert "1 file could not be read" in result.output
    assert "Fixes cannot be applied until the scan completes." in result.output


def test_fix_reports_incomplete_post_apply_verification(tmp_path: Path, monkeypatch) -> None:
    complete = ScanResult(
        target_path=tmp_path,
        diagnostics=ScanDiagnostics(git_index_status=GitIndexStatus.NOT_A_REPOSITORY),
    )
    incomplete = ScanResult(
        target_path=tmp_path,
        diagnostics=ScanDiagnostics(
            git_index_status=GitIndexStatus.NOT_A_REPOSITORY,
            entries_skipped=2,
        ),
    )
    scans = iter((complete, incomplete))
    monkeypatch.setattr("permlint.cli._scan_target", lambda _path, _config: (next(scans), Config()))
    result = runner.invoke(app, ["fix", str(tmp_path)])
    assert result.exit_code == 2
    assert "Applied 0 safe fixes" in result.output
    assert "After repair: verification incomplete" in result.output
    assert "2 files could not be inspected" in result.output
    assert "After repair: 0 errors, 0 warnings." not in result.output


def test_text_scan_handles_non_utf8_filename(tmp_path: Path) -> None:
    raw_path = os.fsencode(tmp_path) + b"/bad\xff.md"
    descriptor = os.open(raw_path, os.O_WRONLY | os.O_CREAT, 0o755)
    try:
        os.write(descriptor, b"data\n")
    finally:
        os.close(descriptor)
    os.chmod(raw_path, 0o755)
    result = runner.invoke(app, ["scan", str(tmp_path)])
    assert result.exit_code == 1
    assert "bad\\udcff.md" in result.output
    assert "surrogates not allowed" not in result.output


def test_cli_errors_escape_control_characters_in_paths(tmp_path: Path) -> None:
    target = tmp_path / "missing\x1b[31m"
    result = runner.invoke(app, ["scan", str(target)])
    assert result.exit_code == 2
    assert "\\x1b" in result.output
    assert "\x1b" not in result.output
