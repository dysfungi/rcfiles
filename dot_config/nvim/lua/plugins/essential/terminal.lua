-- https://neovim.io/doc/user/terminal.html#_start
noremap('<leader>tx', function(ev)
  vim.cmd 'split term://$SHELL'
  -- vim.cmd 'wincmd h'
  -- vim.cmd 'stopinsert'
end, {
  desc = 'New [T]erminal [X]split',
})
noremap('<leader>tv', function(ev)
  vim.cmd 'vsplit term://$SHELL'
  -- vim.cmd 'wincmd h'
  -- vim.cmd 'stopinsert'
end, {
  desc = 'New [T]erminal [V]split',
})
noremap('<leader>tt', function(ev)
  vim.cmd 'tabedit term://$SHELL'
  -- vim.cmd 'wincmd h'
  -- vim.cmd 'stopinsert'
end, {
  desc = 'New [T]erminal [T]ab',
})

-- https://github.com/rebelot/terminal.nvim#auto-insert-mode
-- https://github.com/neovim/neovim/issues/2815#issuecomment-110571245
vim.api.nvim_create_autocmd({ 'WinEnter', 'BufWinEnter', 'TermOpen' }, {
  callback = function(ev)
    if vim.startswith(vim.api.nvim_buf_get_name(ev.buf), 'term://') then
      vim.cmd 'startinsert'
    end
  end,
})

return {
  'chomosuke/term-edit.nvim',
  event = 'TermOpen',
  version = '1.*',
  opts = {
    prompt_end = '─@> ',
    mapping = {
      n = {
        i = 'l',
        I = 'L',
      },
    },
  },
}
