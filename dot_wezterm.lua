local wezterm = require "wezterm"
local config = wezterm.config_builder and wezterm.config_builder() or {}

local isDarwin = wezterm.target_triple:find "[-]apple[-]darwin" -- https://doc.rust-lang.org/nightly/rustc/platform-support/apple-darwin.html
local isLinux = wezterm.target_triple:find "[-]linux[-]" -- https://doc.rust-lang.org/nightly/rustc/platform-support/aarch64-unknown-linux-gnu.html
local isWindows = wezterm.target_triple:find "[-]pc[-]windows[-]" -- https://doc.rust-lang.org/nightly/rustc/platform-support/x86_64-pc-cygwin.html
local isUnixLike = isDarwin or isLinux

local modifierKey = "CTRL"

local function fileExists(path)
  local f = io.open(path, "r")
  if f then
    f:close()
    return true
  end
  return false
end

local function firstExisting(paths)
  for _, path in ipairs(paths) do
    if fileExists(path) then
      return path
    end
  end
  return nil
end

local function hasAnyFonts(dir)
  if not dir then
    return false
  end

  local patterns = {
    dir .. "/*.ttf",
    dir .. "/*.otf",
    dir .. "/*.ttc",
  }

  for _, pattern in ipairs(patterns) do
    if #wezterm.glob(pattern) > 0 then
      return true
    end
  end

  return false
end

if isUnixLike then
  local usrBin = "/usr/bin"
  local usrLocalBin = "/usr/local/bin"
  local homebrewBin = "/opt/homebrew/bin"

  local myPaths = {
    usrLocalBin,
    usrBin,
    os.getenv "PATH",
  }

  if isDarwin then
    modifierKey = "CMD"

    table.insert(myPaths, 1, homebrewBin)
    local tmux = homebrewBin .. "/tmux"
    local xonsh = homebrewBin .. "/xonsh"
    config.default_prog = fileExists(tmux) and { tmux, "new-session", "-A", "-s", "main" }
      or { xonsh }
    -- https://wezterm.org/faq.html#im-on-macos-and-wezterm-cannot-find-things-in-my-path
    config.set_environment_variables = {
      PATH = table.concat(myPaths, ":"),
      SHELL = xonsh,
    }
  else -- Linux
    modifierKey = "SUPER"

    local tmux = firstExisting { "/usr/local/bin/tmux", "/usr/bin/tmux" }
    local xonsh = firstExisting { "/usr/local/bin/xonsh", wezterm.home_dir .. "/.local/bin/xonsh" }
      or "xonsh"
    config.default_prog = tmux and { tmux, "new-session", "-A", "-s", "main" } or { xonsh }
    -- https://wezterm.org/faq.html#im-on-macos-and-wezterm-cannot-find-things-in-my-path
    config.set_environment_variables = {
      PATH = table.concat(myPaths, ":"),
      SHELL = xonsh,
    }
  end
elseif isWindows then
  modifierKey = "SUPER"

  local gitBin = "C:/Program Files/Git/bin"
  local xonshBin = wezterm.home_dir .. "/.local/xonsh-env/xbin"

  -- Prefer WSL2 (full Linux) when a distribution is installed; fall back to Git Bash.
  -- wsl.exe --list exits non-zero when no distributions are installed.
  local wslOk, _, _ = wezterm.run_child_process { "wsl.exe", "--list", "--quiet" }
  if wslOk then
    config.default_prog = {
      "wsl.exe",
      "--cd",
      "~",
      "--",
      "bash",
      "-c",
      "command -v tmux > /dev/null 2>&1 && exec tmux new-session -A -s main || exec bash",
    }
  else
    -- bash -i sources ~/.bashrc (mise shims); exec replaces bash (no lingering shell)
    config.default_prog = {
      gitBin .. "/bash.exe",
      "-i",
      "-c",
      -- cd normalizes CWD to POSIX $HOME before tmux inherits it
      "cd && command -v tmux > /dev/null 2>&1 && exec tmux new-session -A -s main || exec bash",
    }
  end

  config.set_environment_variables = {
    PATH = table.concat({
      xonshBin,
      gitBin,
      os.getenv "PATH",
    }, ";"),
    SHELL = gitBin .. "/bash.exe",
  }

  config.launch_menu = {
    {
      label = "WSL2 (Ubuntu)",
      args = { "wsl.exe", "--cd", "~" },
    },
    {
      label = "Git Bash",
      args = { gitBin .. "/bash.exe" },
    },
    {
      label = "Xonsh",
      args = { xonshBin .. "/xbin-xonsh" },
    },
    {
      label = "Powershell",
      args = { "powershell.exe", "-NoLogo" },
    },
    {
      label = "Wezterm (Admin)",
      args = { "powershell.exe", "-NoLogo", "-Command", '"Start-Process Wezterm -Verb RunAs"' },
    },
  }
