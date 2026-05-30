#!/usr/bin/env -S uv run
"""Stop hook: merges permissions from settings.local.json into settings.json.

WHY this hook exists:
  Claude Code accumulates per-session permission grants in settings.local.json
  (a gitignored file). These permissions are useful to keep across sessions but
  would be lost if settings.local.json is cleared or the machine is reprovisioned.
  This hook migrates them into the tracked settings.json on session stop so they
  persist in version control.

HOW it works:
  1. Read .claude/settings.local.json — exit early if missing or no permissions.allow
  2. Merge its allow list into .claude/settings.json (deduped, sorted)
  3. Remove the permissions key from settings.local.json
  4. Write both files atomically (tmpfile in same directory + os.replace)

WHY atomic writes:
  If the process is killed mid-write (e.g., machine sleep during session stop),
  a half-written JSON file would corrupt settings. Writing to a tmpfile and then
  os.replace() is atomic on POSIX — the file is either fully old or fully new.
"""

import json
import os
import sys
import tempfile
from pathlib import Path


def atomic_json_write(path: Path, data: dict) -> None:
    """Write JSON atomically via tmpfile + os.replace."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def main() -> None:
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()
    local_path = project_dir / ".claude" / "settings.local.json"
    settings_path = project_dir / ".claude" / "settings.json"

    if not local_path.exists():
        return

    try:
        local = json.loads(local_path.read_text())
    except (json.JSONDecodeError, OSError):
        return

    new_perms = local.get("permissions", {}).get("allow", [])
    if not new_perms:
        return

    try:
        settings = json.loads(settings_path.read_text())
    except (json.JSONDecodeError, OSError):
        print(f"ERROR: Could not read {settings_path}", file=sys.stderr)
        return

    existing = settings.get("permissions", {}).get("allow", [])
    merged = sorted(set(existing) | set(new_perms))
    settings.setdefault("permissions", {})["allow"] = merged
    atomic_json_write(settings_path, settings)

    local.pop("permissions", None)
    atomic_json_write(local_path, local)


if __name__ == "__main__":
    main()
