"""End-to-end rendering and validation tests for Pi custom model metadata.

The central LLM catalog declares Pi's logical thinking levels. These tests render
``private_models.json.tmpl`` through chezmoi with a fake 1Password CLI, so the
catalog, shared template guard, and generated Pi JSON are exercised together.
They also invoke the configured JSON-schema hook against malformed temporary
catalogs: structural and conditional contracts must fail before apply.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG = REPO_ROOT / ".chezmoidata" / "large-language-models.yaml"
SCHEMA = REPO_ROOT / ".schemas" / "large-language-models.schema.yaml"
MODELS_TEMPLATE = REPO_ROOT / "dot_pi" / "agent" / "private_models.json.tmpl"
VALIDATE_TEMPLATE = REPO_ROOT / ".chezmoitemplates" / "llm" / "validate.tmpl"
LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
OPENAI_GPT_5_6_MAP = {
    "off": "none",
    "minimal": "minimal",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "max",
}
ANTHROPIC_STANDARD_MAP = {
    "off": "disabled",
    "minimal": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": None,
    "max": None,
}
ANTHROPIC_OPUS_4_6_MAP = {
    "off": "disabled",
    "minimal": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": None,
    "max": "max",
}
ANTHROPIC_PREMIUM_MAP = {
    "off": "disabled",
    "minimal": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "max",
}
GOOGLE_PRO_MAP = {
    "off": None,
    "minimal": None,
    "low": "LOW",
    "medium": None,
    "high": "HIGH",
    "xhigh": None,
    "max": None,
}
GOOGLE_FLASH_MAP = {
    "off": None,
    "minimal": "MINIMAL",
    "low": "LOW",
    "medium": "MEDIUM",
    "high": "HIGH",
    "xhigh": None,
    "max": None,
}
GOOGLE_PRO_OPENAI_MAP = {
    "off": None,
    "minimal": None,
    "low": "low",
    "medium": None,
    "high": "high",
    "xhigh": None,
    "max": None,
}
GOOGLE_FLASH_OPENAI_MAP = {
    "off": None,
    "minimal": "minimal",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": None,
    "max": None,
}


def _clean_environment() -> dict[str, str]:
    """Avoid a caller's Git routing while subprocesses use temporary sources."""
    return {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }


def _write_fake_op(bin_dir: Path) -> None:
    """Supply deterministic secret material without reading a real vault."""
    op = bin_dir / "op"
    op.write_text("#!/bin/sh\nprintf '%s' fake-token\n")
    op.chmod(0o755)


def _render_models(source: Path, tmp_path: Path, machine: str) -> dict[str, Any]:
    """Render the private template as chezmoi does for one machine namespace."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_op(bin_dir)
    config = tmp_path / "chezmoi.toml"
    config.write_text(f"[data]\nis_riot_machine = {str(machine == 'riot').lower()}\n")
    environment = _clean_environment()
    # Account-mode onepasswordRead uses the fake CLI; a service-account token
    # inherited from mise conflicts with that mode before `op` is invoked.
    environment.pop("OP_SERVICE_ACCOUNT_TOKEN", None)
    environment["PATH"] = f"{bin_dir}{os.pathsep}{environment['PATH']}"
    result = subprocess.run(
        [
            "chezmoi",
            "execute-template",
            "--config",
            str(config),
            "--source",
            str(source),
            "--file",
            str(source / "dot_pi" / "agent" / "private_models.json.tmpl"),
        ],
        cwd=source,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _models_by_id(rendered: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten Pi providers to their provider-qualified model identities."""
    return {
        f"{provider_id}/{model['id']}": model
        for provider_id, provider in rendered["providers"].items()
        for model in provider["models"]
    }


def _fixture_source(tmp_path: Path, catalog: dict[str, Any]) -> Path:
    """Build the minimal source tree required to render a catalog fixture."""
    source = tmp_path / "source"
    (source / ".chezmoidata").mkdir(parents=True)
    (source / ".chezmoitemplates" / "llm").mkdir(parents=True)
    (source / "dot_pi" / "agent").mkdir(parents=True)
    (source / ".chezmoidata" / CATALOG.name).write_text(
        yaml.safe_dump(catalog, sort_keys=False)
    )
    shutil.copy2(
        VALIDATE_TEMPLATE, source / ".chezmoitemplates" / "llm" / "validate.tmpl"
    )
    shutil.copy2(MODELS_TEMPLATE, source / "dot_pi" / "agent" / MODELS_TEMPLATE.name)
    return source


@pytest.fixture(scope="session")
def catalog_data() -> dict[str, Any]:
    """Load the production catalog with YAML aliases resolved for mutation."""
    return yaml.safe_load(CATALOG.read_text())


@pytest.fixture(params=["personal", "riot"])
def rendered_models(
    request: pytest.FixtureRequest, tmp_path: Path
) -> tuple[str, dict[str, Any]]:
    """Render both supported machine namespaces with fake credentials."""
    machine = request.param
    return machine, _render_models(REPO_ROOT, tmp_path, machine)


