return {
  'folke/noice.nvim',
  event = 'VeryLazy',
  opts = {
    routes = {
      -- {
      --   filter = {
      --     event = "notify",
      --     find = "Could not find source",
      --   },
      --   opts = { skip = true },
      -- },
      { -- https://github.com/LazyVim/LazyVim/issues/3465#issuecomment-2365137155
        filter = {
          event = 'notify',
          find = 'Request textDocument/documentHighlight failed',
        },
        opts = { skip = true },
      },
    },
  },
}
