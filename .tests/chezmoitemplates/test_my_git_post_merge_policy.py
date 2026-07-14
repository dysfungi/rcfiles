"""Rendered-policy regression coverage for the shared ``my-git`` post-merge contract.

WHY
    The canonical skill is rendered into four harness-specific wrappers. Integration
    verification and silent best-effort cleanup must remain identical across those
    outputs, while Claude and Pi lifecycle mechanics must stay harness-scoped.

DESIGN
    Render each real wrapper with ``chezmoi execute-template`` rather than inspecting
    source text. This exercises template inclusion, source data, and conditional
    lifecycle sections exactly as managed targets receive them. Assertions focus on
    stable policy markers and ordering rather than snapshotting human-facing prose.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPERS = (
    ("claude", Path("dot_claude/exact_skills/my-git/SKILL.md.tmpl")),
    ("codex", Path("dot_codex/exact_skills/my-git/SKILL.md.tmpl")),
    ("gemini", Path("dot_gemini/exact_extensions/my-git/SKILL.md.tmpl")),
    ("pi", Path("dot_pi/agent/exact_skills/my-git/SKILL.md.tmpl")),
)
CLAUDE_LIFECYCLE_HEADINGS = (
    "### Committing from a worktree when the root thread can't run Bash",
    "### Claude Code create / exit mechanics",
)
PI_LIFECYCLE_HEADINGS = ("### Pi create / exit mechanics",)


def _section(rendered: str, start: str, end: str) -> str:
    start_index = rendered.index(start)
    end_index = rendered.index(end, start_index + len(start))
    return rendered[start_index:end_index]


def _markdown_section(rendered: str, heading: str) -> str:
    start_index = rendered.index(heading)
    end_index = rendered.find("\n### ", start_index + len(heading))
    return (
        rendered[start_index:] if end_index == -1 else rendered[start_index:end_index]
    )


def _render(wrapper: Path) -> subprocess.CompletedProcess[str]:
    """Render one wrapper from this worktree without inherited Git routing."""
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    return subprocess.run(
        [
            "chezmoi",
            "execute-template",
            "--source",
            str(REPO_ROOT),
            "--file",
            str(wrapper),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=environment,
    )


@pytest.mark.parametrize(
    ("harness", "wrapper"),
    WRAPPERS,
    ids=[harness for harness, _ in WRAPPERS],
)
def test_rendered_my_git_post_merge_policy(harness: str, wrapper: Path) -> None:
    """Every wrapper shares the verified-integration contract, not lifecycle details."""
    result = _render(wrapper)
    assert result.returncode == 0, (
        f"render failed for {wrapper}\nstderr:\n{result.stderr}"
    )
    rendered = result.stdout
    merge_workflow = _section(
        rendered,
        "6. **PR-ready/final handoff — before any merge.**",
        "9. **Cleanup — after an approved merge only, and silent only after ",
    )
    github_route = _section(
        merge_workflow,
        "- *Repos I own (",
        "- *Work / shared (owner not mine):*",
    )
    cleanup_step = _section(
        rendered,
        "9. **Cleanup — after an approved merge only, and silent only after ",
        "### Post-merge reporting",
    )
    post_merge_policy = _markdown_section(rendered, "### Post-merge reporting")

    for marker in (
        "`Integration: verified`",
        "`Integration: failed`",
        "`Integration: unverified`",
        "This contract governs only the model-authored final handoff.",
    ):
        assert marker in post_merge_policy, (
            f"{wrapper}: missing policy marker {marker!r}"
        )

    for marker in (
        "`gh pr view <pr> --json state,mergeCommit`",
        "`state=MERGED`",
        "`mergeCommit.oid`",
    ):
        assert marker in post_merge_policy, (
            f"{wrapper}: missing GitHub evidence {marker!r}"
        )

    for marker in (
        "The squash operation and resulting conventional commit succeed",
        "`main` resolves to that commit.",
        "If remote publication was requested, confirm the target remote ref too.",
    ):
        assert marker in post_merge_policy, (
            f"{wrapper}: missing local evidence {marker!r}"
        )

    for marker in (
        "An authoritative provider/organization merge status confirms integration",
        "Without authoritative automated evidence, report `Integration: unverified`",
    ):
        assert marker in post_merge_policy, (
            f"{wrapper}: missing shared-work evidence {marker!r}"
        )

    for condition in (
        "blocks the requested outcome",
        "risks data loss or unmerged work",
        "requires user action",
        "was explicitly requested",
    ):
        assert condition in post_merge_policy, (
            f"{wrapper}: missing escalation condition"
        )

    merge_command = "`gh pr merge --squash`"
    assert "gh pr ready" in merge_workflow
    assert merge_command in github_route
    assert "--delete-branch" not in github_route
    assert merge_workflow.index("gh pr ready") < merge_workflow.index(merge_command)
    assert github_route.index("after I approve in-session") < github_route.index(
        merge_command
    )
    assert github_route.index("`state=MERGED`") < github_route.index(
        "declaring `Integration: verified`"
    )
    assert github_route.index("`mergeCommit.oid`") < github_route.index(
        "declaring `Integration: verified`"
    )

    remote_branch_cleanup = "`git push origin --delete <branch>`"
    assert remote_branch_cleanup in cleanup_step
    assert "best-effort remote cleanup" in cleanup_step
    assert cleanup_step.index(remote_branch_cleanup) < cleanup_step.index(
        "Exit/remove the worktree"
    )
    assert "git branch -D <branch>" not in rendered
    assert cleanup_step.index("Exit/remove the worktree") < cleanup_step.index(
        "optional local branch"
    )

    for heading in CLAUDE_LIFECYCLE_HEADINGS:
        assert (heading in rendered) == (harness == "claude"), (
            f"{wrapper}: Claude lifecycle heading leaked or is missing: {heading!r}"
        )
    for heading in PI_LIFECYCLE_HEADINGS:
        assert (heading in rendered) == (harness == "pi"), (
            f"{wrapper}: Pi lifecycle heading leaked or is missing: {heading!r}"
        )
