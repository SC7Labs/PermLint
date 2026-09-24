# PermLint

**Catch permission mistakes before they ship.**

PermLint is a lightweight CLI that scans repositories for suspicious Unix file-permission mistakes.

---

## Overview

Unix file permission bits (e.g., `chmod +x` / mode `0755` vs `0644`, world-writability, or privilege bits) are often committed accidentally or forgotten during development. A deployment script missing its executable bit fails in CI or production, while executable configuration files or world-writable assets introduce security risks and version-control noise.

PermLint inspects repository files deterministically and reports permission inconsistencies before they ship.

### What PermLint Does
- Recursively scans repository files in a single, safe traversal pass.
- Evaluates 8 primary permission rules covering execution, writability, privilege bits, and Git index consistency.
- Inspects Git index modes once at scan startup to catch staged vs working-tree discrepancies.
- Skips a **fixed built-in list** of directory names (`.git`, `.hg`, `.svn`, `.venv`, `venv`, `node_modules`, `vendor`, `dist`, `build`, `__pycache__`, and similar) without following directory symlinks or symlink loops. PermLint does **not** read `.gitignore` and does not implement gitignore semantics — the list is hard-coded in `DEFAULT_IGNORE_DIRS`.

### What PermLint Does NOT Do
PermLint is intentionally focused and does one job well. It is **not**:
- A vulnerability scanner or CVE database.
- A secret scanner or malware detector (no content scanning for secrets).
- An automated `chmod` modification tool (it will never modify your files).
- A Windows ACL auditor.

---

## Installation for Development

PermLint requires **Python 3.12+**.

From a clone of this repository, install in editable mode with development
dependencies:

```bash
pip install -e ".[dev]"
```

Verify installation:

```bash
permlint --version
```

---

## Usage

Scan the current working directory:

```bash
permlint .
```

Scan a specific repository or directory:

```bash
permlint /path/to/project
```

Display the version:

```bash
permlint --version
```

---

## Example Output

### Clean Repository

```text
PermLint 0.1.1
Scanning: /path/to/project

✓ 137 files inspected

No issues found.
```

### Issues Discovered

```text
PermLint 0.1.1
Scanning: /path/to/project

PL001 ERROR  scripts/deploy.sh
             Has a shebang but is not executable

PL002 WARN   tools/migrate.py
             Executable text file has no shebang

PL003 WARN   config/settings.yaml
             File type normally should not be executable

PL004 ERROR  data/shared.csv
             File is writable by all users

PL005 WARN   keys/id_ed25519
             Sensitive-looking file is accessible by group or other users

PL006 ERROR  scripts/broken.sh
             Malformed shebang

PL007 WARN   scripts/run.sh
             Working tree executable bit does not match Git index

PL008 ERROR  bin/daemon
             Regular file has setuid/setgid permission bits

Files inspected: 137
Errors: 4
Warnings: 4

8 issues found
```

---

## Rules (Checks)

PermLint v0.1.1 implements exactly 8 primary checks:

| Rule ID | Severity | Name | Description |
| :--- | :--- | :--- | :--- |
| **PL001** | `ERROR` | Shebang but not executable | Script file begins with a valid shebang (`#!`) but has no executable permission bits set. |
| **PL002** | `WARN` | Executable script without shebang | Recognized script file (`.py`, `.sh`, `.js`, etc.) is marked executable but missing a shebang line. |
| **PL003** | `WARN` | Unexpected executable data/document file | Data, configuration, or documentation file (`.md`, `.yaml`, `.json`, `.toml`, etc.) has executable permission bits set. |
| **PL004** | `ERROR` | World-writable file | Regular repository file has the world/other write bit (`S_IWOTH`, `0o002`) set. |
| **PL005** | `WARN` | Sensitive-looking file has broad permissions | File with a private-key-like name (`id_rsa`, `id_ed25519`, `*.key`, `*private*.pem`) is accessible by group or other users (`0o077`). *Note: This is a conservative filename-based heuristic, not a content scanner.* |
| **PL006** | `ERROR` | Malformed shebang | File begins with `#!` but has a malformed or unusable shebang line (e.g. empty or non-absolute interpreter path). |
| **PL007** | `WARN` | Git executable-bit mismatch | Working-tree owner execute bit differs from the recorded Git staged index mode (`100644` vs `100755`). *Applies only to tracked files in Git repositories.* |
| **PL008** | `ERROR` | Unexpected privilege bits | Regular file has setuid (`S_ISUID`, `0o4000`) or setgid (`S_ISGID`, `0o2000`) permission bits set. |

