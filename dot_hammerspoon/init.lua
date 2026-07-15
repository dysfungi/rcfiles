-- http://www.hammerspoon.org/docs/index.html

-- wezterm configuration
-- https://github.com/kovidgoyal/kitty/issues/45#issuecomment-1097554906
hs.hotkey.bind({ "ctrl" }, "space", function()
  print()
  print "Handling hotkey to show/hide Wezterm"
  local wezterm = hs.application.get "wezterm"

  -- AppKit applies WezTerm activate/hide/unhide requests asynchronously; their
  -- return values and immediately reread state can be stale. Later observable
  -- state, such as the next hotkey press, is authoritative.

  if wezterm then
    print("Wezterm application PID =", wezterm:pid())
    local primaryScreen = hs.screen.primaryScreen()
    print("Primary screen ID =", primaryScreen:id())
    local primaryActiveSpaceId = hs.spaces.activeSpaceOnScreen(primaryScreen)
    print("Primary active space ID =", primaryActiveSpaceId)
    local weztermWindows = wezterm:allWindows() or {}
    local weztermWindow = wezterm:mainWindow()
    local wasFrontmost = wezterm:isFrontmost()
    local wasHidden = wezterm:isHidden()
    if not weztermWindow and #weztermWindows > 0 then
      -- mainWindow() can be nil even when real (backgrounded, unfocused) windows
      -- exist -- macOS/Accessibility doesn't always flag one as "main" for a
      -- non-frontmost app. Let WezTerm/macOS resolve which of its own windows
      -- becomes main by activating it, rather than Hammerspoon guessing an index
      -- into the window list.
      print "Wezterm has windows but no resolvable main window; activating to let it pick one"
      wezterm:activate()
      weztermWindow = wezterm:mainWindow()
    end
    local weztermWindowId
    if weztermWindow then
      weztermWindowId = weztermWindow:id()
      print("Wezterm window ID =", weztermWindowId)
    end
    if #weztermWindows == 0 then
      print "Opening new Wezterm window because there are none"
      wezterm:selectMenuItem("New OS Window", true)
    elseif not weztermWindow then
      -- Windows exist but none could be resolved as main even after activating --
      -- don't guess which one to touch; surface the ambiguous state instead.
      hs.alert.show "Wezterm: couldn't determine which window to show"
      print "ERROR: Wezterm has windows but none resolved as main after activation"
    elseif wasFrontmost then
      print "Hiding Wezterm because it is already frontmost"
      wezterm:hide()
    elseif wasHidden then
      print "Unhiding Wezterm and moving to primary space"
      -- AppKit updates hidden state asynchronously; immediate readback can be
      -- stale, so this request is intentionally fire-and-forget.
      wezterm:unhide()
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
