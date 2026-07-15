"""Tests for the per-host SSH keypair generation script.

WHY THIS FILE EXISTS
    `home/.chezmoiscripts/20/run_before_generate-ssh-key.unix-like.sh` replaced a
    `modify_` script that inferred "generate a new key" from EMPTY STDIN and so
    destroyed an intact keypair under disk-full/ENOSPC (2026-06-26 incident).
    These tests are the executable spec for the replacement's guarantees:
      - generate exactly once when the key is absent;
      - NEVER regenerate or modify an existing key (the regression that bit us);
      - always keep id_ed25519.pub derived from the private key (atomic, no drift);
      - be idempotent across runs.

WHY SUBPROCESS TESTS
    The artifact is a standalone bash script keyed off $HOME. We run it as a real
    user would, in a throwaway $HOME, and assert on the resulting files.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANAGED_ROOT = REPO_ROOT / "home"
SCRIPT = (
    MANAGED_ROOT / ".chezmoiscripts" / "20" / "run_before_generate-ssh-key.unix-like.sh"
)

_BASH = shutil.which("bash") or "/bin/bash"
_KEYGEN = shutil.which("ssh-keygen")
_SYSTEM_DIRS = ":".join(
    d for d in ["/usr/local/bin", "/usr/bin", "/bin"] if Path(d).is_dir()
)

pytestmark = pytest.mark.skipif(_KEYGEN is None, reason="ssh-keygen not available")


def _run(home: Path) -> subprocess.CompletedProcess:
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        "HOME": str(home),
        "PATH": _SYSTEM_DIRS,
    }
    return subprocess.run([_BASH, str(SCRIPT)], capture_output=True, text=True, env=env)


def _fingerprint(key: Path) -> str:
    assert _KEYGEN is not None
    return subprocess.run(
        [_KEYGEN, "-lf", str(key)], capture_output=True, text=True, check=True
    ).stdout.split()[1]


def _derived_pub_body(key: Path) -> str:
    assert _KEYGEN is not None
    out = subprocess.run(
        [_KEYGEN, "-y", "-f", str(key)], capture_output=True, text=True, check=True
    ).stdout
    return out.split()[1]


def test_generates_when_absent(tmp_path: Path) -> None:
    """No key → a fresh keypair is created with correct perms and matching .pub."""
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr

    key = tmp_path / ".ssh" / "id_ed25519"
    pub = tmp_path / ".ssh" / "id_ed25519.pub"
    assert key.is_file() and pub.is_file()
    assert oct(key.stat().st_mode)[-3:] == "600"
    assert oct(pub.stat().st_mode)[-3:] == "644"
    assert oct((tmp_path / ".ssh").stat().st_mode)[-3:] == "700"
    # .pub matches the private key.
    assert pub.read_text().split()[1] == _derived_pub_body(key)


def test_existing_key_is_never_regenerated(tmp_path: Path) -> None:
    """An existing key is preserved byte-for-byte — the ENOSPC regression guard."""
    assert _KEYGEN is not None
    ssh = tmp_path / ".ssh"
    ssh.mkdir(mode=0o700)
    key = ssh / "id_ed25519"
    subprocess.run(
        [_KEYGEN, "-t", "ed25519", "-N", "", "-C", "orig@host", "-f", str(key), "-q"],
        check=True,
    )
    before_bytes = key.read_bytes()
    before_fp = _fingerprint(key)

    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr

    assert key.read_bytes() == before_bytes, "private key must not change"
    assert _fingerprint(key) == before_fp


def test_repairs_drifted_pub(tmp_path: Path) -> None:
    """A wrong/orphan .pub is repaired to match the private key (the 06-26 damage)."""
    assert _KEYGEN is not None
    ssh = tmp_path / ".ssh"
    ssh.mkdir(mode=0o700)
    key = ssh / "id_ed25519"
    subprocess.run(
        [_KEYGEN, "-t", "ed25519", "-N", "", "-f", str(key), "-q"], check=True
    )
    pub = ssh / "id_ed25519.pub"
    pub.write_text("ssh-ed25519 AAAAorphanbodythatdoesnotmatch wrong@host\n")

    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert pub.read_text().split()[1] == _derived_pub_body(key)


def test_idempotent(tmp_path: Path) -> None:
    """Second run is a no-op: key and .pub unchanged."""
    assert _run(tmp_path).returncode == 0
    key = tmp_path / ".ssh" / "id_ed25519"
    pub = tmp_path / ".ssh" / "id_ed25519.pub"
    key_bytes, pub_text = key.read_bytes(), pub.read_text()

    assert _run(tmp_path).returncode == 0
    assert key.read_bytes() == key_bytes
    assert pub.read_text() == pub_text
