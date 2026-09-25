# Changelog

## 0.2.0

- Compare Unix owner-execute permissions with the Git index and show both states in findings.
- Preview and apply conservative executable-bit repairs to files and, for tracked files, Git index metadata without staging file contents.
- Verify staged content and index flags before Git mode repairs; leave ambiguous intent, nested repositories, and changing files for manual review.
- Add explicit project configuration, rule explanations, JSON and SARIF reports, and scan/fix CLI commands while retaining bare scans.
- Add compact summary output for large scans and distinguish incomplete scans from policy findings in exit codes.
- Scan full source trees unless paths are explicitly excluded, and build both wheel and source distributions in CI.

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
