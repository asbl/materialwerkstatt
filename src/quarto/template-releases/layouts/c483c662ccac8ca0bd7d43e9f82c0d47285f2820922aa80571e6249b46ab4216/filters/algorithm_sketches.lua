local sketches = {}

local ink, blue, green, orange = "#172033", "#1565c0", "#167647", "#b45309"

local function escape(value)
  return tostring(value):gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;"):gsub('"', "&quot;")
end

local function split(value)
  local result = {}
  for entry in (value or ""):gmatch("[^,]+") do
    table.insert(result, entry:match("^%s*(.-)%s*$"))
  end
  return result
end

local function number(value, default, minimum, maximum)
  local parsed = value == nil and default or tonumber(value)
  if not parsed or parsed ~= math.floor(parsed) or parsed < minimum or parsed > maximum then
    error("Algorithmus-Skizze: ganze Zahl zwischen " .. minimum .. " und " .. maximum .. " erwartet.")
  end
  return parsed
end

local function options_for(args, allowed)
  local options = {}
  for field in args:gmatch("|([^|]+)") do
    local key, value = field:match("^%s*([%a]+)%s*=%s*(.-)%s*$")
    if not key or not allowed[key] then
      error("Algorithmus-Skizze: Unbekannte Option: " .. field)
    end
    if options[key] then error("Algorithmus-Skizze: Doppelte Option: " .. key) end
    options[key] = value
  end
  return options
end

local function flag(value)
  if value == nil or value == "nein" then return false end
  if value == "ja" then return true end
  error("Algorithmus-Skizze: ja oder nein erwartet.")
end

local function values_of(value, default, limit)
  local values = split(value or default)
  if #values < 1 or #values > limit then error("Algorithmus-Skizze: Ungültige Anzahl Werte.") end
  for _, entry in ipairs(values) do
    if not tonumber(entry) or #entry > 5 then error("Algorithmus-Skizze: kurze Zahlenwerte erwartet.") end
  end
  return values
end

local function indices(value, size)
  local selected = {}
  for _, entry in ipairs(split(value)) do selected[number(entry, nil, 1, size)] = true end
  return selected
end

local function text(parts, left, top, value, size, color, anchor)
  if type(value) == "number" then value = string.format("%g", value) end
  table.insert(parts, string.format('<text x="%g" y="%g" font-size="%g" fill="%s" text-anchor="%s">%s</text>', left, top, size or 36, color or ink, anchor or "middle", escape(value)))
end

local function line(parts, left, top, right, bottom, color, dashed)
  table.insert(parts, string.format('<path d="M%g %gL%g %g" fill="none" stroke="%s" stroke-width="3"%s/>', left, top, right, bottom, color or "#94a3b8", dashed and ' stroke-dasharray="8 6"' or ""))
end

local function box(parts, left, top, width, height, fill, stroke)
  table.insert(parts, string.format('<rect x="%g" y="%g" width="%g" height="%g" rx="8" fill="%s" stroke="%s" stroke-width="3"/>', left, top, width, height, fill or "#eff6ff", stroke or blue))
end

local function document(parts, height, title)
  return '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="' .. height .. '" viewBox="0 0 800 ' .. height .. '" role="img"><title>' .. escape(title) .. '</title><rect width="800" height="' .. height .. '" fill="white"/><g font-family="DejaVu Sans, sans-serif">' .. table.concat(parts, "\n") .. '</g></svg>'
end

local default_values = "4,9,13,18,27,31,42,56,68,85"

