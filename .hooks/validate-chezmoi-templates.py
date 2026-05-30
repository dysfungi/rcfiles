#!/usr/bin/env python3
"""
validate-chezmoi-templates.py — pre-commit hook for chezmoi dotfiles.

Renders each staged *.tmpl file (and any file under .chezmoitemplates/) via
`chezmoi execute-template --file` and validates the rendered output with the
appropriate format-specific tool managed by mise.

Design decisions:
  - Two-phase ordering: .chezmoi.*.tmpl files are validated first (without
    --init) because they define the data context that `chezmoi init` uses.
    Only after they pass is `chezmoi init` run once to refresh the on-disk
    config; all other templates then render against the fresh config without
    needing --init themselves. This keeps 1Password lookups to at most one
    per hook run.

  - All validators are required external tools managed via mise. Hard-failing
    on a missing tool (rather than skipping) ensures render-only validation
    never silently replaces format validation — which would defeat the purpose
    of this hook. Run `mise install` to set up the environment.

  - Format-style validators (taplo, markdownlint, shfmt) produce three
    artifacts in a temp directory on failure: the original rendered file,
    the auto-fixed file, and a unified diff. Linter-only validators (jq,
    yamllint, hadolint, luac) produce only their error output — no file is
    preserved, because the error message with line/col is sufficient.

  - Temp directories live under .tmp/chezmoi-validate/ at the repo root
    (gitignored; auto-ignored by chezmoi via dot-prefix). Placing rendered
    output inside the repo lets every format tool discover repo config
    (editorconfig, .stylua.toml, taplo.toml) via the normal upward path
    search — no per-tool flags. Mode 0o700; files within 0o600. On success
    the directory is deleted. On failure it is left in place and its path
    is printed with a secrets warning, since rendered output may contain
    1Password secrets.

  - The Python script is a pure orchestrator — all validation logic lives in
    the external tools. No Python built-ins (json.load, tomllib) are used for
    validation; real linters give better error messages and a consistent model.

Output type detection (filename-based rules first, then extension):
  Filename rules:
    Modelfile, Dockerfile*  ->  dockerfile

  Extension rules:
    .toml   ->  toml
    .json   ->  json
    .yaml   ->  yaml
    .yml    ->  yaml
    .sh     ->  shell
    .lua    ->  lua
    .md     ->  markdown
    (other) ->  render-only

Format-style validators (auto-fixer + linter; produces 3 artifacts on failure):
  toml      auto-fix: taplo fmt <copy>          linter: taplo lint
  markdown  auto-fix: markdownlint --fix <copy> linter: markdownlint
  shell     auto-fix: shfmt -w <copy>               linter: bash -n + shellcheck
  lua       auto-fix: stylua <copy>                 linter: luac -p

Linter-only validators (error output is the artifact; no files preserved):
  dockerfile  hadolint
  json        jq .    (not used as formatter -- reorders keys)
  yaml        yamllint
  python      ruff check

Shebang override: after rendering, the first line is checked for a shebang
(#!.*python, #!.*sh/bash/zsh, #!.*lua). If found, the shebang-detected type
overrides the filename-based type. This handles cases like modify_foo.json.tmpl
that renders to a Python script rather than JSON.

Hard skips (never rendered):
  exact_private_dot_secrets/  renders to bare secret strings
  symlink_* basenames         render to filesystem paths, not parseable formats

Render-only (Go template syntax checked; no format validator):
  .ps1, .conf, no-extension, and any unrecognised extension

Mise-managed tools (all required; hard-fail if missing):
  taplo, jq, yamllint, hadolint, shellcheck, shfmt, stylua, lua, npm:markdownlint-cli, ruff
"""

from __future__ import annotations

import functools
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_TOOL_NOT_FOUND_RE = re.compile(
    r"(no tool found|tool .+? not found|cannot find|command not found)",
    re.IGNORECASE,
)

_EXT_TO_OUTPUT_TYPE: dict[str, str] = {
    ".toml": "toml",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".sh": "shell",
    ".lua": "lua",
    ".md": "markdown",
    ".py": "python",
}

_OUTPUT_TYPE_TO_SUFFIX: dict[str, str] = {
    "toml": ".toml",
    "json": ".json",
    "yaml": ".yaml",
    "shell": ".sh",
    "lua": ".lua",
    "markdown": ".md",
    "python": ".py",
    "dockerfile": "",
    "render-only": "",
}

# Matches `uv` because modify_* scripts use `#!/usr/bin/env -S uv run`
# shebangs (per AGENTS.md convention) and have non-.py extensions like .json.
_SHEBANG_TO_OUTPUT_TYPE: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^#!.*(\bpython|\buv\b)"), "python"),
    (re.compile(r"^#!.*(bash|sh|zsh|dash)"), "shell"),
    (re.compile(r"^#!.*\blua\b"), "lua"),
]

