local no_tmux_session = vim.env.TMUX == nil

return {
  {
    'tamton-aquib/duck.nvim',
    config = function()
      -- 🦆 ඞ 🦀 🐈 🐎 🦖 🐤
      vim.keymap.set('n', '<leader>dd', function()
        require('duck').hatch()
      end, {})
      vim.keymap.set('n', '<leader>dk', function()
        require('duck').cook()
      end, {})
      vim.keymap.set('n', '<leader>da', function()
        require('duck').cook_all()
      end, {})
    end,
  },
  {
    'giusgad/pets.nvim',
    cond = no_tmux_session,
    dependencies = {
      'MunifTanjim/nui.nvim',
      {
        'giusgad/hologram.nvim',
        opts = {
          auto_display = true,
        },
      },
    },
    opts = {
      -- https://github.com/giusgad/pets.nvim#%EF%B8%8F-configuration
      death_animation = true,
      default_pet = 'dog',
      default_style = 'black',
      random = true,
      col = 10,
      row = 9,
      popup = {
        avoid_statusline = false,
      },
    },
  },
}
