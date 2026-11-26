-- Author-facing Markdown blocks for compact diagnosis worksheets.
return function(el, target)
  local function has(name)
    for _, value in ipairs(el.classes) do if value == name then return true end end
    return false
  end
  local function quoted(value)
    return '"' .. value:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', '\\n') .. '"'
  end
  local function raw(text) return pandoc.RawBlock(target, text) end
  if has('mini-karte') then
    local title = el.attributes.titel or ''
    local number = el.attributes.nummer or ''
    local height = el.attributes.hoehe or '34mm'
    local amount = tonumber(height:match('^(%d+%.?%d*)mm$'))
    if not amount or amount < 20 or amount > 120 then
      error('Mini-Karte: hoehe muss zwischen 20mm und 120mm liegen.')
    end
    if target ~= 'typst' then return el.content end
    local blocks = {raw('#mini_karte(' .. quoted(number) .. ', ' .. quoted(title) .. ', height: ' .. height .. ')[')}
    for _, block in ipairs(el.content) do table.insert(blocks, block) end
    table.insert(blocks, raw(']'))
    return blocks
  end
  if has('mini-auswertung') then
    local entries = {}
    local function cell_content(cell)
      local div = pandoc.Div(cell.contents):walk({RawInline = function(inline)
        if inline.format == 'html' and inline.text:match('^<br%s*/?>$') then
          return pandoc.LineBreak()
        end
      end})
      return '[' .. pandoc.write(pandoc.Pandoc(div.content), 'typst'):gsub('%s+$', '') .. ']'
    end
    local found = false
    for _, block in ipairs(el.content) do
      if block.t == 'Table' then
        if found then error('Mini-Auswertung: Genau eine Tabelle verwenden.') end
        found = true
        local function add(row)
          if #row.cells ~= 3 then error('Mini-Auswertung: Erwartet drei Spalten: Nummer, Lösung, Heftaufgaben.') end
          for _, cell in ipairs(row.cells) do table.insert(entries, cell_content(cell)) end
        end
        for _, row in ipairs(block.head.rows) do add(row) end
        for _, body in ipairs(block.bodies) do
          for _, row in ipairs(body.head) do add(row) end
          for _, row in ipairs(body.body) do add(row) end
        end
      end
    end
    if not found or #entries < 6 then error('Mini-Auswertung: Tabelle mit Kopf und mindestens einer Lösungszeile nötig.') end
    if target ~= 'typst' then return el.content end
    return {raw('#mini_auswertung(' .. table.concat(entries, ',\n') .. ')')}
  end
end
