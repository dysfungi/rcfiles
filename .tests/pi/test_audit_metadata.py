"""Runtime regression coverage for Pi's read-only audit metadata extension.

The Node harness loads the managed TypeScript module through Pi's bundled Jiti
loader, registers it against a controlled ExtensionAPI, and invokes the actual
tool handler. Controlled runtime scenarios make identity fields deterministic;
the default-runtime scenario verifies Pi's real OS wrapper.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from itertools import product
from pathlib import Path

import pytest

from _test_env import _clean_env

REPO_ROOT = Path(__file__).resolve().parents[2]
MANAGED_ROOT = REPO_ROOT / "home"
EXTENSION = MANAGED_ROOT / "dot_pi" / "agent" / "extensions" / "audit-metadata.ts"
HARNESS = Path(__file__).with_name("audit_metadata_runtime_harness.mjs")
PI = shutil.which("pi")
NODE = shutil.which("node")

INVALID_VALUES = [
    ("blank", ""),
    ("whitespace", " \t "),
    ("unknown", "unknown"),
    ("unknown-with-source", "Unknown (source: unavailable)"),
    ("carriage-return", "invalid\rvalue"),
    ("newline", "invalid\nvalue"),
]
INVALID_CASES = [
    pytest.param(field, value, id=f"{field}-{label}")
    for field, (label, value) in product(
        ["model", "modelProvider", "sessionId", "hostname", "piVersion"],
        INVALID_VALUES,
    )
]
SINGLE_SCENARIO_CASES = [
    pytest.param(
        "extraction",
        id="extraction: returns the exact live model, session, and host values in details",
    ),
    pytest.param(
        "output-format",
        id="output-format: emits the verified Pi version once as authored-by provenance",
    ),
    pytest.param(
        "gateway-provider",
        id="gateway-provider: emits the catalog display name only for catalog-marked gateway providers",
    ),
    pytest.param(
        "direct-provider",
        id="direct-provider: omits model gateway metadata for direct providers",
    ),
    pytest.param(
        "default-runtime",
        id="default-runtime: reads the current host and Pi version through the extension's default runtime wrapper",
    ),
    pytest.param(
        "nested-root-envelope",
        id="nested-root-envelope: a real two-hop child process preserves root attribution in audit metadata",
    ),
    pytest.param(
        "missing-version",
        id="missing-version: rejects an unprovable Pi harness label rather than emitting one",
    ),
    pytest.param(
        "missing-model",
        id="missing-model: routes through validation instead of dereferencing undefined",
    ),
    pytest.param(
        "fresh-snapshot",
        id="fresh-snapshot: never caches model, session, host, or version across invocations",
    ),
    pytest.param(
        "extension-surface",
        id="extension-surface: registers only a tool, no commands/events/exec/bash override",
    ),
]

pytestmark = pytest.mark.skipif(
    PI is None or NODE is None,
    reason="Pi CLI and Node.js are required for audit metadata runtime coverage",
)


def _run_harness(
    scenario: str, *args: str, environment: dict[str, str] | None = None
) -> None:
    assert PI is not None
    assert NODE is not None
    package_dir = Path(PI).resolve().parent.parent
    child_environment = _clean_env()
    child_environment.pop("PI_ROOT_IDENTITY", None)
    if environment is not None:
        child_environment.update(environment)
    result = subprocess.run(
        [NODE, str(HARNESS), str(EXTENSION), str(package_dir), scenario, *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env=child_environment,
    )
    assert result.stdout == "audit metadata runtime harness: ok\n"


@pytest.mark.parametrize(("field", "value"), INVALID_CASES)
def test_audit_metadata_rejects_invalid_values_without_a_result(
    field: str, value: str
) -> None:
    """Reject every invalid representation for each required audit field."""
    _run_harness("invalid-value", field, json.dumps(value))


@pytest.mark.parametrize(("scenario",), SINGLE_SCENARIO_CASES)
def test_audit_metadata_exercises_single_scenario_harness_checks(scenario: str) -> None:
    """Exercise no-argument scenarios; each pytest ID states its regression guarantee."""
    _run_harness(scenario)


@pytest.mark.parametrize(
    ("envelope", "expected_error"),
    [
        pytest.param(
            '{"provider":"root-provider","sessionId":"root-session"}',
            r"PI_ROOT_IDENTITY envelope is missing field 'model'",
            id="partial-envelope-missing-model",
        ),
        pytest.param(
            '{"model":"root-model","sessionId":"root-session"}',
            r"PI_ROOT_IDENTITY envelope is missing field 'provider'",
            id="partial-envelope-missing-provider",
        ),
        pytest.param(
            '{"model":"root-model","provider":"root-provider"}',
            r"PI_ROOT_IDENTITY envelope is missing field 'sessionId'",
            id="partial-envelope-missing-session-id",
        ),
        pytest.param(
            '{"model":123,"provider":"root-provider","sessionId":"root-session"}',
            r"PI_ROOT_IDENTITY envelope field 'model' must be a string",
            id="model-is-not-a-string",
        ),
        pytest.param(
            '{"model":null,"provider":"root-provider","sessionId":"root-session"}',
            r"PI_ROOT_IDENTITY envelope field 'model' must be a string",
            id="model-is-null",
        ),
        pytest.param(
            '{"model":" \\t ","provider":"root-provider","sessionId":"root-session"}',
            r"PI_ROOT_IDENTITY envelope field 'model' must be a non-empty string",
            id="model-is-whitespace",
        ),
        pytest.param(
            "[]",
            r"PI_ROOT_IDENTITY envelope must be a JSON object",
            id="envelope-is-an-array",
        ),
        pytest.param(
            '"x"',
            r"PI_ROOT_IDENTITY envelope must be a JSON object",
            id="envelope-is-a-string",
        ),
        pytest.param(
            "not-json",
            r"PI_ROOT_IDENTITY envelope contains invalid JSON",
            id="corrupt-envelope-invalid-json",
        ),
    ],
)
def test_audit_metadata_rejects_invalid_root_identity_envelopes(
    envelope: str, expected_error: str
) -> None:
    """A present root envelope is authoritative and never falls back to child identity."""
    _run_harness(
        "invalid-root-envelope",
        expected_error,
        environment={"PI_ROOT_IDENTITY": envelope},
    )


def test_audit_metadata_uses_complete_root_identity_envelope() -> None:
    """A managed child records root authorship while retaining its executing hostname."""
    _run_harness(
        "root-envelope",
        environment={
            "PI_ROOT_IDENTITY": json.dumps(
                {
                    "model": "root-model",
                    "provider": "root-provider",
                    "sessionId": "root-session",
                }
            )
        },
    )
