-- QMD-Inhalte bleiben Markdown; nur das zweispaltige Seitenlayout ist Typst.
local function quote(s)
  return '"' .. s:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\r', ''):gsub('\n', '\\n'):gsub('\t', '\\t') .. '"'
end
local function render(blocks)
  -- Generierte Shortcut-Bilder auch innerhalb der zweispaltigen Karte erhalten.
  local doc = pandoc.Pandoc(blocks):walk({Image = function(img)
    local mime, data = pandoc.mediabag.lookup(img.src)
    if mime == 'image/svg+xml' then
      if img.attributes['checkup-square'] == 'yes' then
        -- Bestehenden Quadrat-Shortcut im Ausschnitt zeigen, ohne seine
        -- Beschriftungen zu verkleinern oder Seitenlabels abzuschneiden.
        data = data:gsub('viewBox="0 0 460 250"', 'viewBox="95 30 240 215"')
          :gsub('width="460" height="250"', 'width="240" height="215"')
      end
      local size = 'width: ' .. (img.attributes.width or '100%')
      if img.attributes.height then size = size .. ', height: ' .. img.attributes.height .. ', fit: "cover"' end
      return pandoc.RawInline('typst', '#image(bytes(' .. quote(data) .. '), format: "svg", ' .. size .. ')')
    end
  end})
  return pandoc.write(doc, 'typst')
end
function Div(d)
  if not FORMAT:match('typst') then return end
  if d.classes:includes('check-sketch') then
    return d:walk({Image = function(img)
      img.attributes.width = '56mm'
      img.attributes.height = nil
      img.attributes['checkup-square'] = 'yes'
      -- Der native Bildpfad bleibt für Lösungsblätter im AST verfügbar;
      -- das ausgeschnittene SVG wird als eigenständige Medienvariante eingefügt.
      local mime, data = pandoc.mediabag.lookup(img.src)
      if mime == 'image/svg+xml' then
        data = data:gsub('viewBox="0 0 460 250"', 'viewBox="95 30 240 215"')
          :gsub('width="460" height="250"', 'width="240" height="215"')
        local name = 'checkup-square-' .. pandoc.utils.sha1(data) .. '.svg'
        pandoc.mediabag.insert(name, mime, data)
        img.src = name
      end
      return img
    end})
  end
  if d.classes:includes('check-figure') then
    local cells = {}
    for _, b in ipairs(d.content) do
      assert(b.t == 'Div', 'Check-up-Inhalte müssen in benannten Inhaltsbereichen stehen.')
      cells[#cells + 1] = render(b.content)
    end
    assert(#cells == 2, 'Skizzen benötigen Bild und Erläuterung.')
    return pandoc.RawBlock('typst', '#checkfigure([\n' .. cells[1] .. '\n], [\n' .. cells[2] .. '\n])')
  end
  if d.classes:includes('check-section') then
    local cells = {}
    for _, b in ipairs(d.content) do
      assert(b.t == 'Div', 'Check-up-Inhalte müssen in benannten Inhaltsbereichen stehen.')
      cells[#cells + 1] = render(b.content)
    end
    assert(#cells == 2, 'Check-up-Bereiche benötigen Regel- und Aufgabenspalte.')
    return pandoc.RawBlock('typst', '#checksection(' .. quote(d.attributes.motif or 'cards') .. ', ' ..
      quote(d.attributes.topic or '') .. ', [\n' .. cells[1] .. '\n], [\n' .. cells[2] .. '\n])')
  end
  if d.classes:includes('checkpage') then
    local parts = {}
    for _, b in ipairs(d.content) do
      assert(b.t == 'RawBlock', 'Check-up-Seiten dürfen nur Check-up-Bereiche enthalten.')
      parts[#parts + 1] = '[' .. b.text .. ']'
    end
    assert(#parts > 0, 'Check-up-Seiten benötigen mindestens einen Check-up-Bereich.')
    return pandoc.RawBlock('typst', '#checkpage(' .. table.concat(parts, ',\n') .. ')')
  end
end
function Span(s)
  if FORMAT:match('typst') and s.classes:includes('zusatz') then
    return pandoc.RawInline('typst', '#text(fill: rgb("#b3261e"))[' .. pandoc.write(pandoc.Pandoc({pandoc.Plain(s.content)}), 'typst'):gsub('%s+$','') .. ']')
  end
end

-- Tabellen dienen hier als Aufgabenraster, ohne Kopfzeilenstil oder Trennlinien.
function Table(tbl)
  if not FORMAT:match('typst') then return end
  local cells = {}
  local function add_rows(rows)
    for _, row in ipairs(rows) do
      for _, cell in ipairs(row.cells) do
        local contents = cell.contents
        -- Reine Formelzellen erhalten die volle Höhe ihrer Brüche.
        if #contents == 1 and (contents[1].t == 'Plain' or contents[1].t == 'Para')
           and #contents[1].content == 1 and contents[1].content[1].t == 'Math' then
          contents = {pandoc.Para({pandoc.Math('DisplayMath', contents[1].content[1].text)})}
        end
        cells[#cells + 1] = '[' .. pandoc.write(pandoc.Pandoc(contents), 'typst') .. ']'
      end
    end
  end
  add_rows(tbl.head.rows)
  for _, body in ipairs(tbl.bodies) do
    add_rows(body.head)
    add_rows(body.body)
  end
  add_rows(tbl.foot.rows)
  local widths = {}
  for _ = 1, #tbl.colspecs do widths[#widths + 1] = '1fr' end
  return pandoc.RawBlock('typst', '#block(above: 4pt, below: 5pt, width: 100%)[#grid(columns: (' ..
    table.concat(widths, ', ') .. '), column-gutter: 8pt, row-gutter: 8pt, align: left + top, ' ..
    table.concat(cells, ',\n') .. ')]')
end
