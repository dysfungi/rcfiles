"""Regression coverage for Pi 0.80.6 custom-model scope resolution.

Pi resolves a scope as a canonical ``provider/model`` before considering a
literal model ID. A generated model such as ``openai/gpt-5.6-terra`` therefore
needs the serialized scope ``openai/openai/gpt-5.6-terra``; otherwise it can
silently select Pi's bundled OpenAI model with the same apparent reference.

This test renders the Riot settings and models exactly as chezmoi does, then
runs Pi's pinned 0.80.6 RPC runtime against a temporary, credential-free agent
state. It verifies custom provider/model identity and the persisted new-session
``xhigh → high → xhigh`` transition while cycling across models with different
thinking ceilings. No request is sent to a model API.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path
from typing import Any, TextIO

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG = REPO_ROOT / ".chezmoidata" / "large-language-models.yaml"
DEFAULT_THINKING_LEVEL = yaml.safe_load(CATALOG.read_text())["default_thinking_level"]
MISE_CONFIG = REPO_ROOT / ".mise.toml"
SETTINGS_TEMPLATE = REPO_ROOT / "dot_pi" / "agent" / "modify_settings.json.py.tmpl"
MODELS_TEMPLATE = REPO_ROOT / "dot_pi" / "agent" / "private_models.json.tmpl"
VALIDATE_TEMPLATE = REPO_ROOT / ".chezmoitemplates" / "llm" / "validate.tmpl"
NODE_MISE_TOOL = "node"
NODE_VERSION = "24.18.0"
PI_MISE_TOOL = "npm:@earendil-works/pi-coding-agent"
PI_VERSION = "0.80.6"
RIOT_BASE_URL = "https://truefoundry.riotgames.io/api/llm"
SETUP_TIMEOUT_SECONDS = 30
RESPONSE_TIMEOUT_SECONDS = 30
PROCESS_EXIT_TIMEOUT_SECONDS = 30
PROCESS_TERMINATION_TIMEOUT_SECONDS = 5

RIOT_SCOPE_IDS = [
    "openai/openai/gpt-5.6-terra",
    "openai/openai/gpt-5.6-luna",
    "truefoundry/claude-vertex/anthropic-claude-opus-4-8",
    "truefoundry/claude-vertex/anthropic-claude-sonnet-5",
    "openai/google-vertexai/gemini-3.1-pro-preview",
    "openai/google-vertexai/gemini-3.5-flash",
    "openai/google-vertexai/gemini-3.1-flash-lite-preview",
]
RIOT_SCOPES = [f"{scope_id}:{DEFAULT_THINKING_LEVEL}" for scope_id in RIOT_SCOPE_IDS]

# The runtime fixture fixes its own level so its clamp/cycle contract remains
# independent of the production catalog default.
RUNTIME_FIXTURE_THINKING_LEVEL = "xhigh"
RUNTIME_RIOT_SCOPES = [
    f"{scope_id}:{RUNTIME_FIXTURE_THINKING_LEVEL}" for scope_id in RIOT_SCOPE_IDS
]
RUNTIME_RIOT_SCOPED_MODELS = [
    {
        "provider": "openai",
        "id": "openai/gpt-5.6-terra",
        "thinkingLevel": RUNTIME_FIXTURE_THINKING_LEVEL,
    },
    {
        "provider": "openai",
        "id": "openai/gpt-5.6-luna",
        "thinkingLevel": RUNTIME_FIXTURE_THINKING_LEVEL,
    },
    {
        "provider": "truefoundry",
        "id": "claude-vertex/anthropic-claude-opus-4-8",
        "thinkingLevel": RUNTIME_FIXTURE_THINKING_LEVEL,
    },
    {
        "provider": "truefoundry",
        "id": "claude-vertex/anthropic-claude-sonnet-5",
        "thinkingLevel": RUNTIME_FIXTURE_THINKING_LEVEL,
    },
    {
        "provider": "openai",
        "id": "google-vertexai/gemini-3.1-pro-preview",
        "thinkingLevel": RUNTIME_FIXTURE_THINKING_LEVEL,
    },
    {
        "provider": "openai",
        "id": "google-vertexai/gemini-3.5-flash",
        "thinkingLevel": RUNTIME_FIXTURE_THINKING_LEVEL,
    },
    {
        "provider": "openai",
        "id": "google-vertexai/gemini-3.1-flash-lite-preview",
        "thinkingLevel": RUNTIME_FIXTURE_THINKING_LEVEL,
    },
]

# Google scopes deliberately request xhigh, but Pi clamps them to their highest
# declared capability while cycling. Returning to Terra restores the fixture level.
RUNTIME_RIOT_CYCLE_RESULTS = [
    *RUNTIME_RIOT_SCOPED_MODELS[1:4],
    *[{**model, "thinkingLevel": "high"} for model in RUNTIME_RIOT_SCOPED_MODELS[4:]],
    RUNTIME_RIOT_SCOPED_MODELS[0],
]


def _clean_environment() -> dict[str, str]:
    """Keep mise activation while preventing pre-commit Git routing leakage."""
    return {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }


def _diagnostic_output(output: str | bytes | None) -> str:
    """Render partial subprocess output consistently after a timeout."""
    if isinstance(output, bytes):
        output = output.decode(errors="replace")
    return output or "<empty>"


def _command_diagnostics(result: subprocess.CompletedProcess[str]) -> str:
    """Return a failure message with the complete captured command context."""
    return (
        f"command: {result.args!r}\n"
        f"returncode: {result.returncode}\n"
        f"stdout:\n{_diagnostic_output(result.stdout)}\n"
        f"stderr:\n{_diagnostic_output(result.stderr)}"
    )


def _run_setup_command(
    command: list[str],
    environment: dict[str, str],
    *,
    standard_input: str | None = None,
    timeout_seconds: float = SETUP_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Run bounded setup work and retain partial output when it hangs."""
    try:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            input=standard_input,
            text=True,
            timeout=timeout_seconds,
            env=environment,
        )
    except subprocess.TimeoutExpired as error:
        raise AssertionError(
            f"Timed out after {timeout_seconds} seconds while running {command!r}.\n"
            f"stdout:\n{_diagnostic_output(error.stdout)}\n"
            f"stderr:\n{_diagnostic_output(error.stderr)}"
        ) from error

    assert result.returncode == 0, _command_diagnostics(result)
    return result


