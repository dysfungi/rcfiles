"""Integration tests for the chezmoi-update-cron runner script.

WHY THIS FILE EXISTS
    `~/.local/bin/chezmoi-update-cron` (source:
    `dot_local/bin/executable_chezmoi-update-cron.tmpl`) is the unattended
    daily updater. After the secrets-to-mise migration it must:
      1. run the update via `mise x` (mise injects OP_SERVICE_ACCOUNT_TOKEN
         from ~/.config/mise/conf.d/secrets.toml) with `--keep-going`, then
         report drift/failure summaries on fd 3 — the saved original stderr,
         which cron mails to /var/mail/$USER — while full detail stays in
         the log; a clean run writes nothing to fd 3 (no mail)
      2. fail loudly (ERROR + non-zero) when mise is absent from PATH
      3. never reference the retired ~/.secrets token file
    Plus the pre-existing lock/log behavior it has always had.

TESTING LENS — NO MOCK-THEATER
    Assertions target observable outcomes only (files written/removed, exit
    codes, output routed to log vs mail channel) — never "the script invoked
    a stub with these args", which merely restates the script. The mise stub
    is file-driven: marker files under $HOME select its behavior. The
    subprocess harness captures the script's outer stderr (= the fd 3 mail
    channel, since fd 3 dups the original stderr) separately from the log.

WHY SUBPROCESS TESTS
    The script is a .tmpl whose only template input is `{{ .path_str }}`
    (the [scriptEnv] PATH). Rendering it via chezmoi would require 1Password;
    instead the test substitutes the placeholder with the hermetic bin dir —
    which doubles as exercising the PATH-mirroring behavior. The script then
    runs as a black box with a hermetic PATH (see
    .tests/chezmoiscripts/test_install_update_cron.py for the strategy).

REAL-MISE LINK TEST
    test_mise_confd_env_injection proves the mechanism cron depends on with a
    REAL mise binary: a 0600 conf.d/*.toml [env] var inside MISE_CONFIG_DIR is
    auto-loaded and delivered by `mise x` from a fully stripped environment.
    Trust: config files under MISE_CONFIG_DIR (the global config dir) are
    implicitly trusted by mise, so no interactive `mise trust` prompt fires;
    MISE_TRUSTED_CONFIG_PATHS is set anyway to pin the behavior explicitly
    across mise versions.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_TMPL = REPO_ROOT / "dot_local" / "bin" / "executable_chezmoi-update-cron.tmpl"

_BASH = shutil.which("bash") or "/bin/bash"

# Real coreutils the script needs on its hermetic PATH:
#   mkdir — lock dir + log dir creation
#   rm    — lock removal in the EXIT trap
#   date, hostname, whoami — log lines
#   awk   — drift-report parsing of `chezmoi status` output
#   cat   — used inside the file-driven mise stub
_REAL_TOOLS = ("mkdir", "rm", "date", "hostname", "whoami", "awk", "cat")


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _render_script(tmp_path: Path, path_str: str) -> Path:
    """Substitute the template's sole input ({{ .path_str }}) and write the
    rendered script. Fails loudly if the template's inputs change shape."""
    body = SCRIPT_TMPL.read_text()
    assert "{{ .path_str }}" in body, (
        "template no longer uses {{ .path_str }} — update this test's renderer"
    )
    rendered_body = body.replace("{{ .path_str }}", path_str)
    assert not re.search(r"{{.*}}", rendered_body), (
        "template grew new inputs this test does not render"
    )
    rendered = tmp_path / "chezmoi-update-cron"
    rendered.write_text(rendered_body)
    return rendered


