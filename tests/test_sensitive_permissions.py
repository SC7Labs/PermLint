"""Tests for PL005: Sensitive-looking file has broad permissions."""

from __future__ import annotations

from pathlib import Path

import pytest

from permlint.checks.sensitive_permissions import SensitiveFilePermissionsCheck
from permlint.filesystem import FileInfo
from permlint.models import Severity


def make_file_info(path: Path, mode: int) -> FileInfo:
    path.chmod(mode)
    return FileInfo(path=path, rel_path=Path(path.name), mode=mode)


@pytest.mark.parametrize("mode", [0o600, 0o400, 0o700])
def test_sensitive_files_with_owner_only_permissions_clean(tmp_path: Path, mode: int) -> None:
    check = SensitiveFilePermissionsCheck()

    f1 = tmp_path / "id_ed25519"
    f1.write_text("private key data\n")
    assert check.inspect(make_file_info(f1, mode)) is None

    f2 = tmp_path / "server.key"
    f2.write_text("key data\n")
    assert check.inspect(make_file_info(f2, mode)) is None

    f3 = tmp_path / "server-private.pem"
    f3.write_text("pem data\n")
    assert check.inspect(make_file_info(f3, mode)) is None


@pytest.mark.parametrize(
    "filename",
    [
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "app.key",
        "server-private.pem",
        "privkey.pem",
        "server.key.pem",
    ],
)
@pytest.mark.parametrize("mode", [0o644, 0o640, 0o660, 0o755])
def test_sensitive_files_with_broad_permissions_warn(
    tmp_path: Path, filename: str, mode: int
) -> None:
    check = SensitiveFilePermissionsCheck()

    f = tmp_path / filename
    f.write_text("dummy key\n")
    info = make_file_info(f, mode)
    finding = check.inspect(info)

    assert finding is not None
    assert finding.check_id == "PL005"
    assert finding.severity == Severity.WARNING
    assert finding.message == "Sensitive-looking file is accessible by group or other users"


def test_public_key_and_cert_files_never_flagged(tmp_path: Path) -> None:
    check = SensitiveFilePermissionsCheck()

    f1 = tmp_path / "id_rsa.pub"
    f1.write_text("ssh-rsa ...\n")
    assert check.inspect(make_file_info(f1, 0o644)) is None

    f2 = tmp_path / "id_ed25519.pub"
    f2.write_text("ssh-ed25519 ...\n")
    assert check.inspect(make_file_info(f2, 0o644)) is None

    f3 = tmp_path / "certificate.pem"
    f3.write_text("-----BEGIN CERTIFICATE-----\n")
    assert check.inspect(make_file_info(f3, 0o644)) is None

    f4 = tmp_path / "public.pem"
    f4.write_text("-----BEGIN PUBLIC KEY-----\n")
    assert check.inspect(make_file_info(f4, 0o644)) is None

    f5 = tmp_path / "README.key-format.md"
    f5.write_text("Documentation\n")
    assert check.inspect(make_file_info(f5, 0o644)) is None

    f6 = tmp_path / "cert.pem"
    f6.write_text("-----BEGIN CERTIFICATE-----\n")
    assert check.inspect(make_file_info(f6, 0o644)) is None

    f7 = tmp_path / "fullchain.pem"
    f7.write_text("-----BEGIN CERTIFICATE-----\n")
    assert check.inspect(make_file_info(f7, 0o644)) is None

    f8 = tmp_path / "chain.pem"
    f8.write_text("-----BEGIN CERTIFICATE-----\n")
    assert check.inspect(make_file_info(f8, 0o644)) is None