FORMAT_STYLE_TYPES = frozenset({"toml", "markdown", "shell", "lua"})


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def is_chezmoi_config_template(path: str) -> bool:
    return bool(re.search(r"\.chezmoi\..+\.tmpl$", path))


def is_hard_skip(path: str) -> bool:
    rel = path.replace("\\", "/")
    return rel.startswith("exact_private_dot_secrets/") or Path(path).name.startswith(
        "symlink_"
    )


def detect_output_type(path: str) -> str:
    name = Path(path).name
    stem = name.removesuffix(".tmpl") if name.endswith(".tmpl") else name
    if stem == "Modelfile" or re.match(r"^Dockerfile", stem):
        return "dockerfile"
    return _EXT_TO_OUTPUT_TYPE.get(Path(stem).suffix.lower(), "render-only")


def detect_output_type_from_shebang(rendered: Path) -> str | None:
    try:
        first_line = rendered.read_text(errors="replace").splitlines()[0]
    except (IndexError, OSError):
        return None
    for pattern, output_type in _SHEBANG_TO_OUTPUT_TYPE:
        if pattern.match(first_line):
            return output_type
    return None


def suffix_for_output_type(output_type: str) -> str:
    return _OUTPUT_TYPE_TO_SUFFIX.get(output_type, "")


# ---------------------------------------------------------------------------
# Partitioning
# ---------------------------------------------------------------------------


def partition_into_config_and_other(
    files: list[str],
) -> tuple[list[str], list[str]]:
    config = [f for f in files if is_chezmoi_config_template(f)]
    other = [f for f in files if not is_chezmoi_config_template(f)]
    return config, other


# ---------------------------------------------------------------------------
# Mise subprocess wrapper
# ---------------------------------------------------------------------------


def _mise(tool: str, *args: str) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            ["mise", "exec", "--", tool, *args],
            capture_output=True,
        )
    except FileNotFoundError:
        sys.exit("FAIL: mise not found on PATH — install mise first")
    stderr = result.stderr.decode(errors="replace")
    if result.returncode != 0 and _TOOL_NOT_FOUND_RE.search(stderr):
        sys.exit(f"FAIL: {tool} not found — run: mise install")
    return result


@functools.lru_cache(maxsize=None)
def _scratch_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True
    )
    root = (
        Path(result.stdout.decode().strip()) if result.returncode == 0 else Path.cwd()
    )
    scratch = root / ".tmp" / "chezmoi-validate"
    scratch.mkdir(parents=True, exist_ok=True)
    return scratch


