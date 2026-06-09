#!/usr/bin/env -S uv run --script --no-project
"""
Manages ~/.claude.json (Claude Code per-user config: MCP servers + project trust).

Merges managed MCP server entries and project trust keys into the existing file,
preserving any keys Claude adds at runtime (numStartups, tipsHistory, etc.).

Machine detection mirrors .chezmoi.toml.tmpl:
  IS_RIOT_MACHINE  USER/USERNAME == dfrank
  IS_DARWIN        sys.platform == darwin
  IS_WSL           Linux with Microsoft kernel

Secrets fetched via `op read` (1Password CLI) at apply time.
MCP server / project data mirrors .chezmoidata/{mcp-servers,projects}.yaml.
"""

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

IS_RIOT_MACHINE = os.getenv("USER", os.getenv("USERNAME", "")) == "dfrank"
IS_DARWIN = sys.platform == "darwin"
IS_WSL = sys.platform == "linux" and "microsoft" in platform.uname().release.lower()
HOME = Path.home()


def op_read(path: str) -> str:
    return subprocess.run(
        ["op", "read", path], capture_output=True, text=True, check=True
    ).stdout.strip()


def build_mcp_servers() -> dict:
    if not IS_RIOT_MACHINE:
        return {}
    tf_token = op_read("op://Riot/TrueFoundry - Personal Access Token/credential")
    p4_env = {"P4CHARSET": "utf8", "P4USER": "dfrank"}
    if IS_DARWIN:
        p4_env["P4PORT"] = "PERFLAX01:1666"
    else:
        p4_env["P4PORT"] = "ssl:uegames.p4.riotgames.io:1666"
        p4_env["P4CONFIG"] = ".p4config"
    return {
        "atlassian-rovo": {"type": "http", "url": "https://mcp.atlassian.com/v1/mcp"},
        "datadog": {
            "type": "http",
            "url": "https://mcp.datadoghq.com/api/unstable/mcp-server/mcp",
        },
        "notion": {"type": "http", "url": "https://mcp.notion.com/mcp"},
        "riot-lore": {
            "type": "http",
            "url": "https://riot-lore-beta.rcluster.io/lore/v1/mcp",
        },
        "riot-slack": {
            "type": "http",
            "url": "https://truefoundry.riotgames.io/api/llm/riotgames/mcp/slack-mcp-sandbox/server",
            "headers": {"Authorization": f"Bearer {tf_token}"},
        },
        "p4-mcp": {
            "type": "stdio",
            "command": "uvx",
            "args": ["p4mcp-server", "--allow-usage"],
            "env": p4_env,
        },
    }


def build_project_keys() -> list[str]:
    keys = [str(HOME / ".local/share/chezmoi"), str(HOME / "Code")]
    if IS_RIOT_MACHINE:
        keys.append(str(HOME / ".local/my/riot-slack"))
        if IS_WSL:
            keys += ["/mnt/t/p4/flyingfox/dev-main", "/mnt/t/p4/lion/dev-main"]
    return keys


def main() -> None:
    stdin = sys.stdin.read().strip()
    config = json.loads(stdin) if stdin else {}

    config.setdefault("mcpServers", {}).update(build_mcp_servers())

    projects = config.setdefault("projects", {})
    for key in build_project_keys():
        projects.setdefault(key, {})["hasTrustDialogAccepted"] = True

    print(json.dumps(config, indent=2))


if __name__ == "__main__":
    main()
