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
        ["model", "modelProvider", "sessionId", "username", "hostname"],
        INVALID_VALUES,
    )
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
    """Return the exact live model, session, user, and host values in details."""
    _run_harness("extraction")


def test_audit_metadata_formats_paste_ready_runtime_sources() -> None:
    """Label every emitted audit field as sourced from the Pi runtime."""
    _run_harness("output-format")


def test_audit_metadata_uses_live_default_runtime_identity() -> None:
    """Read the current user and host through the extension's default runtime wrapper."""
    _run_harness("default-runtime")


@pytest.mark.parametrize(("field", "value"), INVALID_CASES)
def test_audit_metadata_rejects_invalid_values_without_a_result(
    field: str, value: str
) -> None:
    """Reject every invalid representation for each required audit field."""
    _run_harness("invalid-value", field, json.dumps(value))


def test_audit_metadata_rejects_a_missing_model_without_type_error() -> None:
    """Report missing model fields through validation instead of dereferencing undefined."""
    _run_harness("missing-model")


def test_audit_metadata_reads_a_fresh_runtime_snapshot_per_call() -> None:
    """Never cache model, session, user, or host identity across tool invocations."""
    _run_harness("fresh-snapshot")


def test_audit_metadata_extension_surface_is_read_only() -> None:
    """Register exactly one tool without handlers, command execution, or a bash override."""
    _run_harness("extension-surface")
