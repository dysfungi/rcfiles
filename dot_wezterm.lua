local wezterm = require "wezterm"
local config = {}

-- https://wezterm.org/faq.html#im-on-macos-and-wezterm-cannot-find-things-in-my-path
config.set_environment_variables = {
  PATH = "/opt/homebrew/bin:/usr/local/bin:" .. os.getenv "PATH",
}

-- https://wezterm.org/config/lua/config/default_prog.html
-- config.default_prog = { '/opt/homebrew/bin/xonsh', '--no-rc' }

-- https://wezterm.org/config/lua/config/term.html
config.term = "wezterm"
-- config.term = "xterm-256color"

config.enable_tab_bar = true
-- config.color_scheme = 'Batman'

-- https://wezfurlong.org/wezterm/config/fonts.html
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
}

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
    mods = "CMD",
    action = wezterm.action.DisableDefaultAssignment,
  },
  -- Add shortcut to open config really quickly
  -- https://blog-v2.ansidev.xyz/posts/2023-05-18-wezterm-cheatsheet#open-wezterm-config-file-quickly
  {
    key = ",",
    mods = "CMD",
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
