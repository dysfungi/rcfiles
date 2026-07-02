"""Tests for the my-git skill's PR reviewer-feedback policy.

WHY THIS FILE EXISTS
    `.chezmoitemplates/agents/skills/my-git.SKILL.md.tmpl` is the shared source
    for the my-git skill, rendered into four tool wrappers (Claude, Codex,
    Gemini, Pi). The reviewer-feedback policy is load-bearing behavior: after a
    PR is marked ready, the agent must reply on each review thread (once
    addressed, or first to discuss) and must NEVER resolve review threads — the
    human resolves each one after verifying. This test pins that policy against
    silent regression in every wrapper render:
      - body: the merge-back flow step containing "Never resolve review
        threads" — the enforcement text agents act on.
      - frontmatter description: the "never resolve review threads" trigger
        keywords — what makes the skill activate on review-comment work at all.

WHY WE RENDER EACH WRAPPER
    Each wrapper is a one-line `includeTemplate` of the shared source, but the
    shared source branches on `$.chezmoi.sourceFile` (`dot_claude/` vs
    `dot_pi/` sections) and interpolates `.my.github_personal_owners` from
    `.chezmoidata/git.yaml`. Rendering every wrapper exactly as chezmoi does
    (`chezmoi execute-template --source <repo> --file <abs path>`) proves the
    policy survives each real include path, not just the shared source text.
    A throwaway empty --config keeps the render hermetic (isolated from the
    user's real chezmoi config); the my-git template chain needs no [data]
    variables, so none are pinned.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

WRAPPERS = [
    pytest.param("dot_claude/exact_skills/my-git/SKILL.md.tmpl", id="claude"),
    pytest.param("dot_codex/exact_skills/my-git/SKILL.md.tmpl", id="codex"),
    pytest.param("dot_gemini/exact_extensions/my-git/SKILL.md.tmpl", id="gemini"),
    pytest.param("dot_pi/agent/exact_skills/my-git/SKILL.md.tmpl", id="pi"),
]

# (scope, exact text that must appear in every render). Scope selects the
# region searched: "body" = the whole render, "frontmatter" = only the YAML
# block between the first two `---` delimiter lines.
POLICY_MARKERS = [
    pytest.param(
        "body",
        "**Never resolve review threads** — the human resolves each thread",
        id="body-never-resolve-policy",
    ),
    pytest.param(
        "frontmatter",
        "never resolve review threads",
        id="description-trigger-keyword",
    ),
]


def _frontmatter(rendered: str) -> str:
    """The YAML frontmatter block between the first two `---` delimiter lines."""
    return rendered.split("---\n", 2)[1]


@pytest.fixture(scope="module")
def render(tmp_path_factory: pytest.TempPathFactory):
    """Return a wrapper-path -> rendered-text function, cached per wrapper.

    cwd and --source are the repo root so .chezmoidata feeds the render, GIT_*
    is stripped because pre-commit leaks GIT_DIR into the subprocess env
    (pointing chezmoi at the wrong tree), and --file takes the absolute source
    path so chezmoi renders the working-tree body rather than its configured
    default source.
    """
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    config = tmp_path_factory.mktemp("chezmoi-config") / "chezmoi.toml"
    config.write_text("")
    cache: dict[str, str] = {}

    def _render(wrapper: str) -> str:
        if wrapper not in cache:
            proc = subprocess.run(
                [
                    "chezmoi",
                    "execute-template",
                    "--config",
                    str(config),
                    "--source",
                    str(REPO_ROOT),
                    "--file",
                    str(REPO_ROOT / wrapper),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                env=clean,
            )
            assert proc.returncode == 0, proc.stderr
            cache[wrapper] = proc.stdout
        return cache[wrapper]

    return _render


@pytest.mark.parametrize(("scope", "marker"), POLICY_MARKERS)
@pytest.mark.parametrize("wrapper", WRAPPERS)
def test_reviewer_feedback_policy_rendered(
    render, wrapper: str, scope: str, marker: str
) -> None:
    """Every wrapper render carries the reviewer-feedback policy and trigger."""
    rendered = render(wrapper)
    haystack = _frontmatter(rendered) if scope == "frontmatter" else rendered
    assert marker in haystack, f"{marker!r} missing from {scope} of rendered {wrapper}"
