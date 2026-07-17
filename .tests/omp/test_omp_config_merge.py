"""Integration tests for OMP's state-preserving ``modify_`` config script.

Chezmoi renders the catalog-derived settings into the script, then invokes it
with OMP's current YAML on stdin. These tests exercise that rendered script as
chezmoi does, including a catalog role disappearing between applies.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "home/dot_omp/agent/modify_config.yml.py.tmpl"
VALIDATOR = REPO_ROOT / "home/.chezmoitemplates/llm/validate.tmpl"
BUILTIN_MODEL_ROLE_NAMES = (
    "default",
    "smol",
    "slow",
    "plan",
    "commit",
    "vision",
    "designer",
    "tiny",
    "task",
    "advisor",
)


def _clean_environment() -> dict[str, str]:
    """Prevent parent chezmoi/Git state from affecting subprocesses."""
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("CHEZMOI_", "GIT_"))
    }


def _catalog(roles: list[str]) -> dict[str, Any]:
    """Return an independent catalog with one enabled OMP-capable model."""
    return {
        "default_thinking_level": "high",
        "my": {
            "llm": {
                "models": [
                    {
                        "id": "fixture/model",
                        "vendor": "openai",
                        "enabled": True,
                        "roles": roles,
                    }
                ]
            }
        },
        "riot": {"llm": {"models": []}},
    }


def _render_script(tmp_path: Path, catalog: dict[str, Any]) -> Path:
    """Render the production merger against a self-contained catalog fixture."""
    source = tmp_path / "source"
    script = source / "home/dot_omp/agent" / SCRIPT.name
    validator = source / "llm/validate.tmpl"
    script.parent.mkdir(parents=True)
    validator.parent.mkdir(parents=True)
    shutil.copy2(SCRIPT, script)
    shutil.copy2(VALIDATOR, validator)

    config = tmp_path / "chezmoi.toml"
    config.write_text("[data]\nis_riot_machine = false\n")
    catalog_path = source / ".chezmoidata/large-language-models.yaml"
    catalog_path.parent.mkdir()
    catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False))

    rendered = tmp_path / "modify_config.py"
    result = subprocess.run(
        [
            "chezmoi",
            "execute-template",
            "--config",
            str(config),
            "--source",
            str(source),
            "--file",
            str(script),
        ],
        cwd=source,
        capture_output=True,
        text=True,
        env=_clean_environment(),
    )
    assert result.returncode == 0, result.stderr
    rendered.write_text(result.stdout)
    rendered.chmod(0o755)
    return rendered


def _run(script: Path, stdin: str) -> subprocess.CompletedProcess[str]:
    """Run the rendered PEP 723 script through its production shebang."""
    return subprocess.run(
        [str(script)],
        input=stdin,
        capture_output=True,
        text=True,
        env=_clean_environment(),
    )


def test_reconciles_every_builtin_model_role(tmp_path: Path) -> None:
    """Every OMP built-in role resolves from the catalog in one merge."""
    script = _render_script(tmp_path, _catalog(list(BUILTIN_MODEL_ROLE_NAMES)))
    result = _run(script, "modelRoles:\n  custom: user/model\n")

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(result.stdout)["modelRoles"] == {
        **{role: "fixture/model" for role in BUILTIN_MODEL_ROLE_NAMES},
        "custom": "user/model",
    }
    assert "WARNING:" not in result.stderr


def test_reconciles_builtin_roles_and_preserves_unmanaged_state(
    tmp_path: Path,
) -> None:
    """A vanished catalog role is removed without touching custom OMP state."""
    initial_script = _render_script(tmp_path / "initial", _catalog(["smol"]))
    initial = _run(
        initial_script,
        """modelRoles:
  smol: stale/model
  custom: user/model
tools:
  approval:
    bash: ask
""",
    )
    assert initial.returncode == 0, initial.stderr
    initial_config = yaml.safe_load(initial.stdout)
    assert initial_config["modelRoles"] == {
        "smol": "fixture/model",
        "custom": "user/model",
    }
    assert initial_config["tools"]["approval"]["bash"] == "ask"

    removed_script = _render_script(tmp_path / "removed", _catalog([]))
    removed = _run(removed_script, initial.stdout)
    assert removed.returncode == 0, removed.stderr
    merged = yaml.safe_load(removed.stdout)
    assert merged["modelRoles"] == {"custom": "user/model"}
    assert "WARNING: modelRoles.smol has no backing model, removing\n" in removed.stderr


def test_omits_empty_model_roles_mapping(tmp_path: Path) -> None:
    """No catalog or custom role leaves OMP's default empty mapping implicit."""
    script = _render_script(tmp_path, _catalog([]))
    result = _run(script, "modelRoles:\n  vision: stale/model\n")

    assert result.returncode == 0, result.stderr
    assert "modelRoles" not in yaml.safe_load(result.stdout)
    assert (
        "WARNING: modelRoles.vision has no backing model, removing\n" in result.stderr
    )


def test_empty_stdin_is_a_valid_new_omp_config(tmp_path: Path) -> None:
    """A first apply can initialize config state when OMP has not written YAML."""
    result = _run(_render_script(tmp_path, _catalog(["default"])), "")

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(result.stdout)["modelRoles"] == {"default": "fixture/model"}


def test_malformed_yaml_fails_loudly_without_a_traceback(tmp_path: Path) -> None:
    """Invalid persisted OMP state is reported instead of being overwritten."""
    result = _run(_render_script(tmp_path, _catalog([])), "modelRoles: [broken")

    assert result.returncode != 0
    assert result.stdout == ""
    assert "omp config.yml: invalid YAML:" in result.stderr
    assert "Traceback" not in result.stderr
