-- Einheitliche Antwortfelder, auch innerhalb hochgestellter Exponenten.
-- Eingerahmte Ergebnisse ohne phantom bleiben unverändert.
function Math(el)
  if not FORMAT:match("typst") then return nil end
  local has_square = el.text:find("\\square", 1, true)
  local has_empty_box = el.text:match("\\boxed%s*{%s*\\phantom")
  local has_decimal = el.text:match("%d{,}%d")
  if not has_square and not has_empty_box and not has_decimal then return nil end
  local content = pandoc.write(pandoc.Pandoc({pandoc.Plain({el})}), "typst")
  content = content:gsub("square%.stroked%.tiny",
    '#box(width: 5mm, height: 3.5mm, stroke: none, fill: rgb("#eeeeee"))')
  content = content:gsub('#box%(stroke: black, inset: 3pt, %[%$ #hide',
    '#box(stroke: none, fill: rgb("#eeeeee"), inset: 3pt, [$ #hide')
  -- Das Dezimalkomma ist ein Zahlzeichen, kein Satztrenner.
  content = content:gsub('(%d)%s*\\,%s*(%d)', 'upright("%1,%2")')
  return pandoc.RawInline("typst", content:gsub("%s+$", ""))
end
