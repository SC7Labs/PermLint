"""Real Git and filesystem integration tests for safe executable-bit repairs."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from permlint.config import Config
from permlint.fixer import apply_fixes, plan_fixes
from permlint.scanner import Scanner


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True).stdout


def _stage(root: Path, rel_path: str) -> tuple[str, str]:
    raw = _git(root, "ls-files", "--stage", "-z", "--", rel_path)
    entry = raw.rstrip(b"\0").split(b"\t", 1)[0].split()
    return entry[0].decode("ascii"), entry[1].decode("ascii")


def _file(root: Path, rel_path: str, data: bytes, mode: int) -> Path:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)
    return path


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("Git is unavailable")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "PermLint Test")
    _git(tmp_path, "config", "user.email", "permlint@example.invalid")
    return tmp_path


def test_tracked_shebang_fixes_filesystem_and_index_without_staging_content(
    git_repo: Path,
) -> None:
    script = _file(git_repo, "scripts/deploy.sh", b"#!/bin/sh\necho deploy\n", 0o644)
    _git(git_repo, "add", "--", "scripts/deploy.sh")
    before_index_mode, before_blob = _stage(git_repo, "scripts/deploy.sh")
    assert before_index_mode == "100644"

    plan = plan_fixes(Scanner().scan(git_repo))
    assert len(plan.actions) == 1
    action = plan.actions[0]
    assert action.rel_path == Path("scripts/deploy.sh")
    assert (action.before_mode, action.after_mode) == (0o644, 0o744)
    assert (action.before_git_mode, action.after_git_mode) == ("100644", "100755")

    outcome = apply_fixes(plan)
    assert outcome.failures == []
    assert outcome.applied == [action]
    assert _mode(script) == 0o744
    assert _stage(git_repo, "scripts/deploy.sh") == ("100755", before_blob)
    assert script.read_bytes() == b"#!/bin/sh\necho deploy\n"
    assert not Scanner().scan(git_repo).findings


def test_planning_is_a_true_dry_run_for_file_and_index(git_repo: Path) -> None:
    script = _file(git_repo, "run.sh", b"#!/bin/sh\necho ok\n", 0o644)
    _git(git_repo, "add", "--", "run.sh")
    before_file = script.read_bytes()
    before_mode = _mode(script)
    before_index = (git_repo / ".git" / "index").read_bytes()

    plan = plan_fixes(Scanner().scan(git_repo))

    assert len(plan.actions) == 1
    assert script.read_bytes() == before_file
    assert _mode(script) == before_mode
    assert (git_repo / ".git" / "index").read_bytes() == before_index


def test_clean_tracked_executable_has_no_action(git_repo: Path) -> None:
    _file(git_repo, "run.sh", b"#!/bin/sh\necho ok\n", 0o755)
    _git(git_repo, "add", "--", "run.sh")
    assert _stage(git_repo, "run.sh")[0] == "100755"
    plan = plan_fixes(Scanner().scan(git_repo))
    assert plan.actions == []
    assert plan.manual == []


def test_shebang_resolves_working_tree_executable_index_nonexecutable(
    git_repo: Path,
) -> None:
    script = _file(git_repo, "run.sh", b"#!/bin/sh\n", 0o644)
    _git(git_repo, "add", "--", "run.sh")
    script.chmod(0o755)
    before_blob = _stage(git_repo, "run.sh")[1]

    plan = plan_fixes(Scanner().scan(git_repo))
    assert [(a.before_mode, a.after_mode) for a in plan.actions] == [(0o755, 0o755)]
    assert [(a.before_git_mode, a.after_git_mode) for a in plan.actions] == [("100644", "100755")]
    assert apply_fixes(plan).failures == []
    assert _mode(script) == 0o755
    assert _stage(git_repo, "run.sh") == ("100755", before_blob)


def test_shebang_resolves_index_executable_working_tree_nonexecutable(
    git_repo: Path,
) -> None:
    script = _file(git_repo, "run.sh", b"#!/bin/sh\n", 0o755)
    _git(git_repo, "add", "--", "run.sh")
    script.chmod(0o644)
    before_index = (git_repo / ".git" / "index").read_bytes()

    plan = plan_fixes(Scanner().scan(git_repo))
    assert len(plan.actions) == 1
    assert (plan.actions[0].before_git_mode, plan.actions[0].after_git_mode) == (
        "100755",
        "100755",
    )
    assert apply_fixes(plan).failures == []
    assert _mode(script) == 0o744
    assert _stage(git_repo, "run.sh")[0] == "100755"
    assert (git_repo / ".git" / "index").read_bytes() == before_index


def test_data_file_clears_execute_bits_on_disk_and_in_index(git_repo: Path) -> None:
    data = _file(git_repo, "docs/notes.md", b"# Notes\n", 0o755)
    _git(git_repo, "add", "--", "docs/notes.md")
    before_blob = _stage(git_repo, "docs/notes.md")[1]

    plan = plan_fixes(Scanner().scan(git_repo))
    assert len(plan.actions) == 1
    assert (plan.actions[0].before_mode, plan.actions[0].after_mode) == (0o755, 0o644)
    assert apply_fixes(plan).failures == []
    assert _mode(data) == 0o644
    assert _stage(git_repo, "docs/notes.md") == ("100644", before_blob)


def test_data_evidence_can_fix_index_only_mismatch(git_repo: Path) -> None:
    data = _file(git_repo, "notes.txt", b"plain text\n", 0o755)
    _git(git_repo, "add", "--", "notes.txt")
    data.chmod(0o644)
    before_blob = _stage(git_repo, "notes.txt")[1]

    plan = plan_fixes(Scanner().scan(git_repo))
    assert len(plan.actions) == 1
    assert (plan.actions[0].before_mode, plan.actions[0].after_mode) == (0o644, 0o644)
    assert apply_fixes(plan).failures == []
    assert _stage(git_repo, "notes.txt") == ("100644", before_blob)


def test_untracked_and_non_git_files_receive_filesystem_only_repair(
    git_repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    untracked = _file(git_repo, "new.sh", b"#!/bin/sh\n", 0o644)
    untracked_plan = plan_fixes(Scanner().scan(git_repo))
    assert len(untracked_plan.actions) == 1
    assert untracked_plan.actions[0].before_git_mode is None
    assert untracked_plan.actions[0].after_git_mode is None
    assert apply_fixes(untracked_plan).failures == []
    assert _mode(untracked) == 0o744
    assert _git(git_repo, "ls-files", "--", "new.sh") == b""

    plain_root = tmp_path_factory.mktemp("plain-permlint")
    plain = _file(plain_root, "new.sh", b"#!/bin/sh\n", 0o644)
    plain_plan = plan_fixes(Scanner().scan(plain_root))
    assert len(plain_plan.actions) == 1
    assert apply_fixes(plain_plan).failures == []
    assert _mode(plain) == 0o744


def test_ambiguous_mismatch_is_manual_and_leaves_file_untouched(git_repo: Path) -> None:
    module = _file(git_repo, "module.py", b"print('library')\n", 0o644)
    _git(git_repo, "add", "--", "module.py")
    module.chmod(0o755)
    before_index = (git_repo / ".git" / "index").read_bytes()

    plan = plan_fixes(Scanner().scan(git_repo))
    assert plan.actions == []
    assert len(plan.manual) == 1
    assert plan.manual[0].rel_path == Path("module.py")
    assert "ambiguous" in plan.manual[0].reason
    assert apply_fixes(plan).applied == []
    assert _mode(module) == 0o755
    assert (git_repo / ".git" / "index").read_bytes() == before_index


def test_fix_does_not_stage_unstaged_content_or_touch_unrelated_entries(
    git_repo: Path,
) -> None:
    script = _file(git_repo, "run.sh", b"#!/bin/sh\necho baseline\n", 0o644)
    other = _file(git_repo, "other.txt", b"baseline\n", 0o644)
    _git(git_repo, "add", "--", "run.sh", "other.txt")
    _git(git_repo, "commit", "-q", "-m", "baseline")

    script.write_bytes(b"#!/bin/sh\necho staged\n")
    other.write_bytes(b"staged unrelated\n")
    _git(git_repo, "add", "--", "run.sh", "other.txt")
    script.write_bytes(b"#!/bin/sh\necho unstaged\n")
    staged_script = _stage(git_repo, "run.sh")
    staged_other = _stage(git_repo, "other.txt")

    plan = plan_fixes(Scanner().scan(git_repo))
    assert len(plan.actions) == 1
    assert apply_fixes(plan).failures == []
    assert _stage(git_repo, "run.sh") == ("100755", staged_script[1])
    assert _stage(git_repo, "other.txt") == staged_other
    assert script.read_bytes() == b"#!/bin/sh\necho unstaged\n"
    assert other.read_bytes() == b"staged unrelated\n"


def test_config_can_forbid_git_index_changes_without_partial_fix(git_repo: Path) -> None:
    script = _file(git_repo, "run.sh", b"#!/bin/sh\n", 0o644)
    _git(git_repo, "add", "--", "run.sh")
    plan = plan_fixes(Scanner().scan(git_repo), Config(fix_git_index=False))
    assert plan.actions == []
    assert len(plan.manual) == 1
    assert "disabled" in plan.manual[0].reason
    assert _mode(script) == 0o644
    assert _stage(git_repo, "run.sh")[0] == "100644"


def test_selected_paths_limit_repairs_and_reject_escape(git_repo: Path) -> None:
    first = _file(git_repo, "scripts/first.sh", b"#!/bin/sh\n", 0o644)
    second = _file(git_repo, "scripts/second.sh", b"#!/bin/sh\n", 0o644)
    _file(git_repo, "other.sh", b"#!/bin/sh\n", 0o644)
    scan = Scanner().scan(git_repo)

    exact = plan_fixes(scan, selected_paths=[Path("scripts/first.sh")])
    assert [a.rel_path for a in exact.actions] == [Path("scripts/first.sh")]
    directory = plan_fixes(scan, selected_paths=[Path("scripts")])
    assert [a.rel_path for a in directory.actions] == [
        Path("scripts/first.sh"),
        Path("scripts/second.sh"),
    ]
    assert _mode(first) == 0o644
    assert _mode(second) == 0o644
    with pytest.raises(ValueError, match="unsafe"):
        plan_fixes(scan, selected_paths=[Path("../outside.sh")])
    with pytest.raises(ValueError, match="outside"):
        plan_fixes(scan, selected_paths=[git_repo.parent / "outside.sh"])


def test_changed_content_after_planning_is_refused(git_repo: Path) -> None:
    script = _file(git_repo, "run.sh", b"#!/bin/sh\n", 0o644)
    _git(git_repo, "add", "--", "run.sh")
    plan = plan_fixes(Scanner().scan(git_repo))
    script.write_bytes(b"#!/bin/sh\necho changed\n")

    outcome = apply_fixes(plan)
    assert outcome.applied == []
    assert len(outcome.failures) == 1
    assert "changed" in outcome.failures[0].reason
    assert _mode(script) == 0o644
    assert _stage(git_repo, "run.sh")[0] == "100644"


def test_changed_git_index_after_planning_is_refused(git_repo: Path) -> None:
    script = _file(git_repo, "run.sh", b"#!/bin/sh\n", 0o644)
    _git(git_repo, "add", "--", "run.sh")
    plan = plan_fixes(Scanner().scan(git_repo))
    _git(git_repo, "update-index", "--chmod=+x", "--", "run.sh")

    outcome = apply_fixes(plan)
    assert outcome.applied == []
    assert len(outcome.failures) == 1
    assert "Git index" in outcome.failures[0].reason
    assert _mode(script) == 0o644


def test_replaced_file_symlink_cannot_escape_scan_root(git_repo: Path) -> None:
    script = _file(git_repo, "run.sh", b"#!/bin/sh\n", 0o644)
    _git(git_repo, "add", "--", "run.sh")
    plan = plan_fixes(Scanner().scan(git_repo))
    external = _file(git_repo.parent, "external-fix-target.txt", b"outside\n", 0o600)
    script.unlink()
    script.symlink_to(external)
    try:
        outcome = apply_fixes(plan)
        assert outcome.applied == []
        assert len(outcome.failures) == 1
        assert _mode(external) == 0o600
        assert _stage(git_repo, "run.sh")[0] == "100644"
    finally:
        external.unlink()


def test_replaced_parent_symlink_cannot_escape_scan_root(git_repo: Path) -> None:
    _file(git_repo, "scripts/run.sh", b"#!/bin/sh\n", 0o644)
    _git(git_repo, "add", "--", "scripts/run.sh")
    plan = plan_fixes(Scanner().scan(git_repo))
    outside = git_repo.parent / "external-fix-parent"
    outside.mkdir()
    external_file = _file(outside, "run.sh", b"outside\n", 0o600)
    (git_repo / "scripts").rename(git_repo / "scripts_original")
    (git_repo / "scripts").symlink_to(outside, target_is_directory=True)
    try:
        outcome = apply_fixes(plan)
        assert outcome.applied == []
        assert len(outcome.failures) == 1
        assert _mode(external_file) == 0o600
        assert _stage(git_repo, "scripts/run.sh")[0] == "100644"
    finally:
        (git_repo / "scripts").unlink()
        external_file.unlink()
        outside.rmdir()


def test_nonregular_git_entry_is_manual(git_repo: Path) -> None:
    real = _file(git_repo, "real.sh", b"#!/bin/sh\n", 0o755)
    link = git_repo / "link.sh"
    link.symlink_to(real)
    _git(git_repo, "add", "--", "link.sh")
    link.unlink()
    link.write_bytes(b"#!/bin/sh\n")
    link.chmod(0o644)
    assert _stage(git_repo, "link.sh")[0] == "120000"

    plan = plan_fixes(Scanner().scan(git_repo))
    assert not any(action.rel_path == Path("link.sh") for action in plan.actions)
    assert any(
        item.rel_path == Path("link.sh") and "not a regular file" in item.reason
        for item in plan.manual
    )


def test_fix_nested_git_subdirectory_uses_only_its_paths(git_repo: Path) -> None:
    sub = git_repo / "sub"
    target = _file(git_repo, "sub/run.sh", b"#!/bin/sh\n", 0o644)
    outside = _file(git_repo, "outside.sh", b"#!/bin/sh\n", 0o644)
    _git(git_repo, "add", "--", "sub/run.sh", "outside.sh")
    before_outside = _stage(git_repo, "outside.sh")

    plan = plan_fixes(Scanner().scan(sub))
    assert [action.rel_path for action in plan.actions] == [Path("run.sh")]
    assert apply_fixes(plan).failures == []
    assert _mode(target) == 0o744
    assert _stage(git_repo, "sub/run.sh")[0] == "100755"
    assert _mode(outside) == 0o644
    assert _stage(git_repo, "outside.sh") == before_outside


def test_no_auto_fix_for_world_writable_script(git_repo: Path) -> None:
    script = _file(git_repo, "run.sh", b"#!/bin/sh\n", 0o666)
    _git(git_repo, "add", "--", "run.sh")
    plan = plan_fixes(Scanner().scan(git_repo))
    assert plan.actions == []
    assert len(plan.manual) == 1
    assert _mode(script) == 0o666


def test_no_auto_fix_for_conflicting_data_extension_and_shebang(git_repo: Path) -> None:
    data = _file(git_repo, "notes.txt", b"#!/bin/sh\n", 0o644)
    _git(git_repo, "add", "--", "notes.txt")
    plan = plan_fixes(Scanner().scan(git_repo))
    assert plan.actions == []
    assert any("conflicting" in item.reason for item in plan.manual)
    assert _mode(data) == 0o644


def test_owner_execute_only_preserves_other_permission_bits(git_repo: Path) -> None:
    script = _file(git_repo, "private.sh", b"#!/bin/sh\n", 0o600)
    plan = plan_fixes(Scanner().scan(git_repo))
    assert len(plan.actions) == 1
    assert plan.actions[0].after_mode == 0o700
    assert apply_fixes(plan).failures == []
    assert _mode(script) == 0o700


def test_apply_refuses_stale_file_mode(git_repo: Path) -> None:
    script = _file(git_repo, "run.sh", b"#!/bin/sh\n", 0o644)
    plan = plan_fixes(Scanner().scan(git_repo))
    script.chmod(0o600)
    outcome = apply_fixes(plan)
    assert outcome.applied == []
    assert len(outcome.failures) == 1
    assert _mode(script) == 0o600


def test_git_update_failure_rolls_back_filesystem_mode(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from permlint import fixer

    script = _file(git_repo, "run.sh", b"#!/bin/sh\n", 0o644)
    _git(git_repo, "add", "--", "run.sh")
    plan = plan_fixes(Scanner().scan(git_repo))
    real_git_run = fixer._git_run

    def fail_update(
        root: Path,
        args: list[str],
        input_data: bytes | None = None,
        *,
        index_file: Path | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        if args[0] == "update-index":
            raise fixer._UnsafeFixError("injected Git failure")
        return real_git_run(root, args, input_data, index_file=index_file)

    monkeypatch.setattr(fixer, "_git_run", fail_update)
    outcome = apply_fixes(plan)
    assert outcome.applied == []
    assert len(outcome.failures) == 1
    assert "injected Git failure" in outcome.failures[0].reason
    assert _mode(script) == 0o644
    assert _stage(git_repo, "run.sh")[0] == "100644"


@pytest.mark.parametrize(
    ("flag_command", "label"),
    [
        ("--assume-unchanged", "assume-unchanged"),
        ("--skip-worktree", "skip-worktree"),
    ],
)
def test_nonstandard_git_index_flags_are_manual(
    git_repo: Path, flag_command: str, label: str
) -> None:
    script = _file(git_repo, "run.sh", b"#!/bin/sh\n", 0o644)
    _git(git_repo, "add", "--", "run.sh")
    before_entry = _stage(git_repo, "run.sh")
    _git(git_repo, "update-index", flag_command, "--", "run.sh")
    before_tag = _git(git_repo, "ls-files", "-v", "--", "run.sh")

    plan = plan_fixes(Scanner().scan(git_repo))
    assert plan.actions == []
    assert len(plan.manual) == 1
    assert "nonstandard flags" in plan.manual[0].reason
    assert apply_fixes(plan).applied == []
    assert _mode(script) == 0o644
    assert _stage(git_repo, "run.sh") == before_entry
    assert _git(git_repo, "ls-files", "-v", "--", "run.sh") == before_tag
    assert label in plan.manual[0].reason


def test_intent_to_add_flag_is_manual(git_repo: Path) -> None:
    script = _file(git_repo, "run.sh", b"#!/bin/sh\n", 0o644)
    _git(git_repo, "add", "-N", "--", "run.sh")
    assert _git(git_repo, "ls-files", "-v", "--", "run.sh") == b"H run.sh\n"
    before_entry = _stage(git_repo, "run.sh")

    plan = plan_fixes(Scanner().scan(git_repo))
    assert plan.actions == []
    assert len(plan.manual) == 1
    assert "intent-to-add" in plan.manual[0].reason
    assert _mode(script) == 0o644
    assert _stage(git_repo, "run.sh") == before_entry


def test_new_git_index_flag_after_planning_refuses_apply(git_repo: Path) -> None:
    script = _file(git_repo, "run.sh", b"#!/bin/sh\n", 0o644)
    _git(git_repo, "add", "--", "run.sh")
    plan = plan_fixes(Scanner().scan(git_repo))
    assert len(plan.actions) == 1
    _git(git_repo, "update-index", "--skip-worktree", "--", "run.sh")

    outcome = apply_fixes(plan)
    assert outcome.applied == []
    assert len(outcome.failures) == 1
    assert "nonstandard flags" in outcome.failures[0].reason
    assert _mode(script) == 0o644
    assert _stage(git_repo, "run.sh")[0] == "100644"
    assert _git(git_repo, "ls-files", "-v", "--", "run.sh").startswith(b"S ")


def test_staged_content_without_shebang_blocks_git_mode_change(git_repo: Path) -> None:
    script = _file(git_repo, "run.sh", b"plain staged content\n", 0o644)
    _git(git_repo, "add", "--", "run.sh")
    staged_entry = _stage(git_repo, "run.sh")
    script.write_bytes(b"#!/bin/sh\necho unstaged\n")

    plan = plan_fixes(Scanner().scan(git_repo))
    assert plan.actions == []
    assert len(plan.manual) == 1
    assert "Staged Git content" in plan.manual[0].reason
    assert _stage(git_repo, "run.sh") == staged_entry
    assert _mode(script) == 0o644


def test_staged_shebang_blocks_data_file_mode_removal(git_repo: Path) -> None:
    data = _file(git_repo, "notes.txt", b"#!/bin/sh\n", 0o755)
    _git(git_repo, "add", "--", "notes.txt")
    staged_entry = _stage(git_repo, "notes.txt")
    data.write_bytes(b"plain working content\n")

    plan = plan_fixes(Scanner().scan(git_repo))
    assert plan.actions == []
    assert len(plan.manual) == 1
    assert "Staged Git content" in plan.manual[0].reason
    assert _stage(git_repo, "notes.txt") == staged_entry
    assert _mode(data) == 0o755


def test_planning_reads_multiple_staged_headers_in_one_batch(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from permlint import fixer

    for name in ("one.sh", "two.sh", "three.sh"):
        _file(git_repo, name, f"#!/bin/sh\necho {name}\n".encode(), 0o644)
    _git(git_repo, "add", "--", "one.sh", "two.sh", "three.sh")
    expected_blobs = {_stage(git_repo, name)[1] for name in ("one.sh", "two.sh", "three.sh")}
    calls: list[set[str]] = []
    real_read = fixer.read_staged_headers

    def record_read(root: Path, blobs: set[str]) -> dict[str, bytes]:
        calls.append(blobs.copy())
        return real_read(root, blobs)

    monkeypatch.setattr(fixer, "read_staged_headers", record_read)
    plan = plan_fixes(Scanner().scan(git_repo))

    assert len(plan.actions) == 3
    assert calls == [expected_blobs]


def test_staged_header_read_failure_is_manual_for_tracked_files(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from permlint import fixer
    from permlint.staged_content import StagedContentError

    tracked = _file(git_repo, "tracked.sh", b"#!/bin/sh\n", 0o644)
    _git(git_repo, "add", "--", "tracked.sh")
    _file(git_repo, "untracked.sh", b"#!/bin/sh\n", 0o644)

    def fail_read(_root: Path, _blobs: set[str]) -> dict[str, bytes]:
        raise StagedContentError("injected staged read failure")

    monkeypatch.setattr(fixer, "read_staged_headers", fail_read)
    plan = plan_fixes(Scanner().scan(git_repo))

    assert [action.rel_path for action in plan.actions] == [Path("untracked.sh")]
    assert len(plan.manual) == 1
    assert plan.manual[0].rel_path == Path("tracked.sh")
    assert "injected staged read failure" in plan.manual[0].reason
    assert _mode(tracked) == 0o644


def test_nested_git_repository_requires_direct_scan(git_repo: Path) -> None:
    inner = git_repo / "nested"
    inner.mkdir()
    _git(inner, "init", "-q")
    script = _file(inner, "run.sh", b"#!/bin/sh\n", 0o644)
    _git(inner, "add", "--", "run.sh")
    inner_entry = _stage(inner, "run.sh")

    outer_plan = plan_fixes(Scanner().scan(git_repo))
    assert outer_plan.actions == []
    assert any(
        item.rel_path == Path("nested/run.sh") and "nested Git repository" in item.reason
        for item in outer_plan.manual
    )
    assert _mode(script) == 0o644
    assert _stage(inner, "run.sh") == inner_entry

    direct_plan = plan_fixes(Scanner().scan(inner))
    assert [action.rel_path for action in direct_plan.actions] == [Path("run.sh")]
    assert apply_fixes(direct_plan).failures == []
    assert _mode(script) == 0o744
    assert _stage(inner, "run.sh")[0] == "100755"


def test_nested_git_boundary_appearing_after_plan_refuses_apply(git_repo: Path) -> None:
    script = _file(git_repo, "nested/run.sh", b"#!/bin/sh\n", 0o644)
    plan = plan_fixes(Scanner().scan(git_repo))
    assert len(plan.actions) == 1
    _git(script.parent, "init", "-q")

    outcome = apply_fixes(plan)
    assert outcome.applied == []
    assert len(outcome.failures) == 1
    assert "nested Git repository" in outcome.failures[0].reason
    assert _mode(script) == 0o644


def test_selected_missing_or_symlinked_path_is_rejected(git_repo: Path) -> None:
    target = _file(git_repo, "outside.txt", b"outside\n", 0o600)
    link = git_repo / "link.sh"
    link.symlink_to(target)
    scan = Scanner().scan(git_repo)

    with pytest.raises(ValueError, match="cannot be opened safely"):
        plan_fixes(scan, selected_paths=[Path("missing.sh")])
    with pytest.raises(ValueError, match="cannot be opened safely"):
        plan_fixes(scan, selected_paths=[Path("link.sh")])

    outside_dir = git_repo.parent / "external-selected-dir"
    outside_dir.mkdir()
    _file(outside_dir, "file.sh", b"#!/bin/sh\n", 0o644)
    link_dir = git_repo / "linkdir"
    link_dir.symlink_to(outside_dir, target_is_directory=True)
    try:
        with pytest.raises(ValueError, match="cannot be opened safely"):
            plan_fixes(scan, selected_paths=[Path("linkdir/file.sh")])
    finally:
        link_dir.unlink()
        (outside_dir / "file.sh").unlink()
        outside_dir.rmdir()


def test_concurrent_stage_before_index_lock_is_preserved(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Git writer that wins the index lock cannot have its blob overwritten."""
    from permlint import fixer

    script = _file(git_repo, "run.sh", b"#!/bin/sh\necho staged-v1\n", 0o644)
    _git(git_repo, "add", "--", "run.sh")
    original_blob = _stage(git_repo, "run.sh")[1]
    script.write_bytes(b"#!/bin/sh\necho staged-v2\n")
    plan = plan_fixes(Scanner().scan(git_repo))
    assert len(plan.actions) == 1
    real_locked_index = fixer._locked_index

    def stage_before_lock(the_plan):
        _git(git_repo, "add", "--", "run.sh")
        return real_locked_index(the_plan)

    monkeypatch.setattr(fixer, "_locked_index", stage_before_lock)
    outcome = apply_fixes(plan)

    assert outcome.applied == []
    assert len(outcome.failures) == 1
    assert "staged content changed" in outcome.failures[0].reason.lower()
    new_mode, new_blob = _stage(git_repo, "run.sh")
    assert new_mode == "100644"
    assert new_blob != original_blob
    assert new_blob == _git(git_repo, "hash-object", "run.sh").decode().strip()
    assert _mode(script) == 0o644
    assert not (git_repo / ".git" / "index.lock").exists()


