-- Turns fenced divs into styled boxes in the Typst output:
--
--   ::: dotnet          ::: note          ::: warning          ::: try
--   In .NET you'd...    Worth knowing.    A trap to avoid.     A small exercise.
--   :::                 :::               :::                  :::
--
-- The box itself is drawn by `callout` in template.typ.
local kinds = { dotnet = true, note = true, warning = true, try = true }

function Div(el)
  local kind = el.classes[1]
  if not kinds[kind] then
    return nil
  end
  local blocks = { pandoc.RawBlock('typst', '#callout("' .. kind .. '")[') }
  for _, block in ipairs(el.content) do
    table.insert(blocks, block)
  end
  table.insert(blocks, pandoc.RawBlock('typst', ']'))
  return blocks
end
