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

    Frontmatter is parsed with real PyYAML (`yaml.safe_load`), NOT a hand-rolled
    stdlib reader. An earlier version of this test used a tiny tolerant parser
    and gave false confidence: it happily read frontmatter that a real YAML
    loader rejects. 13 of the deployed skills had an unquoted plain-scalar
    `description` containing `": "` (colon-space, e.g. `Keywords: ...`), which is
    invalid in a YAML plain scalar — the real loader raised a ScannerError and
    the harness silently fell back to the H1 title. Parsing with the same loader
    the agent harness uses means any unparseable frontmatter fails here loudly.
    PyYAML is supplied to both test runners via `uv run --with pyyaml` (the mise
    `test` task and the pre-commit pytest hooks).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

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


def _parse_frontmatter(rendered: str) -> dict[str, Any]:
    """Extract and `yaml.safe_load` the leading `---`-delimited YAML frontmatter.

    Parses with the real YAML loader, so any frontmatter the agent harness
    cannot parse (e.g. an unquoted plain scalar containing `": "`) raises here
    instead of being silently tolerated — this is the regression guard. Raises
    ValueError if the `---` fences are missing, and lets `yaml.YAMLError`
    propagate so an invalid-YAML render fails the test loudly. A non-mapping
    frontmatter body is also rejected.
    """
    lines = rendered.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing opening frontmatter fence")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration as exc:
        raise ValueError("missing closing frontmatter fence") from exc

    block = "\n".join(lines[1:end])
    data = yaml.safe_load(block)
    if not isinstance(data, dict):
        raise ValueError(f"frontmatter is not a mapping: {type(data).__name__}")
    return data


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
