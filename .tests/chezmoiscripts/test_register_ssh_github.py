"""Integration tests for the SSH public-key GitHub/GHE registration helper.

WHY THIS FILE EXISTS
    `home/.chezmoitemplates/github/register-ssh-key.sh` defines `register_ssh_key
    <host> <token>` — the shared bash function used by both:
      - `home/.chezmoiscripts/20/run_onchange_after_register-ssh-github.unix-like.sh.tmpl`
        (personal github.com, every unix-like machine)
      - `home/.chezmoiscripts/20/run_onchange_after_register-ssh-github-enterprise.unix-like.sh.tmpl`
        (gh.riotgames.com, Riot machines only, gated on is_riot_machine)

    The helper's contract is safety-critical (it caused a github.com lockout on
    2026-06-26) and warrants an executable spec:
      - derive the public half from the PRIVATE key (never upload an orphan);
      - ADD-ONLY (never delete an existing key);
      - idempotent (skip if already registered);
      - best-effort (missing key / unreachable host → warn + return 0).

WHY SUBPROCESS / SOURCE TESTS (NOT UNIT TESTS)
    The helper is pure bash with no template directives — it's tested by sourcing
    it in a bash subprocess and calling the function directly. A stub `gh` on
    PATH records every invocation (args + env) to a log file for assertions.
    A real ed25519 keypair is generated in a fake $HOME so `ssh-keygen -y`
    produces a genuine public body, exactly as in production.

WHY GH_* ENV IS STRIPPED IN _clean_env
    The helper's GHE branch uses `env GH_HOST=... GH_ENTERPRISE_TOKEN=... gh`.
    `env` adds vars but does NOT unset existing ones — a real GH_TOKEN in the test
    environment would bleed into GHE-mode calls and break auth assertions.

TRUTH TABLE
    Logic tests (subprocess + real key + gh stub):
      1. key already present        → ssh-key add NOT called, delete NEVER called
      2. key absent                 → ssh-key add called (--type authentication),
                                       delete NEVER called (add-only)
      3. no private key in $HOME    → no gh calls at all (orphan-upload prevented)
      4. gh ssh-key list fails      → best-effort skip, no add
      5. github.com auth            → GH_TOKEN set, GH_HOST/GH_ENTERPRISE_TOKEN empty
      6. GHE auth                   → GH_HOST + GH_ENTERPRISE_TOKEN set, GH_TOKEN empty
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
HELPER = MANAGED_ROOT / ".chezmoitemplates" / "github" / "register-ssh-key.sh"

_BASH = shutil.which("bash") or "/bin/bash"
_KEYGEN = shutil.which("ssh-keygen")
_SYSTEM_DIRS = ":".join(
    d for d in ["/usr/local/bin", "/usr/bin", "/bin"] if Path(d).is_dir()
)

pytestmark = pytest.mark.skipif(_KEYGEN is None, reason="ssh-keygen not available")


def _clean_env() -> dict[str, str]:
    """os.environ minus vars that would contaminate git/gh auth in the subprocess."""
    return {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GIT_")
        and not k.startswith("GH_")
        and not k.startswith("MISE_GITHUB")
    }


def _make_stub(bin_dir: Path, name: str, body: str) -> Path:
    p = bin_dir / name
    p.write_text(f"#!{_BASH}\n{body}\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return p


def _make_gh_stub(
    bin_dir: Path,
    calls_log: Path,
    *,
    mode: str,
    key_body: str,
) -> None:
    """Recording gh stub.

    mode:
      key_present — `ssh-key list` echoes a line containing key_body (skip path).
      key_absent  — `ssh-key list` echoes an unrelated key (clean add path).
      list_fails  — `ssh-key list` exits 1 (best-effort skip path).
    Every call appends ARGS + the three auth env vars to calls_log.
    """
    calls_log.write_text("")
    _make_stub(
        bin_dir,
        "gh",
        textwrap.dedent(f"""\
            set -euo pipefail
            LOG="{calls_log}"
            KEY_BODY="{key_body}"
            MODE="{mode}"
            {{
                echo "ARGS: $*"
                echo "GH_TOKEN=${{GH_TOKEN:-}}"
                echo "GH_HOST=${{GH_HOST:-}}"
                echo "GH_ENTERPRISE_TOKEN=${{GH_ENTERPRISE_TOKEN:-}}"
                echo "---"
            }} >> "$LOG"
            case "$1 ${{2:-}}" in
                "ssh-key list")
                    if [[ "$MODE" == "list_fails" ]]; then exit 1; fi
                    if [[ "$MODE" == "key_present" ]]; then
                        echo "ssh-ed25519 $KEY_BODY present@machine"
                    else
                        echo "ssh-ed25519 AAAAUnrelatedOtherKeyBody other@machine"
                    fi
                    ;;
                "ssh-key add"|"ssh-key delete") ;;
                *) echo >&2 "gh stub: unexpected: $*"; exit 1 ;;
            esac
        """),
    )


def _setup_fake_home(tmp_path: Path, *, with_key: bool = True) -> str:
    """Create ~/.ssh; optionally generate a real ed25519 key. Return its pub body."""
    assert _KEYGEN is not None
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir(mode=0o700)
    if not with_key:
        return ""
    key = ssh_dir / "id_ed25519"
    subprocess.run(
        [_KEYGEN, "-t", "ed25519", "-N", "", "-C", "test@test", "-f", str(key), "-q"],
        check=True,
    )
    pub = subprocess.run(
        [_KEYGEN, "-y", "-f", str(key)], capture_output=True, text=True, check=True
    ).stdout
    return pub.split()[1]


def _run_helper(
    tmp_path: Path, bin_dir: Path, *, host: str = "", token: str = "tok"
) -> subprocess.CompletedProcess:
    driver = f'source {HELPER}\nregister_ssh_key "$1" "$2"\n'
    env = {
        **_clean_env(),
        "HOME": str(tmp_path),
        "PATH": f"{bin_dir}:{_SYSTEM_DIRS}",
    }
    return subprocess.run(
        [_BASH, "-c", driver, "--", host, token],
        capture_output=True,
        text=True,
        env=env,
    )


# ── Logic tests ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "mode,expect_add,fragment",
    [
        pytest.param("key_present", False, "already registered", id="present-skip"),
        pytest.param("key_absent", True, "added to", id="absent-add"),
        pytest.param("list_fails", False, "cannot reach", id="list-fails-skip"),
    ],
)
def test_register_logic(
    tmp_path: Path, mode: str, expect_add: bool, fragment: str
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_log = tmp_path / "gh_calls.log"
    body = _setup_fake_home(tmp_path)
    _make_gh_stub(bin_dir, calls_log, mode=mode, key_body=body)

    result = _run_helper(tmp_path, bin_dir)

    assert result.returncode == 0, result.stderr
    assert fragment in result.stderr
    log = calls_log.read_text()
    assert ("ssh-key add" in log) is expect_add
    if expect_add:
        assert "--type authentication" in log
    # ADD-ONLY: delete must never be called, in any path.
    assert "ssh-key delete" not in log


def test_register_skips_when_no_private_key(tmp_path: Path) -> None:
    """No private key in $HOME → no gh calls (never upload an orphan)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_log = tmp_path / "gh_calls.log"
    _setup_fake_home(tmp_path, with_key=False)
    _make_gh_stub(bin_dir, calls_log, mode="key_absent", key_body="x")

    result = _run_helper(tmp_path, bin_dir)

    assert result.returncode == 0, result.stderr
    assert "missing" in result.stderr
    assert calls_log.read_text() == ""  # gh never invoked


@pytest.mark.parametrize(
    "host,token,exp_token,exp_host,exp_ent",
    [
        pytest.param("", "ghtok", "ghtok", "", "", id="github-uses-GH_TOKEN"),
        pytest.param(
            "gh.riotgames.com", "riot", "", "gh.riotgames.com", "riot", id="ghe-auth"
        ),
    ],
)
def test_register_auth_env(
    tmp_path: Path, host: str, token: str, exp_token: str, exp_host: str, exp_ent: str
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_log = tmp_path / "gh_calls.log"
    body = _setup_fake_home(tmp_path)
    _make_gh_stub(bin_dir, calls_log, mode="key_absent", key_body=body)

    result = _run_helper(tmp_path, bin_dir, host=host, token=token)

    assert result.returncode == 0, result.stderr
    log = calls_log.read_text()
    assert f"GH_TOKEN={exp_token}\n" in log
    assert f"GH_HOST={exp_host}\n" in log
    assert f"GH_ENTERPRISE_TOKEN={exp_ent}\n" in log
