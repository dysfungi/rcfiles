"""Integration tests for Pi's state-preserving ``modify_`` settings script.

Pi stores its app-owned runtime state beside durable preferences in one JSON
file. The script is rendered with real chezmoi data, then run as chezmoi runs
it: existing target JSON arrives on stdin and merged JSON is emitted on stdout.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANAGED_ROOT = REPO_ROOT / "home"
SCRIPT = MANAGED_ROOT / "dot_pi" / "agent" / "modify_settings.json.py.tmpl"
TARGET = Path.home() / ".pi" / "agent" / "settings.json"


def _execute_template(source: Path, script: Path, config: Path) -> str:
    """Render a settings script with isolated chezmoi source and config data."""
    clean_environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
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
        env=clean_environment,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _render_script(tmp_path_factory: pytest.TempPathFactory, machine: str) -> Path:
    """Render Pi settings with a selected machine namespace."""
    config = tmp_path_factory.mktemp(f"pi-{machine}-config") / "chezmoi.toml"
    config.write_text(f"[data]\nis_riot_machine = {str(machine == 'riot').lower()}\n")
    rendered = tmp_path_factory.mktemp(f"pi-{machine}") / "modify_settings.py"
    rendered.write_text(_execute_template(REPO_ROOT, SCRIPT, config))
    return rendered


def _render_synthetic_default(
    tmp_path: Path,
    model: str,
    vendor: str,
    gateway_provider: str | None,
) -> Path:
    """Render the production derivation against one self-contained model fixture."""
    source = tmp_path / "source"
    script = source / "home" / "dot_pi" / "agent" / SCRIPT.name
    validator = source / "llm" / "validate.tmpl"
    script.parent.mkdir(parents=True)
    validator.parent.mkdir(parents=True)
    shutil.copy2(SCRIPT, script)
    shutil.copy2(
        MANAGED_ROOT / ".chezmoitemplates" / "llm" / "validate.tmpl", validator
    )

    gateway = (
        "\n[data.my.llm.models.gateway]\n"
        f"provider = {json.dumps(gateway_provider)}\n"
        'api = "anthropic-messages"\n'
        if gateway_provider is not None
        else ""
    )
    config = tmp_path / "chezmoi.toml"
    config.write_text(
        "[data]\n"
        "is_riot_machine = false\n"
        'default_thinking_level = "high"\n\n'
        "[[data.my.llm.models]]\n"
        f"id = {json.dumps(model)}\n"
        f"vendor = {json.dumps(vendor)}\n"
        "enabled = true\n"
        'default_for = ["pi"]\n'
        'subagent_roles = ["scout", "planner", "reviewer", "worker"]\n'
        f"{gateway}"
        "\n[data.riot.llm]\n"
        "models = []\n"
    )
    rendered = tmp_path / "modify_settings.py"
    rendered.write_text(_execute_template(source, script, config))
    return rendered


@pytest.fixture(scope="session", params=["personal", "riot"])
def rendered_script(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, str]:
    """Render the source through chezmoi with each catalog namespace selected."""
    machine = request.param
    return _render_script(tmp_path_factory, machine), machine


def _run(script: Path, stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script)],
        input=stdin,
        capture_output=True,
        text=True,
    )


def test_modify_source_maps_to_pi_settings_target(tmp_path: Path) -> None:
    """The modify_ filename maps to Pi's settings target, not ``.py``."""
    source = tmp_path / "source"
    copied_script = source / "dot_pi" / "agent" / SCRIPT.name
    copied_script.parent.mkdir(parents=True)
    shutil.copy2(SCRIPT, copied_script)
    config = tmp_path / "chezmoi.toml"
    config.write_text(
        '[interpreters]\npy = { command = "uv", args = ["run", "--script", "--no-project"] }\n'
    )

    result = subprocess.run(
        [
            "chezmoi",
            "source-path",
            "--config",
            str(config),
            "--source",
            str(source),
            str(TARGET),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == copied_script


@pytest.mark.parametrize(
    ("model", "vendor", "gateway_provider", "expected_provider", "enabled_model"),
    [
        pytest.param(
            "claude-test",
            "anthropic",
            None,
            "anthropic",
            "claude-test:high",
            id="built-in-uses-vendor",
        ),
        pytest.param(
            "claude-vertex/anthropic-test",
            "anthropic",
            "truefoundry",
            "truefoundry",
            "truefoundry/claude-vertex/anthropic-test:high",
            id="gateway-overrides-vendor",
        ),
        pytest.param(
            "gpt-test",
            "openai",
            "litellm",
            "litellm",
            "litellm/gpt-test:high",
            id="other-gateway-provider",
        ),
    ],
)
def test_default_model_derivation(
    tmp_path: Path,
    model: str,
    vendor: str,
    gateway_provider: str | None,
    expected_provider: str,
    enabled_model: str,
) -> None:
    """A default uses its vendor unless its gateway declares a provider."""
    script = _render_synthetic_default(tmp_path, model, vendor, gateway_provider)
    result = _run(script, "")
    assert result.returncode == 0, result.stderr
    settings = json.loads(result.stdout)
    assert (settings["defaultModel"], settings["defaultProvider"]) == (
        model,
        expected_provider,
    )
    assert settings["enabledModels"] == [enabled_model]


def test_preserves_app_and_unknown_nested_state(
    rendered_script: tuple[Path, str],
) -> None:
    """Pi-owned state, including changelog progress, survives a managed apply."""
    script, _ = rendered_script
    existing = {
        "appState": {"panes": [{"id": 7, "metadata": {"expanded": True}}]},
        "lastChangelogVersion": "0.80.6",
        "unknown": {"nested": ["keep", {"all": "values"}]},
    }
    result = _run(script, json.dumps(existing))
    assert result.returncode == 0, result.stderr

    merged = json.loads(result.stdout)
    assert merged["appState"] == existing["appState"]
    assert merged["lastChangelogVersion"] == "0.80.6"
    assert merged["unknown"] == existing["unknown"]


@pytest.mark.parametrize(
    ("key", "existing_value", "managed_value"),
    [
        pytest.param("defaultProjectTrust", "ask", "always", id="project-trust"),
        pytest.param("hideThinkingBlock", True, False, id="thinking-block"),
        pytest.param("showCacheMissNotices", False, True, id="cache-miss-notices"),
        pytest.param("theme", "light", "dark", id="theme"),
    ],
)
def test_managed_values_take_precedence(
    rendered_script: tuple[Path, str],
    key: str,
    existing_value: object,
    managed_value: object,
) -> None:
    """Declared durable preferences override conflicting persisted values."""
    script, _ = rendered_script
    existing = {
        "runtime": {"keep": True},
        key: existing_value,
        "lastChangelogVersion": "0.1.0",
    }

    result = _run(script, json.dumps(existing))
    assert result.returncode == 0, result.stderr
    merged = json.loads(result.stdout)
    assert merged[key] == managed_value
    assert merged["runtime"] == {"keep": True}
    assert merged["lastChangelogVersion"] == "0.1.0"


def test_pi_vim_mode_keymap_merge_is_additive(
    rendered_script: tuple[Path, str],
) -> None:
    """Managed Escape keeps user-configured Pi Vim Mode siblings."""
    script, _ = rendered_script
    existing = {
        "piVimMode": {
            "enabled": True,
            "keymap": {
                "enter": ["<CR>"],
                "escape": ["<Esc>"],
            },
        }
    }
    expected = {
        "enabled": True,
        "keymap": {
            "enter": ["<CR>"],
            "escape": ["<C-[>"],
        },
    }
    result = _run(script, json.dumps(existing))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["piVimMode"] == expected


@pytest.mark.parametrize(
    "stdin", ["{not JSON", '{"missing": }'], ids=["token", "value"]
)
def test_malformed_json_fails_loudly(
    rendered_script: tuple[Path, str], stdin: str
) -> None:
    """Malformed non-empty input must not be silently replaced with defaults."""
    script, _ = rendered_script
    result = _run(script, stdin)
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr.startswith("pi settings: invalid JSON:")


@pytest.mark.parametrize(
    "stdin",
    ['{"value": NaN}', '{"value": Infinity}', '{"value": -Infinity}'],
    ids=["nan", "infinity", "negative-infinity"],
)
def test_python_only_json_constants_fail_loudly(
    rendered_script: tuple[Path, str], stdin: str
) -> None:
    """Pi cannot parse Python's non-standard JSON numeric constants."""
    script, _ = rendered_script
    result = _run(script, stdin)
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr.startswith(
        "pi settings: invalid JSON: non-standard JSON constant"
    )


def test_non_finite_number_fails_loudly(
    rendered_script: tuple[Path, str],
) -> None:
    """Reject a number that ECMAScript would silently serialize as ``null``."""
    script, _ = rendered_script
    result = _run(script, '{"value": 1e9999}')
    assert result.returncode != 0
    assert result.stdout == ""
    assert (
        result.stderr == "pi settings: invalid JSON: non-finite JSON number '1e9999'\n"
    )


@pytest.mark.parametrize(
    "stdin", ["[]", '"text"', "null", "1"], ids=["array", "string", "null", "number"]
)
def test_non_object_json_fails_loudly(
    rendered_script: tuple[Path, str], stdin: str
) -> None:
    """Pi settings must be a JSON object so key-preserving merge is defined."""
    script, _ = rendered_script
    result = _run(script, stdin)
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "pi settings: JSON root must be an object\n"


def test_idempotent(rendered_script: tuple[Path, str]) -> None:
    """A second apply of script output is byte-for-byte unchanged."""
    script, _ = rendered_script
    first = _run(
        script,
        json.dumps(
            {
                "lastChangelogVersion": "0.80.6",
                "runtime": {"nested": [1, 2, 3]},
                "theme": "light",
            }
        ),
    )
    assert first.returncode == 0, first.stderr
    second = _run(script, first.stdout)
    assert second.returncode == 0, second.stderr
    assert second.stdout == first.stdout
