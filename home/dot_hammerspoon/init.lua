-- http://www.hammerspoon.org/docs/index.html

-- wezterm configuration
-- https://github.com/kovidgoyal/kitty/issues/45#issuecomment-1097554906
hs.hotkey.bind({ "ctrl" }, "space", function()
  print()
  print "Handling hotkey to show/hide Wezterm"
  local wezterm = hs.application.get "wezterm"

  if not wezterm then
    print "Opening Wezterm because it is not running"
    hs.application.launchOrFocus "wezterm"
    return
  end

  print("Wezterm application PID =", wezterm:pid())

  -- mainWindow() is unreliable for a backgrounded app: it often returns nil even
  -- when real windows exist, because macOS doesn't mark a "main" window for a
  -- non-frontmost app. allWindows() stays reliable, so fall back to its first
  -- window instead of activating and re-reading mainWindow(), which races
  -- AppKit's asynchronous activation and can resolve to nil.
  local weztermWindow = wezterm:mainWindow() or (wezterm:allWindows() or {})[1]

  if not weztermWindow then
    print "Opening new Wezterm window because there are none"
    wezterm:selectMenuItem("New OS Window", true)
    return
  end

  if wezterm:isFrontmost() then
    print "Hiding Wezterm because it is already frontmost"
    wezterm:hide()
    return
  end

  local primaryScreen = hs.screen.primaryScreen()
  local primaryActiveSpaceId = hs.spaces.activeSpaceOnScreen(primaryScreen)
  local weztermWindowId = weztermWindow:id()

  print("Showing Wezterm window " .. weztermWindowId .. " on space " .. primaryActiveSpaceId)
  -- unhide() is a safe no-op when the app isn't hidden, so always call it and
  -- skip the fragile isHidden() branch that read stale AppKit state.
  wezterm:unhide()
  if not hs.spaces.moveWindowToSpace(weztermWindowId, primaryActiveSpaceId) then
    print(
      "ERROR: Could not move window "
        .. weztermWindowId
        .. " to primary space "
        .. primaryActiveSpaceId
    )
  end
  wezterm:activate()
  weztermWindow:raise()
  weztermWindow:moveToUnit "0.0,0.0,1.0,1.0"
end)
