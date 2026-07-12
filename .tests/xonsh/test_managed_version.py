"""Keep the xonsh test interpreter aligned with the managed shell runtime.

The managed mamba environment installs ``xonsh[full]`` while the regression
suite only needs core xonsh.  Both declarations intentionally pin the same core
version, and this test verifies the lock-resolved interpreter too.  That makes a
runtime upgrade explicit rather than silently exercising a different xonsh
release from the one users receive.
"""

from __future__ import annotations

from importlib.metadata import version as distribution_version
from pathlib import Path
import re
import tomllib

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGES = REPO_ROOT / ".chezmoidata" / "packages.yaml"
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _managed_xonsh_requirement() -> str:
    """Return the exact xonsh requirement installed in the mamba environment."""
    package_data = yaml.safe_load(PACKAGES.read_text())
    requirement = package_data["my"]["packages"]["xonsh"]["mamba"]
    assert isinstance(requirement, str)
    return requirement


def _test_xonsh_requirement() -> str:
    """Return the single xonsh requirement declared for regression tests."""
    project = tomllib.loads(PYPROJECT.read_text())
    requirements = project["dependency-groups"]["test"]
    matches = [
        requirement for requirement in requirements if requirement.startswith("xonsh")
    ]
    assert len(matches) == 1
    return matches[0]


def test_xonsh_test_runtime_matches_managed_version() -> None:
    """The lock-resolved test shell and managed shell use one core xonsh release."""
    managed_requirement = _managed_xonsh_requirement()
    match = re.fullmatch(r"xonsh\[full\]==(?P<version>[^=]+)", managed_requirement)
    assert match is not None, managed_requirement

    expected_version = match["version"]
    assert _test_xonsh_requirement() == f"xonsh=={expected_version}"
    assert distribution_version("xonsh") == expected_version
