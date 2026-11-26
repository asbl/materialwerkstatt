-- QMD-Inhalte bleiben Markdown; nur das zweispaltige Seitenlayout ist Typst.
function Div(d)
  if not FORMAT:match('typst') then return end
  if d.classes:includes('check-sketch') then
    -- Die vorhandenen Skizzen-Shortcuts bleiben native Bilder im Pandoc-AST.
    -- 110 mm erhalten auch die Beschriftungen des Quadratmodells lesbar.
    return d:walk({Image = function(img)
      img.attributes.width = '110mm'
      return img
    end})
  end
  if d.classes:includes('checkpage') then
    local cells = {}
    for _, b in ipairs(d.content) do
      if b.t == 'Div' then
        cells[#cells + 1] = pandoc.write(pandoc.Pandoc(b.content), 'typst')
      end
    end
    assert(#cells == 2, 'Check-up-Seiten benötigen Regel- und Aufgabenspalte.')
    return pandoc.RawBlock('typst', '#checkpage([\n' .. cells[1] .. '\n], [\n' .. cells[2] .. '\n])')
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
        cells[#cells + 1] = '[' .. pandoc.write(pandoc.Pandoc(cell.contents), 'typst') .. ']'
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
