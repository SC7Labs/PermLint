"""Project configuration tests, including its effect on real scans."""

from __future__ import annotations

from pathlib import Path

import pytest

from permlint.config import Config, ConfigError, load_config
from permlint.models import Severity
from permlint.scanner import Scanner


def test_missing_implicit_config_uses_defaults(tmp_path: Path) -> None:
    assert load_config(tmp_path) == Config()
    with pytest.raises(ConfigError, match="does not exist"):
        load_config(tmp_path, Path("missing.toml"))


def test_explicit_relative_config_and_values(tmp_path: Path) -> None:
    (tmp_path / "custom.toml").write_text(
        'exclude = ["vendor/**", "*.secret"]\n'
        'disabled_rules = ["PL002"]\n'
        "fix_git_index = false\n"
        'fail_on = "error"\n'
        '[severity_overrides]\nPL003 = "error"\n'
    )

    config = load_config(tmp_path, Path("custom.toml"))
    assert config.exclude == ("vendor/**", "*.secret")
    assert config.disabled_rules == frozenset({"PL002"})
    assert config.fix_git_index is False
    assert config.fail_on == "error"
    assert config.severity_overrides == {"PL003": Severity.ERROR}
    assert config.is_excluded(Path("vendor"))
    assert config.is_excluded(Path("vendor/sub/tool.sh"))
    assert config.is_excluded(Path("nested/token.secret"))
    assert not config.is_excluded(Path("src/app.py"))


@pytest.mark.parametrize(
    ("content", "error"),
    [
        ("exclude = [", "Invalid TOML"),
        ('unknown = "value"\n', "Unknown configuration option"),
        ('exclude = "vendor"\n', "exclude must be a list"),
        ('exclude = ["../outside"]\n', "Invalid relative exclusion pattern"),
        ('disabled_rules = ["PL999"]\n', "Unknown rule ID"),
        ('[severity_overrides]\nPL001 = "critical"\n', "must be 'error' or 'warning'"),
        ('fail_on = "all"\n', "fail_on must be"),
        ('fix_git_index = "yes"\n', "fix_git_index must be"),
    ],
)
def test_malformed_config_fails_closed(tmp_path: Path, content: str, error: str) -> None:
    (tmp_path / ".permlint.toml").write_text(content)
    with pytest.raises(ConfigError, match=error):
        Scanner().scan(tmp_path)


def test_config_exclusion_rule_selection_and_policy(tmp_path: Path) -> None:
    (tmp_path / ".permlint.toml").write_text(
        'exclude = ["vendor", "*.generated"]\n'
        'disabled_rules = ["PL001"]\n'
        'fail_on = "error"\n'
        '[severity_overrides]\nPL003 = "warning"\n'
    )

    vendor = tmp_path / "vendor"
    vendor.mkdir()
    (vendor / "ignored.sh").write_text("#!/bin/sh\n")
    (tmp_path / "ignored.generated").write_text("#!/bin/sh\n")

    script = tmp_path / "disabled.sh"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o644)

    data = tmp_path / "README.md"
    data.write_text("# Project\n")
    data.chmod(0o755)

    result = Scanner().scan(tmp_path)
    assert result.files_inspected == 3  # config, disabled script, executable data
    assert [finding.check_id for finding in result.findings] == ["PL003"]
    assert result.warning_count == 1
    assert result.policy_fail_on == "error"
    assert result.exit_code == 0


def test_severity_override_changes_policy_result(tmp_path: Path) -> None:
    (tmp_path / ".permlint.toml").write_text(
        'fail_on = "error"\n[severity_overrides]\nPL003 = "error"\n'
    )
    data = tmp_path / "README.md"
    data.write_text("# Project\n")
    data.chmod(0o755)

    result = Scanner().scan(tmp_path)
    assert [finding.severity for finding in result.findings] == [Severity.ERROR]
    assert result.exit_code == 1
