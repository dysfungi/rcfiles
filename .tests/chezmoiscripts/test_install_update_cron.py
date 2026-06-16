"""Integration tests for the stage-90 cron install script.

WHY THIS FILE EXISTS
    `.chezmoiscripts/90/run_onchange_after_install-update-cron.unix-like.sh.tmpl`
    must register a managed cron block idempotently, never clobber unrelated entries,
    skip gracefully when crontab is absent, and enable the cronie daemon on Linux.
    These properties are non-trivial enough to warrant an executable spec.

WHY SUBPROCESS TESTS
    The script is tested as a black box via `bash $SCRIPT`. Stubs on PATH replace
    `crontab` and `systemctl` so no real cron state is touched. This matches the
    repo testing convention (real inputs/outputs, adapt harness to production shape).

TRUTH TABLE
    Each parametrized case covers one distinct scenario the script must handle:
    1. fresh install (no existing crontab)   → managed block added
    2. idempotent re-install                  → only one block in result
    3. pre-existing unrelated entries         → those entries preserved
    4. crontab absent from PATH               → WARN + exit 0 (skip)
    5. Linux with systemctl present           → systemctl enable --now cronie called
    6. cronie already enabled                 → systemctl enable NOT called again
    7. systemctl absent (macOS-like)          → succeeds without cronie step

CROSS-PLATFORM PATH STRATEGY
    Tests need system coreutils (cat, awk, cksum, hostname, mkdir, printf) but
    must shadow `crontab` and `systemctl` with stubs. Solution: put tmp_path/bin
    first in PATH, followed by a curated set of real system dirs, then add stubs
    for only `crontab`, `systemctl`, and `chezmoi-sudo`.

    This avoids two problems that arose from previous approaches:
    - Fully isolated PATH (bin only): stubs lack access to `cat`, `grep`, etc.
    - Omitting systemctl stub when /usr/bin is on PATH: the real systemctl on
      GitHub Actions returns "Interactive authentication required" → exit 1.

    The rule: always stub `crontab`, `chezmoi-sudo`, and `systemctl`.
    Tests that want a tool "absent" omit its stub AND also stub it to fail
    (for systemctl: simply don't add the stub; it won't be found on PATH since
    the system dir is excluded when we use _system_path() without it).

    _system_path() returns the real system dirs needed for coreutils, excluding
    any directory that contains a conflicting real tool (crontab, systemctl).
    Since these live in /usr/bin on Linux and /usr/sbin on macOS, we must
    include /usr/bin (for awk/cat/etc.) and rely on stub precedence to shadow
    them — the stub dir is always first.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO_ROOT
    / ".chezmoiscripts"
    / "90"
    / "run_onchange_after_install-update-cron.unix-like.sh.tmpl"
)

_BASH = shutil.which("bash") or "/bin/bash"

# Real system dirs needed for coreutils. Stubs in tmp/bin shadow any conflicting
# tools (crontab, systemctl) since tmp/bin is always first in PATH.
_SYSTEM_DIRS = ":".join(
    d for d in ["/usr/local/bin", "/usr/bin", "/bin"] if Path(d).is_dir()
)


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _make_stub(bin_dir: Path, name: str, body: str) -> Path:
    """Write an executable shell stub to bin_dir."""
    p = bin_dir / name
    p.write_text(f"#!{_BASH}\n{body}\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return p


def _make_base_stubs(bin_dir: Path) -> None:
    """Add stubs for tools the script invokes that must not touch real state.

    - crontab: must be stubbed to avoid touching the real user crontab
    - chezmoi-sudo: delegates to its args (so systemctl stub works)
    - systemctl (no-op): prevents the real systemctl from requiring auth.
      Tests that specifically test systemctl behavior replace this with a
      recording stub via _make_fake_systemctl().
    """
    bin_dir.mkdir(exist_ok=True)
    # Stub crontab with a no-op initial state; callers may replace via _make_fake_crontab.
    _make_stub(bin_dir, "crontab", "exit 1")
    _make_stub(bin_dir, "chezmoi-sudo", 'exec "$@"')
    # Default systemctl stub: cronie already enabled → no enable call, exits 0.
    _make_stub(
        bin_dir,
        "systemctl",
        "if [[ \"$1\" == 'is-enabled' ]]; then exit 0; fi\nexit 0",
    )


def _make_fake_crontab(
    bin_dir: Path, state_file: Path, initial_entries: str = ""
) -> None:
    """Write a crontab stub that reads/writes state_file."""
    state_file.write_text(initial_entries)
    _make_stub(
        bin_dir,
        "crontab",
        textwrap.dedent(f"""\
        STATE="{state_file}"
        if [[ "$1" == "-l" ]]; then
            cat "$STATE" 2>/dev/null || exit 1
        elif [[ "$1" == "-" ]]; then
            cat > "$STATE"
        else
            echo >&2 "crontab stub: unknown arg $1"; exit 1
        fi
        """),
    )


def _make_recording_systemctl(
    bin_dir: Path, calls_log: Path, initial_enabled: bool = False
) -> None:
    """Write a systemctl stub that records calls and simulates enabled state."""
    calls_log.write_text("")
    _make_stub(
        bin_dir,
        "systemctl",
        textwrap.dedent(f"""\
        LOG="{calls_log}"
        echo "$@" >> "$LOG"
        if [[ "$1" == "is-enabled" ]]; then
            {"exit 0" if initial_enabled else "exit 1"}
        fi
        exit 0
        """),
    )


def _run_script(
    tmp_path: Path,
    env_overrides: dict | None = None,
) -> subprocess.CompletedProcess:
    """Run the install-update-cron script.

    PATH: tmp_path/bin first (stubs shadow system tools), then real system dirs
    for coreutils. The stubs for crontab and systemctl always take precedence.
    """
    bin_dir = str(tmp_path / "bin")
    env = {
        **_clean_env(),
        "HOME": str(tmp_path),
        "PATH": f"{bin_dir}:{_SYSTEM_DIRS}",
        **(env_overrides or {}),
    }
    return subprocess.run(
        [_BASH, str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
    )


# ── parametrized truth table ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "initial_crontab,expected_block_count,expect_unrelated_preserved",
    [
        pytest.param("", 1, False, id="fresh-install"),
        pytest.param(
            "# >>> chezmoi-update >>>\n30 12 * * * old-line\n# <<< chezmoi-update <<<\n",
            1,
            False,
            id="idempotent-reinstall",
        ),
        pytest.param(
            "7 3 * * * /other/task\n",
            1,
            True,
            id="preserves-unrelated-entries",
        ),
        pytest.param(
            "7 3 * * * /other/task\n# >>> chezmoi-update >>>\n30 12 * * * old-line\n# <<< chezmoi-update <<<\n",
            1,
            True,
            id="idempotent-with-unrelated",
        ),
    ],
)
def test_cron_block_install(
    tmp_path: Path,
    initial_crontab: str,
    expected_block_count: int,
    expect_unrelated_preserved: bool,
) -> None:
    """Managed block is installed/replaced correctly without clobbering other entries."""
    bin_dir = tmp_path / "bin"
    _make_base_stubs(bin_dir)
    crontab_state = tmp_path / "crontab_state.txt"
    _make_fake_crontab(bin_dir, crontab_state, initial_entries=initial_crontab)

    result = _run_script(tmp_path)
    assert result.returncode == 0, f"script failed:\n{result.stderr}"

    final = crontab_state.read_text()
    assert final.count("# >>> chezmoi-update >>>") == expected_block_count
    assert final.count("# <<< chezmoi-update <<<") == expected_block_count
    assert "chezmoi-update-cron" in final

    if expect_unrelated_preserved:
        assert "/other/task" in final, "unrelated crontab entry was clobbered"


@pytest.mark.skipif(
    shutil.which("crontab") is not None,
    reason="system crontab is on PATH; cannot simulate absence without excluding /usr/bin",
)
def test_skip_when_crontab_absent(tmp_path: Path) -> None:
    """When crontab is not on PATH, script emits WARN and exits 0.

    Skipped on machines where a system crontab is installed (macOS, Ubuntu runner
    with cron) because we cannot reliably hide /usr/bin/crontab while keeping
    coreutils accessible. This scenario is exercised on Arch Linux containers
    where cron is not installed by default.
    """
    bin_dir = tmp_path / "bin"
    _make_base_stubs(bin_dir)
    # Remove the default stub so command -v crontab fails
    (bin_dir / "crontab").unlink()

    result = _run_script(tmp_path)
    assert result.returncode == 0
    assert "WARNING" in result.stderr or "WARNING" in result.stdout


def test_enables_cronie_on_linux(tmp_path: Path) -> None:
    """On Linux (systemctl available, cronie not yet enabled), script enables cronie."""
    bin_dir = tmp_path / "bin"
    _make_base_stubs(bin_dir)
    crontab_state = tmp_path / "crontab_state.txt"
    _make_fake_crontab(bin_dir, crontab_state)
    calls_log = tmp_path / "systemctl_calls.txt"
    _make_recording_systemctl(bin_dir, calls_log, initial_enabled=False)

    result = _run_script(tmp_path)
    assert result.returncode == 0, f"script failed:\n{result.stderr}"

    calls = calls_log.read_text()
    assert "enable --now cronie" in calls, (
        f"expected systemctl enable --now cronie call, got:\n{calls}"
    )


def test_skips_cronie_when_already_enabled(tmp_path: Path) -> None:
    """When cronie is already enabled, systemctl enable is not called again."""
    bin_dir = tmp_path / "bin"
    _make_base_stubs(bin_dir)
    crontab_state = tmp_path / "crontab_state.txt"
    _make_fake_crontab(bin_dir, crontab_state)
    calls_log = tmp_path / "systemctl_calls.txt"
    _make_recording_systemctl(bin_dir, calls_log, initial_enabled=True)

    result = _run_script(tmp_path)
    assert result.returncode == 0, f"script failed:\n{result.stderr}"

    calls = calls_log.read_text()
    assert "enable --now cronie" not in calls, (
        "systemctl enable called when cronie was already enabled"
    )


def test_no_cronie_without_systemctl(tmp_path: Path) -> None:
    """When systemctl is absent (macOS-like), script succeeds without cronie step."""
    bin_dir = tmp_path / "bin"
    _make_base_stubs(bin_dir)
    crontab_state = tmp_path / "crontab_state.txt"
    _make_fake_crontab(bin_dir, crontab_state)
    # Remove the default systemctl stub → command -v systemctl fails → cronie skipped.
    (bin_dir / "systemctl").unlink()

    result = _run_script(tmp_path)
    assert result.returncode == 0, f"script failed:\n{result.stderr}"
    assert "chezmoi-update-cron" in crontab_state.read_text()
