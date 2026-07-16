"""Behavioral coverage for Pi plan-mode command ownership and handlers.

The Node harness loads the real TypeScript extensions through Pi's bundled Jiti
loader, captures their public ``ExtensionAPI`` registrations, and invokes the
handlers with controlled extension contexts. A real Pi RPC command listing then
verifies that the ``/implement`` prompt template is not shadowed. Neither path
starts an LLM turn or depends on source-text assertions.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANAGED_ROOT = REPO_ROOT / "home"
EXTENSION = MANAGED_ROOT / "dot_pi" / "agent" / "extensions" / "plan-mode" / "index.ts"
QUESTIONNAIRE = MANAGED_ROOT / "dot_pi" / "agent" / "extensions" / "questionnaire.ts"
IMPLEMENT_PROMPT = MANAGED_ROOT / "dot_pi" / "agent" / "prompts" / "implement.md"
HARNESS = Path(__file__).with_name("plan_mode_runtime_harness.mjs")
PI = shutil.which("pi")
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    PI is None or NODE is None,
    reason="Pi CLI and Node.js are required for plan-mode runtime coverage",
)


def test_plan_mode_command_handlers() -> None:
    """Exercise registered command and context handlers without an LLM run."""
    assert PI is not None
    assert NODE is not None
    package_dir = Path(PI).resolve().parent.parent

    result = subprocess.run(
        [NODE, HARNESS, EXTENSION, QUESTIONNAIRE, package_dir],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        env={
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_") and key != "PI_SUBAGENT"
        },
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "plan-mode runtime handler harness: ok\n"


def test_implement_resolves_to_canonical_prompt_template(tmp_path: Path) -> None:
    """Verify Pi discovers the managed ``/implement`` template without shadowing it."""
    assert PI is not None
    prompt_path = tmp_path / "pi-agent" / "prompts" / "implement.md"
    prompt_path.parent.mkdir(parents=True)
    prompt_path.symlink_to(IMPLEMENT_PROMPT)

    result = subprocess.run(
        [
            PI,
            "--mode",
            "rpc",
            "--no-session",
            "--no-context-files",
            "--no-extensions",
            "-e",
            EXTENSION,
            "--no-skills",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        input='{"id":"commands","type":"get_commands"}\n',
        text=True,
        timeout=30,
        env={
            **{
                key: value
                for key, value in os.environ.items()
                if not key.startswith("GIT_") and key != "PI_SUBAGENT"
            },
            "PI_CODING_AGENT_DIR": str(prompt_path.parent.parent),
            "PI_OFFLINE": "1",
        },
    )

    assert result.returncode == 0, result.stderr
    responses = [
        json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")
    ]
    command_response = next(
        response for response in responses if response.get("id") == "commands"
    )
    implement_commands = [
        command
        for command in command_response["data"]["commands"]
        if command["name"] == "implement"
    ]

    assert len(implement_commands) == 1
    assert implement_commands[0]["source"] == "prompt"
    assert (
        Path(implement_commands[0]["sourceInfo"]["path"]).resolve() == IMPLEMENT_PROMPT
    )
