"""Tests for the Antigravity CLI settings modify_ script.

WHY THIS FILE EXISTS
    `dot_gemini/antigravity-cli/modify_private_settings.json.py.tmpl` forces a
    fixed set of durable prefs into ~/.gemini/antigravity-cli/settings.json
    (enableTelemetry:false, enableTerminalSandbox:true,
    toolPermission:"always-proceed", a permissions deny-list, etc.) and seeds
    trustedWorkspaces from the repo's PROJECTS data — while PRESERVING the
    runtime keys agy maintains there (notably any folders the user has already
    trusted). The point of a modify_ script over a plain managed file is
    non-destructive merge, so the load-bearing guarantees are:
      - empty/missing stdin (fresh machine) → every enforced pref set;
      - pre-existing trustedWorkspaces entries survive the merge (we only add);
      - a pre-existing enableTelemetry:true / toolPermission:"request-review"
        is overridden to our values;
      - malformed non-empty JSON fails LOUDLY (never silently wipes the file).

WHY WE RENDER FIRST
    Unlike a pure-stdlib modify_ script, this body has a Go-template head that
    injects chezmoidata (homeDir, projects) into Python constants, so the raw
    `.tmpl` is not valid Python. We render it exactly as chezmoi does
    (`chezmoi execute-template --source <repo> --file <abs path>`) into a real
    Python file, then exercise that rendered stdin->stdout filter. Template
    rendering across every host is also covered by
    test_validate_chezmoi_templates.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO_ROOT
    / "dot_gemini"
    / "antigravity-cli"
    / "modify_private_settings.json.py.tmpl"
)

# Prefs the script forces on every run, regardless of input. trustedWorkspaces is
# excluded on purpose: it is a non-destructive merge of input + repo PROJECTS
# (machine-dependent paths), so it is asserted structurally below, not by equality.
ENFORCED = {
    "allowNonWorkspaceAccess": True,
    "enableTelemetry": False,
    "enableTerminalSandbox": True,
    "notifications": True,
    "permissions": {
        "deny": [
            "command(git push -f)",
            "command(git push --force)",
            "command(rm -rf /)",
        ],
    },
    "runningLightSpeed": "slow",
    "showFeedbackSurvey": False,
    "toolPermission": "always-proceed",
}


@pytest.fixture(scope="session")
def rendered_script(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Render the Go-template modify_ script to a runnable Python file.

    Mirrors test_skill_frontmatter._render: cwd and --source are the repo root so
    the repo's .chezmoidata feeds the render, and GIT_* is stripped because
    pre-commit leaks GIT_DIR into the subprocess env (which would point chezmoi at
    the wrong tree). --file takes the absolute source path so chezmoi renders the
    working-tree body rather than chezmoi's configured default source.
    """
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    proc = subprocess.run(
        [
            "chezmoi",
            "execute-template",
            "--source",
            str(REPO_ROOT),
            "--file",
            str(SCRIPT),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=clean,
    )
    assert proc.returncode == 0, proc.stderr
    out = tmp_path_factory.mktemp("agy") / "modify_settings.py"
    out.write_text(proc.stdout)
    return out


def _run(script: Path, stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script)],
        input=stdin,
        capture_output=True,
        text=True,
    )


def _assert_enforced(merged: dict) -> None:
    """Every enforced pref is present with our value (KeyError fails loudly)."""
    for key, value in ENFORCED.items():
        assert merged[key] == value, key


@pytest.mark.parametrize(
    ("stdin", "preserved"),
    [
        pytest.param("", [], id="empty-stdin"),
        pytest.param("   \n  ", [], id="whitespace-only-stdin"),
        pytest.param(
            json.dumps({"trustedWorkspaces": ["/x"]}),
            ["/x"],
            id="preserves-trustedWorkspaces",
        ),
        pytest.param(
            json.dumps(
                {
                    "enableTelemetry": True,
                    "toolPermission": "request-review",
                    "trustedWorkspaces": ["/x"],
                }
            ),
            ["/x"],
            id="overrides-conflicting-prefs-preserves-runtime",
        ),
    ],
)
def test_merge(rendered_script: Path, stdin: str, preserved: list[str]) -> None:
    """All enforced prefs are forced; pre-existing trustedWorkspaces survive."""
    result = _run(rendered_script, stdin)
    assert result.returncode == 0, result.stderr
    merged = json.loads(result.stdout)

    _assert_enforced(merged)

    workspaces = merged["trustedWorkspaces"]
    assert workspaces == sorted(set(workspaces)), "sorted and deduplicated"
    assert set(preserved) <= set(workspaces), "input entries preserved"


def test_idempotent_on_already_correct_input(rendered_script: Path) -> None:
    """Re-running on its own output is a byte-for-byte no-op (apply idempotency)."""
    first = _run(rendered_script, json.dumps({**ENFORCED, "trustedWorkspaces": ["/x"]}))
    assert first.returncode == 0, first.stderr
    second = _run(rendered_script, first.stdout)
    assert second.returncode == 0, second.stderr
    assert second.stdout == first.stdout


def test_malformed_json_fails_loudly(rendered_script: Path) -> None:
    """Non-empty invalid JSON must error out, not silently discard the file."""
    result = _run(rendered_script, "{not valid json")
    assert result.returncode != 0
    assert "JSONDecodeError" in result.stderr
