return {
  'nomnivore/ollama.nvim',
  dependencies = {
    'nvim-lua/plenary.nvim',
  },

  -- All the user commands added by the plugin
  cmd = { 'Ollama', 'OllamaModel', 'OllamaServe', 'OllamaServeStop' },

  keys = {
    -- Sample keybind for prompt menu. Note that the <c-u> is important for selections to work properly.
    {
      '<leader>oo',
      ":<c-u>lua require('ollama').prompt()<cr>",
      desc = 'ollama prompt',
      mode = { 'n', 'v' },
    },

    -- Sample keybind for direct prompting. Note that the <c-u> is important for selections to work properly.
    {
      '<leader>oG',
      ":<c-u>lua require('ollama').prompt('Generate_Code')<cr>",
      desc = 'ollama Generate Code',
      mode = { 'n', 'v' },
    },
  },

  opts = {
    -- https://apxml.com/posts/best-local-llm-apple-silicon-mac
    --
    -- Macs with 16GM - 18GB RAM:
    --
    --   [2025-07-04]
    --   M1 Pro (16GB)
    --   -------------
    --   llama3:8b, deepseek-coder-v2:16b-lite, wizardlm2:7b, gemma:7b, qwen:14b
    --
    -- model = 'llama3:8b',
    -- model = 'deepseek-coder-v2:16b',
    model = 'gemma3n',
    url = 'http://127.0.0.1:11434',
    -- url = 'https://ollama.frank.sh',
    serve = {
      on_start = false,
      command = 'ollama',
      args = { 'serve' },
      stop_command = 'pkill',
      stop_args = { '-SIGTERM', 'ollama' },
    },
    -- View the actual default prompts in ./lua/ollama/prompts.lua
    prompts = {
      -- https://github.com/nomnivore/ollama.nvim?tab=readme-ov-file#writing-your-own-prompts
      Tell_Me_A_Joke = {
        prompt = 'Tell me a joke!',
        -- model = 'mistral',
        action = 'display',
      },
    },
  },
}
