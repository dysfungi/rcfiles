local wk = require 'which-key'
local telescope = require 'telescope'

vim.cmd [[
  let $ONLY_SCRIPTS = 'no-script'
]]

return {
  'xvzc/chezmoi.nvim',
  dependencies = { 'nvim-lua/plenary.nvim' },
  opts = {
    -- https://github.com/xvzc/chezmoi.nvim#configuration
    edit = {
      watch = true,
      force = false,
    },
    events = {
      on_open = {
        notification = {
          enabled = true,
          opts = {},
        },
      },
      on_apply = {
        notification = {
          enabled = true,
          opts = {},
        },
      },
      on_watch = {
        notification = {
          enabled = true,
          opts = {},
        },
      },
    },
    telescope = {
      select = { '<CR>', '<C-v>', '<C-x>', '<C-t>', '<Tab>', '<S-Tab>' },
    },
  },
  init = function()
    -- Treat all files in chezmoi source directory as chezmoi files
    -- The below configuration wll allow you to automatically apply changes on files under chezmoi source path.
    -- e.g. ~/.local/share/chezmoi/*
    vim.api.nvim_create_autocmd({ 'BufRead', 'BufNewFile' }, {
      pattern = { os.getenv 'HOME' .. '/.local/share/chezmoi/*' },
      callback = function(ev)
        local bufnr = ev.buf
        local edit_watch = function()
          require('chezmoi.commands.__edit').watch(bufnr)
        end
        vim.schedule(edit_watch)
      end,
    })

    -- telscope-config.lua
    telescope.load_extension 'chezmoi'
    vim.keymap.set('n', '<leader>sc', function()
      telescope.extensions.chezmoi.find_files {
        -- You can also search a specific target directory and override arguments
        -- Here is an example with the default args
        -- targets = vim.fn.stdpath 'config',
        args = {
          '--path-style',
          'absolute',
          '--include',
          'files,scripts,symlinks',
          '--exclude',
          'externals',
        },
      }
    end, {
      desc = '[S]earch [C]hezmoi Files',
    })
  end,
}
