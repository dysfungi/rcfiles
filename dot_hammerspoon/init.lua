-- http://www.hammerspoon.org/docs/index.html

-- wezterm configuration
-- https://github.com/kovidgoyal/kitty/issues/45#issuecomment-1097554906
hs.hotkey.bind({ "ctrl" }, "space", function()
  print()
  print "Handling hotkey to show/hide Wezterm"
  local wezterm = hs.application.get "wezterm"

  if wezterm then
    print("Wezterm application PID =", wezterm:pid())
    local primaryScreen = hs.screen.primaryScreen()
    print("Primary screen ID =", primaryScreen:id())
    local primaryActiveSpaceId = hs.spaces.activeSpaceOnScreen(primaryScreen)
    print("Primary active space ID =", primaryActiveSpaceId)
    local weztermWindows = wezterm:allWindows() or {}
    local weztermWindow = wezterm:mainWindow() or weztermWindows[1]
    local weztermWindowId
    if weztermWindow then
      weztermWindowId = weztermWindow:id()
      print("Wezterm window ID =", weztermWindowId)
    end
    -- mainWindow() can be nil even when real (backgrounded, unfocused) windows
    -- exist -- macOS/Accessibility doesn't always flag one as "main" for a
    -- non-frontmost app. Use the actual window count, not mainWindow()'s
    -- nilness, to decide whether Wezterm truly has zero windows, and fall back
    -- to any existing window (weztermWindows[1]) so this state reaches the same
    -- branch as any other visible-but-backgrounded window instead of spuriously
    -- opening a new one.
    if #weztermWindows == 0 then
      print "Opening new Wezterm window because there are none"
      wezterm:selectMenuItem("New OS Window", true)
    elseif wezterm:isFrontmost() then
      print "Hiding Wezterm because it is already frontmost"
      wezterm:hide()
    elseif wezterm:isHidden() then
      print "Unhiding Wezterm and moving to primary space"
      if not wezterm:unhide() then
        print "ERROR: Could not unhide Wezterm"
      end
      if not hs.spaces.moveWindowToSpace(weztermWindowId, primaryActiveSpaceId) then
        print(
          "ERROR: Could not move window "
            .. weztermWindowId
            .. " to primary space "
            .. primaryActiveSpaceId
        )
      end
      print "Activating and focusing on Wezterm"
      wezterm:activate()
      weztermWindow:raise()
      weztermWindow:moveToUnit "0.0,0.0,1.0,1.0"
    else
      -- TODO: https://github.com/Hammerspoon/hammerspoon/issues/3698
      print "Moving unhidden Wezterm to primary space"
      print(
        "Wezterm main window " .. weztermWindowId .. " exists on spaces =",
        hs.spaces.windowSpaces(weztermWindowId)
      )
      if not hs.spaces.moveWindowToSpace(weztermWindowId, primaryActiveSpaceId, true) then
        print(
          "ERROR: Could not move window " .. weztermWindowId .. " to space " .. primaryActiveSpaceId
        )
      end
      -- TODO: https://gist.github.com/jdtsmith/8f08cf22a7177884b437cd25c0fba7d5
      local zoomPoint = hs.geometry(weztermWindow:zoomButtonRect())
      local safePoint = zoomPoint:move({ -1, -1 }).topleft
      -- hs.eventtap.event.newMouseEvent(hs.eventtap.event.types.leftMouseDown, safePoint):post()
      -- hs.timer.waitUntil(
      --     function () return hs.spaces.windowSpaces(weztermWindow)[1]~=initialSpace end,
      -- )
      print("Moved window " .. weztermWindowId .. " to space " .. primaryActiveSpaceId)
      wezterm:activate()
    end
  else
    print "Opening Wezterm because it is not already"
    hs.application.launchOrFocus "wezterm"
    wezterm = hs.application.get "wezterm"
  end
  print "Handled hotkey to show Wezterm"
  print()
end)