### Severity Guidelines
- **`ERROR`**: Serious or broken permission state that will likely cause execution failure or security misconfigurations (PL001, PL004, PL006, PL008).
- **`WARN`**: Suspicious or inconsistent permission state that may cause subtle cross-platform or repository issues (PL002, PL003, PL005, PL007).

---

## Exit Codes

PermLint uses explicit exit codes suitable for CI/CD pipelines:

| Exit Code | Meaning | Description |
| :--- | :--- | :--- |
| `0` | **Success** | Scan completed successfully with no permission findings. |
| `1` | **Findings Exist** | Scan completed and one or more permission findings (errors or warnings) were detected. |
| `2` | **Error / Invalid Input** | Invalid target path (nonexistent or a file), scanner error, or runtime failure. |

---

## Supported Platforms & POSIX Limitations

PermLint is designed for POSIX-compliant filesystems (Linux, macOS, BSD).

> **Note on Windows:** Windows filesystems and Git checkouts do not share POSIX permission bit semantics. While PermLint runs on Python across platforms, its permission checks inspect standard POSIX mode bits (`stat.S_IXUSR`, `stat.S_IWOTH`, etc.).

---

## Incomplete Scans

The filesystem does not always cooperate, and a scan that could not look at
something is not a clean scan. PermLint never turns "unknown" into "fine":

- A file whose contents cannot be read produces **no** content-based finding.
  PL001, PL002 and PL006 all decline to conclude anything rather than assert
  that a file it could not open has no shebang.
- Entries that cannot be inspected during traversal are counted.
- PL007 compares working-tree modes against the Git index. When the index is
  unavailable — no `git` on `PATH`, not a repository, or a failed command —
  that is reported as its own state rather than as "no mismatches".

Anything the scan missed is printed under **Scan was incomplete**, including on
runs that found no issues:

```text
✓ 12 files inspected

No issues found.

Scan was incomplete:
  • Git index comparison (PL007) did not run: not a Git repository
  • 1 file could not be read; content checks were skipped for them
```

Programmatically the same information is on `ScanResult.diagnostics`
(`git_index_status`, `entries_skipped`, `files_unreadable`, `is_complete`).

---

## Using PermLint as a Library

```python
from pathlib import Path
from permlint.scanner import InvalidTargetError, Scanner

try:
    result = Scanner().scan(Path("some/repository"))
except InvalidTargetError as exc:
    ...  # missing path, not a directory, or unreadable directory

for finding in result.findings:
    print(finding.check_id, finding.path, finding.message)
```

`Scanner.scan()` validates its own target and raises `InvalidTargetError`
rather than returning an empty result. The CLI does not validate separately, so
the library and the command line cannot disagree about what a valid target is.

---

## What This Guarantees

- **No file modifications.** PermLint is read-only and never alters file modes.
- **No target code execution.** Discovered files and shebang interpreters are
  never executed, imported, or evaluated.
- **Bounded I/O.** Shebang and binary heuristics read only the first chunk of a
  file (≤ 1024 bytes); nothing reads a file whole.
- **No shell.** Git metadata is collected with an explicit argument array, a
  fixed timeout, and `shell=False`.
- **No symlink following.** Traversal does not follow file or directory
  symlinks.

Each of these is covered by tests in `tests/` — see `test_traversal.py` and
`test_scan_integrity.py` in particular.

---

## Development & Quality Assurance

```bash
# Run test suite
python -m pytest

# Run Ruff linter and formatting checks
ruff check .
ruff format --check .
```

---

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for development workflows and check guidelines.

---

## License

PermLint is licensed under the [MIT License](LICENSE).
