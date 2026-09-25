# Contributing to PermLint

Thank you for your interest in contributing to PermLint!

## Development Setup

1. Clone this repository and change into it.

2. Create a virtual environment and install the development dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```

## Development Commands

- Run unit and integration tests:
  ```bash
  python -m pytest
  ```
- Run Ruff linter:
  ```bash
  ruff check .
  ```
- Check code formatting:
  ```bash
  ruff format --check .
  ```
- Build wheel and source distribution:
  ```bash
  python -m build
  ```
- Format code:
  ```bash
  ruff format .
  ```

## Check Architecture & Design

PermLint performs a single filesystem traversal and reads Git index metadata in bulk. Checks must remain independent, deterministic, and safe. The repair engine has a separate planning step; previews must never mutate files or the index.

### Current Rules:
- **PL001**: Shebang but not executable (`ERROR`)
- **PL002**: Executable script without shebang (`WARN`)
- **PL003**: Unexpected executable data/document file (`WARN`)
- **PL004**: World-writable file (`ERROR`)
- **PL005**: Sensitive-looking file has broad permissions (`WARN`)
- **PL006**: Malformed shebang (`ERROR`)
- **PL007**: Git executable-bit mismatch (`WARN`)
- **PL008**: Unexpected privilege bits (`ERROR`)

### Check Rules
- Checks must never execute discovered files, invoke interpreters, or evaluate text.
- Checks should be conservative to prevent false positives.
- File reads must be bounded (avoid reading entire large files).
- Scans should collect Git index data in bulk rather than spawn a subprocess per inspected file. The fixer may recheck each proposed repair.
- Repairs must be limited to deterministic executable-bit changes, recheck file and Git state before applying, and never stage file contents or create commits.

## Pull Request Guidelines

- Ensure all existing and new tests pass (`pytest`).
- Ensure code passes `ruff check .` and `ruff format --check .`.
- Exercise any repair change against a real temporary Git repository, including a dry run and staged-content preservation.
- Keep changes minimal, well-documented, and focused on single objectives.
