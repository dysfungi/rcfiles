"""Integration tests for the chezmoi-sudo wrapper script.

WHY THIS FILE EXISTS
    `~/.local/bin/chezmoi-sudo` (source: `home/dot_local/bin/executable_chezmoi-sudo`)
    provides a three-way fallback for privileged calls in unattended cron runs:
      1. Active sudo credential cache  → plain `sudo`
      2. Interactive TTY               → plain `sudo`
      3. SUDO_ASKPASS set + executable → `sudo -A`
      4. None of the above            → WARN to stderr, exit 0 (skip)
    The script must never block waiting for input.

TRUTH TABLE (branches tested below)
    cached-creds branch: `sudo -n -v` succeeds → exec sudo
    askpass branch:      no cache, no TTY, SUDO_ASKPASS set → exec sudo -A
    skip branch:         no cache, no TTY, no SUDO_ASKPASS  → WARN + exit 0

NOTE: The interactive-TTY branch (branch 2) cannot be reliably tested in a
subprocess harness without a real PTY, so it is not covered here. The other
three branches fully exercise the non-interactive logic.
"""

from __future__ import annotations

import os
import stat
import subprocess
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MANAGED_ROOT = REPO_ROOT / "home"
SCRIPT = MANAGED_ROOT / "dot_local" / "bin" / "executable_chezmoi-sudo"


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _make_stub(bin_dir: Path, name: str, body: str) -> Path:
    p = bin_dir / name
    p.write_text(f"#!/usr/bin/env bash\n{body}\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return p


def _run(
    tmp_path: Path,
    args: list[str],
    *,
    env_overrides: dict | None = None,
) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    env = {
        **_clean_env(),
        "HOME": str(tmp_path),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        **(env_overrides or {}),
    }
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        # Ensure no TTY is attached (simulates unattended cron)
        stdin=subprocess.DEVNULL,
    )


# ── test: cached-creds branch ─────────────────────────────────────────────────


def test_uses_plain_sudo_when_cache_active(tmp_path: Path) -> None:
    """`sudo -n -v` succeeds → forward args to plain `sudo`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "sudo_calls.txt"
    calls.write_text("")

    # sudo stub: -n -v succeeds (cache hit); any other invocation records call
    _make_stub(
        bin_dir,
        "sudo",
        textwrap.dedent(f"""\
        LOG="{calls}"
        if [[ "$1 $2" == "-n -v" ]]; then exit 0; fi
        echo "$@" >> "$LOG"
        exit 0
        """),
    )

    result = _run(tmp_path, ["echo", "hello"])
    assert result.returncode == 0
    assert "echo hello" in calls.read_text(), "expected plain sudo echo hello"
    # Must NOT have called sudo -A
    assert "-A" not in calls.read_text()


# ── test: askpass branch ──────────────────────────────────────────────────────


def test_uses_sudo_askpass_when_no_cache_no_tty(tmp_path: Path) -> None:
    """`sudo -n -v` fails (no cache) + no TTY + SUDO_ASKPASS set → `sudo -A`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "sudo_calls.txt"
    calls.write_text("")

    # sudo stub: -n -v fails (no cache); record all other calls
    _make_stub(
        bin_dir,
        "sudo",
        textwrap.dedent(f"""\
        LOG="{calls}"
        if [[ "$1 $2" == "-n -v" ]]; then exit 1; fi
        echo "$@" >> "$LOG"
        exit 0
        """),
    )

    fake_askpass = bin_dir / "fake-askpass"
    _make_stub(bin_dir, "fake-askpass", "echo 'supersecret'")

    result = _run(
        tmp_path,
        ["pacman", "-Syu"],
        env_overrides={"SUDO_ASKPASS": str(fake_askpass)},
    )
    assert result.returncode == 0, f"script failed:\n{result.stderr}"

    recorded = calls.read_text()
    assert "-A" in recorded, f"expected sudo -A, got:\n{recorded}"
    assert "pacman" in recorded


# ── test: skip branch ─────────────────────────────────────────────────────────


def test_warns_and_skips_when_no_askpass(tmp_path: Path) -> None:
    """No cache, no TTY, no SUDO_ASKPASS → WARN to stderr, exit 0."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    # sudo stub: -n -v always fails
    _make_stub(bin_dir, "sudo", 'if [[ "$1 $2" == "-n -v" ]]; then exit 1; fi; exit 0')

    result = _run(
        tmp_path,
        ["pacman", "-Syu"],
        env_overrides={"SUDO_ASKPASS": ""},  # explicitly empty
    )
    assert result.returncode == 0, (
        f"expected exit 0 (skip), got {result.returncode}:\n{result.stderr}"
    )
    assert "WARN" in result.stderr, f"expected WARN in stderr:\n{result.stderr}"
    assert "chezmoi-sudo" in result.stderr


def test_warns_and_skips_when_askpass_not_executable(tmp_path: Path) -> None:
    """SUDO_ASKPASS set but not executable → same as absent."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    _make_stub(bin_dir, "sudo", 'if [[ "$1 $2" == "-n -v" ]]; then exit 1; fi; exit 0')

    not_exec = tmp_path / "not-executable-askpass"
    not_exec.write_text("#!/usr/bin/env bash\necho secret")
    # Do NOT chmod +x → not executable

    result = _run(
        tmp_path,
        ["pacman", "-Syu"],
        env_overrides={"SUDO_ASKPASS": str(not_exec)},
    )
    assert result.returncode == 0
    assert "WARN" in result.stderr
