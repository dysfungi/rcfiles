"""Integration tests for the stage-90 cron install script.

WHY THIS FILE EXISTS
    `home/.chezmoiscripts/90/run_after_install-update-cron.unix-like.sh`
    must register a managed cron block idempotently, never clobber unrelated entries,
    fail loudly when crontab is absent or the write did not persist, verify the cron
    daemon is running (via systemctl on Linux or launchctl on macOS), and fail loudly
    when no daemon manager is available.
    These properties are non-trivial enough to warrant an executable spec.

WHY SUBPROCESS TESTS
    The script is tested as a black box via `bash $SCRIPT`. Stubs on PATH replace
    `crontab`, `systemctl`, and `launchctl` so no real cron state is touched. This
    matches the repo testing convention (real inputs/outputs, adapt harness to
    production shape).

TRUTH TABLE
    Each parametrized case or standalone test covers one distinct scenario:
    1.  fresh install (no existing crontab)              → managed block added
    2.  idempotent re-install                            → only one block in result
    3.  pre-existing unrelated entries                   → those entries preserved
    4.  idempotent with unrelated entries                → block replaced, rest preserved
    5.  crontab absent from PATH                         → ERROR + exit non-zero
    6.  crontab write did not persist                    → ERROR + exit non-zero
    7.  macOS: launchctl, com.vix.cron already known     → success
    8.  macOS: com.vix.cron not loadable after kickstart → ERROR + exit non-zero
    9.  no daemon manager (no systemctl, no launchctl)   → ERROR + exit non-zero

    (The Linux cronie enable/skip paths are deliberately untested: asserting
    "systemctl was called with these args" only restates the script — mock
    theater, no observable outcome to verify against a stub systemd.)

HERMETIC PATH STRATEGY
    Tests run with PATH set to exactly tmp_path/bin — nothing else. This makes
    "tool absent" a genuine property: unlink() the stub and command -v fails,
    with no real system binary to leak in from /usr/bin.

    The few real coreutils the script (and its stubs) need are symlinked into
    bin_dir by _link_real_tools():
      - awk, cksum, hostname — used directly by the script
      - cat  — used inside the _make_fake_crontab stub
      - grep — used in the post-write crontab verification step

    Everything else is either a bash builtin (echo, printf, [[]], $(( ))) or a
    stub (crontab, chezmoi-sudo, systemctl, launchctl). bash itself is referenced
    by absolute path in stub shebangs, so it needs no PATH entry.

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
MANAGED_ROOT = REPO_ROOT / "home"
SCRIPT = (
    MANAGED_ROOT
    / ".chezmoiscripts"
    / "90"
    / "run_after_install-update-cron.unix-like.sh"
)

_BASH = shutil.which("bash") or "/bin/bash"

# Real coreutils the script (and stubs) need on PATH. Symlinked into bin_dir
# by _link_real_tools() so the subprocess PATH stays fully hermetic (bin_dir only).
#   awk, cksum, hostname — used directly by the cron-install script
#   cat  — used inside the _make_fake_crontab stub
#   grep — used in the post-write crontab verification step
_REAL_TOOLS = ("awk", "cksum", "hostname", "cat", "grep")


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

    - _link_real_tools: symlinks awk, cksum, hostname, cat, grep from the real PATH
    - crontab: stubbed to avoid touching real user crontab; replace via _make_fake_crontab
    - chezmoi-sudo: delegates to its args (so launchctl/systemctl stubs are called correctly)
    - systemctl (no-op): default stub exits 0; tests that need absence call unlink()
      and rely on the hermetic PATH (bin_dir only) to make command -v fail genuinely
    Note: launchctl is NOT included — add it explicitly in macOS-path tests.
    """
    bin_dir.mkdir(exist_ok=True)
    _link_real_tools(bin_dir)
    _make_stub(bin_dir, "crontab", "exit 1")
    _make_stub(bin_dir, "chezmoi-sudo", 'exec "$@"')
    # Default systemctl stub: cronie already enabled + active → no enable call, exits 0.
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


