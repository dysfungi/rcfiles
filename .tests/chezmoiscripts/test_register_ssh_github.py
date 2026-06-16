"""Integration tests for the SSH public-key GitHub/GHE registration helper.

WHY THIS FILE EXISTS
    `.chezmoitemplates/github/register-ssh-key.sh` defines `register_ssh_key
    <host> <token>` — the shared bash function used by both:
      - `.chezmoiscripts/20/run_once_after_register-ssh-github.unix-like.sh.tmpl`
        (personal github.com, every unix-like machine)
      - `.chezmoiscripts/20/run_once_after_register-ssh-github-enterprise.unix-like.sh.tmpl`
        (gh.riotgames.com, Riot machines only, gated on isRiotMachine)

    The helper's three-step idempotency contract (skip if present, delete stale,
    add) and its host-conditional auth-env selection are non-trivial and warrant
    an executable spec.

WHY SUBPROCESS / SOURCE TESTS (NOT UNIT TESTS)
    The helper is pure bash with no template directives — it's tested by sourcing
    it in a bash subprocess and calling the function directly. A stub `gh` on
    PATH records every invocation (args + env) to a log file for assertions.
    No production refactor for testability — harness adapts to production shape.

    The `.tmpl` caller scripts are checked structurally (grep for key directives)
    rather than rendered, because rendering requires real chezmoi data and
    machine-type context that varies across test environments.

WHY GH_* ENV IS STRIPPED IN _clean_env
    The helper's GHE branch uses `env GH_HOST=... GH_ENTERPRISE_TOKEN=... gh`.
    `env` adds vars but does NOT unset existing ones — if the test environment
    carries a real `GH_TOKEN`, the stub would see it in GHE-mode calls and make
    auth assertions unreliable. Stripping GH_* and MISE_GITHUB* from the
    subprocess env prevents that contamination.

TRUTH TABLE
    Fixture-driven logic tests (cases 1-5, via parametrize):
      1. key already present        → ssh-key add NOT called
      2. key absent, no stale key   → ssh-key add called with --type authentication
      3. stale key, same title      → ssh-key delete called before ssh-key add
      4. github.com auth            → GH_TOKEN set, GH_HOST/GH_ENTERPRISE_TOKEN empty
      5. GHE auth                   → GH_HOST + GH_ENTERPRISE_TOKEN set, GH_TOKEN empty
    Structural template tests (cases 6-9, static read):
      6. enterprise .tmpl gated on isRiotMachine
      7. enterprise .tmpl targets gh.riotgames.com + MISE_GITHUB_ENTERPRISE_TOKEN
      8. github .tmpl includes helper + MISE_GITHUB_TOKEN
      9. github .tmpl flips chezmoi remote to SSH
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
HELPER = REPO_ROOT / ".chezmoitemplates" / "github" / "register-ssh-key.sh"
GITHUB_SCRIPT = (
    REPO_ROOT
    / ".chezmoiscripts"
    / "20"
    / "run_once_after_register-ssh-github.unix-like.sh.tmpl"
)
ENTERPRISE_SCRIPT = (
    REPO_ROOT
    / ".chezmoiscripts"
    / "20"
    / "run_once_after_register-ssh-github-enterprise.unix-like.sh.tmpl"
)

FAKE_KEY_BODY = "AAAAB3NzaC1yZDI1NTE5AAAAIFakeKeyBodyForTesting"

_BASH = shutil.which("bash") or "/bin/bash"
_SYSTEM_DIRS = ":".join(
    d for d in ["/usr/local/bin", "/usr/bin", "/bin"] if Path(d).is_dir()
)


def _clean_env() -> dict[str, str]:
    """Return os.environ with vars stripped that would contaminate gh auth checks.

    Strips:
    - GIT_* : leaked by pre-commit; would redirect git calls into real repo.
    - GH_*  : actual gh tokens/host from the user's shell; would bleed into the
               GHE-mode stub call which uses env(...) without unsetting them.
    - MISE_GITHUB* : same concern for token env vars injected by chezmoi scriptEnv.
    """
    return {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GIT_")
        and not k.startswith("GH_")
        and not k.startswith("MISE_GITHUB")
    }


def _make_stub(bin_dir: Path, name: str, body: str) -> Path:
    """Write an executable bash stub to bin_dir."""
    p = bin_dir / name
    p.write_text(f"#!{_BASH}\n{body}\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return p


def _make_gh_stub(
    bin_dir: Path,
    calls_log: Path,
    *,
    mode: str = "key_absent_no_stale",
    stale_id: str = "",
) -> None:
    """Create a recording gh stub that simulates different key registration states.

    mode values:
      key_present        — ssh-key list returns a line containing FAKE_KEY_BODY.
                           Triggers the "already registered, skip" path.
      key_absent_no_stale— ssh-key list returns empty; api /user/keys returns empty.
                           Triggers a clean add (no delete).
      stale_key          — ssh-key list returns empty; api /user/keys returns stale_id.
                           Triggers delete-then-add.

    Every call appends to calls_log: ARGS line, three env lines (GH_TOKEN, GH_HOST,
    GH_ENTERPRISE_TOKEN), and a separator. Tests assert against this log.
    """
    calls_log.write_text("")
    _make_stub(
        bin_dir,
        "gh",
        textwrap.dedent(f"""\
            set -euo pipefail
            LOG="{calls_log}"
            KEY_BODY="{FAKE_KEY_BODY}"
            MODE="{mode}"
            STALE_ID="{stale_id}"

            {{
                echo "ARGS: $*"
                echo "GH_TOKEN=${{GH_TOKEN:-}}"
                echo "GH_HOST=${{GH_HOST:-}}"
                echo "GH_ENTERPRISE_TOKEN=${{GH_ENTERPRISE_TOKEN:-}}"
                echo "---"
            }} >> "$LOG"

            case "$1" in
                ssh-key)
                    case "$2" in
                        list)
                            if [[ "$MODE" == "key_present" ]]; then
                                echo "ssh-ed25519 $KEY_BODY test@machine"
                            fi
                            ;;
                        delete) ;;
                        add) ;;
                        *)
                            echo >&2 "gh stub: unknown ssh-key subcommand: $2"
                            exit 1
                            ;;
                    esac
                    ;;
                api)
                    # Handles: gh api /user/keys --jq "<expr>"
                    # Real gh parses JSON and applies jq; stub shortcuts to pre-set ID.
                    if [[ "$MODE" == "stale_key" ]]; then
                        echo "$STALE_ID"
                    fi
                    ;;
                *)
                    echo >&2 "gh stub: unknown command: $1"
                    exit 1
                    ;;
            esac
        """),
    )


def _setup_fake_home(tmp_path: Path) -> None:
    """Create a minimal home tree with a fake ssh public key."""
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir(mode=0o700)
    (ssh_dir / "id_ed25519.pub").write_text(f"ssh-ed25519 {FAKE_KEY_BODY} test@test\n")


def _run_helper(
    tmp_path: Path,
    *,
    host: str = "",
    token: str = "test_token",
    bin_dir: Path | None = None,
) -> subprocess.CompletedProcess:
    """Source the register-ssh-key.sh helper and call register_ssh_key <host> <token>.

    PATH: bin_dir (stubs) first, then real system dirs for coreutils.
    GH_* and MISE_GITHUB* stripped from env — see _clean_env docstring.
    """
    if bin_dir is None:
        bin_dir = tmp_path / "bin"

    driver = textwrap.dedent(f"""\
        source {HELPER}
        register_ssh_key "$1" "$2"
    """)
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


# ── Helper logic tests ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "mode,host,token,expect_add,expect_delete,expect_stderr_fragment",
    [
        pytest.param(
            "key_present",
            "",
            "tok1",
            False,
            False,
            "already registered",
            id="key-already-present",
        ),
        pytest.param(
            "key_absent_no_stale",
            "",
            "tok2",
            True,
            False,
            "added to",
            id="key-absent-no-stale",
        ),
        pytest.param(
            "stale_key",
            "",
            "tok3",
            True,
            True,
            "Deleted stale",
            id="stale-key-replaced",
        ),
    ],
)
def test_register_ssh_key_idempotency(
    tmp_path: Path,
    mode: str,
    host: str,
    token: str,
    expect_add: bool,
    expect_delete: bool,
    expect_stderr_fragment: str,
) -> None:
    """register_ssh_key follows the list→check-stale→delete→add idempotency contract."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_log = tmp_path / "gh_calls.log"
    _make_gh_stub(bin_dir, calls_log, mode=mode, stale_id="99")
    _setup_fake_home(tmp_path)

    result = _run_helper(tmp_path, host=host, token=token, bin_dir=bin_dir)

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert expect_stderr_fragment in result.stderr

    log = calls_log.read_text()
    if expect_add:
        assert "ssh-key add" in log
        assert "--type authentication" in log
        assert "--title" in log
    else:
        assert "ssh-key add" not in log

    if expect_delete:
        assert "ssh-key delete" in log
        delete_pos = log.find("ssh-key delete")
        add_pos = log.find("ssh-key add")
        assert delete_pos < add_pos, "delete must precede add in call log"
    else:
        assert "ssh-key delete" not in log


