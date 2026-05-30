"""End-to-end regression tests for the npm wrapper-postinstall materializer
in `.chezmoiscripts/20/run_after_sync-mise.unix-like.sh`.

WHY THIS FILE EXISTS
    mise's npm backend installs the optional-deps tree but does NOT execute
    npm lifecycle scripts. Wrapper-binary packages (@anthropic-ai/claude-code,
    esbuild, sharp, @biomejs/biome) ship a small placeholder bin and rely on
    `scripts.postinstall` to hardlink the real native binary from a
    per-platform optional dep. The materializer block in run_after_sync-mise
    detects this pattern (K-δ heuristic: postinstall declared AND
    optionalDependencies has a per-host-platform key AND bin file < 4 KB)
    and re-runs the upstream postinstall, then verifies the bin is > 4 KB
    and executable.

WHY THIS IS A SUBPROCESS TEST (NOT A UNIT TEST)
    The script is treated as a black box. Tests build a fake mise install
    tree under tmp_path, stub `mise` on PATH to a no-op, point HOME and
    CHEZMOI_* at the tmp tree, then invoke the actual script via
    `bash $SCRIPT`. Assertions check filesystem state after the run.
    No production refactor for testability — the harness adapts to the
    script's real shape.

WHY THE PARAMETRIZED TABLE
    Each row is one truth-row of the K-δ predicate that matters in
    practice: wrapper matches, no-postinstall skipped, wrong-platform
    skipped, idempotency, verifier-fails-loudly, mixed packages. The
    table doubles as the executable spec for the materializer's behavior.

GIT ISOLATION DESIGN (root-cause note)
    The script uses `local -x GIT_DIR` / `local -x GIT_WORK_TREE` (pointing
    at `CHEZMOI_SOURCE_DIR`) inside `_commit_backup`, so its git calls target
    the per-test tmp repo, not the real chezmoi repo.  Two local guards prevent
    regressions specific to this test file:

    1. _clean_env() strips GIT_* vars leaked by pre-commit into child
       processes (git init, git commit, the script itself).
    2. _run_script() sets cwd=CHEZMOI_SOURCE_DIR so the bash script starts
       inside the temp git repo; any bare `git` call without GIT_DIR will
       auto-discover the tmp .git via directory traversal, not the real one.

    The session-wide guard (assert_real_repo_unaffected in conftest.py) catches
    regressions in any test file across the whole suite.

    Root cause of the original core.bare corruption: the test was developed
    without _clean_env(), allowing pre-commit to leak GIT_DIR into subprocess
    calls that hit the real chezmoi repo and bare-initialized it.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / ".chezmoiscripts/20/run_after_sync-mise.unix-like.sh"


# Mirror the bash `_host_platform_suffix` logic so tests can construct
# optionalDependency keys that DO and DO NOT match this host.
_HOST_SUFFIX_TABLE: dict[tuple[str, str], str] = {
    ("Darwin", "arm64"): "darwin-arm64",
    ("Darwin", "x86_64"): "darwin-x64",
    ("Linux", "x86_64"): "linux-x64",
    ("Linux", "amd64"): "linux-x64",
    ("Linux", "aarch64"): "linux-arm64",
    ("Linux", "arm64"): "linux-arm64",
}
_uname = os.uname()
HOST_SUFFIX = _HOST_SUFFIX_TABLE.get((_uname.sysname, _uname.machine))
if HOST_SUFFIX is None:
    pytest.skip(
        f"unsupported host platform for these tests: {_uname.sysname}/{_uname.machine}",
        allow_module_level=True,
    )
# Narrow the type for the rest of the module (the skip above never returns
# on unsupported hosts; this assert lets mypy see HOST_SUFFIX as str, not None).
assert HOST_SUFFIX is not None


@dataclasses.dataclass
class FakePkg:
    """Description of a fake npm-backend mise install to materialize on disk.

    Layout produced under HOME:
        ~/.local/share/mise/installs/npm-<sanitized>/<version>/
          lib/node_modules/<name>/
            package.json
            install.cjs        (if `install_cjs` is given)
            bin/<basename>     (sized at `stub_size`)
    """

    name: str  # e.g. "@anthropic-ai/claude-code" or "markdownlint-cli"
    version: str = "1.0.0"
    postinstall: str | None = None  # e.g. "node install.cjs"
    opt_deps: dict[str, str] | None = None
    # `bin` is either a string ("bin/foo") or dict ({"foo": "bin/foo"}).
    bin: str | dict[str, str] | None = None
    stub_size: int = 500  # size of the bin stub written before the script runs
    install_cjs: str | None = None  # Node source for the postinstall shim
    extra_bins: dict[str, int] | None = None  # name → size for additional fakes


def _sanitize_install_dirname(name: str) -> str:
    """Mirror mise's npm-backend install-dir naming. mise stores
    `@scope/pkg` under `npm-scope-pkg` (slashes and `@` stripped)."""
    return "npm-" + name.replace("@", "").replace("/", "-")


def _bin_entries(b: str | dict[str, str] | None) -> list[tuple[str, str]]:
    """Return list of (name, relative_path) tuples from a package.json bin field."""
    if b is None:
        return []
    if isinstance(b, str):
        return [(Path(b).stem, b)]
    return list(b.items())


def _write_fake_pkg(home: Path, p: FakePkg) -> Path:
    """Materialize one FakePkg under HOME. Returns the package dir."""
    pkg_dir = (
        home
        / ".local/share/mise/installs"
        / _sanitize_install_dirname(p.name)
        / p.version
        / "lib/node_modules"
        / p.name
    )
    pkg_dir.mkdir(parents=True)

    pkg_json: dict[str, Any] = {"name": p.name, "version": p.version}
    if p.postinstall:
        pkg_json["scripts"] = {"postinstall": p.postinstall}
    if p.opt_deps:
        pkg_json["optionalDependencies"] = p.opt_deps
    if p.bin is not None:
        pkg_json["bin"] = p.bin
    (pkg_dir / "package.json").write_text(json.dumps(pkg_json, indent=2))

    for _, rel in _bin_entries(p.bin):
        bin_path = pkg_dir / rel
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        # Stub contents: ASCII text padded to `stub_size`.
        # Mimics the real claude.exe stub shape (printable, no shebang).
        body = b"x" * p.stub_size
        bin_path.write_bytes(body)
        # Bins >= 4 KB represent the "already materialized" state and would
        # be executable in reality; chmod +x so the post-run executable check
        # passes on idempotency tests.
        if p.stub_size >= 4096:
            bin_path.chmod(0o755)

    if p.install_cjs is not None:
        (pkg_dir / "install.cjs").write_text(p.install_cjs)

    return pkg_dir


# A working install.cjs shim: opens bin/<bin>, writes 8 KB of zeros, chmods +x.
# Generic so it works for any FakePkg shape (reads bin from package.json).
WORKING_INSTALL_CJS = """
const fs = require('fs');
const path = require('path');
const pkg = require('./package.json');
const bin = pkg.bin;
const rel = typeof bin === 'string' ? bin : Object.values(bin)[0];
const dest = path.join(__dirname, rel);
fs.writeFileSync(dest, Buffer.alloc(8192));
fs.chmodSync(dest, 0o755);
"""

# A broken install.cjs shim: noop, leaves the stub in place.
BROKEN_INSTALL_CJS = "// intentionally no-op for verifier test\n"


def _clean_env() -> dict[str, str]:
    """Return os.environ stripped of GIT_* vars. When this test file is run
    via `pre-commit run pytest`, pre-commit's invocation leaks GIT_DIR /
    GIT_INDEX_FILE / etc. into the child process; those would redirect our
    fixture's `git init` and `git commit` into the chezmoi repo itself and
    trigger its pre-commit hook against the tmp tree."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _build_env(tmp_path: Path, pkgs: list[FakePkg]) -> dict[str, str]:
    """Build HOME + CHEZMOI_SOURCE_DIR + PATH-stubbed-mise env. Returns os.environ-style dict."""
    home = tmp_path / "home"
    home.mkdir()
    src = tmp_path / "chezmoi-src"
    src.mkdir()
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()

    clean = _clean_env()
    # Real git repo at CHEZMOI_SOURCE_DIR so the backup commits in
    # run_after_sync-mise's _commit_backup succeed. `--no-verify` keeps any
    # user-installed pre-commit hook from running against the tmp repo.
    subprocess.run(["git", "init", "-q", "-b", "main", str(src)], check=True, env=clean)
    subprocess.run(
        [
            "git",
            "-C",
            str(src),
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        ],
        check=True,
        env={
            **clean,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )

    # mise stub: no-op for `install --yes`, `upgrade --yes`, `ls`, etc.
    mise_stub = stub_bin / "mise"
    mise_stub.write_text("#!/usr/bin/env bash\nexit 0\n")
    mise_stub.chmod(0o755)

    for p in pkgs:
        _write_fake_pkg(home, p)

    return {
        **clean,
        "HOME": str(home),
        "CHEZMOI_SOURCE_DIR": str(src),
        "CHEZMOI_WORKING_TREE": str(src),
        "PATH": f"{stub_bin}:{clean['PATH']}",
        # Ensure git commits inside the script's _commit_backup work without
        # a real ~/.gitconfig.
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }


def _run_script(
    env: dict[str, str], timeout: float = 30.0
) -> subprocess.CompletedProcess[str]:
    # cwd=CHEZMOI_SOURCE_DIR: the bash script starts inside the temp git repo
    # so any bare `git` call without GIT_DIR set auto-discovers the tmp .git,
    # not the real chezmoi repo (see "GIT ISOLATION DESIGN" in the module doc).
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        cwd=env["CHEZMOI_SOURCE_DIR"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _bin_path(home: Path, p: FakePkg) -> Path:
    """Resolve the on-disk bin path for a FakePkg under HOME."""
    pkg_dir = (
        home
        / ".local/share/mise/installs"
        / _sanitize_install_dirname(p.name)
        / p.version
        / "lib/node_modules"
        / p.name
    )
    _, rel = _bin_entries(p.bin)[0]
    return pkg_dir / rel


# ---------------------------------------------------------------------------
# Truth table — one row per behavior the materializer must guarantee.
# ---------------------------------------------------------------------------

CASES: list[tuple[str, list[FakePkg], dict[str, Any]]] = [
    (
        "wrapper-shape-materializes",
        [
            FakePkg(
                name="@anthropic-ai/claude-code",
                postinstall="node install.cjs",
                opt_deps={f"@anthropic-ai/claude-code-{HOST_SUFFIX}": "1.0.0"},
                bin={"claude": "bin/claude.exe"},
                install_cjs=WORKING_INSTALL_CJS,
            )
        ],
        {
            "returncode": 0,
            "bin_materialized": True,
            "stderr_contains": [
                "npm postinstall: @anthropic-ai/claude-code",
                "npm postinstall OK",
            ],
        },
    ),
    (
        "no-postinstall-skipped",
        [
            FakePkg(
                name="markdownlint-cli",
                postinstall=None,
                opt_deps=None,
                bin={"markdownlint": "bin/markdownlint.js"},
                stub_size=4500,  # a real Node-script bin, not a stub
            )
        ],
        {
            "returncode": 0,
            "bin_materialized": False,  # unchanged
            "stderr_not_contains": ["npm postinstall: markdownlint-cli"],
        },
    ),
    (
        "wrong-platform-optDep-skipped",
        [
            FakePkg(
                name="@anthropic-ai/claude-code",
                postinstall="node install.cjs",
                opt_deps={
                    "@anthropic-ai/claude-code-aix-ppc64": "1.0.0"
                },  # not this host
                bin={"claude": "bin/claude.exe"},
                install_cjs=BROKEN_INSTALL_CJS,  # would not materialize even if run
            )
        ],
        {
            "returncode": 0,
            "bin_materialized": False,
            "stderr_not_contains": ["npm postinstall: @anthropic-ai/claude-code"],
        },
    ),
    (
        "already-materialized-skipped",
        [
            FakePkg(
                name="@anthropic-ai/claude-code",
                postinstall="node install.cjs",
                opt_deps={f"@anthropic-ai/claude-code-{HOST_SUFFIX}": "1.0.0"},
                bin={"claude": "bin/claude.exe"},
                stub_size=8192,  # already > 4 KB; H1 should short-circuit
                # If H1 did NOT short-circuit, this would run and exit 1.
                install_cjs="process.exit(1);\n",
            )
        ],
        {
            "returncode": 0,
            "bin_materialized": True,  # was already
            "stderr_not_contains": ["npm postinstall: @anthropic-ai/claude-code"],
        },
    ),
    (
        "verifier-catches-broken-postinstall",
        [
            FakePkg(
                name="@bad-actor/wrapper",
                postinstall="node install.cjs",
                opt_deps={f"@bad-actor/wrapper-{HOST_SUFFIX}": "1.0.0"},
                bin={"bad": "bin/bad"},
                install_cjs=BROKEN_INSTALL_CJS,
            )
        ],
        {
            "returncode_nonzero": True,
            "stderr_contains": ["ERROR", "unmaterialized"],
        },
    ),
    (
        "mixed-pkgs-only-matching-runs",
        [
            FakePkg(
                name="@anthropic-ai/claude-code",
                postinstall="node install.cjs",
                opt_deps={f"@anthropic-ai/claude-code-{HOST_SUFFIX}": "1.0.0"},
                bin={"claude": "bin/claude.exe"},
                install_cjs=WORKING_INSTALL_CJS,
            ),
            FakePkg(
                name="markdownlint-cli",
                bin={"markdownlint": "bin/markdownlint.js"},
                stub_size=4500,
            ),
        ],
        {
            "returncode": 0,
            "per_pkg_materialized": {0: True, 1: False},
            "stderr_contains": ["npm postinstall: @anthropic-ai/claude-code"],
            "stderr_not_contains": ["npm postinstall: markdownlint-cli"],
        },
    ),
]


@pytest.mark.parametrize(("desc", "pkgs", "expect"), CASES, ids=[c[0] for c in CASES])
def test_materializer(
    tmp_path: Path,
    desc: str,
    pkgs: list[FakePkg],
    expect: dict[str, Any],
) -> None:
    env = _build_env(tmp_path, pkgs)
    result = _run_script(env)
    home = Path(env["HOME"])

    # Exit code.
    if expect.get("returncode_nonzero"):
        assert result.returncode != 0, (
            f"expected nonzero exit; stderr was:\n{result.stderr}"
        )
    elif "returncode" in expect:
        assert result.returncode == expect["returncode"], (
            f"expected exit {expect['returncode']}, got {result.returncode}\n"
            f"stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
        )

    # stderr substring assertions.
    for needle in expect.get("stderr_contains", []):
        assert needle in result.stderr, (
            f"expected substring {needle!r} in stderr:\n{result.stderr}"
        )
    for needle in expect.get("stderr_not_contains", []):
        assert needle not in result.stderr, (
            f"unexpected substring {needle!r} in stderr:\n{result.stderr}"
        )

    # Filesystem assertions.
    if "bin_materialized" in expect:
        bp = _bin_path(home, pkgs[0])
        if expect["bin_materialized"]:
            assert bp.exists(), f"bin missing: {bp}"
            assert bp.stat().st_size >= 4096, (
                f"bin not materialized: {bp.stat().st_size}B"
            )
            assert os.access(bp, os.X_OK), f"bin not executable: {bp}"
        else:
            # Either the stub remains at its original size or doesn't exist.
            if bp.exists():
                assert bp.stat().st_size == pkgs[0].stub_size, (
                    f"bin unexpectedly modified: expected {pkgs[0].stub_size}B, "
                    f"got {bp.stat().st_size}B"
                )

    if "per_pkg_materialized" in expect:
        for idx, should_be_materialized in expect["per_pkg_materialized"].items():
            bp = _bin_path(home, pkgs[idx])
            if should_be_materialized:
                assert bp.stat().st_size >= 4096
                assert os.access(bp, os.X_OK)
            else:
                assert bp.stat().st_size == pkgs[idx].stub_size
