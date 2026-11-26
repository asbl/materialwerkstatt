-- Run after Quarto has merged inherited includes. Only the frozen effective
-- includes (plus the document's own inline additions) may reach the PDF writer.
function Meta(meta)
  local includes = meta["template-frozen-includes"]
  if not includes then return nil end
  local format = FORMAT:match("latex") and "latex" or "typst"
  for target, values in pairs(includes) do
    local blocks = pandoc.List()
    for _, value in ipairs(values) do
      local text = pandoc.utils.stringify(value):gsub("%x%x", function(byte)
        return string.char(tonumber(byte, 16))
      end)
      blocks:insert(pandoc.MetaBlocks({pandoc.RawBlock(format, text)}))
    end
    meta[target] = pandoc.MetaList(blocks)
  end
  meta["template-frozen-includes"] = nil
  return meta
end