@pytest.mark.parametrize(
    "host,token,exp_gh_token,exp_gh_host,exp_enterprise_token",
    [
        pytest.param(
            "",
            "my_gh_token",
            "my_gh_token",
            "",
            "",
            id="github-com-uses-GH_TOKEN",
        ),
        pytest.param(
            "gh.riotgames.com",
            "riot_pat",
            "",
            "gh.riotgames.com",
            "riot_pat",
            id="ghe-uses-GH_HOST-and-GH_ENTERPRISE_TOKEN",
        ),
    ],
)
def test_register_ssh_key_auth_env(
    tmp_path: Path,
    host: str,
    token: str,
    exp_gh_token: str,
    exp_gh_host: str,
    exp_enterprise_token: str,
) -> None:
    """Auth env vars passed to gh differ for github.com vs GitHub Enterprise Server.

    github.com:  GH_TOKEN=<token>, GH_HOST empty, GH_ENTERPRISE_TOKEN empty.
    GHE server:  GH_HOST=<host>, GH_ENTERPRISE_TOKEN=<token>, GH_TOKEN empty.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_log = tmp_path / "gh_calls.log"
    _make_gh_stub(bin_dir, calls_log, mode="key_absent_no_stale")
    _setup_fake_home(tmp_path)

    result = _run_helper(tmp_path, host=host, token=token, bin_dir=bin_dir)

    assert result.returncode == 0, f"stderr: {result.stderr}"
    log = calls_log.read_text()

    assert f"GH_TOKEN={exp_gh_token}\n" in log
    assert f"GH_HOST={exp_gh_host}\n" in log
    assert f"GH_ENTERPRISE_TOKEN={exp_enterprise_token}\n" in log


# ── Template structural tests (static) ───────────────────────────────────────


def test_enterprise_script_gated_on_riot_machine() -> None:
    """Enterprise script body is wrapped in {{- if .isRiotMachine -}} guard."""
    content = ENTERPRISE_SCRIPT.read_text()
    assert "{{- if .isRiotMachine -}}" in content, (
        f"{ENTERPRISE_SCRIPT.name} must open with isRiotMachine guard"
    )
    assert "{{ end -}}" in content


def test_enterprise_script_targets_ghe_host() -> None:
    """Enterprise script references gh.riotgames.com and the enterprise token var."""
    content = ENTERPRISE_SCRIPT.read_text()
    assert "gh.riotgames.com" in content
    assert "MISE_GITHUB_ENTERPRISE_TOKEN" in content


def test_github_script_includes_helper() -> None:
    """github.com script includes the shared helper and uses the personal token var."""
    content = GITHUB_SCRIPT.read_text()
    assert 'includeTemplate "github/register-ssh-key.sh"' in content
    assert "MISE_GITHUB_TOKEN" in content


def test_github_script_flips_remote_to_ssh() -> None:
    """github.com script rewrites the chezmoi git remote from HTTPS to SSH."""
    content = GITHUB_SCRIPT.read_text()
    assert "remote set-url" in content
    assert "git@github.com" in content
