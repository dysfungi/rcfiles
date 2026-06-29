"""Tests for .hooks/validate-chezmoi-templates.py.

Two layers:
  - Unit: pure classification functions that route each staged file — output
    type detection (extension, filename, shebang), hard-skip rules, config
    template identification, partitioning. Deterministic; no filesystem writes
    (except detect_output_type_from_shebang, which reads a file).
  - Integration: the whitespace-only skip guard, exercised by invoking the hook
    as a real subprocess against fixture *.tmpl files in a throwaway git repo
    (see the "empty-render skip" section at the bottom).
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
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


# ---------------------------------------------------------------------------
# Integration: whitespace-only render skip
#
# Subprocess-driven (per repo convention): invoke the hook as a real
# `python3 .hooks/validate-chezmoi-templates.py <file>` against fixture *.tmpl
# files inside a throwaway git repo, exactly as pre-commit would. This is the
# executable spec for the empty-render guard: a template that renders empty on
# the current host (a body wholly wrapped in `{{ if .is_riot_machine }}…{{ end }}`)
# must PASS without being handed to shellcheck (which would false-positive with
# SC2148 on the empty buffer). The malformed-shell case guards against the skip
# being too broad — a NON-empty render must still be linted and still fail.
# ---------------------------------------------------------------------------


def _run_hook(repo: Path, filename: str, body: str) -> subprocess.CompletedProcess:
    """Drop a fixture template into the repo and run the hook against it.

    cwd is the throwaway repo so the hook's `git rev-parse --show-toplevel`
    (used for --source and the .tmp scratch dir) resolves there, not the real
    chezmoi repo. GIT_* is stripped from env for the same isolation reason as
    conftest's git helpers (pre-commit leaks GIT_DIR into subprocess env).
    """
    (repo / filename).write_text(body)
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        [sys.executable, str(_hook_path), filename],
        cwd=repo,
        capture_output=True,
        text=True,
        env=clean,
    )


# (filename, body, should_pass, description)
_EMPTY_RENDER_CASES = [
    (
        "empty.sh.tmpl",
        "{{ if false }}echo hi{{ end }}\n",
        True,
        "conditional renders empty -> skip (no SC2148 false-positive)",
    ),
    (
        "blank.sh.tmpl",
        "{{ if false }}x{{ end }}\n  \n\t\n",
        True,
        "whitespace-only render -> skip (.strip() guard, not just len 0)",
    ),
    (
        "bad.sh.tmpl",
        "if then fi\n",
        False,
        "non-empty malformed shell still linted and fails (skip not too broad)",
    ),
]


@pytest.mark.parametrize(
    ("filename", "body", "should_pass", "desc"),
    _EMPTY_RENDER_CASES,
    ids=[c[3] for c in _EMPTY_RENDER_CASES],
)
def test_empty_render_skip(
    git_repo: Path, filename: str, body: str, should_pass: bool, desc: str
) -> None:
    result = _run_hook(git_repo, filename, body)
    if should_pass:
        assert result.returncode == 0, (
            f"expected PASS: {desc}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    else:
        assert result.returncode != 0, (
            f"expected FAIL: {desc}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# Integration: config refresh reads from the worktree source
# ---------------------------------------------------------------------------


def test_refresh_config_uses_worktree_source(git_repo: Path) -> None:
    """Regression: config refresh must read .chezmoi.toml.tmpl from the worktree
    (`chezmoi init --source <worktree_root>`), not chezmoi's default/configured
    source.

    A template reads a [data] key defined only in the worktree's
    .chezmoi.toml.tmpl. With the fix, `chezmoi init --source <worktree>`
    populates the config with that key and the render succeeds. Without it, a
    bare `chezmoi init` reads the (empty) default source under the isolated
    HOME, the key is absent, and the render fails with "map has no entry".

    Guards the --source flag on the chezmoi init call in
    refresh_chezmoi_config_from_staged_template().
    """
    (git_repo / ".chezmoi.toml.tmpl").write_text(
        '[data]\nworktree_only_key = "test-value"\n'
    )
    (git_repo / "dot_config").mkdir()
    (git_repo / "dot_config" / "thing.toml.tmpl").write_text(
        "value = {{ .worktree_only_key | quote }}\n"
    )
    # __MISE_* are mise's internal activation-state vars (we run under `mise x`).
    # Once HOME is mutated below, mise's __MISE_DIFF reconciliation breaks the
    # nested `mise exec -- <tool>` shim lookup ("not a valid shim"); strip them
    # so the hook's validators still resolve. Same class of wrapper-env leak as
    # GIT_* (see conftest).
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("GIT_", "CHEZMOI_", "__MISE"))
    }
    env["HOME"] = str(git_repo)  # isolate: chezmoi init writes to $HOME/.config/chezmoi
    result = subprocess.run(
        [
            sys.executable,
            str(_hook_path),
            ".chezmoi.toml.tmpl",
            "dot_config/thing.toml.tmpl",
        ],
        cwd=git_repo,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, (
        "validator should pass when the key is defined in the worktree config; "
        f"stderr:\n{result.stderr}"
    )