def _configured_mise_version(tool: str) -> str:
    """Read one exact project tool pin from mise's TOML configuration."""
    tools = tomllib.loads(MISE_CONFIG.read_text(encoding="utf-8"))["tools"]
    assert isinstance(tools, dict)
    version = tools.get(tool)
    assert isinstance(version, str), f"{tool} is not pinned in {MISE_CONFIG}"
    return version


def _mise_executable() -> str:
    """Find the host mise binary needed to resolve project-managed tools."""
    mise = shutil.which("mise")
    assert mise is not None, "Pi runtime regression requires mise"
    return mise


def _render_template(
    template: Path,
    config: Path,
    environment: dict[str, str],
    source: Path = REPO_ROOT,
) -> str:
    """Render one Riot template from the supplied source catalog."""
    result = _run_setup_command(
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
        environment,
    )
    return result.stdout


def _write_fake_onepassword_cli(bin_dir: Path) -> None:
    """Create a deterministic account-mode 1Password CLI for the host OS."""
    if os.name == "nt":
        (bin_dir / "op.cmd").write_text(
            '@echo off\n<nul set /p "=fake-token"\n', encoding="utf-8"
        )
        return

    op = bin_dir / "op"
    op.write_text("#!/bin/sh\nprintf '%s' fake-token\n", encoding="utf-8")
    op.chmod(0o755)


