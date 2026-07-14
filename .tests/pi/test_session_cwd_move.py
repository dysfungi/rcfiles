"""Runtime regression coverage for Pi's managed ``/cwd`` extension command."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import _clean_env

REPO_ROOT = Path(__file__).resolve().parents[2]
EXTENSION = REPO_ROOT / "dot_pi" / "agent" / "extensions" / "session-cwd-move.ts"
HARNESS = Path(__file__).with_name("session_cwd_move_runtime_harness.mjs")
PI = shutil.which("pi")
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    PI is None or NODE is None,
    reason="Pi CLI and Node.js are required for /cwd runtime coverage",
)


def test_session_cwd_move_handler() -> None:
    """Exercise /cwd handler decisions, SessionManager forks, and real runtime replacement."""
    assert PI is not None
    assert NODE is not None
    package_dir = Path(PI).resolve().parent.parent

    result = subprocess.run(
        [NODE, HARNESS, EXTENSION, package_dir],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        env=_clean_env(),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "session-cwd-move runtime handler harness: ok\n"


def test_pi_auto_discovers_direct_cwd_extension(tmp_path: Path) -> None:
    """A direct extension file needs no settings.json registration."""
    assert PI is not None
    extension_dir = tmp_path / "pi-agent" / "extensions"
    extension_dir.mkdir(parents=True)
    (extension_dir / EXTENSION.name).symlink_to(EXTENSION)

    result = subprocess.run(
        [
            PI,
            "--mode",
            "rpc",
            "--no-session",
            "--no-context-files",
            "--no-skills",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        input='{"id":"commands","type":"get_commands"}\n',
        text=True,
        timeout=30,
        env={
            **_clean_env(),
            "PI_CODING_AGENT_DIR": str(extension_dir.parent),
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
    commands = [
        command
        for command in command_response["data"]["commands"]
        if command["name"] == "cwd"
    ]

    assert len(commands) == 1
    assert commands[0]["source"] == "extension"
    assert Path(commands[0]["sourceInfo"]["path"]).resolve() == EXTENSION
