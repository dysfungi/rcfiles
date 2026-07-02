"""Integration tests for the chezmoi-update-cron runner script.

WHY THIS FILE EXISTS
    `~/.local/bin/chezmoi-update-cron` (source:
    `dot_local/bin/executable_chezmoi-update-cron.tmpl`) is the unattended
    daily updater. After the secrets-to-mise migration it must:
      1. run `mise x -- chezmoi update --init --verbose --force` (mise injects
         OP_SERVICE_ACCOUNT_TOKEN from ~/.config/mise/conf.d/secrets.toml)
      2. fail loudly (ERROR + non-zero) when mise is absent from PATH
      3. never reference the retired ~/.secrets token file
    Plus the pre-existing lock/log behavior it has always had.

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
_REAL_TOOLS = ("mkdir", "rm", "date", "hostname", "whoami")


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


def test_runs_chezmoi_update_via_mise_x(tmp_path: Path) -> None:
    """Happy path: the runner delegates to `mise x -- chezmoi update --init
    --verbose --force` — token delivery is mise's job, not the script's.
    --force is required because the run has no TTY: the overwrite prompt for
    perpetually-drifting modify_ targets would otherwise abort every run."""
    bin_dir = _make_bin(tmp_path)
    mise_log = tmp_path / "mise_calls.txt"
    mise_log.write_text("")
    _make_stub(bin_dir, "mise", f'echo "$@" >> "{mise_log}"')

    result = _run_script(tmp_path)
    assert result.returncode == 0, f"script failed:\n{result.stderr}"

    calls = mise_log.read_text()
    assert "x -- chezmoi update --init --verbose --force" in calls, (
        f"expected mise x -- chezmoi update --init --verbose --force, got:\n{calls}"
    )

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
    must exit non-zero with an ERROR. The guard runs AFTER the log redirect,
    so the ERROR must land in the log file (cron mail is rarely read)."""
    _make_bin(tmp_path)  # hermetic PATH, deliberately no mise stub

    result = _run_script(tmp_path)
    assert result.returncode != 0
    log = (tmp_path / ".local/state/chezmoi/update-cron.log").read_text()
    assert "ERROR" in log
    assert "mise not on PATH" in log
    # Lock still released by the EXIT trap on the guard's early exit.
    assert not (tmp_path / ".local/state/chezmoi/update-cron.lock").exists()


def test_no_dot_secrets_references(tmp_path: Path) -> None:
    """Regression: the runner must not source the retired ~/.secrets token
    file — OP_SERVICE_ACCOUNT_TOKEN comes exclusively from `mise x`."""
    rendered = _render_script(tmp_path, "/usr/bin:/bin")
    body = rendered.read_text()
    assert ".secrets" not in body
    assert "load-secrets" not in body


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
