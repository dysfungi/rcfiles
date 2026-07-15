"""Regression tests for the Hammerspoon WezTerm hotkey.

Hammerspoon injects its ``hs`` API only inside the live macOS application, so
there is no headless Hammerspoon runtime to execute in CI. These tests instead
run the unchanged managed ``init.lua`` through the real Lua interpreter provided
by ``mise run test`` and fake only that unavailable OS boundary. The Lua harness
captures the registered hotkey, invokes it under ``pcall``, and reports its calls
as machine-readable output. This keeps the production callback and Lua semantics
on the execution path while making its state transitions reproducible.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_LUA = REPO_ROOT / "dot_hammerspoon" / "init.lua"
MOVE_FAILURE_LOG = "ERROR: Could not move window"
RECOVERY_FAILURE_ALERT = "Wezterm: couldn't determine which window to show"
WINDOW_TOUCHING_ACTIONS = (
    "hide",
    "unhide",
    "moveWindowToSpace",
    "raise",
    "moveToUnit",
    "selectMenuItem",
)

_HARNESS = r"""
local init_lua = assert(arg[1], "missing init.lua path")
local scenario = assert(arg[2], "missing scenario")
local move_succeeds = assert(arg[3], "missing move result") == "true"
local calls = {}
local hotkey_callback

local function format_argument(argument)
  if type(argument) == "string" then
    return string.format("%q", argument)
  end
  return tostring(argument)
end

local function record(name, ...)
  local arguments = table.pack(...)
  if arguments.n == 0 then
    table.insert(calls, name)
    return
  end

  local formatted_arguments = {}
  for index = 1, arguments.n do
    formatted_arguments[index] = format_argument(arguments[index])
  end
  table.insert(calls, name .. "(" .. table.concat(formatted_arguments, ",") .. ")")
end

local fake_window = {
  id = function()
    record("id")
    return 42
  end,
  raise = function()
    record("raise")
  end,
  moveToUnit = function(_, unit)
    record("moveToUnit", unit)
  end,
  zoomButtonRect = function()
    record("zoomButtonRect")
    return {}
  end,
}

local fake_screen = {
  id = function()
    record("screenId")
    return 1
  end,
}

local state = {
  frontmost = scenario == "frontmost",
  hidden = scenario == "hidden" or scenario == "hidden_move_failure" or scenario == "recovery_hidden_trap",
  main_window = fake_window,
  resolves_main_window_on_activate = scenario == "recovery_frontmost_trap" or scenario == "recovery_hidden_trap",
}

if scenario == "no_windows" or scenario == "recovery_frontmost_trap" or scenario == "recovery_hidden_trap" or scenario == "recovery_failure" then
  state.main_window = nil
end

local fake_wezterm = {
  pid = function()
    record("pid")
    return 100
  end,
  allWindows = function()
    record("allWindows")
    if scenario == "no_windows" then
      return {}
    end
    return { fake_window }
  end,
  mainWindow = function()
    record("mainWindow")
    return state.main_window
  end,
  isFrontmost = function()
    record("isFrontmost")
    return state.frontmost
  end,
  isHidden = function()
    record("isHidden")
    return state.hidden
  end,
  unhide = function()
    record("unhide")
    return true
  end,
  hide = function()
    record("hide")
  end,
  activate = function()
    record("activate")
    state.frontmost = true
    state.hidden = false
    if state.resolves_main_window_on_activate then
      state.main_window = fake_window
    end
  end,
  selectMenuItem = function(_, menu_item, enabled)
    record("selectMenuItem", menu_item, enabled)
  end,
}

hs = {
  hotkey = {
    bind = function(modifiers, key, callback)
      record("bind", table.concat(modifiers, "+"), key)
      hotkey_callback = callback
    end,
  },
  alert = {
    show = function(message)
      record("alertShow", message)
    end,
  },
  application = {
    get = function(application_name)
      record("get", application_name)
      if scenario == "app_absent" then
        return nil
      end
      return fake_wezterm
    end,
    launchOrFocus = function(application_name)
      record("launchOrFocus", application_name)
    end,
  },
  screen = {
    primaryScreen = function()
      record("primaryScreen")
      return fake_screen
    end,
  },
  spaces = {
    activeSpaceOnScreen = function()
      record("activeSpaceOnScreen")
      return 2
    end,
    moveWindowToSpace = function(...)
      record("moveWindowToSpace", ...)
      return move_succeeds
    end,
    windowSpaces = function(window_id)
      record("windowSpaces", window_id)
      return { 9 }
    end,
  },
  geometry = function()
    record("geometry")
    return {
      move = function()
        record("geometryMove")
        return { topleft = { x = 0, y = 0 } }
      end,
    }
  end,
}

