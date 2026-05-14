" Disable Vim regex syntax for terraform: Neovim 0.12 ships syntax/terraform.vim
" which runs alongside treesitter on every redraw, causing scrolling freezes.
" Treesitter provides highlighting; Vim syntax is redundant and expensive here.
setlocal syntax=

" Disable indent-blankline scope for terraform: ibl's scope feature runs treesitter
" queries on every WinScrolled event, freezing Neovim on HCL/terraform buffers.
" Basic indent guides still work (whitespace-based, not treesitter).
lua require("ibl").setup_buffer(vim.api.nvim_get_current_buf(), { scope = { enabled = false } })
