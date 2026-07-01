#!/usr/bin/env -S uv run --no-project
"""PreToolUse gate that reminds the agent to self-review a plan before presenting it.

WHY this hook exists:
  `my-planning` mandates a fresh-sub-agent `my-code-review` self-review pass
  BEFORE a plan is presented to the user for approval. That rule lived only
  inside the skill body, so it fired only if the model had already chosen to
  invoke `my-planning` — the exact failure mode this backstop addresses: the
  agent reaches `ExitPlanMode` (the call that presents the finished plan) with
  no review having run.

  `ExitPlanMode` is intercepted at `PreToolUse`, which fires BEFORE the approval
  UI is shown. Blocking there injects the reminder at precisely the
  pre-presentation moment, without depending on skill-description matching.

DESIGN — reminder, not verifier (honest limitation):
  This hook deterministically INJECTS the reminder; it does not VERIFY that a
  review actually ran. The sentinel gates the reminder loop, it does not prove
  compliance. The instruction binding in AGENTS.md is what makes the review
  happen; this hook guarantees the agent cannot reach the approval prompt
  without at least being prompted. Transcript inspection to verify a
  `my-code-review` sub-agent ran is deliberately deferred (brittle;
  violates less-is-more).

DESIGN — fire once per turn:
  A sentinel (`~/.claude/exit-plan-review-fired.<sid>`) makes the gate fire once
  per TURN, not once per session. It exists solely to break the within-turn
  block→re-call loop: a PreToolUse exit-2 returns stderr to the model and
  continues the SAME turn, so the re-call after the review sees the sentinel and
  passes through instead of blocking again. The companion
  `clear_plan_review_sentinel` Stop hook removes the sentinel at each turn
  boundary, so the next turn's first `ExitPlanMode` is gated afresh. The flag is
  a within-turn de-duplicator, not a session latch.

DESIGN — exit codes / stderr (matches root_thread_guard.py):
  exit 0 = allow the tool. exit 2 = hard deny; stderr is returned to the model
  as the actionable payload. This is the Claude Code hooks convention shared
  with the root-thread guard. No stdout, and no start/end logging: hooks stay
  quiet and speak only when they block.

DESIGN — no session id fallback:
  When neither the payload `session_id` nor `CLAUDE_CODE_SESSION_ID` is present,
  a stable fallback sentinel name (`exit-plan-review-fired.no-session`) is used
  so the gate still fires once per turn rather than degrading to fire-every-call
  or never-fire. The companion reset hook resolves the same fallback, so the
  no-session sentinel is cleared at the turn boundary too.
"""

import json
import os
import sys
from pathlib import Path

# Returned to the model verbatim on a block. Gives an explicit out for trivial
# work so the gate never becomes a hard wall.
_REMINDER = (
    "Before presenting this plan, run the `my-code-review` self-review pass "
    "(a fresh sub-agent) per `my-planning` and address findings first. If the "
    "change is genuinely trivial, briefly note that and re-call ExitPlanMode. "
    "(This reminder fires once per turn; the immediate re-call passes through.)"
)

# Fallback sentinel suffix when no session id is available (see module docstring).
_NO_SESSION = "no-session"


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        # Tolerate empty/invalid stdin — nothing to gate.
        sys.exit(0)

    # Valid-but-non-object JSON (e.g. `[]`, `"foo"`) has no `.get`; treat it as
    # nothing to gate rather than raising AttributeError or spuriously blocking.
    if not isinstance(payload, dict):
        sys.exit(0)

    # Defense-in-depth beside the settings `ExitPlanMode` matcher.
    if payload.get("tool_name", "") != "ExitPlanMode":
        sys.exit(0)

    sid = payload.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    home = Path(os.path.expanduser("~"))
    sentinel = home / ".claude" / f"exit-plan-review-fired.{sid or _NO_SESSION}"

    # Fire once per turn: already reminded this turn → let the plan through.
    if sentinel.exists():
        sys.exit(0)

    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.touch()

    print(_REMINDER, file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
