"""Render Pi role frontmatter from the catalog for both machine namespaces."""

from __future__ import annotations

import copy
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
MANAGED_ROOT = REPO_ROOT / "home"
CATALOG = MANAGED_ROOT / ".chezmoidata" / "large-language-models.yaml"
VALIDATE_TEMPLATE = MANAGED_ROOT / ".chezmoitemplates" / "llm" / "validate.tmpl"
AGENTS_DIR = MANAGED_ROOT / "dot_pi" / "agent" / "agents"
ROLE_NAMES = ("planner", "worker", "scout", "reviewer")


def _clean_environment() -> dict[str, str]:
    """Prevent inherited Git routing from changing template subprocess behavior."""
    return {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }


def _render_agents(source: Path, tmp_path: Path, machine: str) -> dict[str, str]:
    """Render every managed role's ``model`` frontmatter value."""
    config = tmp_path / f"{machine}.toml"
    config.write_text(f"[data]\nis_riot_machine = {str(machine == 'riot').lower()}\n")
    models: dict[str, str] = {}
    for role in ROLE_NAMES:
        template = source / "home" / "dot_pi" / "agent" / "agents" / f"{role}.md.tmpl"
        result = subprocess.run(
            [
                "chezmoi",
                "execute-template",
                "--config",
                str(config),
                "--source",
                str(source),
                "--file",
                str(template),
            ],
            cwd=source,
            capture_output=True,
            text=True,
            env=_clean_environment(),
        )
        assert result.returncode == 0, result.stderr
        frontmatter = result.stdout.split("---", 2)[1]
        models[role] = next(
            line.removeprefix("model: ")
            for line in frontmatter.splitlines()
            if line.startswith("model: ")
        )
    return models


def _fixture_source(tmp_path: Path, catalog: dict[str, object]) -> Path:
    """Build the minimal standalone source needed to render role templates."""
    source = tmp_path / "source"
    (source / "home" / ".chezmoidata").mkdir(parents=True)
    (source / "home" / ".chezmoitemplates" / "llm").mkdir(parents=True)
    (source / "home" / "dot_pi" / "agent" / "agents").mkdir(parents=True)
    (source / ".chezmoiroot").write_text("home\n")
    (source / "home" / ".chezmoidata" / CATALOG.name).write_text(
        yaml.safe_dump(catalog, sort_keys=False)
    )
    shutil.copy2(
        VALIDATE_TEMPLATE,
        source / "home" / ".chezmoitemplates" / "llm" / VALIDATE_TEMPLATE.name,
    )
    for role in ROLE_NAMES:
        shutil.copy2(
            AGENTS_DIR / f"{role}.md.tmpl",
            source / "home" / "dot_pi" / "agent" / "agents" / f"{role}.md.tmpl",
        )
    return source


@pytest.mark.parametrize(
    ("machine", "expected"),
    [
        (
            "personal",
            {
                "planner": "claude-opus-4-8",
                "worker": "claude-opus-4-8",
                "scout": "claude-sonnet-5",
                "reviewer": "claude-sonnet-5",
            },
        ),
        (
            "riot",
            {
                "planner": "openai/openai/gpt-5.6-terra",
                "worker": "openai/openai/gpt-5.6-terra",
                "scout": "openai/openai/gpt-5.6-luna",
                "reviewer": "openai/openai/gpt-5.6-luna",
            },
        ),
    ],
    ids=["personal-builtins", "riot-gateways"],
)
def test_role_models_render_builtins_or_canonical_gateway_scopes(
    tmp_path: Path, machine: str, expected: dict[str, str]
) -> None:
    """Built-ins remain bare while gateway models have their provider scope."""
    assert _render_agents(REPO_ROOT, tmp_path, machine) == expected


def test_gateway_backed_role_fixture_uses_canonical_scope(tmp_path: Path) -> None:
    """A gateway role assignment never falls back to the ambiguous raw model ID."""
    catalog = copy.deepcopy(yaml.safe_load(CATALOG.read_text()))
    models = catalog["my"]["llm"]["models"]
    for model in models:
        model.pop("subagent_roles", None)
    gateway_model = next(model for model in models if "gateway" in model)
    gateway_model["subagent_roles"] = list(ROLE_NAMES)

    source = _fixture_source(tmp_path, catalog)
    expected = f"{gateway_model['gateway']['provider']}/{gateway_model['id']}"
    assert _render_agents(source, tmp_path, "personal") == dict.fromkeys(
        ROLE_NAMES, expected
    )
