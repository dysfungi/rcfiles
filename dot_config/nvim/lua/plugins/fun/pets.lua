local no_tmux_session = vim.env.TMUX == nil

return {
  'giusgad/pets.nvim',
  cond = no_tmux_session,
  -- lazy = not no_tmux_session,
  dependencies = {
    'MunifTanjim/nui.nvim',
    {
      'giusgad/hologram.nvim',
      opts = {
        auto_display = true,
      },
    },
  },
  -- https://github.com/giusgad/pets.nvim/issues?tab=readme-ov-file#%EF%B8%8F-configuration
  opts = {
    default_pet = 'dog',
    default_style = 'black',
    random = false,
    popup = {
      avoid_statusline = true,
    },
  },
}
