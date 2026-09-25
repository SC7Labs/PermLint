# PermLint

**Audit what a Unix file can do, what Git will commit, and which executable-bit mistakes can be repaired safely.**

PermLint is a command-line permission auditor for source trees. A script can run on your machine while Git still records it as non-executable; a data file can carry an accidental execute bit into a commit. PermLint compares the working tree with the Git index, checks file evidence such as shebangs and known data formats, and offers a preview before changing anything.

PermLint focuses on permission correctness and repository hygiene. It does not run discovered files, inspect secrets, or claim to find every security problem.

## Install

Python 3.12 or newer and a POSIX filesystem are required. Version 0.2.0 is available from this source checkout; there is no published PyPI package or automatic update channel yet.

~~~sh
python -m venv .venv
. .venv/bin/activate
python -m pip install .
permlint --version
~~~

A `.venv` inside the scan root is scanned by default. Add `.venv/**` to the project's exclusions if you want to omit it.

To update an installation from a local 0.2.0 wheel:

~~~sh
python -m pip install --upgrade build
python -m build
python -m pip install --upgrade dist/permlint-0.2.0-py3-none-any.whl
~~~

The installed command is a copy of the package. Editing a checkout does not update an existing non-editable installation. For development, use `python -m pip install -e ".[dev]"`. The `permlint upgrade` command exits 2 with installation guidance; it does not download or execute remote code.

## Start here

Run these commands from the directory you want to inspect:

~~~sh
permlint                         # scan the current directory
permlint /path/to/repository     # legacy positional form
permlint scan /path/to/repository
permlint scan --summary /path/to/repository  # compact counts for large trees
permlint fix --dry-run           # preview deterministic repairs
permlint fix                     # apply them
permlint explain PL007           # understand a rule
~~~

A targeted repair can be requested with `permlint fix scripts/deploy.sh`. Run `permlint -h` or `permlint --help` for the complete command reference.

A dry run prints the proposed filesystem and Git index modes and leaves both unchanged. The apply command rechecks file and index state before each repair. It reports files that changed, files that need manual review, and any operation that failed. Review staged mode changes with `git diff --cached --summary` before committing.

## Why the Git index matters

Git stores regular tracked files as mode `100644` or `100755`; the distinction follows the **owner execute bit**. It does not store every Unix read/write permission. PermLint compares that index state with the filesystem and with evidence about the file's purpose.

| Evidence | What PermLint reports |
| --- | --- |
| Valid shebang, no owner execute bit | PL001: the script looks runnable but cannot be executed directly |
| Filesystem owner execute bit differs from Git | PL007: the checkout and the next commit disagree |
| Known data or documentation format has execute bits | PL003: execution is unexpected |
| Executable script has no shebang | PL002: possible portability issue; intent needs review |

Tracked files use both filesystem and index information. Untracked files still receive filesystem checks, and ordinary non-Git directories are valid scan targets. A mismatch alone does not reveal which side is correct, so PermLint leaves ambiguous cases for manual review.

PermLint scans the requested tree, including large vendored or upstream directories. Only version-control metadata directories (`.git`, `.hg`, `.svn`) are skipped automatically. Use explicit exclusions for project-specific generated trees.

## Repairs and safety

Automatic repairs are deliberately narrow:

| Strong evidence | Filesystem action | Tracked Git action |
| --- | --- | --- |
| Valid shebang script should be executable | Add owner execute bit | Set index mode to 100755 |
| Known text/data/document format is executable, has no shebang, and is readable non-binary content | Remove execute bits | Set index mode to 100644 |

If the filesystem or index already has the expected state, only the other side changes. For an untracked file or non-Git directory, only the filesystem changes. Tracked repairs update an alternate index under Git's index lock, preserve the staged blob IDs, and replace the index atomically. They do not stage file contents, unrelated changes, or a commit.