def _make_launchctl_stub(bin_dir: Path, *, cron_known: bool) -> None:
    """Write a launchctl stub simulating macOS launchd state for com.vix.cron.

    cron_known=True:  `print system/com.vix.cron` exits 0 — service known to launchd.
    cron_known=False: always exits 1 — service unknown, even after kickstart attempts.
    All other subcommands (e.g. kickstart) exit 0 unconditionally.
    """
    _make_stub(
        bin_dir,
        "launchctl",
        textwrap.dedent(f"""\
        if [[ "$1" == "print" && "$2" == "system/com.vix.cron" ]]; then
            {"exit 0" if cron_known else "exit 1"}
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
    (awk, cksum, hostname, cat, grep) are symlinked in by _make_base_stubs via
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


def test_fail_when_crontab_absent(tmp_path: Path) -> None:
    """When crontab is not on PATH, script emits ERROR and exits non-zero.

    With a hermetic PATH (bin_dir only, no /usr/bin), unlink() genuinely removes
    the only crontab on PATH — no system crontab can leak in regardless of what's
    installed on the runner.
    """
    bin_dir = tmp_path / "bin"
    _make_base_stubs(bin_dir)
    (bin_dir / "crontab").unlink()

    result = _run_script(tmp_path)
    assert result.returncode != 0
    assert "ERROR" in result.stderr


def test_fail_when_crontab_write_not_persisted(tmp_path: Path) -> None:
    """When crontab write does not persist (e.g. macOS Full Disk Access / TCC), script fails loudly.

    The stub accepts stdin on '-' but never writes it anywhere; '-l' always returns
    empty output. The script's post-write verification detects the missing block and
    exits non-zero with actionable remediation instructions.
    """
    bin_dir = tmp_path / "bin"
    _make_base_stubs(bin_dir)
    _make_stub(
        bin_dir,
        "crontab",
        textwrap.dedent("""\
        if [[ "$1" == "-l" ]]; then
            exit 0
        elif [[ "$1" == "-" ]]; then
            cat > /dev/null
        else
            echo >&2 "crontab stub: unknown arg $1"; exit 1
        fi
        """),
    )

    result = _run_script(tmp_path)
    assert result.returncode != 0
    assert "ERROR" in result.stderr


def test_macos_daemon_already_loaded(tmp_path: Path) -> None:
    """When systemctl is absent (macOS), launchctl branch verifies com.vix.cron is known to launchd."""
    bin_dir = tmp_path / "bin"
    _make_base_stubs(bin_dir)
    crontab_state = tmp_path / "crontab_state.txt"
    _make_fake_crontab(bin_dir, crontab_state)
    (bin_dir / "systemctl").unlink()
    _make_launchctl_stub(bin_dir, cron_known=True)

    result = _run_script(tmp_path)
    assert result.returncode == 0, f"script failed:\n{result.stderr}"
    assert "chezmoi-update-cron" in crontab_state.read_text()


def test_fail_when_macos_daemon_unavailable(tmp_path: Path) -> None:
    """When com.vix.cron cannot be loaded even after kickstart, script fails loudly."""
    bin_dir = tmp_path / "bin"
    _make_base_stubs(bin_dir)
    crontab_state = tmp_path / "crontab_state.txt"
    _make_fake_crontab(bin_dir, crontab_state)
    (bin_dir / "systemctl").unlink()
    _make_launchctl_stub(bin_dir, cron_known=False)

    result = _run_script(tmp_path)
    assert result.returncode != 0
    assert "ERROR" in result.stderr


def test_fail_when_no_daemon_manager(tmp_path: Path) -> None:
    """When neither systemctl nor launchctl is on PATH, script fails loudly."""
    bin_dir = tmp_path / "bin"
    _make_base_stubs(bin_dir)
    crontab_state = tmp_path / "crontab_state.txt"
    _make_fake_crontab(bin_dir, crontab_state)
    # Remove systemctl; launchctl is never added to base stubs, so it's absent.
    (bin_dir / "systemctl").unlink()

    result = _run_script(tmp_path)
    assert result.returncode != 0
    assert "ERROR" in result.stderr
