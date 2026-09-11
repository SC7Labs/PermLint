"""Tests for safe filesystem traversal."""

from __future__ import annotations

from pathlib import Path

from permlint.filesystem import walk_repository


def test_walk_discovers_nested_regular_files(tmp_path: Path) -> None:
    src = tmp_path / "src" / "pkg"
    src.mkdir(parents=True)
    file1 = src / "app.py"
    file1.write_text("print('app')\n")
    file2 = tmp_path / "README.md"
    file2.write_text("# Readme\n")

    files = list(walk_repository(tmp_path))
    rel_paths = {f.rel_path for f in files}

    assert Path("src/pkg/app.py") in rel_paths
    assert Path("README.md") in rel_paths
    assert len(files) == 2


def test_walk_ignores_standard_directories(tmp_path: Path) -> None:
    # Create ignored directories
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("git config\n")

    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("fake binary\n")

    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("module\n")

    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "file.pyc").write_bytes(b"pyc")

    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "bundle.whl").write_bytes(b"whl")

    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "output.bin").write_bytes(b"bin")

    # Create valid files
    (tmp_path / "main.py").write_text("print('main')\n")

    files = list(walk_repository(tmp_path))
    assert len(files) == 1
    assert files[0].rel_path == Path("main.py")


def test_walk_does_not_follow_directory_symlinks(tmp_path: Path) -> None:
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    (real_dir / "secret.py").write_text("print('secret')\n")

    # Subdirectory with a symlink to real_dir
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "file.py").write_text("print('sub')\n")

    symlink_dir = sub / "linked_dir"
    symlink_dir.symlink_to(real_dir, target_is_directory=True)

    files = list(walk_repository(sub))
    rel_paths = {f.rel_path for f in files}

    assert Path("file.py") in rel_paths
    assert Path("linked_dir/secret.py") not in rel_paths
    assert len(files) == 1


def test_walk_does_not_follow_symlink_outside_repo(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "external.txt"
    outside_file.write_text("external\n")

    # Create symlink inside repo pointing outside
    (repo_dir / "link_to_external.txt").symlink_to(outside_file)
    (repo_dir / "inside.txt").write_text("inside\n")

    files = list(walk_repository(repo_dir))
    rel_paths = {f.rel_path for f in files}

    assert Path("inside.txt") in rel_paths
    assert Path("link_to_external.txt") not in rel_paths
    assert len(files) == 1


def test_walk_handles_symlink_loops_gracefully(tmp_path: Path) -> None:
    dir_a = tmp_path / "dir_a"
    dir_a.mkdir()
    (dir_a / "file.py").write_text("print('a')\n")

    # Create loop: dir_a/loop -> dir_a
    (dir_a / "loop").symlink_to(dir_a, target_is_directory=True)

    files = list(walk_repository(tmp_path))
    assert len(files) == 1
    assert files[0].rel_path == Path("dir_a/file.py")


def test_walk_handles_broken_symlink_gracefully(tmp_path: Path) -> None:
    nonexistent = tmp_path / "nonexistent.txt"
    broken_link = tmp_path / "broken_link.txt"
    broken_link.symlink_to(nonexistent)

    valid_file = tmp_path / "valid.txt"
    valid_file.write_text("valid\n")

    files = list(walk_repository(tmp_path))
    assert len(files) == 1
    assert files[0].rel_path == Path("valid.txt")


def test_walk_handles_unreadable_file_gracefully(tmp_path: Path) -> None:
    valid_file = tmp_path / "valid.txt"
    valid_file.write_text("valid\n")

    unreadable_file = tmp_path / "unreadable.txt"
    unreadable_file.write_text("secret\n")
    try:
        unreadable_file.chmod(0o000)
    except OSError:
        pass

    files = list(walk_repository(tmp_path))
    # Even if unreadable_file cannot be read, walk does not crash
    assert len(files) >= 1

    # Cleanup permission for tmp_path deletion
    try:
        unreadable_file.chmod(0o644)
    except OSError:
        pass
