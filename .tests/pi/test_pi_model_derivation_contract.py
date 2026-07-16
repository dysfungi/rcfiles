"""Verify Pi model derivation with a self-contained catalog fixture.

Pi must emit non-reasoning custom models without a ``thinkingLevelMap``. This
exercises the production model template and its validation partial with a small
synthetic catalog rather than mirroring the managed model catalog. The fixture
also supplies each required subagent role so the test isolates the derivation
contract from unrelated catalog selection.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS_TEMPLATE = REPO_ROOT / "home/dot_pi/agent/private_models.json.tmpl"
VALIDATION_TEMPLATE = REPO_ROOT / "home/.chezmoitemplates/llm/validate.tmpl"


def _write_fake_op(bin_dir: Path) -> None:
    op = bin_dir / "op"
    op.write_text("#!/bin/sh\nprintf '%s' fixture-token\n")
    op.chmod(0o755)


def _fixture_catalog() -> dict[str, object]:
    roles = ("scout", "planner", "reviewer", "worker")
    models: list[dict[str, object]] = []
    for role in roles:
        model: dict[str, object] = {
            "id": f"fixture-{role}",
            "vendor": "fixture",
            "ctx": 1,
            "max_tokens": 1,
            "cost": {"input": 0, "output": 0},
            "enabled": True,
            "subagent_roles": [role],
        }
        if role == "scout":
            model["gateway"] = {
                "provider": "fixture",
                "name": "Fixture",
                "base_url": "https://example.invalid/v1",
                "api": "openai-completions",
                "api_key_op": "op://fixture/token",
            }
        models.append(model)

    return {
        "my": {"llm": {"models": models}},
        "riot": {"llm": {"models": []}},
    }


def test_non_reasoning_model_omits_thinking_map(tmp_path: Path) -> None:
    """A custom model without reasoning metadata remains valid and unambiguous."""
    source = tmp_path / "source"
    (source / ".chezmoidata").mkdir(parents=True)
    (source / ".chezmoitemplates/llm").mkdir(parents=True)
    (source / "dot_pi/agent").mkdir(parents=True)
    (source / ".chezmoidata/large-language-models.yaml").write_text(
        yaml.safe_dump(_fixture_catalog(), sort_keys=False)
    )
    shutil.copy2(VALIDATION_TEMPLATE, source / ".chezmoitemplates/llm/validate.tmpl")
    shutil.copy2(MODELS_TEMPLATE, source / "dot_pi/agent/private_models.json.tmpl")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_op(bin_dir)
    config = tmp_path / "chezmoi.toml"
    config.write_text("[data]\nis_riot_machine = false\n")
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("GIT_", "CHEZMOI_", "OP_SERVICE_ACCOUNT_TOKEN"))
    }
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
            str(source / "dot_pi/agent/private_models.json.tmpl"),
        ],
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    model = json.loads(result.stdout)["providers"]["fixture"]["models"][0]
    assert model["reasoning"] is False
    assert "thinkingLevelMap" not in model
