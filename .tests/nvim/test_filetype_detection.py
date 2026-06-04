"""Regression tests for chezmoi template filetype detection in Neovim.

WHY THIS FILE EXISTS
    The Neovim config (dot_config/exact_nvim/init.lua) registers a compound-filetype
    detection rule for chezmoi source files: every *.tmpl gets a compound "gotmpl.<lang>"
    type derived by reconstructing the chezmoi target basename (stripping attribute
    prefixes like private_, exact_, dot_ → ., etc.) and querying Neovim's native
    detection. This provides gotmpl TreeSitter highlighting for {{ }} directives (primary)
    and host-language Vim syntax (secondary), replacing the previous static "gotmpl" rule
    that gave zero host-language highlighting.

DESIGN: ONE SPAWN PER CASE, REAL TEMP FILES
    Each test case creates a real temp file with the target basename, opens it in
    headless nvim with the applied config, and queries `vim.bo.filetype` via stderr
    after BufRead fires. This is the only reliable mechanism — vim.filetype.match{filename}
    without a buffer does not invoke extension-key functions (they require a real buffer
    open path), and multi-buffer probes only set filetype on the active buffer.

    A minimal file body is written for cases that need it (e.g. modeline tests). All
    other cases use empty files — filetype detection is purely filename-based for the
    registered patterns.

    WHY NOT vim.filetype.match{filename=}: it works for extension-key string values
    but NOT for extension-key functions or for cases where the extension table is
    overridden (the function is only invoked during real BufRead detection, not during
    programmatic filetype.match calls without a buf).

CRITICAL REGRESSION LOCK
    The dot_zshenv.tmpl -> gotmpl.zsh row is the keystone guard. It fails loudly if
    the vim.fn.fnamemodify(path, ":t") basename extraction or the CHEZMOI_PREFIXES
    stripping loop regresses. Without the basename extraction, pattern functions receive
    the full absolute path (/abs/path/dot_zshenv.tmpl) — the "^dot_" substitution never
    matches — and every file silently falls back to plain "gotmpl".

NOTE
    Tests probe the *applied* config at ~/.config/nvim/init.lua, not the source tree.
    Always run `chezmoi apply ~/.config/nvim/init.lua` after editing init.lua before
    running these tests (or CI will probe a stale config).

WHY SUBPROCESS (NOT UNIT TEST)
    The filetype detection logic lives in init.lua (Lua), not Python. Tests drive it
    as a black box via nvim --headless, matching how a real user encounters it. No
    production refactor for testability — the harness adapts to the artifact's shape.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

# Applied nvim config. Tests skip if this doesn't exist (pre-apply state).
NVIM_CONFIG = Path.home() / ".config" / "nvim" / "init.lua"

# Truth table: (filename, optional_body, expected_ft, description)
# filename: the chezmoi source basename to create as a temp file
# body: file content (None = empty file; use for modeline tests)
# expected_ft: the compound filetype vim.bo.filetype should resolve to
CASES: list[tuple[str, str | None, str, str]] = [
    # --- compound extension: detection survives after stripping .tmpl ---
    ("config.toml.tmpl", None, "gotmpl.toml", "compound .toml.tmpl"),
    ("dot_wezterm.lua.tmpl", None, "gotmpl.lua", "compound .lua.tmpl"),
    ("run_after.linux.sh.tmpl", None, "gotmpl.sh", "compound .sh.tmpl"),
    # --- stacked prefixes: private_ + dot_ stripped, then extension resolves ---
    (
        "private_dot_gh.yml.tmpl",
        None,
        "gotmpl.yaml",
        "stacked private_dot_ + .yml.tmpl",
    ),
    # --- dot_ reconstruction: basename extraction + prefix stripping + dot_→. ---
    # KEYSTONE: fails loudly if fnamemodify(path,":t") is missing (absolute-path bug).
    (
        "dot_zshenv.tmpl",
        None,
        "gotmpl.zsh",
        "dot_zshenv.tmpl → .zshenv → zsh [keystone]",
    ),
    ("dot_profile.tmpl", None, "gotmpl.sh", "dot_profile.tmpl → .profile → sh"),
    # --- UNKNOWN_BASE: reconstructed name has no extension Neovim knows ---
    ("dot_dogrc.tmpl", None, "gotmpl.dosini", "UNKNOWN_BASE: .dogrc → dosini"),
    ("dot_p4enviro.tmpl", None, "gotmpl.dosini", "UNKNOWN_BASE: .p4enviro → dosini"),
    (
        ".chezmoiignore.tmpl",
        None,
        "gotmpl.gitignore",
        "UNKNOWN_BASE: .chezmoiignore → gitignore",
    ),
    # --- modeline override: file body contains # vim: ft=gotmpl.python ---
    # modify_config.json.tmpl uses .json.tmpl name but its body is a Python script;
    # the modeline overrides the gotmpl.json that the extension rule would give.
    (
        "modify_config.json.tmpl",
        "#!/usr/bin/env python3\n# vim: ft=gotmpl.python\nprint(1)\n",
        "gotmpl.python",
        "modeline gotmpl.python overrides extension-based gotmpl.json",
    ),
    # --- plain-gotmpl fallback: unknown body, no host language ---
    ("symlink_vi.tmpl", None, "gotmpl", "symlink target → plain gotmpl fallback"),
    ("private_GEMINI_API_KEY.tmpl", None, "gotmpl", "secret → plain gotmpl fallback"),
    # --- filename key: modify_*.json (no .tmpl suffix) → gotmpl.json ---
    (
        "modify_private_dot_claude.json",
        None,
        "gotmpl.json",
        "modify_*.json (no .tmpl) via filename key → gotmpl.json",
    ),
]


@pytest.fixture(scope="module")
def nvim_bin() -> str:
    nvim = shutil.which("nvim")
    if nvim is None:
        pytest.skip("nvim not on PATH")
    return nvim  # type: ignore[return-value]  # pytest.skip() is NoReturn; mypy can't see it


def _detect_filetype(nvim: str, tmp_path: Path, filename: str, body: str | None) -> str:
    """Open a temp file in headless nvim and return the detected filetype."""
    fpath = tmp_path / filename
    fpath.write_text(body or "")

    result = subprocess.run(
        [
            nvim,
            "--headless",
            "-u",
            str(NVIM_CONFIG),
            str(fpath),
            "-c",
            "lua io.stderr:write('FT=' .. (vim.bo.filetype or 'NIL') .. '\\n')",
            "-c",
            "qa!",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    for line in result.stderr.splitlines():
        if line.startswith("FT="):
            return line[3:].strip()

    # No FT= line found — surface stderr for diagnosis.
    raise AssertionError(
        f"nvim did not emit a FT= line for {filename!r}.\n"
        f"stderr:\n{result.stderr[:2000]}\n"
        f"stdout:\n{result.stdout[:500]}"
    )


@pytest.mark.parametrize(
    "filename,body,expected_ft,description",
    CASES,
    ids=[description for _, _, _, description in CASES],
)
def test_filetype(
    filename: str,
    body: str | None,
    expected_ft: str,
    description: str,
    nvim_bin: str,
    tmp_path: Path,
) -> None:
    """Each chezmoi source filename resolves to the expected compound filetype."""
    if not NVIM_CONFIG.exists():
        pytest.skip(
            f"nvim config not applied: {NVIM_CONFIG} not found — "
            "run `chezmoi apply ~/.config/nvim/init.lua`"
        )

    actual = _detect_filetype(nvim_bin, tmp_path, filename, body)

    assert actual == expected_ft, (
        f"{filename!r}: expected ft={expected_ft!r}, got ft={actual!r}\n"
        f"  description: {description}\n"
        "  Possible causes:\n"
        "  • 'gotmpl' (bare): CHEZMOI_PREFIXES stripping or dot_→. gsub regressed\n"
        "    (check the fnamemodify(':t') call — pattern functions get the abs path)\n"
        "  • 'template': built-in *.tmpl→template rule wins — extension key may be missing\n"
        "  • 'json'/'yaml'/etc.: extension rule wins over filename key — verify\n"
        "    vim.filetype.add filename table entry for this basename\n"
        "  • wrong ft: UNKNOWN_BASE map or reconstruction logic changed\n"
        "  Always `chezmoi apply ~/.config/nvim/init.lua` before running tests."
    )