def test_reasoning_models_emit_complete_capability_maps(
    rendered_models: tuple[str, dict[str, Any]],
) -> None:
    """Every rendered reasoning model exposes every logical level explicitly."""
    _, rendered = rendered_models
    for qualified_id, model in _models_by_id(rendered).items():
        assert model["reasoning"] is True, qualified_id
        assert set(model["thinkingLevelMap"]) == set(LEVELS), qualified_id


def test_rendered_capability_maps_match_each_model_family(
    rendered_models: tuple[str, dict[str, Any]],
) -> None:
    """Every custom model and generated 1M variant has its exact native map."""
    machine, rendered = rendered_models
    models = _models_by_id(rendered)
    actual = {model_id: model["thinkingLevelMap"] for model_id, model in models.items()}
    expected: dict[str, Mapping[str, str | None]]
    if machine == "personal":
        expected = {
            "google/gemini-3.1-pro-preview": GOOGLE_PRO_MAP,
            "google/gemini-3.5-flash": GOOGLE_FLASH_MAP,
            "google/gemini-3.1-flash-lite": GOOGLE_FLASH_MAP,
        }
    else:
        expected = {
            "openai/openai/gpt-5.6-terra": OPENAI_GPT_5_6_MAP,
            "openai/openai/gpt-5.6-luna": OPENAI_GPT_5_6_MAP,
            "truefoundry/claude-vertex/anthropic-claude-opus-4-8": ANTHROPIC_PREMIUM_MAP,
            "truefoundry/claude-vertex/anthropic-claude-opus-4-8[1m]": ANTHROPIC_PREMIUM_MAP,
            "truefoundry/claude-vertex/anthropic-claude-sonnet-5": ANTHROPIC_PREMIUM_MAP,
            "truefoundry/claude-vertex/anthropic-claude-sonnet-5[1m]": ANTHROPIC_PREMIUM_MAP,
            "openai/google-vertexai/gemini-3.1-pro-preview": GOOGLE_PRO_OPENAI_MAP,
            "openai/google-vertexai/gemini-3.5-flash": GOOGLE_FLASH_OPENAI_MAP,
            "openai/google-vertexai/gemini-3.1-flash-lite-preview": GOOGLE_FLASH_OPENAI_MAP,
        }
    assert actual == expected


def test_direct_google_and_openai_responses_maps_are_distinct(
    rendered_models: tuple[str, dict[str, Any]],
) -> None:
    """Direct Google uses native uppercase values; Responses uses effort strings."""
    machine, rendered = rendered_models
    models = _models_by_id(rendered)
    if machine == "personal":
        assert (
            models["google/gemini-3.1-pro-preview"]["thinkingLevelMap"]
            == GOOGLE_PRO_MAP
        )
        assert models["google/gemini-3.5-flash"]["thinkingLevelMap"] == GOOGLE_FLASH_MAP
    else:
        assert (
            models["openai/google-vertexai/gemini-3.1-pro-preview"]["thinkingLevelMap"]
            == GOOGLE_PRO_OPENAI_MAP
        )
        assert (
            models["openai/google-vertexai/gemini-3.5-flash"]["thinkingLevelMap"]
            == GOOGLE_FLASH_OPENAI_MAP
        )
        assert (
            models["openai/openai/gpt-5.6-terra"]["thinkingLevelMap"]
            == OPENAI_GPT_5_6_MAP
        )


def test_one_m_variants_inherit_their_base_capability_map(
    rendered_models: tuple[str, dict[str, Any]],
) -> None:
    """Generated 1M variants must not silently drop their base model ceiling."""
    machine, rendered = rendered_models
    if machine != "riot":
        return

    models = _models_by_id(rendered)
    for base_id in (
        "truefoundry/claude-vertex/anthropic-claude-opus-4-8",
        "truefoundry/claude-vertex/anthropic-claude-sonnet-5",
    ):
        assert (
            models[f"{base_id}[1m]"]["thinkingLevelMap"]
            == models[base_id]["thinkingLevelMap"]
        )


def test_riot_default_resolves_to_a_generated_custom_model(
    rendered_models: tuple[str, dict[str, Any]],
) -> None:
    """The Riot default keeps its canonical provider-qualified catalog identity."""
    machine, rendered = rendered_models
    if machine != "riot":
        return

    assert "openai/openai/gpt-5.6-terra" in _models_by_id(rendered)


def test_dormant_riot_models_render_with_declared_capabilities(
    catalog_data: dict[str, Any], tmp_path: Path
) -> None:
    """Dormant custom models become fully configured when enabled."""
    catalog = copy.deepcopy(catalog_data)
    catalog_models = catalog["riot"]["llm"]["models"]
    dormant_gateway_ids = {
        model["id"]
        for model in catalog_models
        if not model["enabled"] and "gateway" in model
    }
    for model in catalog_models:
        if model["id"] in dormant_gateway_ids:
            model["enabled"] = True

    rendered = _render_models(_fixture_source(tmp_path, catalog), tmp_path, "riot")
    models = _models_by_id(rendered)
    expected_maps = {
        "claude-vertex/anthropic-claude-haiku-4-5-20251001": ANTHROPIC_STANDARD_MAP,
        "claude-vertex/anthropic-claude-opus-4-6": ANTHROPIC_OPUS_4_6_MAP,
        "claude-vertex/anthropic-claude-opus-4-7": ANTHROPIC_PREMIUM_MAP,
    }

    assert dormant_gateway_ids == set(expected_maps)
    for model_id, expected_map in expected_maps.items():
        rendered_model = models[f"truefoundry/{model_id}"]
        assert rendered_model["reasoning"] is True
        assert rendered_model["thinkingLevelMap"] == expected_map

    for model_id in (
        "claude-vertex/anthropic-claude-opus-4-6",
        "claude-vertex/anthropic-claude-opus-4-7",
    ):
        assert (
            models[f"truefoundry/{model_id}[1m]"]["thinkingLevelMap"]
            == expected_maps[model_id]
        )


