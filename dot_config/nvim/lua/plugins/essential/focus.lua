return {
  'nvim-focus/focus.nvim',
  version = '*',
  opts = {
    -- https://github.com/nvim-focus/focus.nvim#configuration
    enable = true,
    commands = true,
    autoresize = {
      enable = true,
    },
    split = {
      bufnew = false,
      tmux = false,
    },
  },
}
