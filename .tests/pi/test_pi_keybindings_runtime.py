"""Runtime coverage for Pi's managed Ctrl+[ cancellation bindings.

The test renders the chezmoi template only to install a keybindings file in an
isolated temporary agent directory. The Node harness imports Pi's installed
internal manager by absolute path and asserts real raw-key matching; Python
never inspects the rendered JSON as a template-content assertion.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANAGED_ROOT = REPO_ROOT / "home"
MISE_CONFIG = REPO_ROOT / ".mise.toml"
TEMPLATE = MANAGED_ROOT / "dot_pi" / "agent" / "keybindings.json.tmpl"
HARNESS = Path(__file__).with_name("keybindings_runtime_harness.mjs")
PI_MISE_TOOL = "npm:@earendil-works/pi-coding-agent"
PI_VERSION = "0.80.6"

pytestmark = pytest.mark.slow


def _clean_environment() -> dict[str, str]:
    """Keep project tooling while removing parent Git routing state."""
    return {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        env=_clean_environment(),
    )
    assert result.returncode == 0, (
        f"command: {command!r}\n"
        f"stdout:\n{result.stdout or '<empty>'}\n"
        f"stderr:\n{result.stderr or '<empty>'}"
    )
    return result


def _mise() -> str:
    mise = shutil.which("mise")
    assert mise is not None, "Pi keybindings runtime coverage requires mise"
    return mise


def _pi_package_root() -> Path:
    tools = tomllib.loads(MISE_CONFIG.read_text(encoding="utf-8"))["tools"]
    assert tools[PI_MISE_TOOL] == PI_VERSION

    install_root = Path(_run([_mise(), "where", PI_MISE_TOOL]).stdout.strip())
    package_root = (
        install_root / "lib" / "node_modules" / "@earendil-works" / "pi-coding-agent"
    )
    assert package_root.is_dir(), f"missing installed Pi package: {package_root}"
    installed = json.loads((package_root / "package.json").read_text(encoding="utf-8"))
    assert installed["version"] == PI_VERSION
    return package_root


def _render_keybindings(agent_dir: Path, tmp_path: Path) -> None:
    config = tmp_path / "chezmoi.toml"
    config.write_text("", encoding="utf-8")
    rendered = _run(
        [
            _mise(),
            "exec",
            "--",
            "chezmoi",
            "execute-template",
            "--config",
            str(config),
            "--source",
            str(REPO_ROOT),
            "--file",
            str(TEMPLATE),
        ]
    )
    agent_dir.mkdir()
    (agent_dir / "keybindings.json").write_text(rendered.stdout, encoding="utf-8")


def test_pi_keybindings_match_raw_escape_ctrl_c_and_csi_u_ctrl_bracket(
    tmp_path: Path,
) -> None:
    """Exercise the pinned manager against a rendered, isolated agent config."""
    package_root = _pi_package_root()
    agent_dir = tmp_path / "agent"
    _render_keybindings(agent_dir, tmp_path)

    node = Path(_run([_mise(), "which", "node"]).stdout.strip())
    assert node.is_file(), f"missing mise-managed Node executable: {node}"
    result = _run(
        [str(node), str(HARNESS), str(agent_dir), str(package_root), PI_VERSION]
    )
    assert result.stdout == "Pi keybindings runtime harness: ok\n"
