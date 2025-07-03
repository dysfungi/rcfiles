-- https://neovim.io/doc/user/terminal.html#_start
-- vim.api.nvim_create_autocmd('VimEnter', {
--   desc = 'Auto-open a terminal',
--   pattern = '*',
--   -- command = 'vsplit term://xonsh',
--   callback = function(ev)
--     vim.cmd 'vsplit term://xonsh'
--     vim.cmd 'wincmd h'
--     vim.cmd 'stopinsert'
--   end,
--   nested = true,
-- })

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
