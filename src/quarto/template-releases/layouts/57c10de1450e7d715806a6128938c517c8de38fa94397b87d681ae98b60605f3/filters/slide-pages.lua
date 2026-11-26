-- Folien-Titel und Seitengrenzen wie bei der Excalidraw-Outline behandeln.
function Pandoc(doc)
  if not FORMAT:match("typst") then return nil end
  local first = doc.blocks[1]
  if first and first.t == "Header" and first.level == 1 then
    -- Ein führender Markdown-Titel ist die Titelfolie, kein zusätzlicher Inhalt.
    doc.meta.title = pandoc.MetaInlines(first.content)
    doc.meta.subtitle = nil
    doc.blocks:remove(1)
    local cover = pandoc.List()
    while #doc.blocks > 0 do
      local block = doc.blocks[1]
      if block.t == "Header" and block.level <= 2 then break end
      cover:insert(doc.blocks:remove(1))
    end
    if #cover > 0 then doc.meta["slide-cover-content"] = pandoc.MetaBlocks(cover) end
  end
  doc.meta["slide-cover"] = pandoc.MetaBool(
    doc.meta.title ~= nil and pandoc.utils.stringify(doc.meta.title) ~= "")
  local output = pandoc.List()
  local section = pandoc.List()
  local title = nil
  local function flush()
    if title == nil and #section == 0 then return end
    local heading = title and pandoc.write(pandoc.Pandoc({pandoc.Plain(title)}), "typst"):gsub("%s+$", "") or "Folie"
    output:insert(pandoc.RawBlock("typst", "#slide([" .. heading .. "])["))
    output:extend(section)
    output:insert(pandoc.RawBlock("typst", "]"))
    section = pandoc.List()
  end
  for _, block in ipairs(doc.blocks) do
    if block.t == "Header" and block.level <= 2 then
      flush()
      title = block.content
    else
      section:insert(block)
    end
  end
  flush()
  return pandoc.Pandoc(output, doc.meta)
end