def _output_if_failed(result: subprocess.CompletedProcess) -> str | None:
    if result.returncode == 0:
        return None
    output = (result.stdout + result.stderr).decode(errors="replace").strip()
    return output or f"(exited {result.returncode})"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_template_to_file(source: str, dest: Path) -> str | None:
    # Pass --source so chezmoi resolves includeTemplate against the current
    # worktree root, not the default ~/.local/share/chezmoi. This matters when
    # wrapper files reference new .chezmoitemplates/ entries that only exist in
    # the worktree and haven't yet been merged to the main source tree.
    worktree_root = Path(
        subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True)
        .stdout.decode()
        .strip()
    )
    result = subprocess.run(
        [
            "chezmoi",
            "execute-template",
            "--source",
            str(worktree_root),
            "--file",
            source,
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        return result.stderr.decode(errors="replace").strip()
    dest.write_bytes(result.stdout)
    os.chmod(dest, 0o600)
    return None


def refresh_chezmoi_config_from_staged_template() -> str | None:
    result = subprocess.run(["chezmoi", "init"], capture_output=True)
    if result.returncode != 0:
        return result.stderr.decode(errors="replace").strip()
    return None


# ---------------------------------------------------------------------------
# Format-style validation (autofix artifacts + diff)
# ---------------------------------------------------------------------------


def _write_artifact(path: Path, content: bytes | str) -> None:
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)
    os.chmod(path, 0o600)


def _unified_diff(original: Path, fixed: Path) -> str:
    result = subprocess.run(
        ["diff", "--unified", str(original), str(fixed)],
        capture_output=True,
    )
    return result.stdout.decode(errors="replace")


def run_autofix_and_write_diff_artifacts(
    output_type: str, rendered: Path, tmpdir: Path
) -> str | None:
    suffix = suffix_for_output_type(output_type)
    fixed = tmpdir / f"fixed{suffix}"
    shutil.copy2(rendered, fixed)
    os.chmod(fixed, 0o600)

    if output_type == "toml":
        _mise("taplo", "fmt", str(fixed))
    elif output_type == "markdown":
        _mise("markdownlint", "--fix", str(fixed))
    elif output_type == "shell":
        _mise("shfmt", "-w", str(fixed))
    elif output_type == "lua":
        _mise("stylua", str(fixed))

    diff = _unified_diff(rendered, fixed)
    if not diff:
        return None

    _write_artifact(tmpdir / "diff.patch", diff)
    return diff


# ---------------------------------------------------------------------------
# Linter-only validation
# ---------------------------------------------------------------------------


def run_linter(output_type: str, rendered: Path) -> str | None:
    if output_type == "toml":
        return _output_if_failed(_mise("taplo", "lint", str(rendered)))

    if output_type == "markdown":
        return _output_if_failed(_mise("markdownlint", str(rendered)))

    if output_type == "shell":
        bash_err = _output_if_failed(
            subprocess.run(["bash", "-n", str(rendered)], capture_output=True)
        )
        sc_err = _output_if_failed(_mise("shellcheck", str(rendered)))
        combined = "\n".join(filter(None, [bash_err, sc_err]))
        return combined or None

    if output_type == "json":
        return _output_if_failed(_mise("jq", ".", str(rendered)))

    if output_type == "yaml":
        return _output_if_failed(_mise("yamllint", str(rendered)))

    if output_type == "lua":
        return _output_if_failed(_mise("luac", "-p", str(rendered)))

    if output_type == "dockerfile":
        return _output_if_failed(_mise("hadolint", str(rendered)))

    if output_type == "python":
        return _output_if_failed(_mise("ruff", "check", str(rendered)))

    return None  # render-only: no format validator


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def validate_rendered_output(
    output_type: str, rendered: Path, tmpdir: Path
) -> str | None:
    if output_type == "render-only":
        return None

    failures: list[str] = []

    if output_type in FORMAT_STYLE_TYPES:
        diff = run_autofix_and_write_diff_artifacts(output_type, rendered, tmpdir)
        if diff:
            failures.append(f"formatting diff:\n{diff.rstrip()}")

    lint_output = run_linter(output_type, rendered)
    if lint_output:
        failures.append(lint_output)

    return "\n".join(failures) if failures else None


def _print_artifact_hint(tmpdir: Path) -> None:
    print(f"hint: artifacts preserved at {tmpdir}/", file=sys.stderr)
    for artifact in sorted(tmpdir.iterdir()):
        print(f"      {artifact.name}", file=sys.stderr)
    print(
        f"      ⚠  may contain secrets — delete when done: rm -rf {tmpdir}",
        file=sys.stderr,
    )


def process_file(source: str) -> bool:
    output_type = detect_output_type(source)
    tmpdir = Path(tempfile.mkdtemp(dir=_scratch_root()))
    os.chmod(tmpdir, 0o700)
    rendered = tmpdir / f"rendered{suffix_for_output_type(output_type)}"

    render_err = render_template_to_file(source, rendered)
    if render_err:
        shutil.rmtree(tmpdir)
        print(f"FAIL  {source}: render failed:\n{render_err}", file=sys.stderr)
        return False

    # Shebang overrides filename-based detection (e.g. modify_foo.json.tmpl
    # that renders to a Python script).
    shebang_type = detect_output_type_from_shebang(rendered)
    if shebang_type and shebang_type != output_type:
        new_rendered = rendered.rename(
            tmpdir / f"rendered{suffix_for_output_type(shebang_type)}"
        )
        rendered = new_rendered
        output_type = shebang_type

    validation_err = validate_rendered_output(output_type, rendered, tmpdir)
    if validation_err:
        print(f"FAIL  {source}: {validation_err}", file=sys.stderr)
        _print_artifact_hint(tmpdir)
        return False

    shutil.rmtree(tmpdir)
    return True


def run_hook(files: list[str]) -> int:
    actionable = [f for f in files if not is_hard_skip(f)]
    config_templates, other_templates = partition_into_config_and_other(actionable)
    needs_config_refresh = bool(config_templates)

    # Chezmoi config templates (e.g. .chezmoi.toml.tmpl) use promptString and
    # onepasswordRead, which are registered only in chezmoi init's FuncMap —
    # not in execute-template's. They fail at compile time (not runtime), so
    # render_template_to_file always rejects them. Use chezmoi init instead.
    config_templates_all_passed = True
    if needs_config_refresh:
        err = refresh_chezmoi_config_from_staged_template()
        if err:
            print(
                f"FAIL  chezmoi config templates: chezmoi init failed:\n{err}",
                file=sys.stderr,
            )
            config_templates_all_passed = False

    other_results = [process_file(f) for f in other_templates]
    other_all_passed = all(other_results)

    return 0 if (config_templates_all_passed and other_all_passed) else 1


if __name__ == "__main__":
    sys.exit(run_hook(sys.argv[1:]))
