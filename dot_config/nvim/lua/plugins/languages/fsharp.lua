-- https://ionide.io/Editors/Vim/usage.html#fsautocomplete-settings
-- https://medium.com/@no1.melman10/f-ionide-and-neovim-update-1-d6e316ec087e
vim.g['fsharp#automatic_workspace_init'] = 1
vim.g['fsharp#fsi_keymap'] = 'vim-fsharp'
vim.g['fsharp#lsp_auto_setup'] = 1
vim.g['fsharp#show_signature_on_cursor_move'] = 1
vim.g['fsharp#workspace_mode_peek_deep_level'] = 5

-- Show tooltip on CursorHold.
-- vim.api.nvim_create_autocmd('CursorHold', {
--   command = 'call fsharp#showTooltip()',
--   group = vim.api.nvim_create_augroup('FSharpShowTooltip', {
--     clear = false,
--   }),
--   pattern = { '*.fs', '*.fsi', '*.fsx' },
-- })

-- https://github.com/ionide/Ionide-vim/issues/85#issuecomment-2154200542
return {
  'ionide/Ionide-vim',
  dependencies = {
    'neovim/nvim-lspconfig',
  },
  -- event = 'LazyFile',
  -- ft = 'fsharp',
}
