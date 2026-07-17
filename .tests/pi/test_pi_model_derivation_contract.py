"""Verify Pi model derivation and catalog validation with synthetic fixtures.

The tests render Pi's production model template and validation partial with a
small independent catalog. They pin contracts that schema validation alone
cannot express, plus the schema hook's structural guarantees, without coupling
to the managed catalog's changing model inventory.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS_TEMPLATE = REPO_ROOT / "home/dot_pi/agent/private_models.json.tmpl"
VALIDATION_TEMPLATE = REPO_ROOT / "home/.chezmoitemplates/llm/validate.tmpl"
SCHEMA = REPO_ROOT / ".schemas/large-language-models.schema.yaml"
_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
_THINKING_MAP = {level: ("native" if level == "high" else None) for level in _LEVELS}


def _write_fake_op(bin_dir: Path) -> None:
    op = bin_dir / "op"
    op.write_text("#!/bin/sh\nprintf '%s' fixture-token\n")
    op.chmod(0o755)


def _fixture_catalog(
    *,
    reasoning: bool = False,
    thinking_level_map: dict[str, str | None] | None = None,
    one_m: bool = False,
) -> dict[str, Any]:
    roles = ("scout", "planner", "reviewer", "worker")
    models: list[dict[str, object]] = []
    for role in roles:
        model: dict[str, object] = {
            "id": f"fixture-{role}",
            "vendor": "openai",
            "ctx": 1,
            "max_tokens": 1,
            "cost": {"input": 0, "output": 0},
            "enabled": True,
            "roles": [role],
        }
        if role == "scout":
            model["gateway"] = {
                "provider": "fixture",
                "name": "Fixture",
                "base_url": "https://example.invalid/v1",
                "api": "openai-completions",
                "api_key_op": "op://fixture/token",
            }
            model["reasoning"] = reasoning
            if thinking_level_map is not None:
                model["thinking_level_map"] = thinking_level_map
            if one_m:
                model["one_m"] = True
        models.append(model)

    return {
        "default_thinking_level": "high",
        "my": {"llm": {"models": models}},
        "riot": {"llm": {"models": []}},
    }


def _fixture_source(tmp_path: Path, catalog: dict[str, Any]) -> Path:
    source = tmp_path / "source"
    (source / ".chezmoidata").mkdir(parents=True)
    (source / ".chezmoitemplates/llm").mkdir(parents=True)
    (source / "dot_pi/agent").mkdir(parents=True)
    (source / ".chezmoidata/large-language-models.yaml").write_text(
        yaml.safe_dump(catalog, sort_keys=False)
    )
    shutil.copy2(VALIDATION_TEMPLATE, source / ".chezmoitemplates/llm/validate.tmpl")
    shutil.copy2(MODELS_TEMPLATE, source / "dot_pi/agent/private_models.json.tmpl")
    return source


def _clean_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("GIT_", "CHEZMOI_", "OP_SERVICE_ACCOUNT_TOKEN"))
    }


def _render_models(source: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_op(bin_dir)
    config = tmp_path / "chezmoi.toml"
    config.write_text("[data]\nis_riot_machine = false\n")
    environment = _clean_environment()
    environment["PATH"] = f"{bin_dir}{os.pathsep}{environment['PATH']}"
    return subprocess.run(
        [
            "chezmoi",
            "execute-template",
            "--config",
            str(config),
            "--source",
            str(source),
            "--file",
            str(source / "dot_pi/agent/private_models.json.tmpl"),
        ],
        capture_output=True,
        text=True,
        env=environment,
    )


def _fixture_model(catalog: dict[str, Any]) -> dict[str, Any]:
    return catalog["my"]["llm"]["models"][0]


def test_non_reasoning_model_omits_thinking_map(tmp_path: Path) -> None:
    """A custom model without reasoning metadata remains valid and unambiguous."""
    source = _fixture_source(tmp_path, _fixture_catalog())
    result = _render_models(source, tmp_path)

    assert result.returncode == 0, result.stderr
    model = json.loads(result.stdout)["providers"]["fixture"]["models"][0]
    assert model["reasoning"] is False
    assert "thinkingLevelMap" not in model


def test_one_m_variant_inherits_base_thinking_map(tmp_path: Path) -> None:
    """A generated 1M model retains its base model's reasoning ceiling."""
    source = _fixture_source(
        tmp_path,
        _fixture_catalog(
            reasoning=True,
            thinking_level_map=_THINKING_MAP,
            one_m=True,
        ),
    )
    result = _render_models(source, tmp_path)

    assert result.returncode == 0, result.stderr
    models = {
        model["id"]: model
        for model in json.loads(result.stdout)["providers"]["fixture"]["models"]
    }
    assert (
        models["fixture-scout[1m]"]["thinkingLevelMap"]
        == models["fixture-scout"]["thinkingLevelMap"]
    )


