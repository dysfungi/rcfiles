"""Integration coverage for removing obsolete subagent role files.

The test runs the real ChezMoi binary with every state root redirected into a
scratch tree. Its blank source contains only the repository's removal manifest,
which proves the deployed extension-local files are deleted while the canonical
managed role-definition paths remain untouched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REMOVAL_MANIFEST = REPO_ROOT / ".chezmoiremove"
MISE = shutil.which("mise")
PATH_CHEZMOI = shutil.which("chezmoi")
DEPRECATED_ROLE_TARGETS = (
    ".pi/agent/extensions/subagent/agents/scout.md",
    ".pi/agent/extensions/subagent/agents/planner.md",
    ".pi/agent/extensions/subagent/agents/reviewer.md",
    ".pi/agent/extensions/subagent/agents/worker.md",
)
CANONICAL_ROLE_TARGETS = (
    ".pi/agent/agents/scout.md",
    ".pi/agent/agents/planner.md",
    ".pi/agent/agents/reviewer.md",
    ".pi/agent/agents/worker.md",
)

pytestmark = pytest.mark.skipif(
    MISE is None and PATH_CHEZMOI is None,
    reason="ChezMoi is required for subagent cleanup coverage",
)


def _chezmoi_binary() -> str:
    """Resolve ChezMoi from the repository's mise tool definition when available."""
    if MISE is not None:
        result = subprocess.run(
            [MISE, "which", "chezmoi"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env={
                key: value
                for key, value in os.environ.items()
                if not key.startswith(("CHEZMOI_", "GIT_"))
            },
        )
        if result.returncode == 0:
            return result.stdout.strip()
    assert PATH_CHEZMOI is not None
    return PATH_CHEZMOI


def _isolated_environment(destination: Path) -> dict[str, str]:
    """Prevent inherited Git or ChezMoi state from affecting the subprocess."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("CHEZMOI_", "GIT_"))
    }
    environment["HOME"] = str(destination)
    return environment


def _seed(destination: Path, targets: tuple[str, ...], contents: str) -> None:
    """Create one pre-existing file per target without adding source-managed files."""
    for target in targets:
        path = destination / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{contents}: {target}\n")


def test_apply_removes_obsolete_subagent_roles_only(tmp_path: Path) -> None:
    """ChezMoi removes legacy roles without deleting canonical role definitions."""
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    config = tmp_path / "config" / "chezmoi.toml"
    persistent_state = tmp_path / "persistent-state" / "state.boltdb"
    cache = tmp_path / "cache"
    source.mkdir()
    destination.mkdir()
    config.parent.mkdir()
    config.touch()
    persistent_state.parent.mkdir()
    cache.mkdir()
    shutil.copy2(REMOVAL_MANIFEST, source / REMOVAL_MANIFEST.name)

    _seed(destination, DEPRECATED_ROLE_TARGETS, "obsolete")
    _seed(destination, CANONICAL_ROLE_TARGETS, "canonical sentinel")
    expected_sentinels = {
        target: f"canonical sentinel: {target}\n" for target in CANONICAL_ROLE_TARGETS
    }

    result = subprocess.run(
        [
            _chezmoi_binary(),
            "apply",
            "--force",
            "--no-tty",
            "--source",
            str(source),
            "--destination",
            str(destination),
            "--config",
            str(config),
            "--persistent-state",
            str(persistent_state),
            "--cache",
            str(cache),
        ],
        cwd=source,
        capture_output=True,
        text=True,
        timeout=30,
        env=_isolated_environment(destination),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    for target in DEPRECATED_ROLE_TARGETS:
        assert not (destination / target).exists()
    for target, expected in expected_sentinels.items():
        assert (destination / target).read_text() == expected