def test_non_reasoning_fixture_omits_thinking_map(
    catalog_data: dict[str, Any], tmp_path: Path
) -> None:
    """A non-reasoning custom model remains renderable without thinking metadata."""
    catalog = copy.deepcopy(catalog_data)
    catalog["my"]["llm"]["models"].append(
        {
            "id": "fixture-no-reasoning",
            "vendor": "google",
            "gateway": catalog["x"]["gateways"]["google"],
            "ctx": 1,
            "max_tokens": 1,
            "cost": {"input": 0, "output": 0},
            "enabled": True,
        }
    )
    rendered = _render_models(_fixture_source(tmp_path, catalog), tmp_path, "personal")
    model = _models_by_id(rendered)["google/fixture-no-reasoning"]
    assert model["reasoning"] is False
    assert "thinkingLevelMap" not in model


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (
            lambda catalog: catalog["my"]["llm"]["models"][3]["thinking_level_map"].pop(
                "max"
            ),
            'missing "max"',
        ),
        (
            lambda catalog: catalog["my"]["llm"]["models"][0].update(
                {"thinking_level_map": ANTHROPIC_PREMIUM_MAP}
            ),
            "non-reasoning model claude-opus-4-8 must not declare",
        ),
    ],
    ids=["reasoning-map-incomplete", "non-reasoning-map-prohibited"],
)
def test_template_rejects_conditional_thinking_map_contracts(
    catalog_data: dict[str, Any],
    tmp_path: Path,
    mutation: Any,
    expected: str,
) -> None:
    """The shared template guard fails before a malformed catalog can apply."""
    catalog = copy.deepcopy(catalog_data)
    mutation(catalog)
    source = _fixture_source(tmp_path, catalog)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_op(bin_dir)
    config = tmp_path / "chezmoi.toml"
    config.write_text("[data]\nis_riot_machine = false\n")
    environment = _clean_environment()
    environment.pop("OP_SERVICE_ACCOUNT_TOKEN", None)
    environment["PATH"] = f"{bin_dir}{os.pathsep}{environment['PATH']}"
    result = subprocess.run(
        [
            "chezmoi",
            "execute-template",
            "--config",
            str(config),
            "--source",
            str(source),
            "--file",
            str(source / "dot_pi" / "agent" / MODELS_TEMPLATE.name),
        ],
        cwd=source,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.returncode != 0
    assert expected in result.stderr


def _schema_result(
    tmp_path: Path, catalog: dict[str, Any]
) -> subprocess.CompletedProcess[str]:
    """Run the configured check-jsonschema hook in an isolated temporary repo."""
    root = tmp_path / "schema-repo"
    (root / ".chezmoidata").mkdir(parents=True)
    (root / ".schemas").mkdir()
    (root / ".chezmoidata" / CATALOG.name).write_text(
        yaml.safe_dump(catalog, sort_keys=False)
    )
    shutil.copy2(SCHEMA, root / ".schemas" / SCHEMA.name)
    (root / ".pre-commit-config.yaml").write_text(
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
    subprocess.run(
        ["git", "add", ".chezmoidata/large-language-models.yaml"],
        cwd=root,
        check=True,
        capture_output=True,
        env=environment,
    )
    return subprocess.run(
        ["pre-commit", "run", "--all-files"],
        cwd=root,
        capture_output=True,
        text=True,
        env=environment,
    )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (
            lambda catalog: catalog["my"]["llm"]["models"][3]["thinking_level_map"].pop(
                "max"
            ),
            "max",
        ),
        (
            lambda catalog: catalog["my"]["llm"]["models"][3][
                "thinking_level_map"
            ].update({"unsupported": "high"}),
            "unsupported",
        ),
        (
            lambda catalog: catalog["my"]["llm"]["models"][3][
                "thinking_level_map"
            ].update({"low": 1}),
            "1 is not of type",
        ),
    ],
    ids=["incomplete", "unknown-level", "invalid-value"],
)
def test_schema_hook_rejects_invalid_thinking_maps(
    catalog_data: dict[str, Any],
    tmp_path: Path,
    mutation: Any,
    expected: str,
) -> None:
    """The pre-commit schema hook closes map shape before template rendering."""
    catalog = copy.deepcopy(catalog_data)
    mutation(catalog)
    result = _schema_result(tmp_path, catalog)
    assert result.returncode != 0
    assert expected in result.stdout + result.stderr
