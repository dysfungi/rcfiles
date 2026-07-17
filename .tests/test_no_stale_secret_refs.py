"""Repo sweep: no stale references to the retired secrets plumbing.

The secrets-to-mise migration removed:
  - ~/.secrets/OP_SERVICE_ACCOUNT_TOKEN (token file)
  - load-secrets.sh / load-secrets.ps1 (shell sourcing shims)
  - the xonsh OnePass integration (xontrib-1password)
  - asdf (mise is the sole version manager)

This test is the executable spec that they stay gone: no file in the repo may
reference them outside an explicit allowlist. Enumeration is git-based
(tracked + untracked-not-ignored) rather than an rg walk so gitignored scratch
dirs (.tmp/) are excluded for free and dotfiles/dotdirs are included (rg
skips hidden files by default; --hidden would be needed there).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MANAGED_ROOT = REPO_ROOT / "home"

# (pattern, human-readable description)
_FORBIDDEN = [
    (re.compile(r"\.secrets\b"), "~/.secrets token-file path"),
    (re.compile(r"load-secrets"), "load-secrets.{sh,ps1} sourcing shim"),
    (re.compile(r"OnePass"), "xonsh OnePass integration"),
    (re.compile(r"xontrib-1password"), "xontrib-1password package"),
    (re.compile(r"\basdf\b", re.IGNORECASE), "asdf version manager"),
]

# Deliberate mentions only — everything else must be migration-clean.
_ALLOWED_FILES = {
    # Historical record of completed work (todo.txt archive convention).
    "done.txt",
    # Deferred-work entries may name leftovers (e.g. the xontrib-1password
    # declarative-removal todo).
    "todo.txt",
    # The removal directives themselves: .chezmoiremove names .secrets et al.
    # precisely to delete them from target machines.
    (MANAGED_ROOT.relative_to(REPO_ROOT) / ".chezmoiremove").as_posix(),
    # This file (defines the forbidden patterns).
    ".tests/test_no_stale_secret_refs.py",
    # Asserts the cron runner contains no ".secrets" literal.
    ".tests/local-bin/test_chezmoi_update_cron.py",
    # Generated node IDs include intentional forbidden-pattern test parameter labels.
    ".test_durations",
}

# Audit-trail snapshots legitimately record historical machine state.
_ALLOWED_PREFIXES = (".backups/",)


def _repo_files() -> list[str]:
    """Tracked + untracked-not-ignored files, relative to the repo root."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    files: set[str] = set()
    for args in (
        ["git", "ls-files", "-z"],
        ["git", "ls-files", "-z", "--others", "--exclude-standard"],
    ):
        out = subprocess.run(
            args, cwd=REPO_ROOT, capture_output=True, check=True, env=env
        ).stdout
        files.update(f for f in out.decode().split("\0") if f)
    return sorted(files)


def test_no_stale_secret_references() -> None:
    violations: list[str] = []
    for rel in _repo_files():
        if rel in _ALLOWED_FILES or rel.startswith(_ALLOWED_PREFIXES):
            continue
        path = REPO_ROOT / rel
        if not path.is_file():  # e.g. submodule entries, dangling symlinks
            continue
        text = path.read_bytes().decode(errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern, desc in _FORBIDDEN:
                if pattern.search(line):
                    violations.append(f"{rel}:{lineno}: [{desc}] {line.strip()}")
    assert not violations, (
        "stale secrets-migration references found (fix or extend the "
        "allowlist deliberately):\n" + "\n".join(violations)
    )


def test_allowlist_entries_exist() -> None:
    """Allowlisted files must exist — a stale allowlist silently widens the
    guard's blind spots after renames."""
    missing = [f for f in _ALLOWED_FILES if not (REPO_ROOT / f).exists()]
    assert not missing, f"stale allowlist entries: {missing}"


@pytest.mark.parametrize(
    ("sample", "should_match"),
    [
        ("token in ~/.secrets/OP_SERVICE_ACCOUNT_TOKEN", True),
        ("source load-secrets.sh", True),
        ("import OnePassCLI", True),
        ("pip install xontrib-1password", True),
        ("asdf install python", True),
        ("mise is great", False),
        ("exact_private_dot_secrets/", False),  # no literal dot before 'secrets'
        ("private_secrets.toml.tmpl", False),
        ("onepasswordRead is the sanctioned mechanism", False),
    ],
    ids=[
        "dot-secrets-path",
        "load-secrets",
        "OnePass",
        "xontrib-1password",
        "asdf",
        "clean-line",
        "chezmoi-source-name",
        "mise-secrets-fragment",
        "onepasswordRead-allowed",
    ],
)
def test_forbidden_patterns_shape(sample: str, should_match: bool) -> None:
    """Pin the patterns themselves: they catch the retired plumbing but not
    the sanctioned onepasswordRead/private_secrets.toml surfaces."""
    matched = any(p.search(sample) for p, _ in _FORBIDDEN)
    assert matched is should_match
