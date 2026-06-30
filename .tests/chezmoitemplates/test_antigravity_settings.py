"""Tests for the Antigravity CLI settings modify_ script.

WHY THIS FILE EXISTS
    `dot_gemini/antigravity-cli/modify_private_settings.json.py.tmpl` enforces
    three durable prefs in ~/.gemini/antigravity-cli/settings.json —
    `enableTelemetry: false`, `enableTerminalSandbox: true`, and
    `toolPermission: "proceed-in-sandbox"` — while PRESERVING the runtime keys
    agy maintains there (notably trustedWorkspaces, which agy rewrites as the
    user trusts folders). The whole point of a modify_ script over a plain
    managed file is non-destructive merge — so the load-bearing guarantees are:
      - empty/missing stdin (fresh machine) → all three prefs set;
      - existing runtime keys survive the merge untouched;
      - a pre-existing enableTelemetry:true / toolPermission:"request-review"
        is overridden to our values;
      - malformed non-empty JSON fails LOUDLY (never silently wipes the file).

WHY SUBPROCESS TESTS
    The artifact is a stdin->stdout filter. We run it exactly as chezmoi does
    (feed the current file on stdin, capture stdout) and assert on the merged
    JSON. The Python body has no Go-template directives, so executing the source
    directly is equivalent to the post-render script; template rendering itself
    is covered by test_validate_chezmoi_templates.py.
"""

from __future__ import annotations

import json
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

# The full set of prefs the script enforces on every run, regardless of input.
ENFORCED = {
    "enableTelemetry": False,
    "enableTerminalSandbox": True,
    "toolPermission": "proceed-in-sandbox",
}


def _run(stdin: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=stdin,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    ("stdin", "expected"),
    [
        pytest.param("", ENFORCED, id="empty-stdin"),
        pytest.param("   \n  ", ENFORCED, id="whitespace-only-stdin"),
        pytest.param(
            json.dumps({"trustedWorkspaces": ["/x"]}),
            {**ENFORCED, "trustedWorkspaces": ["/x"]},
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
            {**ENFORCED, "trustedWorkspaces": ["/x"]},
            id="overrides-conflicting-prefs-preserves-runtime",
        ),
    ],
)
def test_merge(stdin: str, expected: dict) -> None:
    """All three prefs are forced; every other key is preserved verbatim."""
    result = _run(stdin)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected


def test_idempotent_on_already_correct_input() -> None:
    """Re-running on its own output is a byte-for-byte no-op (apply idempotency)."""
    first = _run(json.dumps({**ENFORCED, "trustedWorkspaces": ["/x"]}))
    assert first.returncode == 0, first.stderr
    second = _run(first.stdout)
    assert second.returncode == 0, second.stderr
    assert second.stdout == first.stdout


def test_malformed_json_fails_loudly() -> None:
    """Non-empty invalid JSON must error out, not silently discard the file."""
    result = _run("{not valid json")
    assert result.returncode != 0
    assert "settings.json is not valid JSON" in result.stderr
