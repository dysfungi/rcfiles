"""Regression coverage for Pi's per-role agent templates' model-id rendering.

``home/dot_pi/agent/agents/{planner,reviewer,scout,worker}.md.tmpl`` each scan
the active catalog namespace for the model claiming their role and emit a
``model:`` frontmatter line. A gateway-routed model's `id` alone is ambiguous
with Pi's same-named bundled model (see test_pi_model_scope_runtime.py), so
every template must prefix the id with `gateway.provider` when the winning
model declares a `gateway`. `worker.md.tmpl` once omitted this prefixing
(caught when its role model was reassigned to a gateway-routed model), so
this test renders all four role templates through the identical mechanism to
keep them locked to the same contract.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / "home" / "dot_pi" / "agent" / "agents"
VALIDATE_TEMPLATE = REPO_ROOT / "home" / ".chezmoitemplates" / "llm" / "validate.tmpl"

ROLE_TEMPLATES = {
    "planner": AGENTS_DIR / "planner.md.tmpl",
    "reviewer": AGENTS_DIR / "reviewer.md.tmpl",
    "scout": AGENTS_DIR / "scout.md.tmpl",
    "worker": AGENTS_DIR / "worker.md.tmpl",
}


def _clean_environment() -> dict[str, str]:
    """Prevent parent chezmoi/Git state from affecting the rendered template."""
    return {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }


def _render(template: Path, source: Path, config: Path) -> str:
    """Render one role template exactly as chezmoi would from a synthetic source."""
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
    return result.stdout


def _fixture_source(tmp_path: Path, role: str, *, with_gateway: bool) -> Path:
    """Build an isolated source with one model claiming `role`.

    ``includeTemplate`` resolves its argument literally relative to
    ``--source`` (no ``.chezmoitemplates`` unwrapping outside a full chezmoi
    apply run), so the validator lands at ``source/llm/validate.tmpl`` here,
    matching the convention in test_pi_settings.py's ``_render_synthetic_default``.
    """
    source = tmp_path / "source"
    validator = source / "llm" / "validate.tmpl"
    validator.parent.mkdir(parents=True)
    validator.write_bytes(VALIDATE_TEMPLATE.read_bytes())
    for name, template in ROLE_TEMPLATES.items():
        dest = source / "dot_pi" / "agent" / "agents" / f"{name}.md.tmpl"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(template.read_bytes())
    return source


def _fixture_config(tmp_path: Path, role: str, *, with_gateway: bool) -> Path:
    config = tmp_path / "chezmoi.toml"
    gateway = (
        '\n[data.my.llm.models.gateway]\nprovider = "custom-gateway"\n'
        if with_gateway
        else ""
    )
    config.write_text(
        "[data]\n"
        "is_riot_machine = false\n\n"
        "[[data.my.llm.models]]\n"
        'id = "vendor/some-model"\n'
        'vendor = "anthropic"\n'
        "enabled = true\n"
        f'roles = ["{role}"]\n'
        f"{gateway}"
        "\n[data.riot.llm]\n"
        "models = []\n"
    )
    return config


@pytest.mark.parametrize(
    "role,template", ROLE_TEMPLATES.items(), ids=list(ROLE_TEMPLATES)
)
@pytest.mark.parametrize("with_gateway", [True, False], ids=["gateway", "no-gateway"])
def test_role_template_prefixes_model_id_iff_gateway_routed(
    tmp_path: Path, role: str, template: Path, with_gateway: bool
) -> None:
    """Every role template applies the same gateway-provider prefix contract."""
    source = _fixture_source(tmp_path, role, with_gateway=with_gateway)
    config = _fixture_config(tmp_path, role, with_gateway=with_gateway)
    rendered_template = source / "dot_pi" / "agent" / "agents" / template.name
    output = _render(rendered_template, source, config)

    expected_id = (
        "custom-gateway/vendor/some-model" if with_gateway else "vendor/some-model"
    )
    assert f"model: {expected_id}" in output, output
