#!/usr/bin/env -S uv run --no-project
"""Stop hook: per-turn reset for the ExitPlanMode self-review gate.

WHY this hook exists:
  `exit_plan_review_gate.py` blocks `ExitPlanMode` and drops a per-session
  sentinel (`~/.claude/exit-plan-review-fired.<sid>`) so the immediate
  within-turn re-call (after the agent runs its `my-code-review` self-review)
  passes through instead of blocking a second time. That sentinel is a
  within-turn de-duplicator, NOT a session latch: if it survived past the turn,
  every subsequent plan in the same session would skip the gate.

  This companion hook runs at `Stop` (turn boundary) and deletes THIS session's
  sentinel, so the next turn's first `ExitPlanMode` re-gates afresh. The gate +
  reset pair together produce the intended per-turn cadence.

DESIGN — session-scoped, not glob:
  The sentinel filename is keyed on the session id, resolved here EXACTLY as the
  gate hook resolves it (payload `session_id`, else `CLAUDE_CODE_SESSION_ID`,
  else the shared `_NO_SESSION` fallback). Resolving identically guarantees the
  computed path matches the one the gate created, so only the current session's
  sentinel is removed — safe for concurrent multi-instance sessions. A glob
  would clobber sibling sessions' flags mid-turn and is deliberately avoided.

DESIGN — quiet and total:
  Housekeeping runs unconditionally and never fails the Stop chain: empty/invalid
  stdin is tolerated (nothing to key on → nothing to clean), a missing sentinel
  is a no-op (`missing_ok=True`), and the hook always exits 0. No stdout/stderr;
  hooks stay quiet.
"""

import json
import os
import sys
from pathlib import Path

# Must match exit_plan_review_gate.py verbatim so the computed sentinel path is
# identical; drift here silently orphans no-session sentinels.
_NO_SESSION = "no-session"


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        # Empty/invalid stdin: no session to key on, nothing to clean up.
        sys.exit(0)

    # Valid-but-non-object JSON (e.g. `[]`, `"foo"`) has no `.get`; nothing to
    # key on, so treat it like empty stdin rather than raising AttributeError.
    if not isinstance(payload, dict):
        sys.exit(0)

    sid = payload.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    home = Path(os.path.expanduser("~"))
    sentinel = home / ".claude" / f"exit-plan-review-fired.{sid or _NO_SESSION}"
    sentinel.unlink(missing_ok=True)

    sys.exit(0)


if __name__ == "__main__":
    main()
