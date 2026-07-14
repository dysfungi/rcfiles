"""Tests for dot_claude/executable_statusline.py — context-window color thresholds.

Subprocess-driven: feeds JSON on stdin and checks that the ctx:NN% segment in
the output carries the expected ANSI color code (or none) based on CTX_WARN_PCT
and CTX_CRIT_PCT defined in the script.

Note: the statusline also calls git and tmux; we set TMUX="" and cwd to a
non-git dir so those calls fail silently (the script handles missing output).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "dot_claude" / "executable_statusline.py"

assert SCRIPT.exists(), f"statusline script not found at {SCRIPT}"

_ANSI_YELLOW = "\033[33m"
_ANSI_RED = "\033[31m"
_ANSI_RESET = "\033[0m"


def _run_statusline(used_pct: float | None, tmp_path: Path) -> str:
    """Run the statusline with the given context usage and return stdout."""
    payload: dict = {
        "cwd": str(tmp_path),
        "model": {"display_name": "TestModel"},
    }
    if used_pct is not None:
        payload["context_window"] = {"used_percentage": used_pct}

    env = {**os.environ, "TMUX": "", "HOME": str(tmp_path)}
    result = subprocess.run(
        ["python3", str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, (
        f"statusline exited {result.returncode}: {result.stderr!r}"
    )
    return result.stdout


# (pct, expect_yellow, expect_red, description)
_THRESHOLD_CASES = [
    (0, False, False, "0% — default color"),
    (19, False, False, "19% — just below warn threshold"),
    (20, True, False, "20% — exactly at warn threshold (yellow)"),
    (22, True, False, "22% — between warn and crit (yellow)"),
    (24, True, False, "24% — just below crit threshold (yellow)"),
    (25, False, True, "25% — exactly at crit threshold (red)"),
    (50, False, True, "50% — well above crit (red)"),
    (100, False, True, "100% — full context (red)"),
]


@pytest.fixture(autouse=True)
def configure_thresholds(monkeypatch):
    monkeypatch.setenv("CTX_WARN_PCT", "20")
    monkeypatch.setenv("CTX_CRIT_PCT", "25")


@pytest.mark.parametrize(
    "pct,expect_yellow,expect_red,desc",
    _THRESHOLD_CASES,
    ids=[c[3] for c in _THRESHOLD_CASES],
)
def test_ctx_color_thresholds(
    pct: int, expect_yellow: bool, expect_red: bool, desc: str, tmp_path: Path
) -> None:
    """ctx:NN% carries the correct ANSI color (or none) for each threshold."""
    output = _run_statusline(float(pct), tmp_path)

    if expect_red:
        assert _ANSI_RED in output, f"[{desc}] Expected red ANSI in output:\n{output!r}"
        assert _ANSI_YELLOW not in output, (
            f"[{desc}] Expected no yellow ANSI when red is shown:\n{output!r}"
        )
    elif expect_yellow:
        assert _ANSI_YELLOW in output, (
            f"[{desc}] Expected yellow ANSI in output:\n{output!r}"
        )
        assert _ANSI_RED not in output, (
            f"[{desc}] Expected no red ANSI when yellow is shown:\n{output!r}"
        )
    else:
        assert _ANSI_YELLOW not in output, (
            f"[{desc}] Expected no color ANSI in output:\n{output!r}"
        )
        assert _ANSI_RED not in output, (
            f"[{desc}] Expected no color ANSI in output:\n{output!r}"
        )

    # The ctx: token should always appear regardless of color.
    assert f"ctx:{pct}%" in output, (
        f"[{desc}] Expected 'ctx:{pct}%' in output:\n{output!r}"
    )

    # The model name should never be colored.
    assert _ANSI_RED + "TestModel" not in output, "Model name should not be colored"
    assert _ANSI_YELLOW + "TestModel" not in output, "Model name should not be colored"


def test_no_ctx_when_used_absent(tmp_path: Path) -> None:
    """When context_window is absent, ctx: token is not emitted."""
    output = _run_statusline(None, tmp_path)
    assert "ctx:" not in output
    # No ANSI colors either (nothing to color).
    assert _ANSI_YELLOW not in output
    assert _ANSI_RED not in output
