"""Frontmatter regression test for rendered agent SKILL templates.

WHY
    Every `.chezmoitemplates/agents/skills/*.SKILL.md.tmpl` renders into each AI
    tool's skills dir (Claude, Codex, Pi, …). A skill is only discoverable if its
    YAML frontmatter carries a non-empty `name` and `description`, and the agent
    harnesses key skills by filename — so the frontmatter `name` must match the
    file stem (the basename minus the `.SKILL.md.tmpl` suffixes). A skill whose
    template fails to render, drops a frontmatter field, or whose `name` drifts
    from its filename is silently broken. This test is the executable spec.

DESIGN
    Subprocess-driven, matching the repo harness convention: render each skill
    with the real `chezmoi execute-template --file <f> --source <repo-root>`,
    exactly as the apply pipeline does, rather than reimplementing template
    expansion. Discovery is dynamic (glob) and each skill is its own
    parametrized case (id = file stem) so a failure names the offending skill.

    Frontmatter is parsed with a tiny stdlib reader instead of PyYAML: the mise
    Python has no `yaml` module, and the only fields under test (`name`,
    `description`) are a single inline scalar and a folded scalar — adding a
    dependency to read two keys is not worth it.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / ".chezmoitemplates" / "agents" / "skills"

_SKILL_FILES = sorted(SKILLS_DIR.glob("*.SKILL.md.tmpl"))


def _stem(path: Path) -> str:
    """Skill name the harness expects: basename minus the .SKILL.md.tmpl tail."""
    return path.name.removesuffix(".SKILL.md.tmpl")


def _render(path: Path) -> subprocess.CompletedProcess[str]:
    """Render a skill template via chezmoi, isolated from leaked GIT_* env.

    cwd and --source are the worktree repo root so the worktree's .chezmoidata
    (e.g. git.yaml's github_personal_owners) feeds the render. GIT_* is stripped
    for the same reason as conftest's helpers: pre-commit leaks GIT_DIR into the
    subprocess env. __MISE_*/PATH are preserved so the mise-managed `chezmoi`
    shim still resolves (we never mutate HOME, so mise activation stays intact).
    """
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        [
            "chezmoi",
            "execute-template",
            "--file",
            str(path),
            "--source",
            str(REPO_ROOT),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=clean,
    )


def _parse_frontmatter(rendered: str) -> dict[str, str]:
    """Extract top-level scalar keys from leading `---`-delimited YAML.

    Handles inline scalars (`name: my-git`) and folded scalars whose value
    continues on indented lines (`description:` wrapped across lines). Returns a
    flat key -> whitespace-collapsed string mapping. Raises if no frontmatter
    block is present so a render that loses its `---` fences fails loudly.
    """
    lines = rendered.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing opening frontmatter fence")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration as exc:
        raise ValueError("missing closing frontmatter fence") from exc

    fields: dict[str, str] = {}
    current: str | None = None
    for line in lines[1:end]:
        if line and not line[0].isspace() and ":" in line:
            key, _, value = line.partition(":")
            current = key.strip()
            fields[current] = value.strip()
        elif current is not None and line.strip():
            fields[current] = f"{fields[current]} {line.strip()}".strip()
    return fields


def test_skills_discovered() -> None:
    """Guard: the glob must find skills, else the parametrized suite is a no-op."""
    assert _SKILL_FILES, f"no SKILL templates found under {SKILLS_DIR}"


@pytest.mark.parametrize("skill", _SKILL_FILES, ids=[_stem(p) for p in _SKILL_FILES])
def test_skill_frontmatter(skill: Path) -> None:
    result = _render(skill)
    assert result.returncode == 0, (
        f"render failed for {skill.name}\nstderr:\n{result.stderr}"
    )

    fields = _parse_frontmatter(result.stdout)

    assert fields.get("name"), f"{skill.name}: frontmatter `name` is missing or empty"
    assert fields.get("description"), (
        f"{skill.name}: frontmatter `description` is missing or empty"
    )
    assert fields["name"] == _stem(skill), (
        f"{skill.name}: frontmatter name {fields['name']!r} "
        f"!= filename stem {_stem(skill)!r}"
    )
