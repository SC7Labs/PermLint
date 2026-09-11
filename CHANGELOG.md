# Changelog

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
