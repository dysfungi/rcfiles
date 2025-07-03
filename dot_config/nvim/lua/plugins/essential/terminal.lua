-- https://neovim.io/doc/user/terminal.html#_start
vim.api.nvim_create_autocmd('VimEnter', {
  desc = 'Auto-open a terminal',
  pattern = '*',
  -- command = 'vsplit term://xonsh',
  callback = function(ev)
    vim.cmd 'vsplit term://xonsh'
    vim.cmd 'wincmd h'
    vim.cmd 'stopinsert'
  end,
  -- callback = function(ev)
  --   local win_id = vim.api.nvim_open_win(0, false, {
  --     split = 'right',
  --   })
  --   local buf_id = vim.fn.winbufnr(win_id)
  --   vim.api.nvim_win_call(win_id, function()
  --     vim.cmd 'edit! term://xonsh'
  --   end)
  -- end,
  nested = true,
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
    prompt_end = '@> ',
    mapping = {
      n = {
        i = 'l',
        I = 'L',
      },
    },
  },
}