def _runtime_fixture_source(tmp_path: Path) -> Path:
    """Build an isolated source with the fixed level needed for Pi's cycle test."""
    source = tmp_path / "runtime-source"
    catalog = yaml.safe_load(CATALOG.read_text())
    catalog["default_thinking_level"] = RUNTIME_FIXTURE_THINKING_LEVEL

    catalog_path = source / ".chezmoidata" / CATALOG.name
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False))
    for template in (SETTINGS_TEMPLATE, MODELS_TEMPLATE, VALIDATE_TEMPLATE):
        destination = source / template.relative_to(REPO_ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(template, destination)
    return source


def _render_riot_state(
    agent_dir: Path,
    tmp_path: Path,
    source: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Render exact settings and custom models using a deterministic fake secret."""
    config = tmp_path / "chezmoi.toml"
    config.write_text("[data]\nis_riot_machine = true\n")
    environment = _clean_environment()
    settings_template = source / SETTINGS_TEMPLATE.relative_to(REPO_ROOT)
    models_template = source / MODELS_TEMPLATE.relative_to(REPO_ROOT)

    rendered_settings = _render_template(settings_template, config, environment, source)
    settings_script = tmp_path / "modify_settings.py"
    settings_script.write_text(rendered_settings)
    settings_result = _run_setup_command(
        [sys.executable, str(settings_script)],
        environment,
        standard_input="",
    )
    (agent_dir / "settings.json").write_text(settings_result.stdout)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_onepassword_cli(bin_dir)
    environment.pop("OP_SERVICE_ACCOUNT_TOKEN", None)
    environment["PATH"] = f"{bin_dir}{os.pathsep}{environment['PATH']}"
    (agent_dir / "models.json").write_text(
        _render_template(models_template, config, environment, source)
    )
    return json.loads(settings_result.stdout)


def _pi_package_root() -> Path:
    """Resolve the Pi package pinned in this repository's mise configuration."""
    assert _configured_mise_version(PI_MISE_TOOL) == PI_VERSION
    result = _run_setup_command(
        [_mise_executable(), "where", PI_MISE_TOOL], _clean_environment()
    )

    install_root = Path(result.stdout.strip())
    package_root = (
        install_root / "lib" / "node_modules" / "@earendil-works" / "pi-coding-agent"
    )
    assert package_root.is_dir(), f"{package_root}\n{_command_diagnostics(result)}"
    package_version = json.loads((package_root / "package.json").read_text())["version"]
    assert package_version == PI_VERSION
    return package_root


def _node_executable() -> Path:
    """Resolve and verify the exact Node runtime pinned for this regression."""
    assert _configured_mise_version(NODE_MISE_TOOL) == NODE_VERSION
    node_result = _run_setup_command(
        [_mise_executable(), "which", NODE_MISE_TOOL], _clean_environment()
    )
    node = Path(node_result.stdout.strip())
    assert node.is_file(), f"{node}\n{_command_diagnostics(node_result)}"

    version_result = _run_setup_command([str(node), "--version"], _clean_environment())
    assert version_result.stdout.strip() == f"v{NODE_VERSION}", _command_diagnostics(
        version_result
    )
    return node


def _start_response_reader(
    process: subprocess.Popen[str],
) -> tuple[queue.Queue[str | None], threading.Thread]:
    """Read Pi's JSON Lines output asynchronously so each RPC request can time out."""
    stdout = process.stdout
    assert stdout is not None
    responses: queue.Queue[str | None] = queue.Queue()

    def read_responses() -> None:
        try:
            for line in stdout:
                responses.put(line)
        finally:
            responses.put(None)

    reader = threading.Thread(
        target=read_responses,
        name="pi-rpc-response-reader",
        daemon=True,
    )
    reader.start()
    return responses, reader


def _close_stdin(process: subprocess.Popen[str]) -> None:
    """Close Pi's input without masking an already-exited process."""
    stdin = process.stdin
    if stdin is None or stdin.closed:
        return
    try:
        stdin.close()
    except BrokenPipeError:
        pass
    except OSError:
        if process.poll() is None:
            raise


def _terminate_and_reap(process: subprocess.Popen[str]) -> None:
    """Bound a failed request without leaving a Pi child for later tests."""
    if process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=PROCESS_TERMINATION_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=PROCESS_TERMINATION_TIMEOUT_SECONDS)


def _close_and_reap(process: subprocess.Popen[str]) -> None:
    """Allow normal RPC shutdown, then force cleanup if it does not exit."""
    _close_stdin(process)
    if process.poll() is not None:
        return
    try:
        process.wait(timeout=PROCESS_EXIT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        _terminate_and_reap(process)


def _read_stderr(stderr: TextIO) -> str:
    """Return Pi diagnostics captured in a regular file, never a competing pipe."""
    stderr.seek(0)
    return stderr.read()


def _request(
    process: subprocess.Popen[str],
    responses: queue.Queue[str | None],
    identifier: str,
    command_type: str,
    *,
    response_timeout_seconds: float = RESPONSE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Send one RPC command and wait a bounded interval for its response."""
    assert process.stdin is not None
    process.stdin.write(json.dumps({"id": identifier, "type": command_type}) + "\n")
    process.stdin.flush()

    deadline = time.monotonic() + response_timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            line = responses.get(timeout=remaining)
        except queue.Empty:
            break
        if line is None:
            raise AssertionError(
                f"Pi closed stdout before responding to {identifier} "
                f"({command_type}; returncode={process.poll()})"
            )

        response = json.loads(line)
        if response.get("type") == "response" and response.get("id") == identifier:
            assert response["success"], response
            return response["data"]

    raise TimeoutError(
        f"Pi did not respond to {command_type} request {identifier!r} within "
        f"{response_timeout_seconds} seconds"
    )


def _run_runtime_check(
    package_root: Path, agent_dir: Path, tmp_path: Path
) -> dict[str, Any]:
    """Exercise Pi's no-session RPC runtime without live credentials or requests."""
    node = _node_executable()

    home = tmp_path / "isolated-home"
    home.mkdir()
    environment = _clean_environment()
    for key in tuple(environment):
        if key.endswith(("_API_KEY", "_TOKEN")):
            environment.pop(key)
    environment.update(
        {
            "HOME": str(home),
            "PI_CODING_AGENT_DIR": str(agent_dir),
            "PI_OFFLINE": "1",
            "PI_SKIP_VERSION_CHECK": "1",
            "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_DATA_HOME": str(home / "data"),
        }
    )
    # A regular file cannot fill and block Pi while the response reader waits.
    with (tmp_path / "pi-rpc.stderr").open(
        "w+", encoding="utf-8", errors="replace"
    ) as stderr:
        process = subprocess.Popen(
            [
                str(node),
                str(package_root / "dist" / "cli.js"),
                "--mode",
                "rpc",
                "--no-session",
                "--no-context-files",
                "--no-extensions",
                "--no-skills",
            ],
            cwd=tmp_path,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )
        responses, response_reader = _start_response_reader(process)
        try:
            initial = _request(process, responses, "initial", "get_state")
            cycles = [
                _request(process, responses, f"cycle-{index}", "cycle_model")
                for index in range(1, len(RUNTIME_RIOT_SCOPED_MODELS) + 1)
            ]
            entries = _request(process, responses, "entries", "get_entries")["entries"]
            final = _request(process, responses, "final", "get_state")
        except TimeoutError as error:
            _terminate_and_reap(process)
            raise AssertionError(
                f"{error}; terminated Pi child (returncode={process.returncode}).\n"
                f"stderr:\n{_read_stderr(stderr) or '<empty>'}"
            ) from error
        finally:
            _close_and_reap(process)
            response_reader.join(timeout=PROCESS_TERMINATION_TIMEOUT_SECONDS)
            assert not response_reader.is_alive(), (
                "Pi response reader did not exit after child cleanup.\n"
                f"stderr:\n{_read_stderr(stderr) or '<empty>'}"
            )

        assert process.returncode == 0, _read_stderr(stderr)
    return {
        "initial": {
            "provider": initial["model"]["provider"],
            "id": initial["model"]["id"],
            "thinkingLevel": initial["thinkingLevel"],
        },
        "cycles": [
            {
                "provider": cycle["model"]["provider"],
                "id": cycle["model"]["id"],
                "thinkingLevel": cycle["thinkingLevel"],
            }
            for cycle in cycles
        ],
        "baseUrls": [
            initial["model"]["baseUrl"],
            *[cycle["model"]["baseUrl"] for cycle in cycles],
            final["model"]["baseUrl"],
        ],
        "serializedThinkingLevels": [
            entry["thinkingLevel"]
            for entry in entries
            if entry["type"] == "thinking_level_change"
        ],
        "final": {
            "provider": final["model"]["provider"],
            "id": final["model"]["id"],
            "thinkingLevel": final["thinkingLevel"],
        },
    }


def test_setup_timeout_preserves_partial_diagnostics() -> None:
    """A timed-out setup subprocess reports its captured stdout and stderr."""
    command = [
        sys.executable,
        "-c",
        (
            "import sys, time; "
            "print('setup stdout diagnostic', flush=True); "
            "print('setup stderr diagnostic', file=sys.stderr, flush=True); "
            "time.sleep(60)"
        ),
    ]

    with pytest.raises(AssertionError) as error:
        _run_setup_command(command, _clean_environment(), timeout_seconds=1)

    message = str(error.value)
    assert "Timed out after 1 seconds" in message
    assert "setup stdout diagnostic" in message
    assert "setup stderr diagnostic" in message


def test_rpc_timeout_reaps_child_and_joins_response_reader(tmp_path: Path) -> None:
    """A hung RPC child is reaped without losing diagnostics or its reader."""
    command = [
        sys.executable,
        "-c",
        "\n".join(
            [
                "import sys",
                "import time",
                "sys.stdout.write('ready\\n')",
                "sys.stdout.flush()",
                "sys.stderr.write('timeout fixture diagnostic\\n')",
                "sys.stderr.flush()",
                "time.sleep(60)",
            ]
        ),
    ]
    with (tmp_path / "timeout.stderr").open(
        "w+", encoding="utf-8", errors="replace"
    ) as stderr:
        process = subprocess.Popen(
            command,
            cwd=tmp_path,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_clean_environment(),
        )
        responses, response_reader = _start_response_reader(process)
        try:
            assert (
                responses.get(timeout=PROCESS_TERMINATION_TIMEOUT_SECONDS) == "ready\n"
            )
            assert response_reader.is_alive()
            with pytest.raises(TimeoutError, match="Pi did not respond"):
                _request(
                    process,
                    responses,
                    "timeout",
                    "get_state",
                    response_timeout_seconds=0.25,
                )
        finally:
            _terminate_and_reap(process)
            _close_and_reap(process)
            response_reader.join(timeout=PROCESS_TERMINATION_TIMEOUT_SECONDS)

        assert process.returncode is not None
        assert not response_reader.is_alive()
        assert responses.get(timeout=PROCESS_TERMINATION_TIMEOUT_SECONDS) is None
        assert "timeout fixture diagnostic" in _read_stderr(stderr)


def test_riot_scopes_follow_catalog_default(tmp_path: Path) -> None:
    """Production scope rendering follows the shared catalog default."""
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()

    settings = _render_riot_state(agent_dir, tmp_path)

    assert settings["enabledModels"] == RIOT_SCOPES


@pytest.mark.slow
def test_pi_0_80_6_resolves_custom_scopes_and_serializes_thinking_cycle(
    tmp_path: Path,
) -> None:
    """Generated Riot scopes select custom models and restore the fixed cycle level."""
    source = _runtime_fixture_source(tmp_path)
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    settings = _render_riot_state(agent_dir, tmp_path, source)
    assert settings["defaultThinkingLevel"] == RUNTIME_FIXTURE_THINKING_LEVEL
    assert settings["enabledModels"] == RUNTIME_RIOT_SCOPES

    runtime = _run_runtime_check(_pi_package_root(), agent_dir, tmp_path)
    assert runtime["initial"] == RUNTIME_RIOT_SCOPED_MODELS[0]
    assert runtime["cycles"] == RUNTIME_RIOT_CYCLE_RESULTS
    assert runtime["baseUrls"] == [RIOT_BASE_URL] * (
        len(RUNTIME_RIOT_SCOPED_MODELS) + 2
    )
    assert runtime["serializedThinkingLevels"] == [
        RUNTIME_FIXTURE_THINKING_LEVEL,
        "high",
        RUNTIME_FIXTURE_THINKING_LEVEL,
    ]
    assert runtime["final"] == RUNTIME_RIOT_SCOPED_MODELS[0]
