"""Regression guard: every managed ``.xsh`` file must parse on the live xonsh.

WHY THIS EXISTS
    Python 3.14 adopted the PEP 701 native f-string parser. xonsh's
    ``fstring_adaptor`` cannot handle xonsh subprocess/capture substitution
    (``$(...)``, ``@(...)``, ``${...}``) *inside* an f-string literal, so a
    construct like ``f"--add=:{args[0]}:{$(pwd).strip()}"`` raises
    ``RuntimeError: Unsupported fstring syntax`` at compile time. Because rc.d
    files are sourced at startup, a single such line aborts the entire xonsh
    launch and drops the user to ``/bin/bash``.

    This footgun is invisible until a shell is launched on the new interpreter,
    so a static lint cannot fully cover it. Instead this test drives the *real*
    xonsh execer (via the ``xonsh`` binary, guaranteeing the live Python) to
    compile-check every ``.xsh`` file. Parse-only reproduces the crash class
    without needing the runtime builtins each file depends on.

    See dot_config/xonsh/exact_rc.d/45-cdargs.xsh for the original offender.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANAGED_ROOT = REPO_ROOT / "home"
XONSH_DIR = MANAGED_ROOT / "dot_config" / "xonsh"

# Inline xonsh program template: compile-check one file via the live execer.
# The path is embedded (not passed via argv, which xonsh -c does not forward to
# sys.argv). Prints a sentinel on success; exits non-zero with the error on
# failure.
_COMPILE_CHECK = """
import sys
from xonsh.built_ins import XSH
path = {path!r}
src = open(path).read()
try:
    XSH.execer.compile(src, mode="exec", glbs={{}}, locs={{}}, filename=path)
except BaseException as e:
    print("COMPILE_FAIL:" + type(e).__name__ + ":" + str(e), file=sys.stderr)
    sys.exit(1)
print("COMPILE_OK")
"""

_XONSH_BIN = shutil.which("xonsh")

_XSH_FILES = sorted(XONSH_DIR.rglob("*.xsh")) if XONSH_DIR.is_dir() else []


@pytest.mark.skipif(_XONSH_BIN is None, reason="xonsh binary not on PATH")
@pytest.mark.skipif(not _XSH_FILES, reason="no .xsh files found")
@pytest.mark.parametrize(
    "xsh_file", _XSH_FILES, ids=[str(p.relative_to(REPO_ROOT)) for p in _XSH_FILES]
)
def test_xsh_file_compiles(xsh_file: Path) -> None:
    """Each ``.xsh`` file compiles cleanly under the live xonsh execer."""
    assert _XONSH_BIN is not None  # guaranteed by skipif; narrows for mypy
    proc = subprocess.run(
        [_XONSH_BIN, "--no-rc", "-c", _COMPILE_CHECK.format(path=str(xsh_file))],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"{xsh_file.relative_to(REPO_ROOT)} failed to compile on the live xonsh:\n"
        f"{proc.stderr}"
    )