end

-- https://wezterm.org/config/lua/config/default_prog.html
-- config.default_prog = { '/opt/homebrew/bin/xonsh', '--no-rc' }

-- https://wezterm.org/config/lua/config/term.html
config.term = "wezterm"
-- config.term = "xterm-256color"

config.enable_tab_bar = true
-- config.color_scheme = 'Batman'

-- https://wezfurlong.org/wezterm/config/fonts.html
-- Keep Windows on a conservative stack to avoid dwrote panics from
-- unavailable/invalid family+variant combinations.
if isWindows then
  local localAppData = os.getenv "LOCALAPPDATA"
  local iosevkaDir = localAppData
    and (localAppData:gsub("\\", "/") .. "/Microsoft/Windows/Fonts/Iosevka")

  if hasAnyFonts(iosevkaDir) then
    -- Prefer scanning known Iosevka files directly on Windows.
    -- This avoids DirectWrite resolver issues with broken system registrations.
    config.font_locator = "ConfigDirsOnly"
    config.font_dirs = { iosevkaDir }
    config.font = wezterm.font_with_fallback {
      "Iosevka",
      "Iosevka Fixed",
      "Iosevka Term",
      "Iosevka Slab",
    }
  else
    if iosevkaDir then
      wezterm.log_warn("Iosevka fonts not found in " .. iosevkaDir .. "; falling back to Consolas")
    else
      wezterm.log_warn "LOCALAPPDATA is unset; falling back to Consolas"
    end
    config.font = wezterm.font "Consolas"
  end
else
  -- Test: != {(`'"Illegal10O"'`)}
  config.font = wezterm.font_with_fallback {
    { family = "Iosevka", weight = "Regular", stretch = "Expanded" }, -- https://www.programmingfonts.org/#iosevka
    { family = "Fira Code" }, -- https://www.programmingfonts.org/#firacode
    { family = "Lotion", weight = "Bold" }, -- https://www.programmingfonts.org/#lotion
    "Source Code Pro", -- https://www.programmingfonts.org/#source-code-pro
    "Monofur Nerd Font", -- https://www.programmingfonts.org/#monofur
    "D2Coding", -- https://www.programmingfonts.org/#d2coding
    { family = "Inconsolata", stretch = "Normal" }, -- https://www.programmingfonts.org/#inconsolata
    "Andale Mono",
    { family = "JetBrains Mono" }, -- https://www.programmingfonts.org/#jetbrainsmono
    "Monospace",
  }
end

-- Set window opacity
-- https://blog-v2.ansidev.xyz/posts/2023-05-18-wezterm-cheatsheet#set-window-opacity
config.window_background_opacity = 0.95

config.debug_key_events = false
-- https://www.reddit.com/r/tmux/comments/13rq7wn/wezterm_users_my_config_to_free_up_keybindings/
config.disable_default_key_bindings = false
-- WARN: devs are unable to support global show/hide toggle x-platform
-- https://github.com/kovidgoyal/kitty/issues/45
config.keys = {
  -- Turn off the default CMD-m Hide action, allowing CMD-m to
  -- be potentially recognized and handled by the tab
  {
    key = "m",
    mods = modifierKey,
    action = wezterm.action.DisableDefaultAssignment,
  },
  -- Add shortcut to open config really quickly
  -- https://blog-v2.ansidev.xyz/posts/2023-05-18-wezterm-cheatsheet#open-wezterm-config-file-quickly
  {
    key = ",",
    mods = modifierKey,
    action = wezterm.action.SpawnCommandInNewTab {
      cwd = os.getenv "WEZTERM_CONFIG_DIR",
      set_environment_variables = {
        TERM = "screen-256color",
      },
      args = {
        "nvim",
        -- os.getenv "WEZTERM_CONFIG_FILE",
        wezterm.home_dir .. "/.local/share/chezmoi/dot_wezterm.lua",
      },
    },
  },
}

-- Maximized window on startup
-- https://blog-v2.ansidev.xyz/posts/2023-05-18-wezterm-cheatsheet#maximized-window-on-start-up
wezterm.on("gui-startup", function(cmd)
  local tab, pane, window = wezterm.mux.spawn_window(cmd or {})
  window:gui_window():maximize()
end)

return config