dofile(init_lua)
assert(hotkey_callback, "init.lua did not register a hotkey callback")

local ok, err = pcall(hotkey_callback)
print("OK=" .. tostring(ok))
if not ok then
  print("ERROR=" .. tostring(err))
end
print("CALLS=" .. table.concat(calls, "|"))
"""

SCENARIOS: list[tuple[str, bool, tuple[str, ...], str | None]] = [
    (
        "app_absent",
        True,
        (
            'bind("ctrl","space")',
            'get("wezterm")',
            'launchOrFocus("wezterm")',
            'get("wezterm")',
        ),
        None,
    ),
    (
        "no_windows",
        True,
        (
            'bind("ctrl","space")',
            'get("wezterm")',
            "pid",
            "primaryScreen",
            "screenId",
            "activeSpaceOnScreen",
            "allWindows",
            "mainWindow",
            "isFrontmost",
            "isHidden",
            'selectMenuItem("New OS Window",true)',
        ),
        None,
    ),
    (
        "frontmost",
        True,
        (
            'bind("ctrl","space")',
            'get("wezterm")',
            "pid",
            "primaryScreen",
            "screenId",
            "activeSpaceOnScreen",
            "allWindows",
            "mainWindow",
            "isFrontmost",
            "isHidden",
            "id",
            "hide",
        ),
        None,
    ),
    (
        "hidden",
        True,
        (
            'bind("ctrl","space")',
            'get("wezterm")',
            "pid",
            "primaryScreen",
            "screenId",
            "activeSpaceOnScreen",
            "allWindows",
            "mainWindow",
            "isFrontmost",
            "isHidden",
            "id",
            "unhide",
            "moveWindowToSpace(42,2)",
            "activate",
            "raise",
            'moveToUnit("0.0,0.0,1.0,1.0")',
        ),
        None,
    ),
    (
        "background",
        True,
        (
            'bind("ctrl","space")',
            'get("wezterm")',
            "pid",
            "primaryScreen",
            "screenId",
            "activeSpaceOnScreen",
            "allWindows",
            "mainWindow",
            "isFrontmost",
            "isHidden",
            "id",
            "windowSpaces(42)",
            "moveWindowToSpace(42,2,true)",
            "zoomButtonRect",
            "geometry",
            "geometryMove",
            "activate",
        ),
        None,
    ),
    (
        "hidden_move_failure",
        False,
        (
            'bind("ctrl","space")',
            'get("wezterm")',
            "pid",
            "primaryScreen",
            "screenId",
            "activeSpaceOnScreen",
            "allWindows",
            "mainWindow",
            "isFrontmost",
            "isHidden",
            "id",
            "unhide",
            "moveWindowToSpace(42,2)",
            "activate",
            "raise",
            'moveToUnit("0.0,0.0,1.0,1.0")',
        ),
        "ERROR: Could not move window 42 to primary space 2",
    ),
    (
        "recovery_frontmost_trap",
        True,
        (
            'bind("ctrl","space")',
            'get("wezterm")',
            "pid",
            "primaryScreen",
            "screenId",
            "activeSpaceOnScreen",
            "allWindows",
            "mainWindow",
            "isFrontmost",
            "isHidden",
            "activate",
            "mainWindow",
            "id",
            "windowSpaces(42)",
            "moveWindowToSpace(42,2,true)",
            "zoomButtonRect",
            "geometry",
            "geometryMove",
            "activate",
        ),
        None,
    ),
    (
        "recovery_hidden_trap",
        True,
        (
            'bind("ctrl","space")',
            'get("wezterm")',
            "pid",
            "primaryScreen",
            "screenId",
            "activeSpaceOnScreen",
            "allWindows",
            "mainWindow",
            "isFrontmost",
            "isHidden",
            "activate",
            "mainWindow",
            "id",
            "unhide",
            "moveWindowToSpace(42,2)",
            "activate",
            "raise",
            'moveToUnit("0.0,0.0,1.0,1.0")',
        ),
        None,
    ),
    (
        "recovery_failure",
        True,
        (
            'bind("ctrl","space")',
            'get("wezterm")',
            "pid",
            "primaryScreen",
            "screenId",
            "activeSpaceOnScreen",
            "allWindows",
            "mainWindow",
            "isFrontmost",
            "isHidden",
            "activate",
            "mainWindow",
            'alertShow("Wezterm: couldn\'t determine which window to show")',
        ),
        None,
    ),
]


@pytest.fixture(scope="module")
def lua_bin() -> str:
    """Return the Lua interpreter supplied by the active mise environment."""
    lua_bin = shutil.which("lua")
    if lua_bin is None:
        pytest.fail(
            "mise-managed Lua interpreter is not on PATH; run `mise install lua` "
            "before running the test suite."
        )
    assert lua_bin is not None
    return lua_bin


def _output_value(output: str, prefix: str) -> str:
    for line in output.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix)
    raise AssertionError(f"Lua harness did not emit {prefix!r}.\nstdout:\n{output}")


def _contains_call(calls: list[str], name: str) -> bool:
    return any(call == name or call.startswith(f"{name}(") for call in calls)


def _run_hotkey(
    lua_bin: str, scenario: str, move_succeeds: bool
) -> tuple[bool, list[str], str]:
    result = subprocess.run(
        [lua_bin, "-", str(INIT_LUA), scenario, str(move_succeeds).lower()],
        input=_HARNESS,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Lua harness failed for {scenario!r}.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )

    ok = _output_value(result.stdout, "OK=") == "true"
    calls = [call for call in _output_value(result.stdout, "CALLS=").split("|") if call]
    return ok, calls, result.stdout


@pytest.mark.parametrize(
    "scenario,move_succeeds,expected_calls,expected_error",
    SCENARIOS,
    ids=[
        "app absent launches WezTerm",
        "nil main window with no windows opens a new OS window",
        "frontmost app hides",
        "hidden app unhides and focuses",
        "background app moves and activates",
        "hidden move failure reports an error",
        "recovery preserves pre-activation frontmost state",
        "recovery preserves pre-activation hidden state",
        "unresolvable main window alerts without touching a window",
    ],
)
def test_hotkey_handles_wezterm_state(
    scenario: str,
    move_succeeds: bool,
    expected_calls: tuple[str, ...],
    expected_error: str | None,
    lua_bin: str,
) -> None:
    """The hotkey completes each supported WezTerm state transition."""
    ok, calls, output = _run_hotkey(lua_bin, scenario, move_succeeds)

    assert ok, f"{scenario}: hotkey callback failed.\nstdout:\n{output}"
    if scenario == "no_windows":
        assert not _contains_call(calls, "activate"), (
            "no_windows: recovery activation must not run when the app has no windows.\n"
            f"stdout:\n{output}"
        )
    assert calls == list(expected_calls), (
        f"{scenario}: expected calls {expected_calls!r}, got {calls!r}.\n"
        f"stdout:\n{output}"
    )
    if move_succeeds:
        assert MOVE_FAILURE_LOG not in output, (
            f"{scenario}: unexpected move failure.\nstdout:\n{output}"
        )
    if expected_error is not None:
        assert expected_error in output


def test_recovery_uses_captured_frontmost_state(lua_bin: str) -> None:
    """Recovery activation must not turn a background show into a hide."""
    ok, calls, output = _run_hotkey(lua_bin, "recovery_frontmost_trap", True)

    assert ok, f"recovery_frontmost_trap: hotkey callback failed.\nstdout:\n{output}"
    assert not _contains_call(calls, "hide"), (
        f"Unexpected hide call.\nstdout:\n{output}"
    )
    assert _contains_call(calls, "moveWindowToSpace"), (
        f"Missing show action.\nstdout:\n{output}"
    )
    assert calls.count("activate") == 2, (
        f"Expected recovery and show activation.\nstdout:\n{output}"
    )


def test_recovery_uses_captured_hidden_state(lua_bin: str) -> None:
    """Recovery activation must not bypass the original hidden-window branch."""
    ok, calls, output = _run_hotkey(lua_bin, "recovery_hidden_trap", True)

    assert ok, f"recovery_hidden_trap: hotkey callback failed.\nstdout:\n{output}"
    for action in ("unhide", "raise", "moveToUnit"):
        assert _contains_call(calls, action), (
            f"Missing {action} call.\nstdout:\n{output}"
        )
    assert not _contains_call(calls, "windowSpaces"), (
        f"Unexpected background-branch action.\nstdout:\n{output}"
    )


def test_unresolvable_main_window_alerts_without_touching_windows(lua_bin: str) -> None:
    """An unresolved main window must alert rather than guess which window to use."""
    ok, calls, output = _run_hotkey(lua_bin, "recovery_failure", True)

    assert ok, f"recovery_failure: hotkey callback failed.\nstdout:\n{output}"
    assert _contains_call(calls, "alertShow"), f"Missing alert.\nstdout:\n{output}"
    assert f'alertShow("{RECOVERY_FAILURE_ALERT}")' in calls, (
        f"Unexpected alert message.\nstdout:\n{output}"
    )
    for action in WINDOW_TOUCHING_ACTIONS:
        assert not _contains_call(calls, action), (
            f"recovery_failure must not call {action}.\nstdout:\n{output}"
        )
