return {
  {
    "Yook-S/unreal.nvim",
    -- Only load if we are in a directory that looks like an Unreal project
    cond = function()
      return vim.fn.glob "*.uproject" ~= ""
    end,
    dependencies = {
      "tpope/vim-dispatch", -- Optional: for running build commands
    },
    opts = {
      -- Configuration options
    },
  },
}
