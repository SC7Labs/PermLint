# Real-World Validation: Large Multi-Repository Corpus

## Corpus Overview

- **Corpus**: Large local multi-repository validation corpus
- **Composition**: Mixed historical and open-source source trees
- **Files inspected**: 37,503

## Pre-Fix Baseline

Prior to the fix, scanning the corpus produced:

- **Files inspected**: 37,503
- **Errors**: 675
- **Warnings**: 28
- **Total findings**: 703

### Root Cause Discovered

Rust inner-attribute syntax at the crate/module root:
```rust
#![allow(dead_code)]
#![cfg_attr(...)]
#![feature(...)]
```
Because these lines begin with `#!`, PermLint treated them as candidate shebangs. When parsing the attribute expression as an interpreter path, PermLint noted the missing leading `/` and emitted false-positive **PL006** (`Malformed shebang`) errors.

### Fix Applied

Lines beginning with `#![` are excluded from being treated as shebang candidates. The fix is strictly surgical:
- Does not broadly disable PL006 for `.rs` files.
- Actual malformed shebangs in Rust files (e.g. `#!rust-script`) continue to trigger PL006.
- Valid shebangs (e.g. `#!/usr/bin/env rust-script`) retain existing behavior (clean when executable, PL001 when non-executable).
- Existing PL001 and PL002 behavior is fully preserved.

## Regression Verification

- **Automated test suite**: 180 passed in pytest.
- **Linters/Formatters**: Ruff check and Ruff format checks clean.
- **Manual smoke test**: Clean reproduction with single Rust file returns 0 findings and exit code 0.

## Post-Fix Validation Results

Re-scanning the exact same 37,503-file corpus yielded:

- **Files inspected**: 37,503
- **Errors**: 413
- **Warnings**: 28
- **Total findings**: 441

### Conclusion

- Exactly **262 false-positive errors disappeared** (all PL006 false positives removed).
- Warnings stayed completely unchanged (28).
- Post-fix corpus scan contained zero PL006 findings.
- No additional systematic false-positive class was confirmed during the focused investigation. The remaining findings were not exhaustively validated individually; many are consistent with executable metadata being lost or altered during repository copying/harvesting.
