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

local fake_wezterm = {
  pid = function()
    record("pid")
    return 100
  end,
  mainWindow = function()
    record("mainWindow")
    if scenario == "nil_main_window" then
      return nil
    end
    return fake_window
  end,
  isFrontmost = function()
    record("isFrontmost")
    return scenario == "frontmost"
  end,
  isHidden = function()
    record("isHidden")
    return scenario == "hidden"
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
        "nil_main_window",
        True,
        (
            'bind("ctrl","space")',
            'get("wezterm")',
            "pid",
            "primaryScreen",
            "screenId",
            "activeSpaceOnScreen",
            "mainWindow",
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
            "mainWindow",
            "id",
            "isFrontmost",
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
            "mainWindow",
            "id",
            "isFrontmost",
            "isHidden",
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
            "mainWindow",
            "id",
            "isFrontmost",
            "isHidden",
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
        "hidden",
        False,
        (
            'bind("ctrl","space")',
            'get("wezterm")',
            "pid",
            "primaryScreen",
            "screenId",
            "activeSpaceOnScreen",
            "mainWindow",
            "id",
            "isFrontmost",
            "isHidden",
            "unhide",
            "moveWindowToSpace(42,2)",
            "activate",
            "raise",
            'moveToUnit("0.0,0.0,1.0,1.0")',
        ),
        "ERROR: Could not move window 42 to primary space 2",
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
        "nil main window opens a new OS window",
        "frontmost app hides",
        "hidden app unhides and focuses",
        "background app moves and activates",
        "hidden move failure reports an error",
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
