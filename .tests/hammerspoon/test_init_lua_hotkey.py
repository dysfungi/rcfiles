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
MANAGED_ROOT = REPO_ROOT / "home"
INIT_LUA = MANAGED_ROOT / "dot_hammerspoon" / "init.lua"
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

local function make_window(window_id)
  return {
    id = function()
      record("id", window_id)
      return window_id
    end,
    raise = function()
      record("raise", window_id)
    end,
    moveToUnit = function(_, unit)
      record("moveToUnit", window_id, unit)
    end,
  }
end

local first_window = make_window(42)
local second_window = make_window(43)
local scenario_config = {
  app_absent = {
    application_present = false,
    pid = 100,
    all_windows = {},
    main_window = nil,
    frontmost = false,
  },
  no_windows = {
    application_present = true,
    pid = 100,
    all_windows = {},
    main_window = nil,
    frontmost = false,
  },
  frontmost = {
    application_present = true,
    pid = 100,
    all_windows = { first_window },
    main_window = first_window,
    frontmost = true,
  },
  frontmost_main_nil_fallback = {
    application_present = true,
    pid = 100,
    all_windows = { first_window },
    main_window = nil,
    frontmost = true,
  },
  frontmost_no_windows = {
    application_present = true,
    pid = 100,
    all_windows = {},
    main_window = nil,
    frontmost = true,
  },
  background = {
    application_present = true,
    pid = 100,
    all_windows = { first_window },
    main_window = first_window,
    frontmost = false,
  },
  background_main_nil_fallback = {
    application_present = true,
    pid = 100,
    all_windows = { first_window },
    main_window = nil,
    frontmost = false,
  },
  move_failure = {
    application_present = true,
    pid = 100,
    all_windows = { first_window },
    main_window = first_window,
    frontmost = false,
  },
  multiple_windows = {
    application_present = true,
    pid = 100,
    all_windows = { first_window, second_window },
    main_window = nil,
    frontmost = false,
  },
}
local state = assert(scenario_config[scenario], "unknown scenario: " .. scenario)

local fake_wezterm = {
  pid = function()
    record("pid")
    return state.pid
  end,
  allWindows = function()
    record("allWindows")
    return state.all_windows
  end,
  mainWindow = function()
    record("mainWindow")
    return state.main_window
  end,
  isFrontmost = function()
    record("isFrontmost")
    return state.frontmost
  end,
  unhide = function()
    record("unhide")
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
      if not state.application_present then
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
      return {}
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
  },
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
            "mainWindow",
            "allWindows",
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
            "mainWindow",
            "isFrontmost",
            "hide",
        ),
        None,
    ),
    (
        "frontmost_main_nil_fallback",
        True,
        (
            'bind("ctrl","space")',
            'get("wezterm")',
            "pid",
            "mainWindow",
            "allWindows",
            "isFrontmost",
            "hide",
        ),
        None,
    ),
    (
        "frontmost_no_windows",
        True,
        (
            'bind("ctrl","space")',
            'get("wezterm")',
            "pid",
            "mainWindow",
            "allWindows",
            'selectMenuItem("New OS Window",true)',
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
            "mainWindow",
            "isFrontmost",
            "primaryScreen",
            "activeSpaceOnScreen",
            "id(42)",
            "unhide",
            "moveWindowToSpace(42,2)",
            "activate",
            "raise(42)",
            'moveToUnit(42,"0.0,0.0,1.0,1.0")',
        ),
        None,
    ),
    (
        "background_main_nil_fallback",
        True,
        (
            'bind("ctrl","space")',
            'get("wezterm")',
            "pid",
            "mainWindow",
            "allWindows",
            "isFrontmost",
            "primaryScreen",
            "activeSpaceOnScreen",
            "id(42)",
            "unhide",
            "moveWindowToSpace(42,2)",
            "activate",
            "raise(42)",
            'moveToUnit(42,"0.0,0.0,1.0,1.0")',
        ),
        None,
    ),
    (
        "move_failure",
        False,
        (
            'bind("ctrl","space")',
            'get("wezterm")',
            "pid",
            "mainWindow",
            "isFrontmost",
            "primaryScreen",
            "activeSpaceOnScreen",
            "id(42)",
            "unhide",
            "moveWindowToSpace(42,2)",
            "activate",
            "raise(42)",
            'moveToUnit(42,"0.0,0.0,1.0,1.0")',
        ),
        "ERROR: Could not move window 42 to primary space 2",
    ),
    (
        "multiple_windows",
        True,
        (
            'bind("ctrl","space")',
            'get("wezterm")',
            "pid",
            "mainWindow",
            "allWindows",
            "isFrontmost",
            "primaryScreen",
            "activeSpaceOnScreen",
            "id(42)",
            "unhide",
            "moveWindowToSpace(42,2)",
            "activate",
            "raise(42)",
            'moveToUnit(42,"0.0,0.0,1.0,1.0")',
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
        "app absent launches WezTerm once",
        "nil main window with no windows opens a new OS window",
        "frontmost app hides",
        "fallback window hides frontmost app",
        "frontmost app with no windows opens a new OS window",
        "background app unhides moves and focuses",
        "background fallback window is resolved once and focused",
        "move failure reports an error and still focuses",
        "fallback selects and focuses the first window",
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
