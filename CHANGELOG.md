# Changelog

## 0.1.1

- PL007 now compares the working-tree owner execute bit with the Git index, avoiding incorrect results when only group or other execute is set.

## 0.1.0

- Initial PermLint foundation and rule set.
- PL001: Shebang without executable permission.
- PL002: Executable script without shebang.
- PL003: Unexpected executable data/document file.
- PL004: World-writable file.
- PL005: Sensitive-looking file with broad permissions.
- PL006: Malformed shebang.
- PL007: Git executable-bit mismatch.
- PL008: Unexpected setuid/setgid privilege bits.
- Fixed PL006 false positives on Rust inner attributes beginning with `#![`.
