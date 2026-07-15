"""Runtime coverage for Pi memory Git synchronization helpers.

The Node harness loads the TypeScript extension through Pi's bundled Jiti loader and
exercises its exported helpers against temporary Git repositories. This keeps the
regression tests on real Git behavior without starting a Pi session or touching the
live ``~/.pi/agent/memory`` checkout.
"""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from conftest import _clean_env

REPO_ROOT = Path(__file__).resolve().parents[2]
EXTENSION = REPO_ROOT / "dot_pi" / "agent" / "extensions" / "memory-git-sync.ts"
HARNESS = Path(__file__).with_name("memory_git_sync_runtime_harness.mjs")
EXTERNAL_TEMPLATE = REPO_ROOT / "dot_pi" / "agent" / ".chezmoiexternal.toml.tmpl"
PI = shutil.which("pi")
NODE = shutil.which("node")


@pytest.mark.skipif(
    PI is None or NODE is None,
    reason="Pi CLI and Node.js are required for memory Git sync runtime coverage",
)
def test_memory_git_sync_runtime() -> None:
    """Exercise health, session failure, attributes, and merge behavior in disposable repos."""
    assert PI is not None
    assert NODE is not None
    package_dir = Path(PI).resolve().parent.parent
    result = subprocess.run(
        [NODE, str(HARNESS), str(EXTENSION), str(package_dir)],
        check=True,
        capture_output=True,
        text=True,
        env=_clean_env(),
    )
    assert result.stdout == "memory git sync runtime harness: ok\n"


def test_memory_external_uses_one_time_clone_and_fast_forward_refresh() -> None:
    """Parse the Unix memory stanza without treating template rendering as pytest's job."""
    template = EXTERNAL_TEMPLATE.read_text(encoding="utf-8")
    rendered_unix_stanza = template.replace("{{- if .is_unix_like }}\n", "").replace(
        "{{- end }}\n", ""
    )
    memory = tomllib.loads(rendered_unix_stanza)["memory"]

    assert memory["type"] == "git-repo"
    assert memory["refreshPeriod"] == "0"
    assert memory["pull"]["args"] == ["--no-rebase", "--ff-only"]