def test_unrelated_stage_before_index_lock_is_preserved(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from permlint import fixer

    script = _file(git_repo, "run.sh", b"#!/bin/sh\n", 0o644)
    other = _file(git_repo, "other.txt", b"first version\n", 0o644)
    _git(git_repo, "add", "--", "run.sh", "other.txt")
    original_other_blob = _stage(git_repo, "other.txt")[1]
    plan = plan_fixes(Scanner().scan(git_repo))
    assert len(plan.actions) == 1
    other.write_bytes(b"new version staged by another writer\n")
    real_locked_index = fixer._locked_index

    def stage_before_lock(the_plan):
        _git(git_repo, "add", "--", "other.txt")
        return real_locked_index(the_plan)

    monkeypatch.setattr(fixer, "_locked_index", stage_before_lock)
    outcome = apply_fixes(plan)

    assert outcome.failures == []
    assert len(outcome.applied) == 1
    assert _mode(script) == 0o744
    assert _stage(git_repo, "run.sh")[0] == "100755"
    assert _stage(git_repo, "other.txt")[1] != original_other_blob
    assert (
        _stage(git_repo, "other.txt")[1]
        == _git(git_repo, "hash-object", "other.txt").decode().strip()
    )
    assert not (git_repo / ".git" / "index.lock").exists()


def test_existing_git_index_lock_refuses_before_chmod(git_repo: Path) -> None:
    script = _file(git_repo, "run.sh", b"#!/bin/sh\n", 0o644)
    _git(git_repo, "add", "--", "run.sh")
    plan = plan_fixes(Scanner().scan(git_repo))
    index_lock = git_repo / ".git" / "index.lock"
    index_lock.write_bytes(b"other writer")
    try:
        outcome = apply_fixes(plan)
        assert outcome.applied == []
        assert len(outcome.failures) == 1
        assert "locked by another process" in outcome.failures[0].reason
        assert _mode(script) == 0o644
        assert _stage(git_repo, "run.sh")[0] == "100644"
        assert index_lock.read_bytes() == b"other writer"
    finally:
        index_lock.unlink()


def test_incomplete_scan_plan_refuses_all_changes(git_repo: Path) -> None:
    script = _file(git_repo, "run.sh", b"#!/bin/sh\n", 0o644)
    _git(git_repo, "add", "--", "run.sh")
    plan = plan_fixes(Scanner().scan(git_repo))
    assert len(plan.actions) == 1
    plan.scan.diagnostics.entries_skipped = 1

    outcome = apply_fixes(plan)
    assert outcome.applied == []
    assert len(outcome.failures) == 1
    assert "Scan was incomplete" in outcome.failures[0].reason
    assert _mode(script) == 0o644
    assert _stage(git_repo, "run.sh")[0] == "100644"


def test_linked_worktree_updates_its_private_index_only(git_repo: Path) -> None:
    _file(git_repo, "run.sh", b"#!/bin/sh\n", 0o644)
    _git(git_repo, "add", "--", "run.sh")
    _git(git_repo, "commit", "-q", "-m", "baseline")
    main_entry = _stage(git_repo, "run.sh")
    linked = git_repo.parent / f"{git_repo.name}-linked"
    _git(git_repo, "worktree", "add", "--detach", str(linked), "HEAD")
    try:
        index_path = Path(_git(linked, "rev-parse", "--git-path", "index").decode().strip())
        assert index_path.is_absolute()
        assert index_path != linked / ".git" / "index"
        before_mode = _mode(linked / "run.sh")
        plan = plan_fixes(Scanner().scan(linked))
        assert len(plan.actions) == 1
        outcome = apply_fixes(plan)
        assert outcome.failures == []
        assert _mode(linked / "run.sh") == before_mode | stat.S_IXUSR
        assert _stage(linked, "run.sh")[0] == "100755"
        assert _stage(git_repo, "run.sh") == main_entry
        assert not Path(str(index_path) + ".lock").exists()
    finally:
        _git(git_repo, "worktree", "remove", "--force", str(linked))


def test_existing_hard_link_outside_root_is_manual(tmp_path: Path) -> None:
    root = tmp_path / "scan"
    root.mkdir()
    outside = _file(tmp_path, "outside.sh", b"#!/bin/sh\n", 0o644)
    inside = root / "run.sh"
    os.link(outside, inside)

    plan = plan_fixes(Scanner().scan(root))
    assert plan.actions == []
    assert len(plan.manual) == 1
    assert plan.manual[0].rel_path == Path("run.sh")
    assert "multiple hard links" in plan.manual[0].reason
    assert _mode(inside) == _mode(outside) == 0o644


def test_hard_link_added_after_planning_refuses_apply(tmp_path: Path) -> None:
    root = tmp_path / "scan"
    root.mkdir()
    inside = _file(root, "run.sh", b"#!/bin/sh\n", 0o644)
    plan = plan_fixes(Scanner().scan(root))
    assert [action.rel_path for action in plan.actions] == [Path("run.sh")]

    outside = tmp_path / "outside.sh"
    os.link(inside, outside)
    outcome = apply_fixes(plan)

    assert outcome.applied == []
    assert len(outcome.failures) == 1
    assert "another hard link" in outcome.failures[0].reason
    assert _mode(inside) == _mode(outside) == 0o644
