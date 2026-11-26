-- Allgemeiner Shortcut: Werte und optionale Zusatzzeile sind editierbare Mathematik.
local function split_values(value)
  local values = {}
  for part in (value .. "|"):gmatch("(.-)|") do
    table.insert(values, part:match("^%s*(.-)%s*$"))
  end
  return values
end
local function math_text(value)
  local doc = pandoc.Pandoc({pandoc.Plain({pandoc.Math("InlineMath", value)})})
  local rendered = pandoc.write(doc, "typst"):gsub("%s+$", "")
  return rendered:gsub("square%.stroked%.tiny", "#box(width: 5mm, height: 3.5mm, stroke: 0.5pt + primary, fill: white)")
end
local function rechenfolge(text)
  local body = text:match("^%[Rechenfolge:%s*(.-)%]$")
  if not body then return nil end
  local options = {}
  for field in (body .. ";"):gmatch("(.-);") do
    local key, value = field:match("^%s*([%w%-]+)%s*=%s*(.-)%s*$")
    if not key then error("Rechenfolge: Parameter als name=wert angeben.") end
    if key ~= "werte" and key ~= "zusatz" and key ~= "schritt"
       and key ~= "schritte" and key ~= "breite" then
      error("Rechenfolge: Unbekannter Parameter " .. key)
    end
    options[key] = value
  end
  if not options.werte then error("Rechenfolge: werte fehlt.") end
  local values = split_values(options.werte)
  if #values < 2 then error("Rechenfolge: Mindestens zwei Werte nötig.") end
  local extra = options.zusatz and split_values(options.zusatz)
  if extra and #extra ~= #values then error("Rechenfolge: zusatz muss gleich viele Einträge wie werte haben.") end
  local steps = options.schritte and split_values(options.schritte)
  if steps and #steps ~= #values - 1 then error("Rechenfolge: Ein Schritt pro Verbindung nötig.") end
  local width = options.breite or "150mm"
  if not width:match("^%d+%.?%d*mm$") then error("Rechenfolge: breite in mm angeben.") end
  local cells, cols = {}, {}
  for i, value in ipairs(values) do
    table.insert(cols, "1fr")
    local content = math_text(value)
    if extra then content = content .. "#v(3pt)" .. math_text(extra[i]) end
    table.insert(cells, "rect(width: 100%, height: 17mm, radius: 4pt, "
      .. "fill: primary-light, stroke: 0.5pt + primary, inset: 3pt)["
      .. "#align(center + horizon)[" .. content .. "]]")
    if i < #values then
      table.insert(cols, "9mm")
      local step = steps and steps[i] or options.schritt or ""
      table.insert(cells, "stack(dir: ttb, spacing: 2pt, "
        .. "[" .. math_text(step) .. "], [#text(fill: primary)[→]])")
    end
  end
  if not FORMAT:match("typst") then
    return pandoc.Para({pandoc.Str(table.concat(values, " → "))})
  end
  return pandoc.RawBlock("typst", "#block(width: 100%, above: 6pt, below: 6pt)["
    .. "#set text(size: 11pt)\n#align(center)[#block(width: " .. width .. ")[#grid(columns: ("
    .. table.concat(cols, ", ") .. "), align: center + horizon, column-gutter: 0pt, "
    .. "..(" .. table.concat(cells, ", ") .. ",))]]]")
end

function Para(p)
  return rechenfolge(pandoc.utils.stringify(p))
end
