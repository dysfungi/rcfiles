"""Tests for the Claude Code settings git-permission allow/deny lists.

WHY THIS FILE EXISTS
    `dot_claude/settings.json.tmpl` grants worktree subagents the git verbs
    they need to tidy their own branch without a permission prompt, while still
    walling off history-destroying pushes to shared branches. This test pins the
    entries that matter against silent regression:
      - permissions.deny ⊇ the force-push family ("Bash(git push --force *)",
        "Bash(git push -f *)", "Bash(git push -f)", "Bash(git push --force)") —
        the genuinely load-bearing safety entries. They keep the bare, lease-less
        force-push blocked (in both long and short flag forms, with and without a
        trailing remote/refspec) so shared history stays protected. Dropping any
        of them lets a force-push fall through to the broad `Bash(git *)` allow
        and run with no prompt.
      - permissions.allow ⊇ "Bash(git push --force-with-lease *)" — lets an agent
        update its own draft PR after a rebase; this must stay allowed and must
        never be swept into the deny family above.
      - permissions.allow ⊇ "Bash(git rebase *)" — determinism insurance, not a
        gate. Per Claude Code's documented allow precedence the broad
        `Bash(git *)` glob nominally already covers rebase, but that glob was
        empirically observed NOT to clear a destructive git op (`git reset
        --hard`) in a non-interactive subagent. Pinning `git rebase` explicitly
        makes the sanctioned worktree-tidy path resolve deterministically
        regardless of that discrepancy.

WHY WE RENDER FIRST
    The file is a Go template: its env block branches on machine-detection vars
    (`.is_my_machine` / `.is_riot_machine`) and interpolates `.chezmoi.homeDir`,
    so the raw `.tmpl` is not valid JSON. We render it exactly as chezmoi does
    (`chezmoi execute-template --source <repo> --file <abs path>`) into real JSON,
    then assert on the parsed permissions. We pin is_my_machine=true so the render
    takes the personal branch: the riot branch calls `onepasswordRead`, which CI
    cannot satisfy. The permissions block is machine-independent, so the personal
    render fully covers the contract. Template rendering across every host is also
    covered by test_validate_chezmoi_templates.py.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS = REPO_ROOT / "dot_claude" / "settings.json.tmpl"


@pytest.fixture(scope="session")
def permissions(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Render settings.json.tmpl (personal branch) and return its permissions.

    Mirrors test_antigravity_settings.rendered_script: cwd and --source are the
    repo root so .chezmoidata feeds the render, GIT_* is stripped because
    pre-commit leaks GIT_DIR into the subprocess env (pointing chezmoi at the
    wrong tree), and --file takes the absolute source path so chezmoi renders the
    working-tree body rather than its configured default source.

    A throwaway --config pins is_my_machine=true (and is_riot_machine=false).
    `.chezmoi.toml.tmpl` defines these under [data] during `chezmoi init`, which
    execute-template does not run; without them a fresh checkout (CI) aborts with
    `map has no entry for key`. Pinning the personal machine also avoids the riot
    branch's onepasswordRead calls, which CI cannot satisfy.
    """
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    config = tmp_path_factory.mktemp("chezmoi-config") / "chezmoi.toml"
    config.write_text("[data]\nis_my_machine = true\nis_riot_machine = false\n")
    proc = subprocess.run(
        [
            "chezmoi",
            "execute-template",
            "--config",
            str(config),
            "--source",
            str(REPO_ROOT),
            "--file",
            str(SETTINGS),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=clean,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["permissions"]


@pytest.mark.parametrize(
    ("bucket", "entry"),
    [
        pytest.param("allow", "Bash(git rebase *)", id="allow-git-rebase"),
        pytest.param(
            "allow",
            "Bash(git push --force-with-lease *)",
            id="allow-force-with-lease",
        ),
        pytest.param("deny", "Bash(git push --force *)", id="deny-bare-force-push"),
        pytest.param("deny", "Bash(git push -f *)", id="deny-short-force-push"),
        pytest.param("deny", "Bash(git push -f)", id="deny-short-force-push-bare"),
        pytest.param("deny", "Bash(git push --force)", id="deny-force-push-bare"),
    ],
)
def test_git_permission_entry(permissions: dict, bucket: str, entry: str) -> None:
    """Each load-bearing git permission entry is present in its expected bucket."""
    assert entry in permissions[bucket], f"{entry!r} missing from permissions.{bucket}"
