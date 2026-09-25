# Real-World Validation

## PermLint 0.2.0 — TitanBank scan

The 0.2.0 wheel was installed in an isolated environment and used to scan the local TitanBank source corpus in **scan mode only**. No repair command was run on TitanBank.

| Measure | Result |
| --- | ---: |
| Files inspected | 38,371 |
| Errors / warnings | 413 / 28 |
| Total findings | 441 |
| By rule | PL001: 413; PL002: 23; PL003: 5 |
| Proposed safe repairs / manual review | 418 / 23 |
| Scan completeness | Complete |
| Git index | Not applicable: TitanBank is not a Git repository |

The 0.1.1 scanner had inspected 37,503 files on this corpus. Version 0.2.0 inspects 868 more because dependency, vendor, build, and cache trees are no longer silently excluded by name. Its finding totals are unchanged on this corpus. The Git-aware checks cannot add findings here because the target has no Git index; real temporary Git repositories provide the Git-specific validation.

One final-wheel JSON run took 15.06 seconds and wrote 238 KB. A subsequent compact summary took 2.80 seconds and showed the same counts in 16 lines. A later full text run took 3.77 seconds, wrote 151 KB, and occupied 3,931 lines. These are local observations that include scan and repair-plan construction, not a cross-machine benchmark. The default report remains untruncated.

In a separate synthetic Git repository with 1,000 tracked non-executable shebang scripts, the installed wheel's `scan --summary` found 1,000 PL001 issues and 1,000 proposed repairs in 0.27 seconds. Staged blob headers were read in bounded batches rather than by starting one Git process per file. This flat test is a throughput check, not a substitute for the mixed TitanBank corpus.

## PermLint 0.2.0 — disposable Git repair demonstration

A temporary Git repository committed a baseline with a valid shebang script recorded as 100644 with filesystem mode 0644, plus a Markdown file recorded as 100755 with filesystem mode 0755. The installed wheel's bare command found PL001 and PL003. `permlint fix --dry-run` proposed two repairs and left file contents, modes, and `.git/index` bytes unchanged. `permlint fix` changed the script to filesystem 0744 / Git 100755 and the Markdown file to filesystem 0644 / Git 100644. `git diff --cached --summary` showed only the two intended mode changes, `git diff --summary` was empty, and a rescan exited 0 with no findings. JSON parsed successfully and SARIF validated against the official OASIS 2.1.0 schema.

A second temporary Git repository tested a pure index mismatch. Both a shebang script and a plain extensionless file were staged as 100644, then given owner execute bits on disk. Both produced PL007 with filesystem and Git modes shown. The script's shebang justified a Git-only 100755 repair; the extensionless file remained a manual-review warning. After `permlint fix`, `git diff --cached --summary` showed only the script's mode change, while the extensionless file remained an unstaged mode difference. The command exited 1 because that warning remained.

## Earlier corpus investigation (0.1.1)

### Corpus overview

- **Corpus**: Large local multi-repository validation corpus
- **Composition**: Mixed historical and open-source source trees
- **Files inspected**: 37,503

### Before the 0.1.1 fix

Prior to the fix, scanning the corpus produced:

- **Files inspected**: 37,503
- **Errors**: 675
- **Warnings**: 28
- **Total findings**: 703

#### Root cause

Rust inner-attribute syntax at the crate/module root:
```rust
#![allow(dead_code)]
#![cfg_attr(...)]
#![feature(...)]
```
Because these lines begin with `#!`, PermLint treated them as candidate shebangs. When parsing the attribute expression as an interpreter path, PermLint noted the missing leading `/` and emitted false-positive **PL006** (`Malformed shebang`) errors.

#### Fix applied

Lines beginning with `#![` are excluded from being treated as shebang candidates. The fix is strictly surgical:
- Does not broadly disable PL006 for `.rs` files.
- Actual malformed shebangs in Rust files (e.g. `#!rust-script`) continue to trigger PL006.
- Valid shebangs (e.g. `#!/usr/bin/env rust-script`) retain existing behavior (clean when executable, PL001 when non-executable).
- Existing PL001 and PL002 behavior is fully preserved.

### Regression verification

- **Automated test suite**: 180 passed in pytest.
- **Linters/Formatters**: Ruff check and Ruff format checks clean.
- **Manual smoke test**: Clean reproduction with single Rust file returns 0 findings and exit code 0.

### Results after the 0.1.1 fix

Re-scanning the exact same 37,503-file corpus yielded:

- **Files inspected**: 37,503
- **Errors**: 413
- **Warnings**: 28
- **Total findings**: 441

#### Conclusion

- Exactly **262 false-positive errors disappeared** (all PL006 false positives removed).
- Warnings stayed completely unchanged (28).
- Post-fix corpus scan contained zero PL006 findings.
- No additional systematic false-positive class was confirmed during the focused investigation. The remaining findings were not exhaustively validated individually; many are consistent with executable metadata being lost or altered during repository copying/harvesting.