@pytest.mark.parametrize(
    ("reasoning", "thinking_level_map", "expected"),
    [
        pytest.param(
            True, None, "needs thinking_level_map", id="reasoning-missing-map"
        ),
        pytest.param(
            True,
            {"high": "native"},
            'thinking_level_map is missing "off"',
            id="reasoning-incomplete-map",
        ),
        pytest.param(
            False,
            _THINKING_MAP,
            "must not declare thinking_level_map",
            id="non-reasoning-map-prohibited",
        ),
    ],
)
def test_template_rejects_invalid_thinking_map_contracts(
    tmp_path: Path,
    reasoning: bool,
    thinking_level_map: dict[str, str | None] | None,
    expected: str,
) -> None:
    """The validation partial rejects conditional map-contract violations."""
    source = _fixture_source(
        tmp_path,
        _fixture_catalog(
            reasoning=reasoning,
            thinking_level_map=thinking_level_map,
        ),
    )
    result = _render_models(source, tmp_path)

    assert result.returncode != 0
    assert expected in result.stderr


def test_template_allows_missing_role_assignments(tmp_path: Path) -> None:
    """An absent role lets the consumer fall back to its session model."""
    catalog = _fixture_catalog()
    _fixture_model(catalog).pop("roles")

    result = _render_models(_fixture_source(tmp_path, catalog), tmp_path)

    assert result.returncode == 0, result.stderr


def test_template_rejects_ambiguous_effort_qualified_roles(tmp_path: Path) -> None:
    """Effort variants still compete for one base role assignment."""
    catalog = _fixture_catalog()
    models = catalog["my"]["llm"]["models"]
    models[0]["roles"].append("plan:high")
    models[1]["roles"].append("plan:low")

    result = _render_models(_fixture_source(tmp_path, catalog), tmp_path)

    assert result.returncode != 0
    assert '2 enabled models claim roles "plan"' in result.stderr


@pytest.mark.parametrize(
    ("role", "valid"),
    [
        pytest.param("plan:high", True, id="omp-role-effort-is-valid"),
        pytest.param("scout:high", False, id="pi-role-effort-is-rejected"),
    ],
)
def test_schema_hook_limits_effort_to_omp_roles(
    tmp_path: Path, role: str, valid: bool
) -> None:
    """Only OMP's role vocabulary may carry an effort suffix."""
    catalog = _fixture_catalog()
    _fixture_model(catalog)["roles"].append(role)

    result = _schema_result(tmp_path, catalog)

    assert (result.returncode == 0) is valid, result.stdout + result.stderr


def _schema_result(
    tmp_path: Path, catalog: dict[str, Any]
) -> subprocess.CompletedProcess[str]:
    root = tmp_path / "schema-repo"
    (root / ".chezmoidata").mkdir(parents=True)
    (root / ".schemas").mkdir()
    catalog_path = root / ".chezmoidata/large-language-models.yaml"
    catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False))
    shutil.copy2(SCHEMA, root / ".schemas/large-language-models.schema.yaml")
    config = root / ".pre-commit-config.yaml"
    config.write_text(
        """repos:
  - repo: https://github.com/python-jsonschema/check-jsonschema
    rev: 0.33.0
    hooks:
      - id: check-jsonschema
        args: [--schemafile, .schemas/large-language-models.schema.yaml]
"""
    )
    environment = _clean_environment()
    subprocess.run(
        ["git", "init"], cwd=root, check=True, capture_output=True, env=environment
    )
    return subprocess.run(
        [
            "pre-commit",
            "run",
            "--config",
            str(config),
            "check-jsonschema",
            "--files",
            str(catalog_path),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        env=environment,
    )


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        pytest.param(
            lambda catalog: _fixture_model(catalog).update(
                {"thinking_level_map": {"high": "native"}}
            ),
            "off",
            id="incomplete-map",
        ),
        pytest.param(
            lambda catalog: _fixture_model(catalog)["thinking_level_map"].update(
                {"unexpected": "native"}
            ),
            "unexpected",
            id="unknown-map-key",
        ),
        pytest.param(
            lambda catalog: catalog.pop("default_thinking_level"),
            "default_thinking_level",
            id="missing-default-level",
        ),
        pytest.param(
            lambda catalog: catalog.update({"default_thinking_level": "invalid"}),
            "invalid",
            id="invalid-default-level",
        ),
    ],
)
def test_schema_hook_rejects_invalid_thinking_metadata(
    tmp_path: Path,
    mutate: Any,
    expected: str,
) -> None:
    """The configured schema hook rejects malformed maps and defaults."""
    catalog = _fixture_catalog(reasoning=True, thinking_level_map=_THINKING_MAP)
    mutate(catalog)
    result = _schema_result(tmp_path, catalog)

    assert result.returncode != 0
    assert expected in result.stdout + result.stderr
