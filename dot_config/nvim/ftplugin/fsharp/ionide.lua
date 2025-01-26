require('which-key').add {
  {
    '<leader>T',
    '<CMD>call fsharp#showTooltip()<CR>',
    buffer = true,
    desc = 'Show tooltip over cursor for FSharp files',
    mode = { 'n', 'v', 'o' },
    remap = false,
  },
  {
    '<leader><F1>',
    function()
      -- local f1Help = vim.fn.execute('call fsharp#showF1Help()', 'silent!')
      -- local f1Help = vim.api.nvim_command_output 'call fsharp#showF1Help()'
      -- local f1Help = vim.api.nvim_call_function('fsharp#showF1Help', {})
      -- local f1Help = vim.fn['fsharp#showF1Help']()
      -- local f1Help = vim.api.nvim_eval 'fsharp#showF1Help()'
      local f1Help = vim.api.nvim_exec2('call fsharp#showF1Help()', {
        output = true,
      }).output
      if f1Help == '' then
        return
      end
      -- vim.ui.open(f1Help)
    end,
    buffer = true,
    desc = 'Open help over cursor for FSharp files',
    mode = { 'n', 'v', 'o' },
    remap = false,
  },
}
