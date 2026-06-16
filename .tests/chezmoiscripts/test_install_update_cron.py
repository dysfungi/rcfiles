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

HERMETIC PATH STRATEGY
    Tests run with PATH set to exactly tmp_path/bin — nothing else. This makes
    "tool absent" a genuine property: unlink() the stub and command -v fails,
    with no real system binary to leak in from /usr/bin.

    The few real coreutils the script (and its stubs) need are symlinked into
    bin_dir by _link_real_tools():
      - awk, cksum, hostname — used directly by the script
      - cat — used inside the _make_fake_crontab stub

    Everything else is either a bash builtin (echo, printf, [[]], $(( ))) or a
    stub (crontab, chezmoi-sudo, systemctl). bash itself is referenced by
    absolute path in stub shebangs, so it needs no PATH entry.

    Why hermetic over prepend-and-shadow: if PATH includes /usr/bin, removing a
    stub from bin_dir does not simulate absence — `command -v systemctl` still
    resolves the real /usr/bin/systemctl. On Linux CI this triggers polkit auth
    failure and a spurious exit 1. The hermetic model eliminates this class of
    leaks permanently.
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

# Real coreutils the script (and stubs) need on PATH. Symlinked into bin_dir
# by _link_real_tools() so the subprocess PATH stays fully hermetic (bin_dir only).
#   awk, cksum, hostname — used directly by the cron-install script
#   cat — used inside the _make_fake_crontab stub
_REAL_TOOLS = ("awk", "cksum", "hostname", "cat")


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _link_real_tools(bin_dir: Path) -> None:
    """Symlink real coreutils from _REAL_TOOLS into bin_dir.

    Called by _make_base_stubs so every test gets the hermetic toolset.
    Fails loudly if a tool isn't found — a missing tool surfaces as a clear
    missing-dependency error rather than a confusing script failure.
    """
    for name in _REAL_TOOLS:
        real = shutil.which(name)
        if real is None:
            raise RuntimeError(
                f"Required coreutil '{name}' not found on the builder's PATH. "
                "Install it before running these tests."
            )
        link = bin_dir / name
        if not link.exists():
            link.symlink_to(real)


def _make_stub(bin_dir: Path, name: str, body: str) -> Path:
    """Write an executable shell stub to bin_dir."""
    p = bin_dir / name
    p.write_text(f"#!{_BASH}\n{body}\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return p


def _make_base_stubs(bin_dir: Path) -> None:
    """Populate bin_dir with stubs and real-tool symlinks for a hermetic test env.

    - _link_real_tools: symlinks awk, cksum, hostname, cat from the real PATH
    - crontab: stubbed to avoid touching real user crontab; replace via _make_fake_crontab
    - chezmoi-sudo: delegates to its args (so the systemctl stub is called correctly)
    - systemctl (no-op): default stub exits 0; tests that need absence call unlink()
      and rely on the hermetic PATH (bin_dir only) to make command -v fail genuinely
    """
    bin_dir.mkdir(exist_ok=True)
    _link_real_tools(bin_dir)
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
    """Run the install-update-cron script with a hermetic PATH.

    PATH is set to exactly tmp_path/bin — no system dirs. Real coreutils
    (awk, cksum, hostname, cat) are symlinked in by _make_base_stubs via
    _link_real_tools(). This makes unlink() a genuine absence: command -v
    finds nothing because there is no /usr/bin fallback to leak in.
    """
    bin_dir = str(tmp_path / "bin")
    env = {
        **_clean_env(),
        "HOME": str(tmp_path),
        "PATH": bin_dir,
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


def test_skip_when_crontab_absent(tmp_path: Path) -> None:
    """When crontab is not on PATH, script emits WARN and exits 0.

    With a hermetic PATH (bin_dir only, no /usr/bin), unlink() genuinely removes
    the only crontab on PATH — no system crontab can leak in regardless of what's
    installed on the runner.
    """
    bin_dir = tmp_path / "bin"
    _make_base_stubs(bin_dir)
    # Remove the stub so command -v crontab fails in the hermetic PATH.
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
    # Remove the stub — hermetic PATH means command -v systemctl genuinely fails.
    (bin_dir / "systemctl").unlink()

    result = _run_script(tmp_path)
    assert result.returncode == 0, f"script failed:\n{result.stderr}"
    assert "chezmoi-update-cron" in crontab_state.read_text()
