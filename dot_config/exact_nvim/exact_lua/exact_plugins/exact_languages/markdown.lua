return {
  {
    -- install with yarn or npm
    "iamcco/markdown-preview.nvim",
    cmd = { "MarkdownPreviewToggle", "MarkdownPreview", "MarkdownPreviewStop" },
    build = "cd app && yarn install",
    init = function()
      vim.g.mkdp_filetypes = { "markdown" }
    end,
    ft = { "markdown" },
    -- install without yarn or npm
    -- 'iamcco/markdown-preview.nvim',
    -- cmd = { 'MarkdownPreviewToggle', 'MarkdownPreview', 'MarkdownPreviewStop' },
    -- ft = { 'markdown' },
    -- build = function() vim.fn['mkdp#util#install']() end,
  },
  {
    "MeanderingProgrammer/render-markdown.nvim",
    dependencies = { "nvim-treesitter/nvim-treesitter", "echasnovski/mini.nvim" }, -- if you use the mini.nvim suite
    -- dependencies = { 'nvim-treesitter/nvim-treesitter', 'echasnovski/mini.icons' }, -- if you use standalone mini plugins
    -- dependencies = { 'nvim-treesitter/nvim-treesitter', 'nvim-tree/nvim-web-devicons' }, -- if you prefer nvim-web-devicons
    ---@module 'render-markdown'
    ---@type render.md.UserConfig
    opts = {},
    config = function(_, opts)
      require("render-markdown").setup(opts)
      -- wildcharm's bg-blend makes RenderMarkdownCode nearly invisible against text;
      -- link to CursorLine which is always distinct from Normal in every colorscheme.
      -- vim.schedule defers past render-markdown's own ColorScheme autocmd so ours wins.
      local function fix_code_hl()
        vim.api.nvim_set_hl(0, "RenderMarkdownCode", { link = "CursorLine" })
      end
      fix_code_hl()
      vim.api.nvim_create_autocmd("ColorScheme", {
        pattern = "*",
        callback = function()
          vim.schedule(fix_code_hl)
        end,
      })
    end,
  },
}
