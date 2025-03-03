local wk = require 'which-key'
local telescope = require 'telescope'

return {
  'xvzc/chezmoi.nvim',
  dependencies = { 'nvim-lua/plenary.nvim' },
  opts = {
    -- https://github.com/xvzc/chezmoi.nvim?tab=readme-ov-file#configuration
    edit = {
      watch = true,
      force = false,
    },
    notification = {
      on_open = true,
      on_apply = true,
      on_watch = true,
    },
    telescope = {
      select = { '<CR>' },
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
    vim.keymap.set('n', '<leader>sc', telescope.extensions.chezmoi.find_files, {
      desc = '[S]earch [C]hezmoi Files',
    })
    -- You can also search a specific target directory and override arguments
    -- Here is an example with the default args
    -- vim.keymap.set('n', '<leader>scc', function()
    --   telescope.extensions.chezmoi.find_files {
    --     targets = vim.fn.stdpath 'config',
    --     args = {
    --       '--path-style',
    --       'absolute',
    --       '--include',
    --       'files',
    --       '--exclude',
    --       'externals',
    --     },
    --   }
    -- end, {
    --   desc = '[S]earch [C]hezmoi ~/.[C]onfig Files',
    -- })
    -- wk.add { '<leader>sc', group = '[S]earch [C]hezmoi Files' }
  end,
}