A bare mismatch with no strong intent evidence, an unreadable or changing file, a symlink, a multiply linked file, an unmerged Git entry, or an unexpected file type is not an automatic repair. Before changing a tracked index mode, PermLint also checks that the staged blob supports the same executable intent as the working file. Entries with special Git index flags and files inside nested repositories need manual review. Findings about world-writable files, sensitive-looking names, malformed shebangs, and privilege bits remain review items. Filesystem repairs stay inside the requested root; a tracked repair also updates the containing repository's Git index. State is rechecked when applying each repair.

## Rules

| Rule | Default severity | Meaning |
| --- | --- | --- |
| PL001 | Error | Valid shebang without owner execute permission |
| PL002 | Warning | Executable script-like text without a shebang |
| PL003 | Warning | Executable data or documentation file |
| PL004 | Error | World-writable regular file |
| PL005 | Warning | Sensitive-looking filename with broad permissions |
| PL006 | Error | Malformed shebang |
| PL007 | Warning | Working-tree owner execute bit differs from Git index |
| PL008 | Error | Setuid or setgid bit on a regular file |

Use `permlint explain PL001` for trigger conditions, rationale, repair policy, and edge cases. Filename and extension checks are heuristics: a `.py` suffix alone does not prove that a file should be executable.

## Configuration

Put `.permlint.toml` at the scan root, or provide a file with `--config`:

~~~toml
exclude = [".venv/**", "node_modules/**", "generated/**"]
disabled_rules = ["PL002"]
fail_on = "warning"
fix_git_index = true

[severity_overrides]
PL007 = "error"
~~~

Exclusions are explicit glob patterns. A pattern with a slash is rooted at the scan directory; a bare name or pattern matches a path segment at any depth. For example, `generated/**` prunes that root-level tree, while `*.secret` matches files with that suffix anywhere. These are PermLint patterns, not Git ignore rules. A relative `--config FILE` path is resolved from the scan root. Disabling a rule removes its findings; a severity override changes the level used in reports and policy evaluation. Set `fail_on = "error"` to report warnings without making them fail CI. Set `fix_git_index = false` to prevent the fixer from changing tracked Git metadata. Unknown or malformed configuration is an error, not a silent fallback.

## CI and machine output

Text is the default. It lists every finding; `--summary` gives a compact rule breakdown and diagnostics for large trees without changing the scan or exit code. JSON is deterministic and suitable for scripts; SARIF 2.1.0 has file-level locations and rule descriptions for code scanning:

~~~sh
permlint scan --format json . > permlint.json
permlint scan --format sarif . > permlint.sarif
~~~

JSON schema version 1 contains `tool`, `target`, `summary`, `diagnostics`, and `findings`. The `target` is the absolute scan path, so documents from different checkouts need not be byte-identical. The summary includes scanned-file, error, warning, available-fix, manual-review, completion, and exit-code fields. Each finding includes its rule ID, relative path, severity, message, filesystem and Git modes when applicable, and whether an automatic fix is available. No timestamps or host-specific ordering are added.

A CI step can simply run `permlint scan .`; nonzero status fails the step. If you need to upload SARIF even when findings exist, preserve the command's exit status while uploading the generated file.

| Exit | Meaning |
| --- | --- |
| 0 | Complete scan; no findings at or above the configured failure threshold |
| 1 | Complete scan; policy findings remain |
| 2 | Invalid input, configuration/runtime error, or incomplete scan |

An incomplete scan is never presented as clean. Unreadable files or directories and unavailable Git index data where Git applies are reported in diagnostics. A non-Git directory has no index to compare and is not incomplete for that reason.

## Limits and development

PermLint is designed for POSIX permission bits on Linux, macOS, and similar systems. Windows ACLs and cross-platform checkout mode behavior are outside its scope. Git's index records the execute distinction, not full `chmod` modes. Permissions can change concurrently, so the fixer rechecks state and reports failures instead of claiming a repair it could not complete.

For development and release checks:

~~~sh
python -m pip install -e ".[dev]"
python -m pytest
ruff check .
ruff format --check .
python -m build
~~~

See [CONTRIBUTING.md](CONTRIBUTING.md) for change guidelines and [real-world validation](docs/real-world-validation.md) for large-tree results. PermLint is licensed under [MIT](LICENSE).
