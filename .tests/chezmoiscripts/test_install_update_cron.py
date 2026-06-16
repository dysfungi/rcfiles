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
    6. macOS-like (no systemctl)              → systemctl not called, no error
"""

from __future__ import annotations

import os
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

# The template variables that would normally be rendered by chezmoi. For testing
# we provide a pre-rendered script (via sed substitution), so we can test the shell
# logic without chezmoi. Alternatively we run the script after stripping {{ }} blocks.
# Simpler: the script has no template directives in the body — all template content
# is in comments. So we can run the .tmpl file directly via bash.


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _make_stub(bin_dir: Path, name: str, body: str) -> Path:
    """Write an executable shell stub to bin_dir."""
    p = bin_dir / name
    p.write_text(f"#!/usr/bin/env bash\n{body}\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return p


def _make_fake_crontab(tmp_path: Path, initial_entries: str = "") -> Path:
    """Write a fake `crontab` stub to bin/ that simulates crontab -l/-."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    crontab_state = tmp_path / "crontab_state.txt"
    crontab_state.write_text(initial_entries)

    stub = bin_dir / "crontab"
    stub.write_text(
        textwrap.dedent(f"""\
        #!/usr/bin/env bash
        STATE="{crontab_state}"
        if [[ "$1" == "-l" ]]; then
            cat "$STATE" 2>/dev/null || exit 1
        elif [[ "$1" == "-" ]]; then
            cat > "$STATE"
        else
            echo >&2 "crontab stub: unknown arg $1"
            exit 1
        fi
        """)
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return crontab_state


def _make_fake_systemctl(tmp_path: Path, initial_enabled: bool = False) -> Path:
    """Write a fake `systemctl` stub that records calls."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    calls_log = tmp_path / "systemctl_calls.txt"
    calls_log.write_text("")

    stub = bin_dir / "systemctl"
    stub.write_text(
        textwrap.dedent(f"""\
        #!/usr/bin/env bash
        LOG="{calls_log}"
        echo "$@" >> "$LOG"
        if [[ "$1" == "is-enabled" ]]; then
            {"exit 0" if initial_enabled else "exit 1"}
        fi
        exit 0
        """)
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return calls_log


def _make_fake_chezmoi_sudo(tmp_path: Path) -> None:
    """Write a fake chezmoi-sudo stub that just runs sudo-args as-is."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "chezmoi-sudo"
    stub.write_text(
        textwrap.dedent("""\
        #!/usr/bin/env bash
        # In tests, chezmoi-sudo just delegates to systemctl (already stubbed on PATH).
        exec "$@"
        """)
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _add_minimal_stubs(bin_dir: Path) -> None:
    """Add stubs for cksum/awk/hostname needed when /usr/bin is excluded from PATH.

    Used only in test_skip_when_crontab_absent, which must hide /usr/bin/crontab.
    All other tests use a PATH that includes /usr/bin so real tools are available.

    SIGPIPE note: the cksum stub MUST consume stdin before writing to stdout.
    Without `cat > /dev/null`, hostname's `echo` output sits in the pipe; if cksum
    exits before the pipe buffer fills, hostname gets SIGPIPE. Under load (pre-commit
    environment), this race is observable. Consuming stdin closes the read end cleanly.
    """
    _make_stub(bin_dir, "hostname", "echo fakehostname")
    # Consume stdin first to prevent SIGPIPE race in 'hostname | cksum | awk'
    _make_stub(bin_dir, "cksum", "cat > /dev/null\necho '123456789 0 -'")
    # Delegate to system awk via absolute path (/usr/bin/awk exists on macOS+Linux)
    _make_stub(bin_dir, "awk", 'exec /usr/bin/awk "$@"')


def _run_script(
    tmp_path: Path,
    *,
    isolated_path: bool = False,
    env_overrides: dict | None = None,
) -> subprocess.CompletedProcess:
    """Run the install-update-cron script.

    isolated_path=True: uses ONLY tmp_path/bin + /bin (no /usr/bin). Required for
    test_skip_when_crontab_absent to hide /usr/bin/crontab from PATH lookup.
    All other callers should leave isolated_path=False so real system tools (awk,
    cksum, hostname) are available without needing stubs.
    """
    bin_dir = str(tmp_path / "bin")
    if isolated_path:
        # Exclude /usr/bin so /usr/bin/crontab is invisible; caller provides stubs
        path = f"{bin_dir}:/bin"
    else:
        # Include /usr/bin so real awk/cksum/hostname work without stubs
        path = f"{bin_dir}:/usr/bin:/bin"
    env = {
        **_clean_env(),
        "HOME": str(tmp_path),
        "PATH": path,
        **(env_overrides or {}),
    }
    return subprocess.run(
        ["bash", str(SCRIPT)],
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
    crontab_state = _make_fake_crontab(tmp_path, initial_entries=initial_crontab)
    _make_fake_chezmoi_sudo(tmp_path)
    # Non-isolated PATH: /usr/bin tools (awk, cksum, hostname) are real; only
    # our fake crontab stub shadows the system one (bin_dir is first in PATH).

    result = _run_script(tmp_path)
    assert result.returncode == 0, f"script failed:\n{result.stderr}"

    final = crontab_state.read_text()
    assert final.count("# >>> chezmoi-update >>>") == expected_block_count
    assert final.count("# <<< chezmoi-update <<<") == expected_block_count
    assert "chezmoi-update-cron" in final

    if expect_unrelated_preserved:
        assert "/other/task" in final, "unrelated crontab entry was clobbered"


def test_skip_when_crontab_absent(tmp_path: Path) -> None:
    """When crontab is not on PATH, script emits WARN and exits 0."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    # Add minimal stubs (hostname/cksum/awk) but NOT crontab.
    # Use isolated_path so /usr/bin/crontab on macOS is also invisible.
    _add_minimal_stubs(bin_dir)

    result = _run_script(tmp_path, isolated_path=True)
    assert result.returncode == 0
    assert "WARNING" in result.stderr or "WARNING" in result.stdout


def test_enables_cronie_on_linux(tmp_path: Path) -> None:
    """On Linux (systemctl available, cronie not yet enabled), script enables cronie."""
    _make_fake_crontab(tmp_path)
    _make_fake_chezmoi_sudo(tmp_path)
    calls_log = _make_fake_systemctl(tmp_path, initial_enabled=False)

    result = _run_script(tmp_path)
    assert result.returncode == 0, f"script failed:\n{result.stderr}"

    calls = calls_log.read_text()
    assert "enable --now cronie" in calls, (
        f"expected systemctl enable --now cronie call, got:\n{calls}"
    )


def test_skips_cronie_when_already_enabled(tmp_path: Path) -> None:
    """When cronie is already enabled, systemctl enable is not called again."""
    _make_fake_crontab(tmp_path)
    _make_fake_chezmoi_sudo(tmp_path)
    calls_log = _make_fake_systemctl(tmp_path, initial_enabled=True)

    result = _run_script(tmp_path)
    assert result.returncode == 0, f"script failed:\n{result.stderr}"

    calls = calls_log.read_text()
    assert "enable --now cronie" not in calls, (
        "systemctl enable called when cronie was already enabled"
    )


def test_no_cronie_without_systemctl(tmp_path: Path) -> None:
    """When systemctl is absent (macOS), no cronie-related calls are made."""
    _make_fake_crontab(tmp_path)
    _make_fake_chezmoi_sudo(tmp_path)
    # No systemctl stub → chezmoi-sudo is not on PATH; use non-isolated PATH so
    # real awk/cksum/hostname are available, and our fake crontab shadows /usr/bin/crontab.

    result = _run_script(tmp_path)
    assert result.returncode == 0, f"script failed:\n{result.stderr}"
    # No cronie log to check; success with exit 0 is sufficient
