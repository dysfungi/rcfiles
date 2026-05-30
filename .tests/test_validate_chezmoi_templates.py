"""Tests for .hooks/validate-chezmoi-templates.py — template classification.

Covers the pure classification functions that determine how each staged file
is routed: output type detection (extension, filename, shebang), hard-skip
rules, config template identification, and partitioning.

These are regression tests — the functions are deterministic and don't touch
the filesystem (except detect_output_type_from_shebang, which reads a file).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_hook_path = (
    Path(__file__).resolve().parents[1] / ".hooks" / "validate-chezmoi-templates.py"
)
_spec = importlib.util.spec_from_file_location("validate_chezmoi_templates", _hook_path)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["validate_chezmoi_templates"] = _mod
_spec.loader.exec_module(_mod)

detect_output_type = _mod.detect_output_type
detect_output_type_from_shebang = _mod.detect_output_type_from_shebang
is_chezmoi_config_template = _mod.is_chezmoi_config_template
is_hard_skip = _mod.is_hard_skip
partition_into_config_and_other = _mod.partition_into_config_and_other
suffix_for_output_type = _mod.suffix_for_output_type


# ---------------------------------------------------------------------------
# detect_output_type: extension-based detection
# ---------------------------------------------------------------------------

_OUTPUT_TYPE_CASES = [
    # Extension-based
    ("dot_config/foo/bar.toml.tmpl", "toml"),
    ("dot_config/foo/bar.toml", "toml"),
    ("some/path/config.json.tmpl", "json"),
    ("some/path/config.json", "json"),
    ("dot_config/yamllint/config.yaml.tmpl", "yaml"),
    ("dot_config/yamllint/config.yml.tmpl", "yaml"),
    ("dot_local/bin/script.sh.tmpl", "shell"),
    (".chezmoitemplates/foo.sh", "shell"),
    ("dot_config/nvim/init.lua.tmpl", "lua"),
    ("dot_config/nvim/init.lua", "lua"),
    ("README.md.tmpl", "markdown"),
    ("notes.md", "markdown"),
    ("dot_local/bin/script.py.tmpl", "python"),
    ("script.py", "python"),
    # Filename-based (dockerfile)
    ("Dockerfile.tmpl", "dockerfile"),
    ("Dockerfile", "dockerfile"),
    ("Dockerfile.dev.tmpl", "dockerfile"),
    ("Modelfile", "dockerfile"),
    ("Modelfile.tmpl", "dockerfile"),
    # Render-only (unrecognised extensions)
    ("dot_config/foo/bar.conf.tmpl", "render-only"),
    ("dot_config/foo/bar.ps1.tmpl", "render-only"),
    ("dot_profile.tmpl", "render-only"),
    (".chezmoitemplates/some_partial", "render-only"),
    # Case insensitivity for extensions
    ("CONFIG.TOML.tmpl", "toml"),
    ("data.JSON.tmpl", "json"),
    ("style.SH.tmpl", "shell"),
]


@pytest.mark.parametrize(
    ("path", "expected"),
    _OUTPUT_TYPE_CASES,
    ids=[f"{c[1]}:{Path(c[0]).name}" for c in _OUTPUT_TYPE_CASES],
)
def test_detect_output_type(path: str, expected: str) -> None:
    assert detect_output_type(path) == expected


# ---------------------------------------------------------------------------
# is_hard_skip
# ---------------------------------------------------------------------------

_HARD_SKIP_YES = [
    ("exact_private_dot_secrets/token.txt", "secrets dir"),
    ("exact_private_dot_secrets/nested/deep.json", "nested secrets"),
    ("symlink_dot_gitconfig", "symlink basename"),
    ("some/dir/symlink_foo", "symlink in subdirectory"),
]

_HARD_SKIP_NO = [
    ("dot_config/foo.toml.tmpl", "normal template"),
    ("exact_dot_config/foo.sh.tmpl", "exact prefix but not secrets"),
    (".chezmoitemplates/partial.sh", "shared template"),
    ("dot_local/bin/script.py", "normal script"),
]


@pytest.mark.parametrize(
    ("path", "desc"), _HARD_SKIP_YES, ids=[h[1] for h in _HARD_SKIP_YES]
)
def test_hard_skip_yes(path: str, desc: str) -> None:
    assert is_hard_skip(path) is True, f"should skip: {desc}"


@pytest.mark.parametrize(
    ("path", "desc"), _HARD_SKIP_NO, ids=[h[1] for h in _HARD_SKIP_NO]
)
def test_hard_skip_no(path: str, desc: str) -> None:
    assert is_hard_skip(path) is False, f"should not skip: {desc}"


# ---------------------------------------------------------------------------
# is_chezmoi_config_template
# ---------------------------------------------------------------------------

_CONFIG_TMPL_YES = [
    (".chezmoi.toml.tmpl", "toml config"),
    (".chezmoi.yaml.tmpl", "yaml config"),
    (".chezmoi.json.tmpl", "json config"),
    ("home/.chezmoi.toml.tmpl", "nested path"),
]

_CONFIG_TMPL_NO = [
    ("dot_config/foo.toml.tmpl", "regular template"),
    (".chezmoiignore.tmpl", "ignore file (no dot-name-dot pattern)"),
    (".chezmoitemplates/foo.sh", "shared template"),
    (".chezmoi.toml", "config without .tmpl suffix"),
]


@pytest.mark.parametrize(
    ("path", "desc"), _CONFIG_TMPL_YES, ids=[c[1] for c in _CONFIG_TMPL_YES]
)
def test_config_template_yes(path: str, desc: str) -> None:
    assert is_chezmoi_config_template(path) is True, f"should match: {desc}"


@pytest.mark.parametrize(
    ("path", "desc"), _CONFIG_TMPL_NO, ids=[c[1] for c in _CONFIG_TMPL_NO]
)
def test_config_template_no(path: str, desc: str) -> None:
    assert is_chezmoi_config_template(path) is False, f"should not match: {desc}"


# ---------------------------------------------------------------------------
# partition_into_config_and_other
# ---------------------------------------------------------------------------


def test_partition_empty() -> None:
    config, other = partition_into_config_and_other([])
    assert config == []
    assert other == []


def test_partition_mixed() -> None:
    files = [
        ".chezmoi.toml.tmpl",
        "dot_config/foo.sh.tmpl",
        ".chezmoi.yaml.tmpl",
        "dot_profile.tmpl",
    ]
    config, other = partition_into_config_and_other(files)
    assert config == [".chezmoi.toml.tmpl", ".chezmoi.yaml.tmpl"]
    assert other == ["dot_config/foo.sh.tmpl", "dot_profile.tmpl"]


def test_partition_all_config() -> None:
    files = [".chezmoi.toml.tmpl", ".chezmoi.json.tmpl"]
    config, other = partition_into_config_and_other(files)
    assert config == files
    assert other == []


def test_partition_no_config() -> None:
    files = ["dot_config/foo.sh.tmpl", "dot_profile.tmpl"]
    config, other = partition_into_config_and_other(files)
    assert config == []
    assert other == files


# ---------------------------------------------------------------------------
# suffix_for_output_type
# ---------------------------------------------------------------------------

_SUFFIX_CASES = [
    ("toml", ".toml"),
    ("json", ".json"),
    ("yaml", ".yaml"),
    ("shell", ".sh"),
    ("lua", ".lua"),
    ("markdown", ".md"),
    ("python", ".py"),
    ("dockerfile", ""),
    ("render-only", ""),
    ("unknown-type", ""),
]


@pytest.mark.parametrize(
    ("output_type", "expected"), _SUFFIX_CASES, ids=[s[0] for s in _SUFFIX_CASES]
)
def test_suffix_for_output_type(output_type: str, expected: str) -> None:
    assert suffix_for_output_type(output_type) == expected


# ---------------------------------------------------------------------------
# detect_output_type_from_shebang
# ---------------------------------------------------------------------------

# uv shebangs are critical: modify_* scripts (e.g. modify_config.json.tmpl)
# render to Python but have non-.py extensions — shebang is the only signal.
_SHEBANG_CASES = [
    ("#!/usr/bin/env python3\nimport sys\n", "python"),
    ("#!/usr/bin/python\nimport os\n", "python"),
    ("#!/usr/bin/env python\nimport sys\n", "python"),
    ("#!/usr/bin/env -S uv run\nimport sys\n", "python"),
    ("#!/usr/bin/env -S uv run --script\nimport sys\n", "python"),
    ("#!/usr/bin/env -S uv run --no-project\nimport sys\n", "python"),
    ("#!/bin/bash\nset -euo pipefail\n", "shell"),
    ("#!/usr/bin/env bash\necho hi\n", "shell"),
    ("#!/bin/sh\necho hi\n", "shell"),
    ("#!/usr/bin/env zsh\necho hi\n", "shell"),
    ("#!/usr/bin/env dash\necho hi\n", "shell"),
    ("#!/usr/bin/lua\nprint('hi')\n", "lua"),
    ("#!/usr/bin/env lua\nprint('hi')\n", "lua"),
]

_SHEBANG_NONE = [
    ("no shebang here\njust text\n", "no shebang"),
    ("", "empty file"),
    ('{"key": "value"}\n', "json content"),
    ("# yaml comment\nfoo: bar\n", "yaml comment, not shebang"),
]


@pytest.mark.parametrize(
    ("content", "expected"),
    _SHEBANG_CASES,
    ids=[f"{s[1]}:{s[0].splitlines()[0][:30]}" for s in _SHEBANG_CASES],
)
def test_shebang_detection(tmp_path: Path, content: str, expected: str) -> None:
    f = tmp_path / "rendered"
    f.write_text(content)
    assert detect_output_type_from_shebang(f) == expected


@pytest.mark.parametrize(
    ("content", "desc"),
    _SHEBANG_NONE,
    ids=[s[1] for s in _SHEBANG_NONE],
)
def test_shebang_none(tmp_path: Path, content: str, desc: str) -> None:
    f = tmp_path / "rendered"
    f.write_text(content)
    assert detect_output_type_from_shebang(f) is None, f"should return None: {desc}"


def test_shebang_missing_file(tmp_path: Path) -> None:
    assert detect_output_type_from_shebang(tmp_path / "nonexistent") is None
