local choices = {
  "dog black Dino",
  "cockatiel gray Cock",
  "crab red Crusty",
  "mod purple dotnet-bot",
  "rocky gray Skip",
  "rubber-duck yellow Ducky",
}
math.randomseed(os.time())
local choice = choices[math.random(#choices)]

if package.loaded["pets"] then
  -- vim.cmd.PetsNew 'Dino'
  vim.cmd.PetsNewCustom(choice)
end
