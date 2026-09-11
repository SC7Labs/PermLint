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
- Format code:
  ```bash
  ruff format .
  ```

## Check Architecture & Design

PermLint performs single-pass traversal over the target repository. Checks must remain independent, deterministic, and safe.

### Current v0.1.0 Rules:
- **PL001**: Shebang but not executable (`ERROR`)
- **PL002**: Executable script without shebang (`WARN`)
- **PL003**: Unexpected executable data/document file (`WARN`)
- **PL004**: World-writable file (`ERROR`)
- **PL005**: Sensitive-looking file has broad permissions (`WARN`)
- **PL006**: Malformed shebang (`ERROR`)
- **PL007**: Git executable-bit mismatch (`WARN`)
- **PL008**: Unexpected privilege bits (`ERROR`)

### Check Rules
- Checks must never execute discovered files, invoke interpreters, evaluate text, or modify permissions.
- Checks should be conservative to prevent false positives.
- File reads must be bounded (avoid reading entire large files).
- Subprocesses should not be spawned per file.

## Pull Request Guidelines

- Ensure all existing and new tests pass (`pytest`).
- Ensure code passes `ruff check .` and `ruff format --check .`.
- Keep changes minimal, well-documented, and focused on single objectives.
