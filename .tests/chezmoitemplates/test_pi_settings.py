"""Integration tests for Pi's state-preserving ``modify_`` settings script.

Pi stores its app-owned runtime state beside durable preferences in one JSON
file.  The script is rendered with real chezmoi data, then run as chezmoi runs
it: existing target JSON arrives on stdin and merged JSON is emitted on stdout.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "dot_pi" / "agent" / "modify_settings.json.py.tmpl"
LEGACY_SOURCE = REPO_ROOT / "dot_pi" / "agent" / "settings.json.tmpl"
TARGET = Path.home() / ".pi" / "agent" / "settings.json"
PACKAGES = [
    "npm:@rezamonangg/pi-worktree",
    "npm:pi-mcp-adapter",
    "npm:pi-memory",
    "npm:pi-vimmode",
]

PI_BUILTIN_ANTHROPIC_DEFAULT = "claude-opus-4-8"

EXPECTED = {
    "personal": {
        "defaultModel": "claude-opus-4-8",
        "defaultProvider": "anthropic",
        "enabledModels": [
            "claude-opus-4-8",
            "claude-sonnet-5",
            "claude-fable-5",
            "gemini-3.1-pro-preview",
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
        ],
    },
    "riot": {
        "defaultModel": "openai/gpt-5.6-terra",
        "defaultProvider": "openai",
        "enabledModels": [
            "openai/gpt-5.6-terra",
            "openai/gpt-5.6-luna",
            "claude-vertex/anthropic-claude-opus-4-8",
            "claude-vertex/anthropic-claude-sonnet-5",
            "google-vertexai/gemini-3.1-pro-preview",
            "google-vertexai/gemini-3.5-flash",
            "google-vertexai/gemini-3.1-flash-lite-preview",
        ],
    },
}


def _managed(machine: str) -> dict[str, Any]:
    """Return managed preferences in their intentional append order."""
    return {
        **EXPECTED[machine],
        "packages": PACKAGES,
        "defaultProjectTrust": "always",
        "defaultThinkingLevel": "max",
        "hideThinkingBlock": False,
        "showCacheMissNotices": True,
        "theme": "dark",
    }


@pytest.fixture(scope="session", params=["personal", "riot"])
def rendered_script(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, str]:
    """Render the source through chezmoi with each catalog namespace selected."""
    machine = request.param
    config = tmp_path_factory.mktemp(f"pi-{machine}-config") / "chezmoi.toml"
    config.write_text(f"[data]\nis_riot_machine = {str(machine == 'riot').lower()}\n")
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
            str(REPO_ROOT),
            "--file",
            str(SCRIPT),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=clean_environment,
    )
    assert result.returncode == 0, result.stderr

    rendered = tmp_path_factory.mktemp(f"pi-{machine}") / "modify_settings.py"
    rendered.write_text(result.stdout)
    return rendered, machine


def _run(script: Path, stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script)],
        input=stdin,
        capture_output=True,
        text=True,
    )


def test_source_mapping_and_legacy_source_removal(tmp_path: Path) -> None:
    """The modify_ filename still maps to Pi's settings target, not ``.py``."""
    assert SCRIPT.is_file()
    assert not LEGACY_SOURCE.exists()
    assert SCRIPT.read_bytes().endswith(b"\n")

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


def test_rendered_catalog_preferences(
    rendered_script: tuple[Path, str],
) -> None:
    """Both machine namespaces retain the validated catalog default derivation."""
    script, machine = rendered_script
    result = _run(script, "")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == _managed(machine)


def test_default_model_uses_its_provider_identity(
    rendered_script: tuple[Path, str],
) -> None:
    """Built-ins keep their native IDs; Riot custom models keep their full IDs."""
    script, machine = rendered_script
    result = _run(script, "")
    assert result.returncode == 0, result.stderr
    settings = json.loads(result.stdout)

    if machine == "personal":
        # Anthropic is Pi's bundled provider, not an entry in generated models.json.
        assert settings["defaultProvider"] == "anthropic"
        assert settings["defaultModel"] == PI_BUILTIN_ANTHROPIC_DEFAULT
    else:
        assert settings["defaultProvider"] == "openai"
        assert settings["defaultModel"] == "openai/gpt-5.6-terra"
        assert settings["defaultModel"] in settings["enabledModels"]


@pytest.mark.parametrize("stdin", ["", " \n\t "], ids=["empty", "whitespace"])
def test_empty_input_seeds_only_managed_preferences(
    rendered_script: tuple[Path, str], stdin: str
) -> None:
    """Fresh and whitespace-only targets are treated as an empty JSON object."""
    script, machine = rendered_script
    result = _run(script, stdin)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == _managed(machine)


def test_preserves_app_and_unknown_nested_state(
    rendered_script: tuple[Path, str],
) -> None:
    """Pi-owned state, including changelog progress, survives a managed apply."""
    script, machine = rendered_script
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
    assert list(merged) == [*existing, *_managed(machine)]