function sketches.render(kind, args)
  local parts = {}
  if kind == "suchfeld" then
    local options = options_for(args, { werte = true, verdeckt = true, offen = true, links = true, rechts = true, mitte = true, treffer = true, ziel = true })
    local values = values_of(options.werte, default_values, 12)
    local hidden = flag(options.verdeckt)
    local opened = indices(options.offen, #values)
    local left = number(options.links, 1, 1, #values + 1)
    local right = number(options.rechts, #values, 0, #values)
    local middle = options.mitte and number(options.mitte, nil, 1, #values)
    local found = options.treffer and number(options.treffer, nil, 1, #values)
    if middle and (middle < left or middle > right) then error("Algorithmus-Skizze: Mitte liegt außerhalb des Suchbereichs.") end
    if found and (found < left or found > right) then error("Algorithmus-Skizze: Treffer liegt außerhalb des Suchbereichs.") end
    text(parts, 400, 39, options.ziel and ("Gesucht: " .. options.ziel) or "Suchbereich", 36, blue)
    local cell = 672 / #values
    text(parts, 8, 91, "Position", 26, ink, "start")
    text(parts, 8, 151, "Wert", 26, ink, "start")
    for index, value in ipairs(values) do
      local cell_left = 113 + (index - 1) * cell
      local outside = index < left or index > right
      local fill = index == found and "#dcfce7" or index == middle and "#ffedd5" or outside and "#e2e8f0" or "#eff6ff"
      local stroke = index == found and green or index == middle and orange or outside and "#64748b" or blue
      box(parts, cell_left, 108, cell - 6, 66, fill, stroke)
      text(parts, cell_left + (cell - 6) / 2, 92, index, 28)
      local visible = not hidden or opened[index] or index == middle or index == found
      text(parts, cell_left + (cell - 6) / 2, 153, visible and value or "?", #value > 3 and 26 or 34)
      if outside then line(parts, cell_left + 8, 119, cell_left + cell - 14, 162, "#64748b") end
    end
    local label = left > right and "Suchbereich leer → kein Treffer" or found and "Treffer → Suche beenden" or ("Suchbereich: Position " .. left .. "–" .. right)
    text(parts, 400, 222, label, 32, found and green or blue)
    return document(parts, 245, "Suchfeld mit Positionen, Werten und Suchgrenzen")
  elseif kind == "suchbaum" or kind == "ebenenbaum" then
    local options = options_for(args, { werte = true, ebenen = true, markiert = true })
    local levels = number(options.ebenen, 4, 1, 4)
    local values = values_of(options.werte, default_values, 15)
    if kind == "suchbaum" then
      for index = 2, #values do
        if tonumber(values[index]) <= tonumber(values[index - 1]) then error("Algorithmus-Skizze: Suchbaum braucht streng aufsteigende Werte.") end
      end
    end
    local marked = indices(options.markiert, kind == "suchbaum" and #values or 15)
    local nodes = {}
    local function visit(first, last, depth, center_x, distance, parent)
      if depth > levels or first > last then return end
      local middle = math.floor((first + last) / 2)
      local center_y = 46 + (depth - 1) * 83
      local node = { index = middle, x = center_x, y = center_y }
      if parent then line(parts, parent.x, parent.y + 22, center_x, center_y - 22) end
      table.insert(nodes, node)
      visit(first, middle - 1, depth + 1, center_x - distance, distance / 2, node)
      visit(middle + 1, last, depth + 1, center_x + distance, distance / 2, node)
    end
    visit(1, kind == "suchbaum" and #values or 15, 1, 450, 160, nil)
    for _, node in ipairs(nodes) do
      local color = marked[node.index] and green or blue
      table.insert(parts, string.format('<circle cx="%g" cy="%g" r="26" fill="%s" stroke="%s" stroke-width="3"/>', node.x, node.y, marked[node.index] and "#dcfce7" or "#eff6ff", color))
      if kind == "suchbaum" then text(parts, node.x, node.y + 11, values[node.index], 30, color) end
    end
    for depth = 1, levels do text(parts, 10, 56 + (depth - 1) * 83, "Ebene " .. depth, 28, ink, "start") end
    return document(parts, 80 + (levels - 1) * 83, kind == "suchbaum" and "Entscheidungsbaum der binären Suche" or "Vollständiger Baum mit verdoppelter Knotenzahl je Ebene")
  elseif kind == "halbierung" then
    local options = options_for(args, { start = true, schritte = true })
    local start = number(options.start, 32, 2, 64)
    local steps = number(options.schritte, math.floor(math.log(start) / math.log(2)), 1, 6)
    if start / 2 ^ steps < 1 then error("Algorithmus-Skizze: Zu viele Halbierungen.") end
    local spacing = 700 / (steps + 1)
    for step = 0, steps do
      local center_x = 55 + spacing * (step + 0.5)
      box(parts, center_x - 38, 40, 76, 68)
      text(parts, center_x, 87, string.format("%g", start / 2 ^ step), 38)
      if step < steps then text(parts, center_x + spacing / 2, 86, "→", 34, blue) end
    end
    text(parts, 400, 164, steps .. "-mal halbiert", 36, blue)
    return document(parts, 185, "Wiederholtes Halbieren")
  elseif kind == "suchablauf" then
    local options = options_for(args, { teil = true })
    if options.teil == "abbruch" then
      box(parts, 230, 10, 340, 65)
      text(parts, 400, 55, "Suchbereich leer?", 34)
      line(parts, 300, 75, 200, 125)
      line(parts, 500, 75, 600, 125)
      text(parts, 190, 114, "ja", 32, blue)
      text(parts, 610, 114, "nein", 32, blue)
      box(parts, 20, 135, 350, 65, "#fff7ed", orange)
      box(parts, 430, 135, 350, 65)
      text(parts, 195, 180, "kein Treffer: Stopp", 32, orange)
      text(parts, 605, 180, "Mitte prüfen", 34, blue)
      return document(parts, 220, "Vor jedem Zugriff wird der leere Suchbereich ausgeschlossen")
    elseif options.teil == "vergleich" then
      box(parts, 200, 10, 400, 58)
      text(parts, 400, 51, "Mitte mit Ziel vergleichen", 30)
      for _, branch in ipairs({ { 130, "kleiner", "rechte Hälfte" }, { 400, "gleich", "Treffer: Stopp" }, { 670, "größer", "linke Hälfte" } }) do
        line(parts, 400, 68, branch[1], 125)
        text(parts, branch[1], 111, branch[2], 32, blue)
        box(parts, branch[1] - 122, 135, 244, 58, branch[1] == 400 and "#dcfce7" or "#eff6ff")
        text(parts, branch[1], 175, branch[3], 30)
      end
      text(parts, 400, 237, "Nach Halbierung: Bereich erneut prüfen", 32, blue)
      return document(parts, 260, "Vergleich mit drei Ausgängen: links, rechts oder Treffer")
    elseif options.teil and options.teil ~= "gesamt" then
      error("Algorithmus-Skizze: teil muss abbruch, vergleich oder gesamt sein.")
    end
    box(parts, 235, 12, 330, 58)
    text(parts, 400, 53, "Suchbereich leer?", 30)
    line(parts, 235, 40, 80, 40)
    text(parts, 115, 30, "ja", 28, blue)
    text(parts, 80, 85, "kein Treffer", 28, orange)
    line(parts, 400, 70, 400, 112)
    text(parts, 450, 100, "nein", 28, blue)
    box(parts, 235, 113, 330, 58)
    text(parts, 400, 154, "Mitte mit Ziel vergleichen", 25)
    for _, branch in ipairs({ { 130, "kleiner", "rechte Hälfte" }, { 400, "gleich", "Treffer: Stopp" }, { 670, "größer", "linke Hälfte" } }) do
      line(parts, 400, 171, branch[1], 230)
      text(parts, branch[1], 218, branch[2], 28, blue)
      box(parts, branch[1] - 122, 238, 244, 56, branch[1] == 400 and "#dcfce7" or "#eff6ff")
      text(parts, branch[1], 276, branch[3], 28)
    end
    text(parts, 400, 337, "Nach einer Halbierung: wieder oben prüfen", 29, blue)
    return document(parts, 355, "Binäre Suche mit Treffer, leerem Bereich und Wiederholung")
  elseif kind == "kostenbalken" then
    local options = options_for(args, { werte = true })
    local values = values_of(options.werte, "1,2,3,4", 10)
    local maximum = 1
    for _, value in ipairs(values) do
      if tonumber(value) < 0 then error("Algorithmus-Skizze: Kosten müssen nichtnegativ sein.") end
      maximum = math.max(maximum, tonumber(value))
    end
    text(parts, 15, 34, "Schritte", 30, blue, "start")
    local spacing = 660 / #values
    for index, value in ipairs(values) do
      local bar_left = 110 + (index - 1) * spacing
      local height = tonumber(value) / maximum * 145
      box(parts, bar_left, 210 - height, spacing - 20, height)
      text(parts, bar_left + (spacing - 20) / 2, 200 - height, value, 34)
      text(parts, bar_left + (spacing - 20) / 2, 253, index, 32)
    end
    text(parts, 400, 298, "Zielposition", 30, blue)
    return document(parts, 315, "Kosten bei unterschiedlichen Zielpositionen")
  elseif kind == "operationen" then
    local options = options_for(args, { zeilen = true, spalten = true })
    local rows = number(options.zeilen, 1, 1, 5)
    local columns = number(options.spalten, 4, 1, 8)
    local cell = math.min(95, 640 / columns)
    local left = (800 - columns * cell) / 2
    for row = 1, rows do
      for column = 1, columns do
        box(parts, left + (column - 1) * cell + 5, 10 + (row - 1) * 61, cell - 10, 51)
        text(parts, left + (column - 0.5) * cell, 47 + (row - 1) * 61, "•", 36)
      end
    end
    return document(parts, rows * 61 + 20, "Ein Kästchen steht für eine ausgeführte Operation")
  elseif kind == "spaltenaddition" then
    local options = options_for(args, { oben = true, unten = true })
    local top, bottom = options.oben or "723573", options.unten or "232683"
    if not top:match("^%d+$") or not bottom:match("^%d+$") or #top ~= #bottom or #top > 10 then error("Algorithmus-Skizze: Zwei gleich lange Ziffernfolgen mit höchstens zehn Stellen erwartet.") end
    local width = 64
    local left = (800 - #top * width) / 2
    text(parts, left - 45, 113, "+", 40)
    for index = 1, #top do
      local column_left = left + (index - 1) * width
      box(parts, column_left, 8, width - 7, 119)
      text(parts, column_left + 28, 54, top:sub(index, index), 40)
      text(parts, column_left + 28, 109, bottom:sub(index, index), 40)
      text(parts, column_left + 28, 196, "?", 40, blue)
    end
    line(parts, left - 65, 146, left + #top * width, 146, ink)
    return document(parts, 215, "Schriftliche Addition mit einzeln markierten Ziffernspalten")
  elseif kind == "suchvergleich" then
    local options = options_for(args, { offen = true })
    local hidden = flag(options.offen)
    text(parts, 170, 38, "Elemente", 34, blue)
    text(parts, 450, 38, "linear", 34, blue)
    text(parts, 680, 38, "binär", 34, green)
    local rows = { { "10", "10", "4" }, { "1.000", "1.000", "10" }, { "1.000.000", "1.000.000", "20" }, { "100.000.000", "100.000.000", "27" } }
    for index, row in ipairs(rows) do
      local baseline = 95 + (index - 1) * 59
      line(parts, 10, baseline - 34, 790, baseline - 34, "#cbd5e1")
      text(parts, 170, baseline, row[1], 32)
      text(parts, 450, baseline, hidden and "?" or row[2], 32)
      text(parts, 680, baseline, hidden and "?" or row[3], 34, green)
    end
    return document(parts, 295, "Maximal geprüfte Elemente im Worst Case")
  elseif kind == "wachstum" then
    local options = options_for(args, { kurven = true, xmax = true, ymax = true, schwelle = true })
    local curves = {
      konstant = { label = "1", evaluate = function() return 1 end },
      logarithmisch = { label = "log₂ n", evaluate = function(value) return math.log(value) / math.log(2) end },
      linear = { label = "n", evaluate = function(value) return value end },
      nlogn = { label = "n · log₂ n", evaluate = function(value) return value * math.log(value) / math.log(2) end },
      quadratisch = { label = "n²", evaluate = function(value) return value ^ 2 end },
      kubisch = { label = "n³", evaluate = function(value) return value ^ 3 end },
      exponentiell = { label = "2ⁿ", evaluate = function(value) return 2 ^ value end },
      kosten = { label = "2n + 4", evaluate = function(value) return 2 * value + 4 end },
      schranke = { label = "4n", evaluate = function(value) return 4 * value end },
    }
    local names = split(options.kurven or "konstant,logarithmisch")
    if #names < 1 or #names > 3 then error("Algorithmus-Skizze: Eine bis drei Kurven erwartet.") end
    local maximum_x = number(options.xmax, 32, 2, 100)
    local maximum_y = number(options.ymax, 6, 2, 100000)
    local colors = { blue, green, orange }
    text(parts, 70, 30, "Schritte", 30, ink, "start")
    text(parts, 400, 30, "lineare Skala", 27, ink)
    for tick = 0, 2 do
      local tick_x, tick_y = 80 + tick * 250, 240 - tick * 90
      line(parts, 80, tick_y, 580, tick_y, "#cbd5e1")
      text(parts, 67, tick_y + 9, maximum_y * tick / 2, 27, ink, "end")
      text(parts, tick_x, 279, maximum_x * tick / 2, 27)
    end
    line(parts, 80, 60, 80, 240, ink)
    line(parts, 80, 240, 580, 240, ink)
    text(parts, 610, 251, "n", 30)
    table.insert(parts, '<defs><clipPath id="plot"><rect x="80" y="60" width="500" height="180"/></clipPath></defs>')
    for index, name in ipairs(names) do
      local curve = curves[name]
      if not curve then error("Algorithmus-Skizze: Unbekannte Kurve: " .. name) end
      local points = {}
      for step = 0, 400 do
        local value = 1 + (maximum_x - 1) * step / 400
        local result = curve.evaluate(value)
        table.insert(points, string.format("%.3f,%.3f", 80 + value / maximum_x * 500, 240 - result / maximum_y * 180))
      end
      table.insert(parts, '<polyline clip-path="url(#plot)" points="' .. table.concat(points, " ") .. '" fill="none" stroke="' .. colors[index] .. '" stroke-width="4"/>')
      text(parts, 635, 91 + (index - 1) * 66, curve.label, 30, colors[index], "start")
    end
    if options.schwelle then
      if #names ~= 2 or not ((names[1] == "kosten" and names[2] == "schranke") or (names[1] == "schranke" and names[2] == "kosten")) then
        error("Algorithmus-Skizze: schwelle ist nur für kosten und schranke verfügbar.")
      end
      local threshold = number(options.schwelle, nil, 2, maximum_x)
      local threshold_x = 80 + threshold / maximum_x * 500
      line(parts, threshold_x, 60, threshold_x, 240, orange, true)
      text(parts, 400, 325, "Ab n₀ = " .. threshold .. ": 2n + 4 ≤ 4n", 32, orange)
    end
    return document(parts, options.schwelle and 350 or 300, "Wachstumsvergleich auf gemeinsamer linearer Skala")
  end
  error("Algorithmus-Skizze: Unbekannte Skizze: " .. tostring(kind))
end

return sketches
