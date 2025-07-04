vim.cmd [[
  let $VISUAL = 'nvr -cc vsplit --remote-wait'
  let $EDITOR = 'nvim -e'
  let $GIT_EDITOR = $VISUAL

  augroup _git
    autocmd FileType gitcommit,gitrebase,gitconfig setlocal bufhidden=delete
    autocmd FileType gitcommit setlocal wrap
    autocmd FileType gitcommit setlocal spell
  augroup end
]]

-- autocmd FileType gitcommit,gitrebase,gitconfig set bufhidden=delete
-- vim.api.nvim_create_autocmd('FileType', {
--   desc = 'Make sure to delete terminal buffer after saving commit message.',
--   command = 'setlocal bufhidden=delete',
--   pattern = { 'gitcommit', 'gitconfig', 'gitrebase' },
-- })

return {
  'mhinz/neovim-remote',
}
