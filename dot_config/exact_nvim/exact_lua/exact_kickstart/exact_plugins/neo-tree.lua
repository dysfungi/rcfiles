-- Neo-tree is a Neovim plugin to browse the file system
-- https://github.com/nvim-neo-tree/neo-tree.nvim

return {
  "nvim-neo-tree/neo-tree.nvim",
  version = "*",
  dependencies = {
    "nvim-lua/plenary.nvim",
    "nvim-tree/nvim-web-devicons", -- not strictly required, but recommended
    "MunifTanjim/nui.nvim",
  },
  cmd = "Neotree",
  keys = {
    { "\\", ":Neotree reveal<CR>", desc = "NeoTree reveal", silent = true },
  },
  opts = {
    window = {
      mappings = {
        -- Colemak navigation: e=up, n=down, i=open, h=close
        -- normal! bypasses global Colemak remaps (e→k, n→j, etc.)
        ["e"] = function()
          vim.cmd "normal! k"
        end,
        ["n"] = function()
          vim.cmd "normal! j"
        end,
        ["i"] = "open",
        -- Noop displaced QWERTY keys so global remaps (j→e, k→n) don't fire
        ["j"] = "noop",
        ["k"] = "noop",
        -- Relocate displaced neo-tree actions
        ["ge"] = "toggle_auto_expand_width",
        ["gi"] = "show_file_details",
      },
    },
    filesystem = {
      window = {
        mappings = {
          ["\\"] = "close_window",
        },
      },
    },
  },
}