def _make_stub(bin_dir: Path, name: str, body: str) -> Path:
    p = bin_dir / name
    p.write_text(f"#!{_BASH}\n{body}\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return p


def _make_bin(tmp_path: Path) -> Path:
    """Hermetic PATH dir: real coreutils only. Add stubs per test."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in _REAL_TOOLS:
        real = shutil.which(name)
        if real is None:
            raise RuntimeError(f"Required coreutil '{name}' not found on PATH.")
        link = bin_dir / name
        if not link.exists():
            link.symlink_to(real)
    return bin_dir


def _make_mise_stub(bin_dir: Path) -> None:
    """File-driven mise stub — behavior selected by marker files under $HOME:

      $HOME/update_rc   → `mise x -- chezmoi update …` exits with its contents
      $HOME/status_rc   → `mise x -- chezmoi status` exits with its contents
      $HOME/status.txt  → `mise x -- chezmoi status` prints its contents

    Absent markers mean success with empty output (a clean run).
    """
    _make_stub(
        bin_dir,
        "mise",
        "\n".join(
            (
                'case "$*" in',
                '  *"chezmoi status"*)',
                '    [[ -f "$HOME/status_rc" ]] && exit "$(cat "$HOME/status_rc")"',
                '    [[ -f "$HOME/status.txt" ]] && cat "$HOME/status.txt"',
                "    ;;",
                '  *"chezmoi update"*)',
                '    [[ -f "$HOME/update_rc" ]] && exit "$(cat "$HOME/update_rc")"',
                "    ;;",
                "esac",
                "exit 0",
            )
        ),
    )


def _run_script(tmp_path: Path) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    script = _render_script(tmp_path, str(bin_dir))
    env = {**_clean_env(), "HOME": str(tmp_path), "PATH": str(bin_dir)}
    return subprocess.run(
        [_BASH, str(script)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


# ── stubbed-mise behavior ─────────────────────────────────────────────────────


def test_happy_path_logs_and_releases_lock(tmp_path: Path) -> None:
    """Happy path on a FRESH HOME: exit 0, log has Starting/Ending, lock
    released by the EXIT trap. (No arg-string assertions — what the script
    passes to chezmoi is visible in the diff, not a behavior to restate.)
    The fresh HOME is the regression pairing for the bare-`mkdir`-on-missing-
    parent bug that masqueraded as lock contention."""
    bin_dir = _make_bin(tmp_path)
    _make_mise_stub(bin_dir)

    result = _run_script(tmp_path)
    assert result.returncode == 0, f"script failed:\n{result.stderr}"

    log = (tmp_path / ".local/state/chezmoi/update-cron.log").read_text()
    assert "Starting chezmoi-update-cron" in log
    assert "Ending chezmoi-update-cron" in log
    # Lock released by the EXIT trap.
    assert not (tmp_path / ".local/state/chezmoi/update-cron.lock").exists()


def test_existing_lock_skips_run(tmp_path: Path) -> None:
    """An existing lock dir means another run is in progress: exit 0 without
    invoking mise. (The happy-path test conversely proves a FRESH HOME takes
    the lock — regression for the bare `mkdir` failing on a missing parent
    dir and masquerading as lock contention.)"""
    bin_dir = _make_bin(tmp_path)
    mise_log = tmp_path / "mise_calls.txt"
    mise_log.write_text("")
    _make_stub(bin_dir, "mise", f'echo "$@" >> "{mise_log}"')
    (tmp_path / ".local/state/chezmoi/update-cron.lock").mkdir(parents=True)

    result = _run_script(tmp_path)
    assert result.returncode == 0
    assert "another run is in progress" in result.stderr
    assert mise_log.read_text() == ""


def test_fails_loudly_when_mise_absent(tmp_path: Path) -> None:
    """Guard: without mise on PATH the token cannot be delivered — the script
    must exit non-zero with an ERROR in the log AND a one-line notice on the
    mail channel (fd 3 → outer stderr) so the failure is nagged, not buried."""
    _make_bin(tmp_path)  # hermetic PATH, deliberately no mise stub

    result = _run_script(tmp_path)
    assert result.returncode != 0
    log = (tmp_path / ".local/state/chezmoi/update-cron.log").read_text()
    assert "ERROR" in log
    assert "mise not on PATH" in log
    assert "mise not on PATH" in result.stderr
    # Lock still released by the EXIT trap on the guard's early exit.
    assert not (tmp_path / ".local/state/chezmoi/update-cron.lock").exists()


def test_no_dot_secrets_references(tmp_path: Path) -> None:
    """Regression: the runner must not source the retired ~/.secrets token
    file — OP_SERVICE_ACCOUNT_TOKEN comes exclusively from `mise x`."""
    rendered = _render_script(tmp_path, "/usr/bin:/bin")
    body = rendered.read_text()
    assert ".secrets" not in body
    assert "load-secrets" not in body


# ── drift report (two-channel: log detail + fd 3 mail summary) ───────────────

# `chezmoi status` fixture: MM (both columns) and ` M` (actual≠target) are
# drift-class; ` A` is the non-M control that must never be reported.
_DRIFTED_STATUS = "MM .claude/settings.json\n M .claude.json\n A control-target\n"
_DRIFT_TARGETS = (".claude/settings.json", ".claude.json")


@pytest.mark.parametrize(
    ("status_body", "status_rc", "update_rc", "want_rc"),
    [
        pytest.param(_DRIFTED_STATUS, None, None, 0, id="drift-detected"),
        pytest.param("", None, None, 0, id="clean-silent"),
        pytest.param(_DRIFTED_STATUS, None, 1, 1, id="update-error-propagates"),
        pytest.param(None, 2, None, 0, id="status-failure-still-notifies"),
    ],
)
def test_drift_report(
    tmp_path: Path,
    status_body: str | None,
    status_rc: int | None,
    update_rc: int | None,
    want_rc: int,
) -> None:
    """Two-channel drift/failure reporting:
    - drift-detected: drifted targets land in the log (ERROR banner) AND on
      the mail channel (outer stderr = fd 3); the non-M control line does
      not; exit stays 0; no custom drift state file is written.
    - clean-silent: empty status → mail channel EMPTY (⇒ cron sends no mail).
    - update-error-propagates: a failed update still runs the report, puts
      a failure notice on the mail channel, and the exit code propagates.
    - status-failure-still-notifies: a broken `chezmoi status` cannot
      silently eat the report — a notice reaches the mail channel and the
      script still exits with the update's rc (guards the set -e trap).
    """
    bin_dir = _make_bin(tmp_path)
    _make_mise_stub(bin_dir)
    if status_body is not None:
        (tmp_path / "status.txt").write_text(status_body)
    if status_rc is not None:
        (tmp_path / "status_rc").write_text(f"{status_rc}\n")
    if update_rc is not None:
        (tmp_path / "update_rc").write_text(f"{update_rc}\n")

    result = _run_script(tmp_path)
    assert result.returncode == want_rc, f"stderr:\n{result.stderr}"

    log = (tmp_path / ".local/state/chezmoi/update-cron.log").read_text()
    mail = result.stderr  # fd 3 dups the original stderr → the mail channel

    if status_rc is not None:
        assert "chezmoi status failed" in mail
        return

    if update_rc is not None:
        assert f"chezmoi update exited rc={update_rc}" in mail
        # Report still ran after the failure: drift summary also present.
        assert "drifted target(s)" in mail

    if status_body == _DRIFTED_STATUS:
        assert "ERROR" in log and "2 drifted target(s)" in log
        assert "2 drifted target(s)" in mail
        for target in _DRIFT_TARGETS:
            assert target in log
            assert target in mail
        assert "control-target" not in log
        assert "control-target" not in mail
        assert "chezmoi apply --force" in mail  # human fix-hint
        # No custom drift state file — the mail spool IS the state.
        state_files = {
            p.name for p in (tmp_path / ".local/state").rglob("*") if p.is_file()
        }
        assert state_files == {"update-cron.log"}
    else:  # clean run
        assert "ERROR" not in log
        assert mail == "", f"clean run must not produce cron mail, got:\n{mail}"


# ── real-mise conf.d link ─────────────────────────────────────────────────────


@pytest.mark.skipif(shutil.which("mise") is None, reason="mise binary not on PATH")
def test_mise_confd_env_injection(tmp_path: Path) -> None:
    """The 0600-conf.d-auto-load link cron depends on, proven with real mise:
    a static [env] var in $MISE_CONFIG_DIR/conf.d/*.toml (mode 0600, exactly
    how chezmoi deploys secrets.toml) is injected by `mise x` into a child
    process from a fully stripped environment."""
    mise = shutil.which("mise")
    assert mise is not None  # skipif guard guarantees this; narrows str | None for mypy
    cfg = tmp_path / "cfg"
    (cfg / "conf.d").mkdir(parents=True)
    frag = cfg / "conf.d" / "test.toml"
    frag.write_text('[env]\nDUMMY_SECRET = "hunter2"\n')
    frag.chmod(0o600)
    assert stat.S_IMODE(frag.stat().st_mode) == 0o600
    for d in ("data", "cache", "state", "home", "cwd"):
        (tmp_path / d).mkdir()

    env = {
        # Stripped environment: only what mise itself needs, nothing inherited.
        "HOME": str(tmp_path / "home"),
        "PATH": "/usr/bin:/bin",
        "MISE_CONFIG_DIR": str(cfg),
        "MISE_DATA_DIR": str(tmp_path / "data"),
        "MISE_CACHE_DIR": str(tmp_path / "cache"),
        "MISE_STATE_DIR": str(tmp_path / "state"),
        # Implicitly trusted already (global config dir); pinned explicitly.
        "MISE_TRUSTED_CONFIG_PATHS": str(cfg),
    }
    result = subprocess.run(
        [mise, "x", "--", "printenv", "DUMMY_SECRET"],
        env=env,
        cwd=tmp_path / "cwd",  # no repo mise config in scope
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"mise x failed:\n{result.stderr}"
    assert result.stdout.strip() == "hunter2"
