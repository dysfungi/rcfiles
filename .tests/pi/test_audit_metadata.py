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

from conftest import _clean_env

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
NO_ARGUMENT_SCENARIOS = [
    pytest.param("missing-version", id="missing-version"),
    pytest.param("missing-model", id="missing-model"),
    pytest.param("fresh-snapshot", id="fresh-snapshot"),
    pytest.param("extension-surface", id="extension-surface"),
]

pytestmark = pytest.mark.skipif(
    PI is None or NODE is None,
    reason="Pi CLI and Node.js are required for audit metadata runtime coverage",
)


def _run_harness(scenario: str, *args: str) -> None:
    assert PI is not None
    assert NODE is not None
    package_dir = Path(PI).resolve().parent.parent
    result = subprocess.run(
        [NODE, str(HARNESS), str(EXTENSION), str(package_dir), scenario, *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env=_clean_env(),
    )
    assert result.stdout == "audit metadata runtime harness: ok\n"


def test_audit_metadata_extracts_runtime_values() -> None:
    """Return the exact live model, session, and host values in details."""
    _run_harness("extraction")


def test_audit_metadata_formats_paste_ready_runtime_metadata() -> None:
    """Emit the verified Pi version once as the metadata block's harness provenance."""
    _run_harness("output-format")


def test_audit_metadata_uses_live_default_runtime_identity() -> None:
    """Read the current host and Pi version through the extension's default runtime wrapper."""
    _run_harness("default-runtime")


@pytest.mark.parametrize(("field", "value"), INVALID_CASES)
def test_audit_metadata_rejects_invalid_values_without_a_result(
    field: str, value: str
) -> None:
    """Reject every invalid representation for each required audit field."""
    _run_harness("invalid-value", field, json.dumps(value))


@pytest.mark.parametrize(("scenario",), NO_ARGUMENT_SCENARIOS)
def test_audit_metadata_exercises_no_argument_scenarios(scenario: str) -> None:
    """Exercise no-argument validation, freshness, and read-only surface scenarios."""
    _run_harness(scenario)
