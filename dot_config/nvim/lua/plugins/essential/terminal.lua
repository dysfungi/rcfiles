vim.api.nvim_create_autocmd('VimEnter', {
  desc = 'Auto-open a terminal',
  pattern = '*',
  command = 'split term://xonsh',
  nested = true,
})

return {
  'chomosuke/term-edit.nvim',
  event = 'TermOpen',
  version = '1.*',
  opts = {
    prompt_end = ' @ ',
    mapping = {
      n = {
        i = 'l',
        I = 'L',
      },
    },
  },
}