def test_managed_values_take_precedence_for_the_full_allowlist(
    rendered_script: tuple[Path, str],
) -> None:
    """Only the nine declared durable preferences are overwritten."""
    script, machine = rendered_script
    managed = _managed(machine)
    existing: dict[str, object] = {
        "runtime": {"keep": True},
        **{key: "wrong" for key in managed},
        "lastChangelogVersion": "0.1.0",
    }
    existing["enabledModels"] = ["wrong-model"]
    existing["packages"] = ["wrong-package"]
    existing["hideThinkingBlock"] = True
    existing["showCacheMissNotices"] = False

    result = _run(script, json.dumps(existing))
    assert result.returncode == 0, result.stderr
    merged = json.loads(result.stdout)
    for key, value in managed.items():
        assert merged[key] == value
    assert merged["runtime"] == {"keep": True}
    assert merged["lastChangelogVersion"] == "0.1.0"


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


def test_unicode_output_key_order_and_no_final_newline(
    rendered_script: tuple[Path, str],
) -> None:
    """Output is Pi-compatible JSON without escaping Unicode or adding a newline."""
    script, machine = rendered_script
    existing = {
        "z": "café",
        "nested": {"漢": "✓"},
        "lastChangelogVersion": "0.80.6",
    }
    result = _run(script, json.dumps(existing, ensure_ascii=False))
    assert result.returncode == 0, result.stderr

    expected = {**existing, **_managed(machine)}
    assert result.stdout == json.dumps(expected, indent=2, ensure_ascii=False)
    assert not result.stdout.endswith("\n")
    assert "café" in result.stdout
    assert "漢" in result.stdout
    assert list(json.loads(result.stdout)) == [*existing, *_managed(machine)]


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


def _node_merged_stringify(existing: str, managed: dict[str, Any]) -> str:
    """Return the exact JavaScript serialization of the Pi settings merge."""
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(
        [
            node,
            "-e",
            "let input = ''; process.stdin.on('data', chunk => input += chunk); "
            "process.stdin.on('end', () => { "
            "const [existing, managed] = input.split('\\0').map(JSON.parse); "
            "Object.assign(existing, managed); "
            "process.stdout.write(JSON.stringify(existing, null, 2)); "
            "});",
        ],
        input=existing + "\0" + json.dumps(managed, ensure_ascii=False),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
@pytest.mark.parametrize(
    "raw_number",
    [
        "-0",
        "9007199254740991",
        "-9007199254740991",
        "9007199254740993",
        "-9007199254740993",
        "100000000000000000000",
        "-100000000000000000000",
        "1000000000000000000000",
        "-1000000000000000000000",
    ],
    ids=[
        "negative-zero",
        "safe-integer-limit",
        "negative-safe-integer-limit",
        "rounds-past-safe-integer-limit",
        "negative-rounds-past-safe-integer-limit",
        "decimal-before-scientific-cutoff",
        "negative-decimal-before-scientific-cutoff",
        "scientific-cutoff",
        "negative-scientific-cutoff",
    ],
)
def test_integer_output_matches_node_json_stringify(
    rendered_script: tuple[Path, str], raw_number: str
) -> None:
    """Parse every integer through IEEE-754 before matching Node byte-for-byte."""
    script, machine = rendered_script
    existing = f'{{"integer": {raw_number}}}'
    result = _run(script, existing)
    assert result.returncode == 0, result.stderr
    assert result.stdout == _node_merged_stringify(existing, _managed(machine))


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_output_matches_node_json_stringify_edge_cases(
    rendered_script: tuple[Path, str],
) -> None:
    """Match Pi's JavaScript serializer for numbers, Unicode, and nested objects."""
    script, machine = rendered_script
    existing = r"""{
  "z": "root-z",
  "10": "root-ten",
  "2": "root-two",
  "01": "root-leading-zero",
  "00": "root-double-leading-zero",
  "4294967295": "root-not-index",
  "0": "root-zero",
  "4294967294": "root-max-index",
  "negativeZero": -0.0,
  "smallExponent": 1e-7,
  "smallDecimal": 1e-6,
  "largeDecimal": 1e20,
  "largeExponent": 1e21,
  "decimal": 123.456,
  "unicode": "café 漢 ✓ 🦊",
  "loneHighSurrogate": "\ud800",
  "loneLowSurrogate": "\udc00",
  "nested": {
    "z": "nested-z",
    "10": "nested-ten",
    "2": "nested-two",
    "01": "nested-leading-zero",
    "00": "nested-double-leading-zero",
    "4294967295": "nested-not-index",
    "0": "nested-zero",
    "4294967294": "nested-max-index"
  },
  "array": [
    {
      "z": "array-z",
      "10": "array-ten",
      "2": "array-two",
      "01": "array-leading-zero",
      "00": "array-double-leading-zero",
      "4294967295": "array-not-index",
      "0": "array-zero",
      "4294967294": "array-max-index",
      "numbers": [-0.0, 1e-7, 1e-6, 1e20, 1e21, 123.456],
      "unicode": "café 漢 ✓ 🦊",
      "loneHighSurrogate": "\ud800",
      "loneLowSurrogate": "\udc00"
    }
  ]
}"""
    result = _run(script, existing)
    assert result.returncode == 0, result.stderr

    merged = json.loads(result.stdout)
    assert merged["nested"]["01"] == "nested-leading-zero"
    assert merged["array"][0]["01"] == "array-leading-zero"
    assert merged["4294967295"] == "root-not-index"
    assert "\\ud800" in result.stdout
    assert "\\udc00" in result.stdout
    assert "café 漢 ✓ 🦊" in result.stdout

    assert result.stdout == _node_merged_stringify(existing, _managed(machine))

    second = _run(script, result.stdout)
    assert second.returncode == 0, second.stderr
    assert second.stdout == result.stdout
