"""Integration tests for Parsec's rendered config management.

The shared ``modify_`` template is the source of truth for macOS and native
Windows. Render it through chezmoi, execute the resulting stdin-to-stdout
filter, and assert the platform-specific source stays idempotent with Parsec's
own serialization behavior.

The platform-routing regression uses a scratch source and real ``chezmoi apply
--dry-run --verbose`` invocation. Source-state consistency is evaluated while
chezmoi builds its full source state; rendering or ``source-path`` alone cannot
expose incompatible special-file rules.
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
SHARED_CONFIG = MANAGED_ROOT / "private_dot_parsec" / "modify_config.json.py.tmpl"
WINDOWS_CONFIG = (
    MANAGED_ROOT / "AppData" / "Roaming" / "Parsec" / "modify_config.json.py.tmpl"
)
IGNORE = MANAGED_ROOT / ".chezmoiignore.tmpl"
REMOVALS = MANAGED_ROOT / ".chezmoiremove"
WINDOWS_TARGET = Path.home() / "AppData" / "Roaming" / "Parsec" / "config.json"


def _clean_environment() -> dict[str, str]:
    """Keep mise tooling while isolating chezmoi from caller state."""
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("CHEZMOI_", "GIT_"))
    }


def _write_config(
    tmp_path: Path,
    data: dict[str, bool],
    *,
    with_python_interpreter: bool = False,
) -> Path:
    """Write deterministic machine-detection data for a chezmoi subprocess."""
    config = tmp_path / "chezmoi.toml"
    content = "[data]\n" + "".join(
        f"{key} = {str(value).lower()}\n" for key, value in sorted(data.items())
    )
    if with_python_interpreter:
        content += (
            "\n[interpreters]\n"
            f"py = {{ command = {json.dumps(str(sys.executable))} }}\n"
        )
    config.write_text(content)
    return config


def _render(template: Path, data: dict[str, bool], tmp_path: Path) -> bytes:
    """Render one template with deterministic machine-detection data."""
    config = _write_config(tmp_path, data)
    result = subprocess.run(
        [
            "chezmoi",
            "execute-template",
            "--config",
            str(config),
            "--source",
            str(REPO_ROOT),
            "--file",
            str(template),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        env=_clean_environment(),
    )
    assert result.returncode == 0, result.stderr.decode()
    return result.stdout


def _scratch_source(tmp_path: Path) -> Path:
    """Copy the Parsec sources and special files needed for an apply dry run."""
    source = tmp_path / "source"
    source.mkdir()
    for template in (IGNORE, REMOVALS, SHARED_CONFIG, WINDOWS_CONFIG):
        copied = source / template.relative_to(MANAGED_ROOT)
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(template, copied)
    return source


def _dry_run_apply(
    source: Path, data: dict[str, bool], tmp_path: Path
) -> subprocess.CompletedProcess[str]:
    """Build source state in an isolated destination without applying changes."""
    destination = tmp_path / "destination"
    destination.mkdir()
    config = _write_config(tmp_path, data, with_python_interpreter=True)
    return subprocess.run(
        [
            "chezmoi",
            "apply",
            "--dry-run",
            "--verbose",
            "--no-tty",
            "--config",
            str(config),
            "--source",
            str(source),
            "--destination",
            str(destination),
            "--cache",
            str(tmp_path / "cache"),
            "--persistent-state",
            str(tmp_path / "state.boltdb"),
        ],
        cwd=source,
        capture_output=True,
        text=True,
        env=_clean_environment(),
    )


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(
            {"is_darwin": True, "is_riot_machine": True, "is_windows": False},
            id="darwin-riot",
        ),
        pytest.param(
            {"is_darwin": False, "is_riot_machine": True, "is_windows": True},
            id="windows-riot",
        ),
    ],
)
def test_config_output_has_no_trailing_newline(
    data: dict[str, bool], tmp_path: Path
) -> None:
    """Parsec rewrites its JSON without a final newline, so applies must match."""
    script = tmp_path / "modify_config.py"
    script.write_bytes(_render(SHARED_CONFIG, data, tmp_path))

    result = subprocess.run(
        [sys.executable, str(script)], input=b"", capture_output=True
    )

    assert result.returncode == 0, result.stderr.decode()
    assert json.loads(result.stdout)[0]
    assert not result.stdout.endswith(b"\n")


def test_windows_config_template_reuses_shared_rendering(tmp_path: Path) -> None:
    """The Windows target must stay behaviorally identical to the shared source."""
    data = {"is_darwin": False, "is_riot_machine": True, "is_windows": True}

    assert _render(WINDOWS_CONFIG, data, tmp_path) == _render(
        SHARED_CONFIG, data, tmp_path
    )


def test_windows_config_source_maps_to_parsec_target(tmp_path: Path) -> None:
    """Chezmoi's modify_ filename maps to the config file Parsec actually reads."""
    source = tmp_path / "source"
    copied_config = source / WINDOWS_CONFIG.relative_to(MANAGED_ROOT)
    copied_config.parent.mkdir(parents=True)
    shutil.copy2(WINDOWS_CONFIG, copied_config)
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
            str(WINDOWS_TARGET),
        ],
        capture_output=True,
        text=True,
        env=_clean_environment(),
    )

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == copied_config


_IGNORE_CASES = [
    pytest.param(
        {
            "is_darwin": False,
            "is_linux": False,
            "is_riot_machine": False,
            "is_unix_like": False,
            "is_windows": True,
            "is_work_machine": False,
            "is_wsl": False,
        },
        True,
        id="native-windows",
    ),
    pytest.param(
        {
            "is_darwin": False,
            "is_linux": True,
            "is_riot_machine": False,
            "is_unix_like": True,
            "is_windows": False,
            "is_work_machine": False,
            "is_wsl": True,
        },
        True,
        id="wsl",
    ),
    pytest.param(
        {
            "is_darwin": True,
            "is_linux": False,
            "is_riot_machine": False,
            "is_unix_like": True,
            "is_windows": False,
            "is_work_machine": False,
            "is_wsl": False,
        },
        False,
        id="darwin",
    ),
]


@pytest.mark.parametrize(("data", "should_ignore"), _IGNORE_CASES)
def test_parsec_ignore_is_platform_scoped_with_consistent_source_state(
    data: dict[str, bool], should_ignore: bool, tmp_path: Path
) -> None:
    """Ignored platforms must not collide with the active Parsec modify_ source."""
    rendered_lines = _render(IGNORE, data, tmp_path).decode().splitlines()
    assert (".parsec/**" in rendered_lines) is should_ignore

    result = _dry_run_apply(_scratch_source(tmp_path), data, tmp_path)
    combined_output = result.stdout + result.stderr
    assert result.returncode == 0, combined_output
    assert "inconsistent state" not in combined_output.lower()
