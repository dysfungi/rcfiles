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

return {
  'xvzc/chezmoi.nvim',
  dependencies = { 'nvim-lua/plenary.nvim' },
  opts = {
    -- https://github.com/xvzc/chezmoi.nvim?tab=readme-ov-file#configuration
    edit = {
      watch = false,
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
}
