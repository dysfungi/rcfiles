return {
  "coder/claudecode.nvim",
  config = true,
  keys = {
    { "<leader>a", nil, desc = "Claude Code" },
    { "<leader>ac", "<cmd>ClaudeCode<cr>", desc = "Toggle" },
    { "<leader>af", "<cmd>ClaudeCodeFocus<cr>", desc = "Focus" },
    { "<leader>ar", "<cmd>ClaudeCode --resume<cr>", desc = "Resume" },
    { "<leader>aC", "<cmd>ClaudeCode --continue<cr>", desc = "Continue" },
    { "<leader>am", "<cmd>ClaudeCodeSelectModel<cr>", desc = "Select model" },
    { "<leader>ab", "<cmd>ClaudeCodeAdd %<cr>", desc = "Add buffer" },
    { "<leader>as", "<cmd>ClaudeCodeSend<cr>", mode = "v", desc = "Send selection" },
    { "<leader>aa", "<cmd>ClaudeCodeDiffAccept<cr>", desc = "Accept diff" },
    { "<leader>ad", "<cmd>ClaudeCodeDiffDeny<cr>", desc = "Deny diff" },
  },
}
