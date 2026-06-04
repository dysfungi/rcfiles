local telescope = require "telescope"
local wk = require "which-key"

-- Async chezmoi integration: replaces chezmoi.nvim's synchronous watch() and
-- apply() calls, which block the editor for 2.7-6s (chezmoi status/apply on
-- this repo exceeds plenary's 5s default timeout).
--
-- Load order: requires for chezmoi.* and plenary.job are deferred into
-- function bodies so they resolve after Lazy loads plugins. Lua caches in
-- package.loaded — repeat calls are a hash lookup, effectively free.
--
-- Queue pattern: single-flight + queue-latest, keyed by source_path (not
-- bufnr — multiple buffers can open the same file on disk).
--   - No active job → start immediately.
--   - Active job running → stash as pending, replacing any prior pending
--     (only the latest save matters, intermediates are coalesced).
--   - On exit → drain pending if present.
--
-- Future considerations:
--   - vim.throttle()/vim.debounce() (neovim/neovim#33179, Mar 2025, not
--     merged as of nvim 0.12.2): when available, evaluate as a built-in for
--     the time-gating aspect.
--   - lazy.util.throttle: provides single-flight + queue-one, but (a)
--     coroutine-based (requires bridging to plenary Job callbacks), (b) no
--     per-key support (single global `pending` flag), (c) no argument passing
--     (our apply needs per-buffer source_path).
--   - Why hand-rolled: completion-driven queuing (wait for process exit, then
--     start next), not time-driven. No existing library fits cleanly.
local _active = {} -- source_path → running Job
local _pending = {} -- source_path → {args, on_done}

local function _build_args(cmd, source_path)
  local config = require("chezmoi").config
  local util = require "chezmoi.util"
  local extra = util.__normalize_args(config.extra_args or {})
  local args = { cmd, "--source-path", source_path }
  vim.list_extend(args, extra)
  return args
end

local function _run(source_path, args, on_done)
  if _active[source_path] then
    _pending[source_path] = { args = args, on_done = on_done }
    return
  end
  local notify = require "chezmoi.notify"
  local job = require("plenary.job"):new {
    command = "chezmoi",
    args = args,
    on_stderr = function(_, data)
      if data and data ~= "" then
        vim.schedule(function()
          notify.warn(data)
        end)
      end
    end,
    -- vim.schedule_wrap: plenary callbacks run in a libuv thread; this
    -- marshals back to the Neovim main loop where API calls are safe.
    on_exit = vim.schedule_wrap(function(_, code)
      _active[source_path] = nil
      on_done(code)
      local next = _pending[source_path]
      if next then
        _pending[source_path] = nil
        _run(source_path, next.args, next.on_done)
      end
    end),
  }
  _active[source_path] = job
  job:start()
end

-- Async replacement for chezmoi.nvim's watch(). Flow:
--   1. chezmoi status (async) — confirms the file is chezmoi-managed.
--   2. On status success → fire on_watch notification + register BufWritePost.
--   3. BufWritePost → chezmoi apply (async) → fire on_apply notification.
local function watch(bufnr)
  bufnr = bufnr or vim.api.nvim_get_current_buf()
  local config = require("chezmoi").config
  local notify = require "chezmoi.notify"
  local util = require "chezmoi.util"
  local source_path = vim.api.nvim_buf_get_name(bufnr)
  local filename = vim.fn.fnamemodify(source_path, ":t")

  if util.str_matches_any_of(filename, config.edit.ignore_patterns) then
    return
  end

  _run(source_path, _build_args("status", source_path), function(status_code)
    if status_code ~= 0 then
      return
    end
    if not vim.api.nvim_buf_is_valid(bufnr) then
      return
    end

    local on_watch_conf = config.events.on_watch
    if on_watch_conf.override and type(on_watch_conf.override) == "function" then
      on_watch_conf.override(bufnr)
    elseif on_watch_conf.notification.enable then
      notify.info(on_watch_conf.notification.msg, on_watch_conf.notification.opts)
    end

    local augroup = vim.api.nvim_create_augroup("chezmoi", { clear = false })
    vim.api.nvim_clear_autocmds { event = { "BufWritePost" }, group = augroup, buffer = bufnr }
    vim.api.nvim_create_autocmd("BufWritePost", {
      group = augroup,
      buffer = bufnr,
      callback = function()
        if not vim.api.nvim_buf_is_valid(bufnr) then
          return
        end
        local apply_args = _build_args("apply", source_path)
        if config.edit.force then
          table.insert(apply_args, "--force")
        end
        _run(source_path, apply_args, function(apply_code)
          if apply_code ~= 0 then
            return
          end
          if not vim.api.nvim_buf_is_valid(bufnr) then
            return
          end
          local on_apply_conf = config.events.on_apply
          if on_apply_conf.override and type(on_apply_conf.override) == "function" then
            on_apply_conf.override(bufnr)
          elseif on_apply_conf.notification.enable then
            notify.info(on_apply_conf.notification.msg, on_apply_conf.notification.opts)
          end
        end)
      end,
    })
  end)
end

return {
  "xvzc/chezmoi.nvim",
  dependencies = { "nvim-lua/plenary.nvim" },
  opts = {
    -- https://github.com/xvzc/chezmoi.nvim#configuration
    edit = {
      watch = true,
      force = false,
    },
    events = {
      on_open = {
        notification = {
          enable = true,
          opts = {},
        },
      },
      on_apply = {
        notification = {
          enable = true,
          opts = {},
        },
      },
      on_watch = {
        notification = {
          enable = true,
          opts = {},
        },
      },
    },
    telescope = {
      select = { "<CR>", "<C-v>", "<C-x>", "<C-t>", "<Tab>", "<S-Tab>" },
    },
  },
  init = function()
    -- Automatically apply chezmoi-managed files on save.
    -- Covers all files under ~/.local/share/chezmoi/*, excluding scripts
    -- (run_*) and dot files (handled natively by chezmoi, not this autocmd).
    local home = vim.env.HOME or vim.env.USERPROFILE or vim.fn.expand "~"
    home = home and home ~= "" and home:gsub("\\", "/") or nil

    if not home or home == "~" then
      vim.schedule(function()
        vim.notify(
          "chezmoi.nvim: unable to resolve home dir (HOME/USERPROFILE); watch autocmd disabled",
          vim.log.levels.WARN
        )
      end)
      return
    end

    vim.api.nvim_create_autocmd({ "BufRead", "BufNewFile" }, {
      pattern = { home .. "/.local/share/chezmoi/*" },
      callback = function(ev)
        local filename = vim.fs.basename(ev.file)
        local dirname = vim.fs.dirname(ev.file)
        if vim.startswith(filename, "run_") then
          -- Skip watch/apply for scripts.
          return
        end
        if vim.startswith(filename, ".") or vim.startswith(dirname, ".") then
          -- Skip watch/apply for dot files.
          return
        end
        -- vim.schedule defers watch() past BufRead so the buffer is fully
        -- registered before we query its name via nvim_buf_get_name.
        vim.schedule(function()
          watch(ev.buf)
        end)
      end,
    })

    if not pcall(telescope.load_extension, "chezmoi") then
      vim.schedule(function()
        vim.notify("chezmoi.nvim: failed to load telescope extension", vim.log.levels.WARN)
      end)
    end

    vim.keymap.set("n", "<leader>sc", function()
      telescope.extensions.chezmoi.find_files {
        args = {
          "--path-style",
          "absolute",
          "--include",
          "files,symlinks",
          "--exclude",
          "externals",
        },
      }
    end, { desc = "[S]earch [C]hezmoi Files" })
  end,
}
