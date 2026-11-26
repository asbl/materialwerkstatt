-- Quarto may deduplicate project/document filters by filename and retain only
-- the project exam.lua. Delegate to the pinned filter instead of disabling all
-- author syntax. A private environment also preserves the frozen helper paths.
local release_filters = os.getenv("MATERIAL_TEMPLATE_FILTER_DIR")
local script_path = PANDOC_SCRIPT_FILE
if release_filters and not pandoc.path.is_absolute(script_path) then
  script_path = pandoc.system.get_working_directory() .. "/" .. script_path
end
if release_filters and pandoc.path.normalize(script_path) ~= release_filters .. "/exam.lua" then
  local environment = setmetatable({ PANDOC_SCRIPT_FILE = release_filters .. "/exam.lua" }, { __index = _G })
  local loader, message = loadfile(environment.PANDOC_SCRIPT_FILE, "t", environment)
  if not loader then error(message) end
  local result = loader()
  if result then return result end
  local callbacks = {}
  for name, value in pairs(environment) do
    if type(value) == "function" then callbacks[name] = value end
  end
  return { callbacks }
end

local function has_class(el, class)
  for _, value in ipairs(el.classes) do
    if value == class then
      return true
    end
  end
  return false
end

local function target_format()
  if FORMAT:match("latex") or FORMAT:match("pdf") then
    return "latex"
  end
  return "typst"
end

local TARGET = target_format()

local function typst_string(value)
  value = value or ""
  value = value:gsub("\\", "\\\\")
  value = value:gsub('"', '\\"')
  return '"' .. value .. '"'
end

local function latex_string(value)
  value = value or ""
  value = value:gsub("\\", "\\textbackslash{}")
  value = value:gsub("([%%${}_&#])", "\\%1")
  value = value:gsub("%^", "\\textasciicircum{}")
  value = value:gsub("~", "\\textasciitilde{}")
  return value
end

local function quote(value)
  if TARGET == "latex" then
    return "{" .. latex_string(value) .. "}"
  end
  return typst_string(value)
end

local function value_arg(value)
  value = value or ""
  if TARGET == "latex" then
    return "{" .. value .. "}"
  end
  return value
end

local function attr(el, name, default)
  local value = el.attributes[name]
  if value == nil or value == "" then
    return default
  end
  return value
end

local function points_arg(value)
  if value == nil or value == "" then
    if TARGET == "latex" then
      return "{}"
    end
    return "none"
  end
  return value_arg(value)
end

local RED = "#c62828"
local BLUE = "#1565c0"

local function highlight_color(value, prefix, default)
  if value == nil or value == "" then
    return default or "#b34300"
  end
  if value == "rot" then
    return RED
  end
  if value:match("^#%x%x%x%x%x%x$") then
    return value:lower()
  end
  error(prefix .. ": farbe muss 'rot' oder ein Hex-Code wie #b34300 sein.")
end

-- Benannte Rahmenfarben für [Box farbe=...], damit Autor:innen keine
-- rohen LaTeX-/Typst-Farbangaben schreiben müssen.
local FARBBOX_COLORS = {
  blau = { latex = "examprimary", typst = "#1565c0" },
  tuerkis = { latex = "teal!70!black", typst = "#00897b" },
  orange = { latex = "orange!85!black", typst = "#e65100" },
  lila = { latex = "purple!70!black", typst = "#6a1b9a" },
}
local function farbbox_color(value)
  local entry = FARBBOX_COLORS[value]
  if not entry then
    error("Box: farbe muss blau, tuerkis, orange oder lila sein.")
  end
  return TARGET == "latex" and entry.latex or entry.typst
end

-- Images that are the sole content of a paragraph become a Figure block
-- (alt text promoted to a numbered caption). Aufgabe boxes never want that
-- numbering/caption, regardless of whether the image has alt text.
local function strip_figure_captions(el)
  return el:walk({
    Figure = function(fig)
      return fig.content
    end,
  })
end

local function alpha_label(index)
  local letters = {}
  while index > 0 do
    local rem = (index - 1) % 26
    table.insert(letters, 1, string.char(97 + rem))
    index = math.floor((index - 1) / 26)
  end
  return table.concat(letters)
end

local function abbildungen_label(index, mode)
  if mode == "abc" then
    return alpha_label(index) .. ")"
  elseif mode == "123" then
    return tostring(index) .. ")"
  end
  return nil
end

local function float_side_of(value)
  value = string.lower(value or "")
  if value == "right" or value == "rechts" then
    return "right"
  end
  if value == "left" or value == "links" then
    return "left"
  end
  if value ~= "" then
    error("Abbildungen: Unbekannte float-Richtung \"" .. value .. "\". Erlaubt sind right/rechts und left/links.")
  end
  return nil
end

local function red_text(args)
  if TARGET == "latex" then
    return pandoc.RawInline("latex", "\\textcolor{red}{" .. latex_string(args) .. "}")
  end
  local escaped = args:gsub("\\", "\\\\")
    :gsub("#", "\\#")
    :gsub("%[", "\\[")
    :gsub("%]", "\\]")
    :gsub("%$", "\\$")
    :gsub("%*", "\\*")
    :gsub("_", "\\_")
  return pandoc.RawInline("typst", '#text(fill: rgb("' .. RED .. '"))[' .. escaped .. ']')
end

local function unit_circle_image(args)
  local angle_field, option_text = args, ""
  local split_at = args:find("|", 1, true)
  if split_at then
    angle_field = args:sub(1, split_at - 1)
    option_text = args:sub(split_at)
  end
  local angle_text = angle_field:match("^%s*([+-]?%d+%.?%d*)%s*$")
    or angle_field:match("^%s*([+-]?%d*,%d+)%s*$")
  local angle = angle_text and tonumber((angle_text:gsub(",", ".")))
  local options = {}
  for field in option_text:gmatch("|([^|]+)") do
    local key, value = field:match("^%s*([%a]+)%s*=%s*(.-)%s*$")
    if key == nil or (key ~= "markiert" and key ~= "farbe" and key ~= "punkt") then
      error("Einheitskreis: Unbekannte Option: " .. field)
    end
    options[key] = value
  end
  local without_point = options.punkt == "nein"
  if options.punkt ~= nil and not without_point then
    error("Einheitskreis: punkt muss 'nein' sein.")
  end
  if without_point and options.markiert then
    error("Einheitskreis: markiert ist mit punkt=nein nicht kombinierbar.")
  end
  if angle == nil or angle ~= angle or math.abs(angle) == math.huge then
    if not without_point then
      error("Einheitskreis: Bitte einen Winkel in Grad angeben, z. B. [Einheitskreis 75].")
    end
    angle = 0
  end
  local marked = {}
  for name in (options.markiert or ""):gmatch("[^,%s]+") do
    if name ~= "sin" and name ~= "cos" then
      error("Einheitskreis: Unbekannte Markierung: " .. name)
    end
    marked[name] = true
  end
  local color = highlight_color(options.farbe, "Einheitskreis")

  local quarter = not without_point and angle >= 0 and angle <= 90
  local center_x, center_y = quarter and 38 or 155, quarter and 252 or 155
  local radius = quarter and 210 or 110
  local size = 310
  local radians = math.rad(angle % 360)
  local point_x = center_x + radius * math.cos(radians)
  local point_y = center_y - radius * math.sin(radians)
  local sweep = math.max(-360, math.min(360, angle))
  local sector
  if not without_point then
    sector = { string.format("M %g %g L %g %g", center_x, center_y, center_x + radius * 0.37, center_y) }
    local steps = math.max(1, math.ceil(math.abs(sweep) / 3))
    for step = 1, steps do
      local theta = math.rad(sweep * step / steps)
      table.insert(sector, string.format("L %.3f %.3f", center_x + radius * 0.37 * math.cos(theta), center_y - radius * 0.37 * math.sin(theta)))
    end
    table.insert(sector, "Z")
  end
  local axis_start = quarter and 10 or 16
  local axis_end = quarter and 278 or 288
  local label_angle = math.rad(sweep / 2)
  local label_x = center_x + radius * 0.23 * math.cos(label_angle)
  local label_y = center_y - radius * 0.23 * math.sin(label_angle)
  local parts = {
    string.format('<svg xmlns="http://www.w3.org/2000/svg" width="310" height="310" viewBox="0 0 %d %d">', size, size),
    '<g fill="none" stroke="black" stroke-width="2" stroke-linejoin="round">',
  }
  if sector then
    table.insert(parts, '<path d="' .. table.concat(sector, " ") .. '" fill="#e6e6e6" stroke-width="1"/>')
  end
  table.insert(parts, string.format('<path d="M %g %g H %g M %g %g V 16"/>', axis_start, center_y, axis_end, center_x, axis_end))
  table.insert(parts, string.format('<path d="M %g %g l -10 -4 v 8 Z M %g 16 l -4 10 h 8 Z" fill="black"/>', axis_end, center_y, center_x))
  if quarter then
    table.insert(parts, string.format('<path d="M %g %g A %g %g 0 0 0 %g %g"/>', center_x + radius, center_y, radius, radius, center_x, center_y - radius))
  else
    table.insert(parts, string.format('<circle cx="%g" cy="%g" r="%g"/>', center_x, center_y, radius))
  end
  if not without_point then
    table.insert(parts, string.format('<path d="M %g %g L %.3f %.3f"/><circle cx="%.3f" cy="%.3f" r="5" fill="white"/>', center_x, center_y, point_x, point_y, point_x, point_y))
  end
  if marked.cos and math.abs(point_x - center_x) > 1 then
    table.insert(parts, string.format('<path d="M %g %g L %.3f %g" stroke="%s" stroke-width="4"/>', center_x, center_y, point_x, center_y, color))
  end
  if marked.sin and math.abs(point_y - center_y) > 1 then
    table.insert(parts, string.format('<path d="M %.3f %g L %.3f %.3f" stroke="%s" stroke-width="4"/>', point_x, center_y, point_x, point_y, color))
  end
  table.insert(parts, '</g>')
  table.insert(parts, '<g font-family="DejaVu Sans, sans-serif" font-size="19" fill="black">')
  table.insert(parts, string.format('<text x="%g" y="%g">x</text><text x="%g" y="18">y</text>', axis_end + 7, center_y + 7, center_x - 23))
  local one_x = quarter and center_x + radius or center_x + radius + 12
  local one_top_x = quarter and center_x - 9 or center_x - 20
  local one_top_y = quarter and center_y - radius + 7 or center_y - radius - 8
  table.insert(parts, string.format('<text x="%g" y="%g">0</text><text x="%g" y="%g" text-anchor="middle">1</text><text x="%g" y="%g" text-anchor="end">1</text>', center_x - 20, center_y + 23, one_x, center_y + 23, one_top_x, one_top_y))
  if not quarter then
    table.insert(parts, string.format('<text x="%g" y="%g" text-anchor="middle">−1</text><text x="%g" y="%g" text-anchor="end">−1</text>', center_x - radius - 16, center_y + 23, center_x - 9, center_y + radius + 18))
  end
  -- Beschriftungen mit weißem Hof, damit Linien unter dem Text sauber unterbrochen werden
  local halo = ' paint-order="stroke" stroke="white" stroke-width="5" stroke-linejoin="round"'
  local function label_box(x, y, text, anchor)
    local glyphs = (utf8.len and utf8.len(text)) or #text
    local width = glyphs * 19 * 0.6
    local x0 = anchor == "end" and x - width or (anchor == "middle" and x - width / 2 or x)
    return { x0, y - 19 * 0.75, x0 + width, y + 19 * 0.25 }
  end
  local function boxes_overlap(a, b)
    return a[1] < b[3] and b[1] < a[3] and a[2] < b[4] and b[2] < a[4]
  end
  local fixed_boxes = {
    label_box(center_x - 20, center_y + 23, "0", "middle"),
    label_box(one_x, center_y + 23, "1", "middle"),
    label_box(one_top_x, one_top_y, "1", "end"),
  }
  if not quarter then
    table.insert(fixed_boxes, label_box(center_x - radius - 16, center_y + 23, "−1", "middle"))
    table.insert(fixed_boxes, label_box(center_x - 9, center_y + radius + 18, "−1", "end"))
  end
  local p_box, degree_box
  if not without_point then
    local p_x = point_x + (math.cos(radians) < -0.1 and -10 or 10)
    local p_y = point_y + (math.sin(radians) < -0.1 and 22 or -10)
    local p_anchor = math.cos(radians) < -0.1 and "end" or "start"
    p_box = label_box(p_x, p_y, "P", p_anchor)
    table.insert(parts, string.format('<text x="%.3f" y="%.3f" text-anchor="%s"%s>P</text>', p_x, p_y, p_anchor, halo))
    degree_box = label_box(label_x, label_y, angle_text .. "°", "middle")
    table.insert(parts, string.format('<text x="%.3f" y="%.3f" text-anchor="middle" dominant-baseline="middle"%s>%s°</text>', label_x, label_y, halo, angle_text))
  end
  -- sin/cos liegen auf ihrer Strecke (wie die TikZ-Vorbilder mit fill=white)
  -- und weichen anderen Beschriftungen entlang der Strecke aus
  local function free_position(x, y, text, anchor, step_x, step_y, extra_boxes)
    local obstacles = {}
    for _, box in ipairs(fixed_boxes) do table.insert(obstacles, box) end
    if p_box then table.insert(obstacles, p_box) end
    if degree_box then table.insert(obstacles, degree_box) end
    for _, box in ipairs(extra_boxes or {}) do table.insert(obstacles, box) end
    for _ = 1, 8 do
      local clear = true
      local box = label_box(x, y, text, anchor)
      for _, obstacle in ipairs(obstacles) do
        if boxes_overlap(box, obstacle) then clear = false break end
      end
      if clear then return x, y end
      x, y = x + step_x, y + step_y
    end
    return x, y
  end
  local cos_box
  if marked.cos and math.abs(point_x - center_x) > 1 then
    local x = free_position((center_x + point_x) / 2, center_y, "cos", "middle", point_x < center_x and -9 or 9, 0)
    cos_box = label_box(x, center_y, "cos", "middle")
    table.insert(parts, string.format('<text x="%.3f" y="%g" text-anchor="middle" fill="%s"%s>cos</text>', x, center_y, color, halo))
  end
  if marked.sin and math.abs(point_y - center_y) > 1 then
    local x, y = free_position(point_x, (center_y + point_y) / 2, "sin", "middle", 0, point_y < center_y and -9 or 9, cos_box and { cos_box } or nil)
    table.insert(parts, string.format('<text x="%.3f" y="%.3f" text-anchor="middle" fill="%s"%s>sin</text>', x, y, color, halo))
  end
  table.insert(parts, '</g></svg>')
  local svg = table.concat(parts, "\n")
  local filename = "einheitskreis-" .. pandoc.utils.sha1(svg)
  if TARGET == "latex" then
    filename = filename .. ".pdf"
    pandoc.mediabag.insert(filename, "application/pdf", pandoc.pipe("rsvg-convert", { "--format=pdf" }, svg))
  else
    filename = filename .. ".svg"
    pandoc.mediabag.insert(filename, "image/svg+xml", svg)
  end
  local alt = without_point and "Einheitskreis" or ("Einheitskreis mit Winkel " .. angle_text .. "° und Punkt P")
  return pandoc.Image({ pandoc.Str(alt) }, filename, "", pandoc.Attr("", {}, { width = "80%" }))
end

local algorithm_kinds = {
  suchfeld = true, suchbaum = true, ebenenbaum = true, halbierung = true,
  suchablauf = true, wachstum = true, kostenbalken = true,
  operationen = true, spaltenaddition = true, suchvergleich = true,
}
local algorithm_sketches

local function geometry_image(args)
  local kind = args:match("^%s*([^|]+)")
  kind = kind and kind:match("^%s*(.-)%s*$")
  if algorithm_kinds[kind] then
    if not algorithm_sketches then
      algorithm_sketches = dofile(pandoc.path.directory(PANDOC_SCRIPT_FILE) .. "/algorithm_sketches.lua")
    end
    local svg = algorithm_sketches.render(kind, args)
    local filename = "algorithmus-" .. pandoc.utils.sha1(svg)
    if TARGET == "latex" then
      filename = filename .. ".pdf"
      pandoc.mediabag.insert(filename, "application/pdf", pandoc.pipe("rsvg-convert", { "--format=pdf" }, svg))
    else
      filename = filename .. ".svg"
      pandoc.mediabag.insert(filename, "image/svg+xml", svg)
    end
    return pandoc.Image({ pandoc.Str("Skizze: " .. kind) }, filename, "", pandoc.Attr("", {}, { width = "100%" }))
  end
  local options = {}
  local allowed = {
    form = true, a = true, b = true, c = true, alpha = true, beta = true,
    gamma = true, hoehe = true, h = true, x = true, s = true,
    laenge = true, breite = true, oben = true, unten = true,
    drehung = true, A = true, B = true, C = true, markiert = true, farbe = true,
    raeder = true, ziffern = true, innen = true, spiele = true, zeichen = true,
    r = true,
  }
  for field in args:gmatch("|([^|]+)") do
    local key, value = field:match("^%s*([%a]+)%s*=%s*(.-)%s*$")
    if key == nil or not allowed[key] then
      error("Skizze: Unbekannte Option: " .. field)
    end
    options[key] = value
  end
  local markable = kind == "steigung" and { x = true, h = true, s = true, alpha = true }
    or kind == "quader" and { boden = true, raumdiagonale = true }
    or { a = true, b = true, c = true, alpha = true, beta = true, gamma = true }
  local marked = {}
  for name in (options.markiert or ""):gmatch("[^,%s]+") do
    if not markable[name] then
      error("Skizze: Unbekannte Markierung: " .. name)
    end
    marked[name] = true
  end
  local color = highlight_color(options.farbe, "Skizze")
  local rotation = tonumber(options.drehung or "0")
  if not rotation or rotation ~= rotation or math.abs(rotation) == math.huge then
    error("Skizze: drehung muss eine endliche Gradzahl sein.")
  end
  if kind ~= "dreieck" and (options.drehung or options.A or options.B or options.C) then
    error("Skizze: drehung und Eckpunktnamen sind nur für Dreiecke verfügbar.")
  end
  if options.markiert and kind ~= "dreieck" and kind ~= "steigung" and kind ~= "quader" then
    error("Skizze: markiert ist nur für Dreiecke, Steigung und Quader verfügbar.")
  end
  local parts = {
    '<svg xmlns="http://www.w3.org/2000/svg" width="460" height="250" viewBox="0 0 460 250">',
    '<g stroke="#172033" stroke-width="2" fill="none" stroke-linejoin="round">',
  }
  local labels = {}
  local function escape(value)
    return value:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;"):gsub('"', "&quot;")
  end
  local function line(start, finish, dashed, highlight)
    table.insert(parts, string.format('<path d="M %g %g L %g %g"%s%s/>', start[1], start[2], finish[1], finish[2], dashed and ' stroke-dasharray="6 4"' or "", highlight and string.format(' stroke="%s" stroke-width="4"', highlight) or ""))
  end
  local function label(point, value, offset_x, offset_y, size)
    if value and value ~= "" then
      table.insert(labels, string.format('<text x="%g" y="%g" text-anchor="middle"%s>%s</text>', point[1] + (offset_x or 0), point[2] + (offset_y or 0), size and string.format(' font-size="%d"', size) or "", escape(value)))
    end
  end
  local function midpoint(start, finish, value, offset_x, offset_y)
    label({ (start[1] + finish[1]) / 2, (start[2] + finish[2]) / 2 }, value, offset_x, offset_y)
  end
  local function direction(origin, endpoint)
    local delta_x, delta_y = endpoint[1] - origin[1], endpoint[2] - origin[2]
    local length = math.sqrt(delta_x * delta_x + delta_y * delta_y)
    return { delta_x / length, delta_y / length }
  end
  local function angle(vertex, first, second, value, right, highlight, label_offset)
    local first_dir, second_dir = direction(vertex, first), direction(vertex, second)
    local radius = right and 13 or 26
    if right then
      local cross = first_dir[1] * second_dir[2] - first_dir[2] * second_dir[1]
      table.insert(parts, string.format('<path d="M %g %g A %g %g 0 0 %d %g %g"%s/>', vertex[1] + radius * first_dir[1], vertex[2] + radius * first_dir[2], radius, radius, cross > 0 and 1 or 0, vertex[1] + radius * second_dir[1], vertex[2] + radius * second_dir[2], highlight and string.format(' stroke="%s" stroke-width="3"', highlight) or ""))
      local bisector = direction({ 0, 0 }, { first_dir[1] + second_dir[1], first_dir[2] + second_dir[2] })
      table.insert(parts, string.format('<circle cx="%.3f" cy="%.3f" r="2.5" fill="%s" stroke="none"/>', vertex[1] + radius * 0.55 * bisector[1], vertex[2] + radius * 0.55 * bisector[2], highlight or "#172033"))
    elseif value and value ~= "" then
      local cross = first_dir[1] * second_dir[2] - first_dir[2] * second_dir[1]
      table.insert(parts, string.format('<path d="M %g %g A %g %g 0 0 %d %g %g"%s/>', vertex[1] + radius * first_dir[1], vertex[2] + radius * first_dir[2], radius, radius, cross > 0 and 1 or 0, vertex[1] + radius * second_dir[1], vertex[2] + radius * second_dir[2], highlight and string.format(' stroke="%s" stroke-width="3"', highlight) or ""))
      local bisector = direction({ 0, 0 }, { first_dir[1] + second_dir[1], first_dir[2] + second_dir[2] })
      if label_offset then
        label(vertex, value, label_offset[1], label_offset[2])
      else
        -- Abstand entlang der Halbierenden so wählen, dass die Textbox beide Schenkel freihält
        local cos_angle = math.max(-1, math.min(1, first_dir[1] * second_dir[1] + first_dir[2] * second_dir[2]))
        local sin_half = math.max(0.15, math.sin(math.acos(cos_angle) / 2))
        local width = #value * 17 * 0.6 / 2
        local extent = math.max(width * math.abs(first_dir[2]) + 9 * math.abs(first_dir[1]),
          width * math.abs(second_dir[2]) + 9 * math.abs(second_dir[1]))
        local distance = math.max(26, (extent + 4) / sin_half)
        label(vertex, value, distance * bisector[1], distance * bisector[2] + 5)
      end
    end
  end
  if kind == "dreieck" then
    local form = options.form or "allgemein"
    local vertices = {
      allgemein = { { 45, 200 }, { 370, 200 }, { 150, 30 } },
      gleichschenklig = { { 45, 200 }, { 370, 200 }, { 207.5, 30 } },
      ["stumpf-A"] = { { 150, 200 }, { 370, 200 }, { 45, 30 } },
      ["stumpf-C"] = { { 45, 200 }, { 370, 200 }, { 150, 120 } },
      ["recht-A"] = { { 55, 200 }, { 365, 200 }, { 55, 30 } },
      ["recht-B"] = { { 55, 200 }, { 365, 200 }, { 365, 30 } },
      ["recht-C"] = { { 55, 200 }, { 365, 40 }, { 55, 40 } },
    }
    if not vertices[form] then
      error("Skizze: Unbekannte Dreiecksform: " .. form)
    end
    local point_a, point_b, point_c = table.unpack(vertices[form])
    local foot = { point_c[1], 200 }
    if options.drehung then
      local radians = math.rad(rotation % 360)
      local transformed = {}
      local min_x, max_x, min_y, max_y = math.huge, -math.huge, math.huge, -math.huge
      for _, point in ipairs({ point_a, point_b, point_c, foot }) do
        local delta_x, delta_y = point[1] - 230, point[2] - 125
        local rotated = { delta_x * math.cos(radians) + delta_y * math.sin(radians), -delta_x * math.sin(radians) + delta_y * math.cos(radians) }
        table.insert(transformed, rotated)
        min_x, max_x = math.min(min_x, rotated[1]), math.max(max_x, rotated[1])
        min_y, max_y = math.min(min_y, rotated[2]), math.max(max_y, rotated[2])
      end
      local scale = math.min(310 / (max_x - min_x), 160 / (max_y - min_y))
      for _, point in ipairs(transformed) do
        point[1] = 230 + (point[1] - (min_x + max_x) / 2) * scale
        point[2] = 120 + (point[2] - (min_y + max_y) / 2) * scale
      end
      point_a, point_b, point_c, foot = table.unpack(transformed)
    end
    line(point_a, point_b, false, marked.c and color)
    line(point_b, point_c, false, marked.a and color)
    line(point_c, point_a, false, marked.b and color)
    local center = { (point_a[1] + point_b[1] + point_c[1]) / 3, (point_a[2] + point_b[2] + point_c[2]) / 3 }
    local function outer_label(point, value, distance)
      local outward = direction(center, point)
      label(point, value, distance * outward[1], distance * outward[2] + 5)
    end
    -- Seitenbeschriftung senkrecht zur Kante nach außen, damit sie die Kante nicht berührt
    local function side_label(start, finish, value)
      if not value or value == "" then return end
      local middle = { (start[1] + finish[1]) / 2, (start[2] + finish[2]) / 2 }
      local along = direction(start, finish)
      local normal = { along[2], -along[1] }
      if (center[1] - middle[1]) * normal[1] + (center[2] - middle[2]) * normal[2] > 0 then
        normal = { -normal[1], -normal[2] }
      end
      local width = #value * 17 * 0.6 / 2
      local distance = width * math.abs(normal[1]) + 9 * math.abs(normal[2]) + 6
      label(middle, value, distance * normal[1], distance * normal[2] + 5)
    end
    outer_label(point_a, options.A or "A", 23)
    outer_label(point_b, options.B or "B", 23)
    outer_label(point_c, options.C or "C", 23)
    side_label(point_b, point_c, options.a or "a")
    side_label(point_a, point_c, options.b or "b")
    side_label(point_a, point_b, options.c or "c")
    angle(point_a, point_b, point_c, options.alpha or (marked.alpha and "α"), form == "recht-A", marked.alpha and color)
    angle(point_b, point_a, point_c, options.beta or (marked.beta and "β"), form == "recht-B", marked.beta and color)
    angle(point_c, point_a, point_b, options.gamma or (marked.gamma and "γ"), form == "recht-C", marked.gamma and color)
    if options.hoehe == "ja" then
      if form ~= "allgemein" and form ~= "gleichschenklig" then
        error("Skizze: hoehe=ja erfordert form=allgemein oder form=gleichschenklig.")
      end
      line(point_c, foot, true)
      -- H links vom Fußpunkt; beim gleichschenkligen Dreieck liegt der Fußpunkt auf der
      -- Seitenmitte, dann zusätzlich am c-Label vorbei
      local c_text = options.c or "c"
      local h_x = math.min(foot[1] - 16, (point_a[1] + point_b[1]) / 2 - #c_text * 17 * 0.6 / 2 - 8)
      label({ h_x, foot[2] }, "H", 0, 23)
      midpoint(point_c, foot, options.h or "h", 16, 0)
      angle(foot, point_c, point_b, nil, true)
    end
  elseif kind == "steigung" then
    local start, foot, finish = { 45, 200 }, { 365, 200 }, { 365, 40 }
    line(start, foot, true, marked.x and color)
    line(foot, finish, false, marked.h and color)
    line(start, finish, false, marked.s and color)
    midpoint(start, foot, options.x or "x", 0, 27)
    midpoint(foot, finish, options.h or "h", 40, 0)
    midpoint(start, finish, options.s or "s", -12, -14)
    angle(start, foot, finish, options.alpha or "α", false, marked.alpha and color)
    angle(foot, start, finish, nil, true)
    label(finish, options.oben, 16, -4)
    label(start, options.unten, -16, 17)
  elseif kind == "pyramide" then
    local point_a, point_b, point_c, point_d = { 65, 210 }, { 290, 210 }, { 365, 150 }, { 140, 150 }
    local center, peak = { 215, 180 }, { 215, 25 }
    line(point_a, point_b)
    line(point_b, point_c)
    line(point_c, point_d, true)
    line(point_d, point_a, true)
    for _, vertex in ipairs({ point_a, point_b, point_c, point_d }) do
      line(peak, vertex, vertex == point_d)
    end
    line(peak, center, true)
    line(center, point_a, true)
    label(point_a, "A", -15, 17)
    label(center, "M", 18, 8)
    label(peak, "S", 0, -10)
    midpoint(point_a, point_b, options.a or "a", 0, 25)
    -- h-Label links der Höhe-Linie (x=215) mit 8px Abstand. Der Korridor zwischen
    -- Kante S-D und Höhe-Linie reicht oberhalb der hinteren Kante C-D (y=150) nur
    -- für schmale Texte; breite wandern in die Tasche zwischen C-D und M (y=170).
    local h_text = options.h or "h"
    local h_width = #h_text * 17 * 0.6
    local h_y = math.max(102.5, 13 + (31 + h_width) / 0.6)
    if h_y > 138 then
      h_y = 170
    end
    label({ 207 - h_width / 2, h_y }, h_text, 0, 0)
    midpoint(point_a, peak, options.s or "s", -20, 0)
    -- Winkel-Label fest versetzt: auf der Halbierenden läge es auf der verdeckten Kante A-D
    angle(point_a, center, peak, options.alpha, false, nil, { 49, -18 })
  elseif kind == "quader" then
    local floor = { { 45, 210 }, { 285, 210 }, { 370, 155 }, { 130, 155 } }
    local top = {}
    for index, vertex in ipairs(floor) do
      top[index] = { vertex[1], vertex[2] - 115 }
    end
    -- Reihenfolge: verdeckte Kanten, dann Diagonalen, dann sichtbare Kanten,
    -- damit vordere Kanten die Diagonalen an den Kreuzungspunkten überdecken.
    local hidden_edges, visible_edges = {}, {}
    for index, vertex in ipairs(floor) do
      local next_index = index % 4 + 1
      local edges = {
        { vertex, floor[next_index], index >= 3 },
        { top[index], top[next_index], false },
        { vertex, top[index], index == 4 },
      }
      for _, edge in ipairs(edges) do
        table.insert(edge[3] and hidden_edges or visible_edges, edge)
      end
    end
    for _, edge in ipairs(hidden_edges) do line(edge[1], edge[2], true) end
    line(floor[1], floor[3], true, marked.boden and color)
    line(floor[1], top[3], false, marked.raumdiagonale and color)
    for _, edge in ipairs(visible_edges) do line(edge[1], edge[2], false) end
    midpoint(floor[1], floor[2], options.laenge or "l", 0, 25)
    midpoint(floor[2], floor[3], options.breite or "b", 16, 20)
    midpoint(floor[3], top[3], options.h or "h", 35, 0)
  elseif kind == "zahlenschloss" then
    local wheels = tonumber(options.raeder or "3")
    local digits = tonumber(options.ziffern or "3")
    if not wheels or wheels ~= math.floor(wheels) or wheels < 1 or wheels > 6 then
      error("Skizze: raeder muss eine ganze Zahl zwischen 1 und 6 sein.")
    end
    if not digits or digits ~= math.floor(digits) or digits < 2 or digits > 9 then
      error("Skizze: ziffern muss eine ganze Zahl zwischen 2 und 9 sein.")
    end
    local wheel_width, wheel_gap = 56, 14
    local spacing = math.min(26, 150 / digits)
    local digit_font = spacing < 20 and 13 or 17
    local wheel_height = digits * spacing + 10
    local body_height = wheel_height + 20
    local body_width = wheels * wheel_width + (wheels - 1) * wheel_gap + 24
    local body_left = (460 - body_width) / 2
    local body_top = math.max(40, (250 - body_height) / 2)
    table.insert(parts, string.format('<path d="M %g %g v -8 a 26 26 0 0 1 52 0 v 8"/>', 230 - 26, body_top))
    table.insert(parts, string.format('<rect x="%g" y="%g" width="%g" height="%g" rx="10"/>', body_left, body_top, body_width, body_height))
    local window_digit = math.floor((digits + 1) / 2)
    for wheel = 1, wheels do
      local left = body_left + 12 + (wheel - 1) * (wheel_width + wheel_gap)
      table.insert(parts, string.format('<rect x="%g" y="%g" width="%g" height="%g" rx="8"/>', left, body_top + 10, wheel_width, wheel_height))
      for digit = 1, digits do
        local center_y = body_top + 15 + (digit - 0.5) * spacing
        if digit == window_digit then
          table.insert(parts, string.format('<rect x="%g" y="%g" width="%g" height="%g" stroke-width="3"/>', left - 2, center_y - spacing / 2 - 1, wheel_width + 4, spacing + 2))
        end
        label({ left + wheel_width / 2, center_y }, tostring(digit), 0, digit_font * 0.35, digit_font)
      end
    end
  elseif kind == "flaeche" then
    local left, top, size = 150, 45, 160
    table.insert(parts, string.format('<rect x="%g" y="%g" width="%g" height="%g"/>', left, top, size, size))
    label({ left + size / 2, top + size }, options.a or "a", 0, 26)
    label({ left, top + size / 2 }, options.a or "a", -24, 6)
    label({ left + size / 2, top + size / 2 }, options.innen, 0, 6)
  elseif kind == "volumen" then
    local floor = { { 90, 215 }, { 210, 215 }, { 250, 175 }, { 130, 175 } }
    local top = {}
    for index, vertex in ipairs(floor) do
      top[index] = { vertex[1], vertex[2] - 120 }
    end
    local hidden_edges, visible_edges = {}, {}
    for index, vertex in ipairs(floor) do
      local next_index = index % 4 + 1
      local edges = {
        { vertex, floor[next_index], index >= 3 },
        { top[index], top[next_index], false },
        { vertex, top[index], index == 4 },
      }
      for _, edge in ipairs(edges) do
        table.insert(edge[3] and hidden_edges or visible_edges, edge)
      end
    end
    for _, edge in ipairs(hidden_edges) do line(edge[1], edge[2], true) end
    for _, edge in ipairs(visible_edges) do line(edge[1], edge[2], false) end
    midpoint(floor[1], floor[2], options.a or "a", 0, 26)
    midpoint(floor[2], floor[3], options.a or "a", 16, 16)
    midpoint(floor[3], top[3], options.a or "a", 32, 0)
    -- Innenlabel im freien Bereich rechts der verdeckten senkrechten Kante.
    label({ (floor[4][1] + floor[2][1]) / 2, (floor[1][2] + top[3][2]) / 2 }, options.innen, 0, 6)
  elseif kind == "kreis" then
    local center, radius = { 230, 125 }, 88
    table.insert(parts, string.format('<circle cx="%g" cy="%g" r="%g"/>', center[1], center[2], radius))
    line(center, { center[1] + radius, center[2] })
    table.insert(parts, string.format('<circle cx="%g" cy="%g" r="2.5" fill="#172033" stroke="none"/>', center[1], center[2]))
    midpoint(center, { center[1] + radius, center[2] }, options.r or "r", 0, -9)
    -- innen unterhalb des Mittelpunkts, damit die Beschriftung der Radiuslinie frei bleibt
    label(center, options.innen, 0, 34)
  elseif kind == "zylinder" then
    local rx, ry = 85, 30
    local top_y, bottom_y = 72, 196
    local left, right = 230 - rx, 230 + rx
    table.insert(parts, string.format('<ellipse cx="230" cy="%g" rx="%g" ry="%g"/>', top_y, rx, ry))
    line({ left, top_y }, { left, bottom_y })
    line({ right, top_y }, { right, bottom_y })
    table.insert(parts, string.format('<path d="M %g %g A %g %g 0 0 0 %g %g"/>', left, bottom_y, rx, ry, right, bottom_y))
    line({ 230, top_y }, { right, top_y })
    table.insert(parts, string.format('<circle cx="230" cy="%g" r="2.5" fill="#172033" stroke="none"/>', top_y))
    -- r-Label bei 40 % der Radiuslinie: auch breite Texte bleiben unter dem
    -- oberen Ellipsenbogen frei, am Mittelpunkt würden sie ihn streifen
    label({ 230 + rx * 0.4, top_y }, options.r or "r", 0, -8)
    midpoint({ right, top_y }, { right, bottom_y }, options.h or "h", 26, 0)
    label({ 230, (top_y + bottom_y) / 2 }, options.innen, 0, 6)
  elseif kind == "tippzettel" then
    local games = tonumber(options.spiele or "13")
    if not games or games ~= math.floor(games) or games < 1 or games > 14 then
      error("Skizze: spiele muss eine ganze Zahl zwischen 1 und 14 sein.")
    end
    local marks = {}
    for mark in (options.zeichen or "1,0,2"):gmatch("[^,%s]+") do
      table.insert(marks, mark)
    end
    if #marks < 2 or #marks > 4 then
      error("Skizze: zeichen braucht 2 bis 4 Einträge, z. B. zeichen=1,0,2.")
    end
    local slip_left, slip_width = 80, 300
    local header_height = 26
    local row_height = math.min(24, 196 / games)
    local slip_height = 16 + header_height + games * row_height
    local slip_top = (250 - slip_height) / 2
    local header_bottom = slip_top + 8 + header_height
    local number_font = row_height < 18 and 11 or 14
    local box_size = math.min(14, row_height - 4)
    local box_font = math.max(9, box_size - 3)
    local box_gap = 5
    local boxes_width = #marks * box_size + (#marks - 1) * box_gap
    local boxes_left = slip_left + slip_width - 12 - boxes_width
    local number_x = slip_left + 26
    table.insert(parts, string.format('<rect x="%g" y="%g" width="%g" height="%g" rx="8"/>', slip_left, slip_top, slip_width, slip_height))
    line({ slip_left, header_bottom }, { slip_left + slip_width, header_bottom }, false)
    label({ number_x, slip_top + 8 + header_height / 2 }, "Spiel", 0, 4, 12)
    label({ boxes_left + boxes_width / 2, slip_top + 8 + header_height / 2 }, "Tipp", 0, 4, 12)
    for game = 1, games do
      local center_y = header_bottom + (game - 0.5) * row_height
      label({ number_x, center_y }, tostring(game), 0, number_font * 0.35, number_font)
      for index, mark in ipairs(marks) do
        local box_left = boxes_left + (index - 1) * (box_size + box_gap)
        table.insert(parts, string.format('<rect x="%g" y="%g" width="%g" height="%g"/>', box_left, center_y - box_size / 2, box_size, box_size))
        label({ box_left + box_size / 2, center_y }, mark, 0, box_font * 0.35, box_font)
      end
    end
  else
    error("Skizze: Erwartet dreieck, steigung, pyramide, quader, kreis, zylinder, zahlenschloss, flaeche, volumen oder tippzettel.")
  end
  table.insert(parts, '</g><g font-family="DejaVu Sans, sans-serif" font-size="17" fill="#172033">')
  table.insert(parts, table.concat(labels, "\n"))
  table.insert(parts, "</g></svg>")
  local svg = table.concat(parts, "\n")
  local filename = "skizze-" .. pandoc.utils.sha1(svg)
  if TARGET == "latex" then
    filename = filename .. ".pdf"
    pandoc.mediabag.insert(filename, "application/pdf", pandoc.pipe("rsvg-convert", { "--format=pdf" }, svg))
  else
    filename = filename .. ".svg"
    pandoc.mediabag.insert(filename, "image/svg+xml", svg)
  end
  return pandoc.Image({ pandoc.Str("Skizze: " .. kind) }, filename, "", pandoc.Attr("", {}, { width = "100%" }))
end

-- Function types plottable in a coordinate system. Adding a new type means one
-- entry: its allowed parameters and an evaluate() that maps x to y.
local plot_types = {
  parabel = {
    params = { d = true, e = true, a = true },
    evaluate = function(options)
      local d = options.d or 0
      local e = options.e or 0
      local a = options.a or 1
      return function(x)
        return a * (x - d) * (x - d) + e
      end
    end,
  },
}

local function coordinate_number(value, name)
  if value == nil or value == "" then
    return nil
  end
  local number = tonumber((value:gsub(",", ".")))
  if number == nil or number ~= number or math.abs(number) == math.huge then
    error("Koordinatensystem: " .. name .. " muss eine Zahl sein.")
  end
  return number
end

local function coordinate_range(value, name, default_min, default_max)
  if value == nil or value == "" then
    return default_min, default_max
  end
  local first, second = value:match("^%s*([+-]?%d+[.,]?%d*)%.%.([+-]?%d+[.,]?%d*)%s*$")
  if first == nil then
    error("Koordinatensystem: " .. name .. " muss als Bereich von..bis angegeben werden, z. B. " .. name .. "=-8..8.")
  end
  local range_min = coordinate_number(first, name)
  local range_max = coordinate_number(second, name)
  if range_min >= range_max then
    error("Koordinatensystem: " .. name .. ": der Startwert muss kleiner als der Endwert sein.")
  end
  return range_min, range_max
end

local function coordinate_system_image(args)
  if not args:match("^%s*|") then
    args = "|" .. args
  end
  local raw = {}
  for field in args:gmatch("|([^|]+)") do
    local key, value = field:match("^%s*([%a]+)%s*=%s*(.-)%s*$")
    if key == nil then
      error("Koordinatensystem: Unbekannte Option: " .. field)
    end
    raw[key] = value
  end
  local plot_type = nil
  if raw.funktion ~= nil and raw.funktion ~= "" then
    plot_type = plot_types[raw.funktion]
    if plot_type == nil then
      error("Koordinatensystem: Unbekannter Funktionstyp: " .. raw.funktion)
    end
  end
  local allowed = { x = true, y = true, raster = true, beschriftung = true, funktion = true, farbe = true }
  if plot_type ~= nil then
    for key in pairs(plot_type.params) do
      allowed[key] = true
    end
  end
  local options = {}
  for key, value in pairs(raw) do
    if not allowed[key] then
      error("Koordinatensystem: Unbekannte Option: " .. key)
    end
    options[key] = value
  end
  local x_min, x_max = coordinate_range(options.x, "x", -10, 10)
  local y_min, y_max = coordinate_range(options.y, "y", -10, 10)
  local raster = coordinate_number(options.raster, "raster") or 1
  if raster <= 0 then
    error("Koordinatensystem: raster muss positiv sein.")
  end
  local label_step = coordinate_number(options.beschriftung, "beschriftung") or 2
  if label_step <= 0 then
    error("Koordinatensystem: beschriftung muss positiv sein.")
  end
  local plot_params = {}
  if plot_type ~= nil then
    for key in pairs(plot_type.params) do
      plot_params[key] = coordinate_number(options[key], key)
    end
  end

  local size, margin = 460, 26
  local plot = size - 2 * margin
  local scale = math.min(plot / (x_max - x_min), plot / (y_max - y_min))
  local left = margin + (plot - (x_max - x_min) * scale) / 2
  local top = margin + (plot - (y_max - y_min) * scale) / 2
  local function px(x)
    return left + (x - x_min) * scale
  end
  local function py(y)
    return top + (y_max - y) * scale
  end
  local axis_x = px(math.max(x_min, math.min(x_max, 0)))
  local axis_y = py(math.max(y_min, math.min(y_max, 0)))
  local parts = {
    string.format('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">', size, size, size, size),
    '<g stroke="#d9d9d9" stroke-width="1">',
  }
  for index = math.ceil(x_min / raster), math.floor(x_max / raster) do
    table.insert(parts, string.format('<path d="M %.2f %g V %.2f"/>', px(index * raster), py(y_max), py(y_min)))
  end
  for index = math.ceil(y_min / raster), math.floor(y_max / raster) do
    table.insert(parts, string.format('<path d="M %.2f %g H %.2f"/>', px(x_min), py(index * raster), px(x_max)))
  end
  table.insert(parts, '</g><g stroke="#172033" stroke-width="2" fill="none" stroke-linejoin="round">')
  table.insert(parts, string.format('<path d="M %.2f %g H %.2f"/>', px(x_min), axis_y, px(x_max)))
  table.insert(parts, string.format('<path d="M %.2f %g V %.2f"/>', axis_x, py(y_min), py(y_max)))
  table.insert(parts, string.format('<path d="M %.2f %g l -10 -4 v 8 Z M %.2f %g l -4 10 h 8 Z" fill="#172033"/>', px(x_max), axis_y, axis_x, py(y_max)))
  table.insert(parts, '</g><g font-family="DejaVu Sans, sans-serif" font-size="14" fill="#172033">')
  local function number_label(value)
    if value == math.floor(value) then
      return string.format("%d", value)
    end
    return string.format("%g", value):gsub("%.", ",")
  end
  for index = math.ceil(x_min / label_step), math.floor(x_max / label_step) do
    local value = index * label_step
    if value ~= 0 then
      table.insert(parts, string.format('<text x="%.2f" y="%g" text-anchor="middle">%s</text>', px(value), axis_y + 18, number_label(value)))
    end
  end
  for index = math.ceil(y_min / label_step), math.floor(y_max / label_step) do
    local value = index * label_step
    if value ~= 0 then
      table.insert(parts, string.format('<text x="%.2f" y="%.2f" text-anchor="end">%s</text>', axis_x - 8, py(value) + 5, number_label(value)))
    end
  end
  table.insert(parts, string.format('<text x="%.2f" y="%g" text-anchor="end">0</text>', axis_x - 8, axis_y + 18))
  if plot_type ~= nil then
    local f = plot_type.evaluate(plot_params)
    local color = highlight_color(options.farbe, "Koordinatensystem")
    local steps = 240
    local segments, current = {}, {}
    for step = 0, steps do
      local x = x_min + (x_max - x_min) * step / steps
      local y = f(x)
      if y >= y_min and y <= y_max then
        table.insert(current, string.format("%.2f %.2f", px(x), py(y)))
      else
        if #current > 1 then
          table.insert(segments, table.concat(current, " L "))
        end
        current = {}
      end
    end
    if #current > 1 then
      table.insert(segments, table.concat(current, " L "))
    end
    for _, segment in ipairs(segments) do
      table.insert(parts, string.format('<path d="M %s" stroke="%s" stroke-width="3.5" fill="none"/>', segment, color))
    end
  end
  table.insert(parts, '</g></svg>')
  local svg = table.concat(parts, "\n")
  local filename = "koordinatensystem-" .. pandoc.utils.sha1(svg)
  if TARGET == "latex" then
    filename = filename .. ".pdf"
    pandoc.mediabag.insert(filename, "application/pdf", pandoc.pipe("rsvg-convert", { "--format=pdf" }, svg))
  else
    filename = filename .. ".svg"
    pandoc.mediabag.insert(filename, "image/svg+xml", svg)
  end
  local alt = plot_type ~= nil and "Koordinatensystem mit Graph" or "Leeres Koordinatensystem"
  return pandoc.Image({ pandoc.Str(alt) }, filename, "", pandoc.Attr("", {}, { width = "100%" }))
end

local function arithmetic_image(args)
  if args:match("^%s*bruchrechteck%s*|") then
    local directory = pandoc.path.directory(PANDOC_SCRIPT_FILE)
    return dofile(directory .. "/fraction-rectangle.lua")(args, TARGET)
  end
  if args:match("^%s*schriftlich%s*|") then
    local directory = pandoc.path.directory(PANDOC_SCRIPT_FILE)
    return dofile(directory .. "/written-multiplication.lua")(args)
  end
  local kind = args:match("^%s*([^|]+)")
  kind = kind and kind:match("^%s*(.-)%s*$")
  local schemas = {
    rechenstrich = { knoten = true, spruenge = true, farbe = true, farben = true, offen = true, kommentar = true },
    punktefeld = { zeilen = true, spalten = true },
    vierhundertfeld = { zeilen = true, spalten = true },
    malkreuz = { oben = true, links = true, felder = true, gruppen = true },
    stellenwerttafel = { ziffern = true, karten = true },
    ziffernraetsel = { aufgabe = true, ergebnis = true },
    rechteck = { laenge = true, breite = true, einheit = true },
    flaeche = { oben = true, links = true },
    hoehenprofil = { start = true, etappen = true, offen = true, summe = true, farbe = true },
  }
  if not schemas[kind] then
    error("Modell: Erwartet rechenstrich, punktefeld, vierhundertfeld, malkreuz, stellenwerttafel, ziffernraetsel, rechteck, flaeche oder hoehenprofil.")
  end
  local options = {}
  for field in args:gmatch("|([^|]+)") do
    local key, value = field:match("^%s*([%a]+)%s*=%s*(.-)%s*$")
    if not key or (not schemas[kind][key] and key ~= "bildbreite") then
      error("Modell: Unbekannte Option: " .. field)
    end
    options[key] = value
  end
  if options.bildbreite then
    local size = tonumber(options.bildbreite:match("^(%d+%.?%d*)mm$"))
    if not size or size < 10 or size > 250 then
      error("Modell: bildbreite muss zwischen 10mm und 250mm liegen.")
    end
  end
  local function entries(value)
    local result = {}
    for entry in ((value or "") .. ","):gmatch("(.-),") do
      table.insert(result, entry:match("^%s*(.-)%s*$"))
    end
    return result
  end
  local width = kind == "vierhundertfeld" and 220 or (kind == "rechteck" and 240 or ((kind == "malkreuz" or kind == "stellenwerttafel") and 320 or 460))
  local height = kind == "vierhundertfeld" and 220 or ((kind == "rechenstrich" or kind == "stellenwerttafel") and 95 or 180)
  if kind == "rechenstrich" and options.kommentar and options.kommentar ~= "" then
    height = height + 26
  end
  if kind == "stellenwerttafel" and options.karten then height = 140 end
  local puzzle_left, puzzle_right, puzzle_result, puzzle_columns
  if kind == "ziffernraetsel" then
    local task = (options.aufgabe or ""):gsub("%s+", ""):gsub("·", "*"):gsub("×", "*"):gsub("x", "*")
    puzzle_left, puzzle_right = task:match("^([%d_?]+)%*([%d_?]+)$")
    if not puzzle_left or #puzzle_left > 6 or #puzzle_right > 6 then
      error("Modell ziffernraetsel: aufgabe braucht zwei Faktoren mit je 1–6 Ziffern oder Lücken (_ oder ?), z. B. 3_1_*2.")
    end
    for _, factor in ipairs({puzzle_left, puzzle_right}) do
      if #factor > 1 and factor:sub(1, 1) == "0" then
        error("Modell ziffernraetsel: Mehrstellige Faktoren dürfen nicht mit 0 beginnen.")
      end
    end
    puzzle_result = options.ergebnis or ""
    if not puzzle_result:match("^%d+$") or #puzzle_result > 12 or (#puzzle_result > 1 and puzzle_result:sub(1, 1) == "0") then
      error("Modell ziffernraetsel: ergebnis muss 1–12 Ziffern ohne führende Nullen enthalten.")
    end
    puzzle_columns = math.max(#puzzle_left + 1 + #puzzle_right, #puzzle_result) + 2
    width, height = puzzle_columns * 28 + 12, 86
  end
  local parts = { string.format('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">', width, height, width, height) }
  local function line(first_x, first_y, last_x, last_y)
    table.insert(parts, string.format('<path d="M %g %g L %g %g" stroke="#172033" stroke-width="1.5" fill="none"/>', first_x, first_y, last_x, last_y))
  end
  local function label(position_x, position_y, value, on_line, fill_color, font_size)
    local escaped = value:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;"):gsub('"', "&quot;")
    local halo = on_line and ' paint-order="stroke" stroke="white" stroke-width="5" stroke-linejoin="round"' or ""
    table.insert(parts, string.format('<text x="%g" y="%g" text-anchor="middle" font-family="DejaVu Sans, sans-serif" font-size="%g" fill="%s"%s>%s</text>', position_x, position_y, font_size or 16, fill_color or "#172033", halo, escaped))
  end
  if kind == "ziffernraetsel" then
    local cell, margin = 28, 6
    local function puzzle_text(column, y, value, color)
      table.insert(parts, string.format('<text x="%g" y="%g" text-anchor="middle" font-family="DejaVu Sans Mono, monospace" font-size="20" fill="%s">%s</text>', margin + (column + 0.5) * cell, y, color, value))
    end
    -- Both factors share the units column with the given product below.
    local start = puzzle_columns - 1 - (#puzzle_left + 1 + #puzzle_right)
    local function digit_cell(column, value)
      local x = margin + column * cell
      table.insert(parts, string.format('<rect class="ziffernkarte" x="%g" y="4" width="24" height="38" fill="white" stroke="#aab6c1" stroke-width="1.2"/>', x + 2))
      table.insert(parts, string.format('<path class="kartenlinie" d="M %g 37 H %g" stroke="#8393a1" stroke-width="1"/>', x + 7, x + 21))
      if value:match("%d") then
        puzzle_text(column, 29, value, "#263747")
      end
    end
    for i = 1, #puzzle_left do digit_cell(start + i - 1, puzzle_left:sub(i, i)) end
    local operator_column = start + #puzzle_left
    puzzle_text(operator_column, 29, "·", "#263747")
    for i = 1, #puzzle_right do digit_cell(operator_column + i, puzzle_right:sub(i, i)) end
    -- One equation: writable factors above, aligned product below the rule.
    local rule_start = math.min(start, puzzle_columns - 1 - #puzzle_result)
    table.insert(parts, string.format('<path class="ergebnislinie" d="M %g 49 H %g" stroke="#35516c" stroke-width="1.5"/>', margin + rule_start * cell, margin + (puzzle_columns - 1) * cell))
    local result_start = puzzle_columns - 1 - #puzzle_result
    for i = 1, #puzzle_result do puzzle_text(result_start + i - 1, 76, puzzle_result:sub(i, i), "#617589") end
  elseif kind == "rechenstrich" then
    local nodes = entries(options.knoten)
    -- Fehlendes spruenge (bei offen=ja erlaubt) darf keinen leeren Eintrag ergeben.
    local jumps = options.spruenge and entries(options.spruenge) or {}
    -- offen=ja zeichnet nur Strich und Knoten: Die Sprünge ergänzt man selbst.
    local open_steps = options.offen == "ja"
    if #nodes < 2 or #nodes > 6 then
      error("Modell rechenstrich: 2–6 knoten nötig.")
    end
    if #jumps ~= #nodes - 1 and not (open_steps and #jumps == 0) then
      error("Modell rechenstrich: Je ein spruenge-Eintrag zwischen benachbarten Knoten nötig (bei offen=ja darf spruenge fehlen).")
    end
    -- Sprungfarbe nach Richtung: Sprünge nach rechts (Plus) sind rot,
    -- Sprünge nach links (Minus) blau. farbe färbt alle Sprünge um; farben
    -- färbt einzelne Sprünge um (ein Eintrag je spruenge-Eintrag, leer
    -- lässt die Standardfarbe).
    local override = options.farbe
    if override == "" then override = nil end
    if override then override = highlight_color(override, "Modell rechenstrich") end
    local jump_overrides = {}
    if options.farben then
      local raw = entries(options.farben)
      if #raw ~= #jumps then
        error("Modell rechenstrich: farben braucht genau einen Eintrag je spruenge-Eintrag (leer lässt die Standardfarbe).")
      end
      for index, value in ipairs(raw) do
        if value ~= "" then jump_overrides[index] = highlight_color(value, "Modell rechenstrich") end
      end
    end
    local function jump_ink(rightward, index)
      if jump_overrides[index] then return jump_overrides[index] end
      if override then return override end
      return rightward and RED or BLUE
    end
    line(20, 60, 445, 60)
    table.insert(parts, '<path d="M 445 60 l -15 -6 v 12 Z" fill="#172033"/>')
    -- Die Sprungrichtung folgt dem Vorzeichen: Plus springt nach rechts,
    -- Minus nach links. Die Knoten werden deshalb nach (geschätztem) Wert
    -- auf dem Strich angeordnet; unbekannte Knoten entstehen aus dem
    -- vorherigen Wert plus Sprung.
    local negative, positive = false, false
    for _, jump in ipairs(jumps) do
      if jump:find("%-") then
        negative = true
      elseif jump:find("%+") then
        positive = true
      end
    end
    local fallback_step = negative and not positive and -1 or 1
    local function jump_step(jump)
      local number = tonumber(jump)
      if number then return number end
      if jump:find("%-") then return -1 end
      if jump:find("%+") then return 1 end
      return fallback_step
    end
    local estimates = {}
    for index = 1, #nodes do estimates[index] = tonumber(nodes[index]) end
    if #jumps == #nodes - 1 then
      for index = 1, #nodes - 1 do
        if estimates[index] and not estimates[index + 1] then
          estimates[index + 1] = estimates[index] + jump_step(jumps[index])
        end
      end
      for index = #nodes - 1, 1, -1 do
        if estimates[index + 1] and not estimates[index] then
          estimates[index] = estimates[index + 1] - jump_step(jumps[index])
        end
      end
      for index = 1, #nodes - 1 do
        local first, second = tonumber(nodes[index]), tonumber(nodes[index + 1])
        if first and second then
          if (jumps[index]:find("%+") and second <= first) or (jumps[index]:find("%-") and second >= first) then
            error("Modell rechenstrich: Der Sprung " .. jumps[index] .. " passt nicht zu den Knoten " .. nodes[index] .. " und " .. nodes[index + 1] .. ": Bei + zeigt der Sprung nach rechts, bei − nach links.")
          end
        end
      end
    end
    local positions = {}
    local ranked = true
    for index = 1, #nodes do
      if not estimates[index] then ranked = false end
    end
    if ranked then
      local order = {}
      for index = 1, #nodes do order[index] = index end
      table.sort(order, function(first, second)
        if estimates[first] ~= estimates[second] then
          return estimates[first] < estimates[second]
        end
        return first < second
      end)
      for rank, index in ipairs(order) do
        positions[index] = 45 + (rank - 1) * 365 / (#nodes - 1)
      end
    else
      local direction = fallback_step < 0 and -1 or 1
      local start = fallback_step < 0 and 410 or 45
      for index = 1, #nodes do
        positions[index] = start + direction * (index - 1) * 365 / (#nodes - 1)
      end
    end
    -- Bogenhöhe: Überlappen sich Sprünge (gemischte Richtungen, ineinander
    -- liegende Bögen), wächst die Höhe mit der Sprungweite – weite Sprünge
    -- wölben sich über flache, sodass sich die Bögen nicht schneiden. Ohne
    -- Überlappung behalten alle Sprünge die gewohnte Höhe.
    local overlapping = false
    for first = 1, #nodes - 2 do
      for second = first + 1, #nodes - 1 do
        local lo_first = math.min(positions[first], positions[first + 1])
        local hi_first = math.max(positions[first], positions[first + 1])
        local lo_second = math.min(positions[second], positions[second + 1])
        local hi_second = math.max(positions[second], positions[second + 1])
        if math.max(lo_first, lo_second) + 0.5 < math.min(hi_first, hi_second) then
          overlapping = true
        end
      end
    end
    local function arc_height(span)
      if not overlapping then return 28 end
      return math.min(31, math.max(8, span / 11 - 3))
    end
    for index, value in ipairs(nodes) do
      local position = positions[index]
      line(position, 55, position, 65)
      label(position, 86, value)
      if not open_steps and index < #nodes then
        local endpoint = positions[index + 1]
        local ink = jump_ink(endpoint > position, index)
        local height = arc_height(math.abs(endpoint - position))
        local control_y = 2 * (51 - height) - 51
        table.insert(parts, string.format('<path d="M %g 51 Q %g %g %g 51" stroke="%s" stroke-width="1.5" fill="none"/>', position, (position + endpoint) / 2, control_y, endpoint, ink))
        -- Gefüllte Pfeilspitze in Bogenrichtung; die Barben waren vorher asymmetrisch
        local tangent = { (endpoint - position) / 2, 51 - control_y }
        local tangent_length = math.sqrt(tangent[1] * tangent[1] + tangent[2] * tangent[2])
        local tx, ty = tangent[1] / tangent_length, tangent[2] / tangent_length
        table.insert(parts, string.format('<path d="M %g 51 l %g %g l %g %g Z" fill="%s"/>',
          endpoint, -13 * tx - 5 * ty, -13 * ty + 5 * tx, 10 * ty, -10 * tx, ink))
        table.insert(parts, string.format('<circle cx="%g" cy="51" r="2.5" fill="%s"/>', position, ink))
        local jump_label = jumps[index]:gsub("[?_]+", "□")
        if jump_label == "+" or jump_label == "-" or jump_label == "" then
          jump_label = jump_label .. "□"
        end
        jump_label = jump_label:gsub("([+%-])%s*□", "%1 □")
        -- Halo: Beschriftungen bleiben lesbar, auch wenn ein Bogen durchläuft
        label((position + endpoint) / 2, 47 - height, jump_label, true, ink)
      end
    end
    if options.kommentar and options.kommentar ~= "" then
      label(width / 2, 95 + 20, options.kommentar, false, "#172033", 14)
    end
  elseif kind == "stellenwerttafel" then
    local digits = options.ziffern and entries(options.ziffern) or {"", "", "", "", "", ""}
    if #digits ~= 6 then
      error("Modell stellenwerttafel: Erwartet sechs Ziffern für HT, ZT, T, H, Z und E.")
    end
    local positions = {"HT", "ZT", "T", "H", "Z", "E"}
    local offset = 0
    if options.karten then
      local cards = entries(options.karten)
      if #cards ~= 6 then
        error("Modell stellenwerttafel: Erwartet sechs Ziffernkarten.")
      end
      for index, card in ipairs(cards) do
        if not card:match("^%d$") then
          error("Modell stellenwerttafel: Jede Ziffernkarte muss eine einzelne Ziffer sein.")
        end
        local horizontal = 35 + (index - 1) * 50
        table.insert(parts, string.format('<rect x="%g" y="5" width="34" height="30" rx="3" stroke="#172033" fill="#f2f4f7"/>', horizontal - 17))
        label(horizontal, 27, card)
      end
      offset = 45
    end
    for index, digit in ipairs(digits) do
      if digit ~= "" and digit ~= "_" and not digit:match("^%d$") then
        error("Modell stellenwerttafel: Nur einzelne Ziffern und _ für leere Felder sind erlaubt.")
      end
      local horizontal = 35 + (index - 1) * 50
      label(horizontal, 36 + offset, positions[index])
      if digit ~= "_" and digit ~= "" then label(horizontal, 73 + offset, digit) end
    end
    for index = 0, 6 do line(10 + index * 50, 10 + offset, 10 + index * 50, 85 + offset) end
    for _, position in ipairs({10, 47.5, 85}) do line(10, position + offset, 310, position + offset) end
  elseif kind == "malkreuz" then
    -- Ohne oben/links bleibt das Malkreuz leer zum Selbst-Eintragen. Mit
    -- oben/links (je eine bis drei ganze Zahlen) werden Zerlegung und
    -- Teilprodukte eingetragen, jedes Teilprodukt in eigener Farbe. Ein
    -- unzerlegter Faktor (eine Zahl) zeigt eine Zerlegung mit nur zwei
    -- Teilprodukten – so wird sichtbar, dass sich das Ganze unterschiedlich
    -- in Teilprodukte zerlegen lässt.
    local function sides(value, name)
      local segments = entries(value)
      if #segments < 1 or #segments > 3 then
        error("Modell malkreuz: " .. name .. " benötigt eine bis drei Zahlen.")
      end
      local numbers = {}
      for _, segment in ipairs(segments) do
        local number = tonumber(segment)
        if not number or number <= 0 or number > 10000 or number % 1 ~= 0 then
          error("Modell malkreuz: " .. name .. " muss aus ganzen Zahlen von 1 bis 10000 bestehen.")
        end
        table.insert(numbers, number)
      end
      return numbers
    end
    local given_fields
    if options.felder then
      if options.oben or options.links then
        error("Modell malkreuz: felder kann nicht mit oben/links kombiniert werden.")
      end
      given_fields = entries(options.felder)
      if #given_fields ~= 8 then
        error("Modell malkreuz: felder benötigt acht Einträge zeilenweise ohne das Malzeichen; ? lässt ein Feld leer.")
      end
      for index, value in ipairs(given_fields) do
        if value ~= "?" then
          local number = tonumber(value)
          local limit = (index == 1 or index == 2 or index == 3 or index == 6) and 10000 or 100000000
          if not number or number <= 0 or number > limit or number % 1 ~= 0 then
            error("Modell malkreuz: felder erwartet positive ganze Zahlen innerhalb der Stellenwertgrenzen oder ?.")
          end
        end
      end
    end
    local top, left
    if options.oben or options.links then
      if not (options.oben and options.links) then
        error("Modell malkreuz: oben und links müssen gemeinsam angegeben werden.")
      end
      top, left = sides(options.oben, "oben"), sides(options.links, "links")
      if #top == 1 and #left == 1 then
        error("Modell malkreuz: Mindestens ein Faktor muss in zwei Teile zerlegt werden.")
      end
    end
    local palette = {
      { fill = "#fdecea", text = "#c62828" },
      { fill = "#e8f0fb", text = "#1565c0" },
      { fill = "#e6f4ea", text = "#2e7d32" },
      { fill = "#fff8c4", text = "#8a6d00" },
    }
    local grouping = options.gruppen or "felder"
    if grouping ~= "felder" and grouping ~= "zeilen" then
      error("Modell malkreuz: gruppen muss felder oder zeilen sein.")
    end
    local function cell_color(index)
      local group = grouping == "zeilen" and math.ceil(index / (top and #top or 2)) or index
      return palette[(group - 1) % #palette + 1]
    end
    local cells = {}
    if top then
      local column_bounds, row_bounds = {}, {}
      for i=1,#top do column_bounds[i] = {80+(i-1)*220/#top,80+i*220/#top} end
      for i=1,#left do row_bounds[i] = {65+(i-1)*100/#left,65+i*100/#left} end
      for row, row_bound in ipairs(row_bounds) do
        for column, column_bound in ipairs(column_bounds) do
          table.insert(cells, { column_bound[1], row_bound[1], column_bound[2], row_bound[2], top[column] * left[row] })
        end
      end
    end
    for index, cell in ipairs(cells) do
      table.insert(parts, string.format('<rect x="%g" y="%g" width="%g" height="%g" fill="%s"/>', cell[1] + 1.5, cell[2] + 1.5, cell[3] - cell[1] - 3, cell[4] - cell[2] - 3, cell_color(index).fill))
    end
    for _, position in ipairs({ 20, 80, 300 }) do line(position, 15, position, 165) end
    for i=1,(top and #top or 2)-1 do local x=80+i*220/(top and #top or 2); line(x,15,x,165) end
    for _, position in ipairs({ 15, 65, 165 }) do line(20, position, 300, position) end
    for i=1,(left and #left or 2)-1 do local y=65+i*100/(left and #left or 2); line(20,y,300,y) end
    label(50, 48, "×")
    if given_fields then
      local positions = { {135, 45}, {245, 45}, {50, 95}, {135, 95}, {245, 95}, {50, 145}, {135, 145}, {245, 145} }
      for index, value in ipairs(given_fields) do
        if value ~= "?" then
          label(positions[index][1], positions[index][2], value)
        end
      end
    elseif top then
      for i,value in ipairs(top) do label(80+(i-0.5)*220/#top,45,tostring(value)) end
      for i,value in ipairs(left) do label(50,65+(i-0.5)*100/#left+5,tostring(value)) end
      for index, cell in ipairs(cells) do
        label((cell[1] + cell[3]) / 2, (cell[2] + cell[4]) / 2 + 5, tostring(cell[5]), false, cell_color(index).text, math.min(16, (cell[3] - cell[1] - 10) / (#tostring(cell[5]) * 0.65)))
      end
    end
  elseif kind == "rechteck" then
    local function dimensions(value)
      local segments = entries(value)
      local total = 0
      if #segments > 2 then
        error("Modell rechteck: Je Seite sind eine Länge oder zwei Teilstrecken erlaubt.")
      end
      for _, segment in ipairs(segments) do
        local number = tonumber(segment)
        if not number or number <= 0 then
          error("Modell rechteck: laenge und breite müssen positive Zahlen bis 10000 sein.")
        end
        total = total + number
      end
      if total > 10000 then
        error("Modell rechteck: Die gesamte Seitenlänge darf höchstens 10000 betragen.")
      end
      return segments, total
    end
    local horizontal, length = dimensions(options.laenge)
    local vertical, breadth = dimensions(options.breite)
    local scale = math.min(180 / length, 120 / breadth)
    local right, bottom = 45 + length * scale, 40 + breadth * scale
    for _, position in ipairs({45, right}) do line(position, 40, position, bottom) end
    for _, position in ipairs({40, bottom}) do line(45, position, right, position) end
    if #horizontal == 2 then
      local split = 45 + tonumber(horizontal[1]) * scale
      line(split, 40, split, bottom)
    end
    if #vertical == 2 then
      local split = 40 + tonumber(vertical[1]) * scale
      line(45, split, right, split)
    end
    local unit = options.einheit and (" " .. options.einheit) or ""
    local position = 45
    line(position, 21, position, 29)
    for _, segment in ipairs(horizontal) do
      local endpoint = position + tonumber(segment) * scale
      line(position, 25, endpoint, 25)
      line(endpoint, 21, endpoint, 29)
      label((position + endpoint) / 2, 17, segment .. unit)
      position = endpoint
    end
    position = 40
    line(26, position, 34, position)
    for _, segment in ipairs(vertical) do
      local endpoint = position + tonumber(segment) * scale
      line(30, position, 30, endpoint)
      line(26, endpoint, 34, endpoint)
      local middle = (position + endpoint) / 2
      table.insert(parts, string.format('<g transform="rotate(-90 17 %g)">', middle))
      label(17, middle, segment .. unit)
      table.insert(parts, '</g>')
      position = endpoint
    end
  elseif kind == "vierhundertfeld" then
    -- Ohne zeilen/spalten bleibt das Feld unmarkiert, damit Lernende eigene
    -- Rechtecke einzeichnen. Mit zeilen/spalten wird das Produkt-Rechteck
    -- oben links an der Zehnerstelle in vier Teilrechtecke zerlegt – in den
    -- Malkreuz-Farben. Die Rechtecke entstehen vor den Punkten, damit die
    -- Punkte auf den Füllflächen sichtbar bleiben.
    local rows, columns = tonumber(options.zeilen), tonumber(options.spalten)
    if options.zeilen or options.spalten then
      if not rows or not columns or rows < 1 or rows > 20 or columns < 1 or columns > 20 or rows % 1 ~= 0 or columns % 1 ~= 0 then
        error("Modell vierhundertfeld: zeilen und spalten müssen ganze Zahlen von 1 bis 20 sein.")
      end
      local right = 18 + (columns - 1) * 9 + (columns > 10 and 12 or 0)
      local bottom = 18 + (rows - 1) * 9 + (rows > 10 and 12 or 0)
      -- Die Lücke zwischen der 10. und 11. Zeile/Spalte (Punkte bei 99 und
      -- 120) ist der natürliche Schnittpunkt der Zerlegung.
      local split = (99 + 120) / 2
      local palette = {
        { fill = "#fdecea", stroke = "#c62828" },
        { fill = "#e8f0fb", stroke = "#1565c0" },
        { fill = "#e6f4ea", stroke = "#2e7d32" },
        { fill = "#fff8c4", stroke = "#8a6d00" },
      }
      -- Zeilen entsprechen dem ersten Faktor (Malkreuz: oben), Spalten dem
      -- zweiten (Malkreuz: links). Zehner mal Zehner ist rot, Einer mal
      -- Zehner blau, Zehner mal Einer grün, Einer mal Einer gelb – jede
      -- Farbe passt zur gleichfarbigen Zelle im Malkreuz. Teile, die über
      -- die Zehnerstelle hinausreichen, entfallen bei kleinen Faktoren.
      local regions = {
        { 13, 13, columns > 10 and split or right + 5, rows > 10 and split or bottom + 5, 1 },
      }
      if rows > 10 then
        table.insert(regions, { 13, split, columns > 10 and split or right + 5, bottom + 5, 2 })
      end
      if columns > 10 then
        table.insert(regions, { split, 13, right + 5, rows > 10 and split or bottom + 5, 3 })
      end
      if rows > 10 and columns > 10 then
        table.insert(regions, { split, split, right + 5, bottom + 5, 4 })
      end
      for _, region in ipairs(regions) do
        table.insert(parts, string.format('<rect x="%g" y="%g" width="%g" height="%g" fill="%s" stroke="%s" stroke-width="2"/>', region[1], region[2], region[3] - region[1], region[4] - region[2], palette[region[5]].fill, palette[region[5]].stroke))
      end
    end
    local colors = { "#555555", "#888888", "#aaaaaa", "#cccccc" }
    for row = 1, 20 do
      for column = 1, 20 do
        local quadrant = (row > 10 and 2 or 0) + (column > 10 and 1 or 0) + 1
        local horizontal = 18 + (column - 1) * 9 + (column > 10 and 12 or 0)
        local vertical = 18 + (row - 1) * 9 + (row > 10 and 12 or 0)
        table.insert(parts, string.format('<circle cx="%g" cy="%g" r="2" fill="%s"/>', horizontal, vertical, colors[quadrant]))
      end
    end
  elseif kind == "punktefeld" then
    local rows, columns = tonumber(options.zeilen), tonumber(options.spalten)
    if not rows or not columns or rows < 1 or columns < 1 or rows > 12 or columns > 20 or rows % 1 ~= 0 or columns % 1 ~= 0 then
      error("Modell punktefeld: zeilen 1–12 und spalten 1–20 müssen ganze Zahlen sein.")
    end
    local spacing = math.min(24, 380 / columns, 140 / rows)
    for row = 1, rows do
      for column = 1, columns do
        table.insert(parts, string.format('<circle cx="%g" cy="%g" r="3" fill="#172033"/>', 230 + (column - (columns + 1) / 2) * spacing, 90 + (row - (rows + 1) / 2) * spacing))
      end
    end
  elseif kind == "hoehenprofil" then
    local sum_color = highlight_color(options.farbe, "Modell hoehenprofil", "#172033")
    local start_height = tonumber(options.start)
    if not start_height or start_height <= 0 or start_height > 10000 then
      error("Modell hoehenprofil: start muss eine positive Zahl bis 10000 sein.")
    end
    local stages = entries(options.etappen)
    if #stages < 1 or #stages > 5 then
      error("Modell hoehenprofil: 1–5 etappen nötig.")
    end
    local heights = { start_height }
    for index, stage in ipairs(stages) do
      local sign, amount = stage:match("^%s*([%+%-])%s*(%d+)%s*m?%s*$")
      if not sign then
        error("Modell hoehenprofil: Jede Etappe braucht Vorzeichen und Zahl, optional mit Einheit m, z. B. -380 oder +20 m.")
      end
      local height = heights[index] + (sign == "-" and -1 or 1) * tonumber(amount)
      if height < 0 then
        error("Modell hoehenprofil: Zwischenhöhen dürfen nicht negativ werden.")
      end
      table.insert(heights, height)
    end
    local lowest, highest = heights[1], heights[1]
    for _, height in ipairs(heights) do
      lowest = math.min(lowest, height)
      highest = math.max(highest, height)
    end
    local function node_x(index)
      return 50 + (index - 1) * 360 / (#heights - 1)
    end
    local function node_y(height)
      if highest == lowest then return 110 end
      return 70 + (highest - height) * 80 / (highest - lowest)
    end
    local profile = { string.format("M %g %g", node_x(1), node_y(heights[1])) }
    for index = 2, #heights do
      table.insert(profile, string.format("L %g %g", node_x(index), node_y(heights[index])))
    end
    table.insert(parts, string.format('<path d="%s" stroke="#172033" stroke-width="1.5" fill="none"/>', table.concat(profile, " ")))
    for index, height in ipairs(heights) do
      local x, y = node_x(index), node_y(height)
      table.insert(parts, string.format('<circle cx="%g" cy="%g" r="3" fill="#172033"/>', x, y))
      label(x, y - 12, (options.offen and index > 1) and "?" or tostring(height))
    end
    for index, stage in ipairs(stages) do
      local x1, y1 = node_x(index), node_y(heights[index])
      local x2, y2 = node_x(index + 1), node_y(heights[index + 1])
      label((x1 + x2) / 2, (y1 + y2) / 2 + 5, stage, true)
    end
    if options.summe then
      local first_x, last_x = node_x(1), node_x(#heights)
      local first_y, last_y = node_y(heights[1]), node_y(heights[#heights])
      local apex_x, apex_y = (first_x + last_x) / 2, math.min(first_y, last_y) - 30
      table.insert(parts, string.format('<path d="M %g %g Q %g %g %g %g" stroke="%s" stroke-width="1.5" fill="none"/>', first_x, first_y, apex_x, apex_y, last_x, last_y, sum_color))
      local tangent = { last_x - apex_x, last_y - apex_y }
      local tangent_length = math.sqrt(tangent[1] * tangent[1] + tangent[2] * tangent[2])
      local tx, ty = tangent[1] / tangent_length, tangent[2] / tangent_length
      table.insert(parts, string.format('<path d="M %g %g l %g %g l %g %g Z" fill="%s"/>', last_x, last_y, -13 * tx - 5 * ty, -13 * ty + 5 * tx, 10 * ty, -10 * tx, sum_color))
      label(apex_x, apex_y - 6, options.summe, false, sum_color)
    end
  else
    local top, left = entries(options.oben), entries(options.links)
    local widths, heights = {}, {}
    for _, pair in ipairs({ { top, widths }, { left, heights } }) do
      if #pair[1] < 1 or #pair[1] > 2 then
        error("Modell flaeche: oben und links benötigen je eine oder zwei positive Zahlen.")
      end
      for index, value in ipairs(pair[1]) do
        local number = tonumber(value)
        if not number or number <= 0 or number > 10000 then
          error("Modell flaeche: Seitenabschnitte müssen positive Zahlen bis 10000 sein.")
        end
        pair[2][index] = number
      end
    end
    local x_positions, y_positions = { 65 }, { 35 }
    if #widths == 2 then
      table.insert(x_positions, 65 + 365 * widths[1] / (widths[1] + widths[2]))
    end
    if #heights == 2 then
      table.insert(y_positions, 35 + 130 * heights[1] / (heights[1] + heights[2]))
    end
    table.insert(x_positions, 430)
    table.insert(y_positions, 165)
    for _, position in ipairs(x_positions) do line(position, 35, position, 165) end
    for _, position in ipairs(y_positions) do line(65, position, 430, position) end
    for _, position in ipairs(x_positions) do line(position, 21, position, 29) end
    line(65, 25, 430, 25)
    for index, value in ipairs(top) do
      label((x_positions[index] + x_positions[index + 1]) / 2, 17, value)
    end
    for _, position in ipairs(y_positions) do line(26, position, 34, position) end
    line(30, 35, 30, 165)
    for index, value in ipairs(left) do
      local middle = (y_positions[index] + y_positions[index + 1]) / 2
      table.insert(parts, string.format('<g transform="rotate(-90 17 %g)">', middle))
      label(17, middle, value)
      table.insert(parts, '</g>')
    end
  end
  table.insert(parts, "</svg>")
  local svg = table.concat(parts, "\n")
  if kind == "stellenwerttafel" then
    svg = svg:gsub('font%-size="16"', 'font-size="20"')
  end
  local filename = "modell-" .. pandoc.utils.sha1(svg)
  if TARGET == "latex" then
    filename = filename .. ".pdf"
    pandoc.mediabag.insert(filename, "application/pdf", pandoc.pipe("rsvg-convert", { "--format=pdf" }, svg))
  else
    filename = filename .. ".svg"
    pandoc.mediabag.insert(filename, "image/svg+xml", svg)
  end
  return pandoc.Image({ pandoc.Str("Modell: " .. kind .. " – " .. args) }, filename, "", pandoc.Attr("", {}, { width = options.bildbreite or "75%" }))
end

local function command_name(command)
  local names = {
    answer_grid = "answergrid",
    code_hinweis = "codehinweis",
    columns_two = "columnstwo",
    cover_header = "coverheader",
    foerderplan_kopf = "foerderplankopf",
    grading_fields = "gradingfields",
    input_table = "inputtable",
    notenspiegel_table = "notenspiegeltable",
    proof_table = "prooftable",
    student_fields = "studentfields",
    title_page = "mathedeckblatt",
    wahr_falsch_layout = "wahrfalschlayout",
  }
  if names[command] ~= nil then
    return names[command]
  end
  return command:gsub("_", "")
end

local function raw(value)
  return pandoc.RawBlock(TARGET, value)
end

local function raw_inline(value)
  return pandoc.RawInline(TARGET, value)
end

local function macro_call(command, args)
  if TARGET == "latex" then
    return "\\" .. command_name(command) .. args
  end
  return "#" .. command .. "(" .. args .. ")"
end

local function begin_call(command, args)
  if TARGET == "latex" then
    return "\\begin{" .. command_name(command) .. "}" .. args
  end
  return "#" .. command .. "(" .. args .. ")["
end

local function close_call(command)
  if TARGET == "latex" then
    return "\\end{" .. command_name(command) .. "}"
  end
  return "]"
end

local function call_args(values)
  if TARGET == "latex" then
    return table.concat(values, "")
  end
  return table.concat(values, ", ")
end

local function wrap_block(command, args, content)
  local blocks
  if TARGET == "latex" then
    blocks = { raw("\\begin{" .. command_name(command) .. "}" .. args) }
  else
    blocks = { raw("#" .. command .. "(" .. args .. ")[") }
  end
  for _, block in ipairs(content) do
    table.insert(blocks, block)
  end
  if TARGET == "latex" then
    table.insert(blocks, raw("\\end{" .. command_name(command) .. "}"))
  else
    table.insert(blocks, raw("]"))
  end
  return blocks
end

local function stringify(block)
  return pandoc.utils.stringify(block):gsub("^%s+", ""):gsub("%s+$", "")
end

local BLOCK_MARKER_PREFIXES = {
  "[abstand", "[Abstand",
  "[Antwortkasten", "[Bewertungsfelder", "[Beweistabelle", "[/Beweistabelle]",
  "[Code-Hinweis]", "[/Code-Hinweis]", "[Deckblatt",
  "[Eingabetabelle", "[/Eingabetabelle]",
  "[Erwartungshorizont", "[/Erwartungshorizont]",
  "[Förderbereich", "[/Förderbereich]", "[Förderplan-Kopf", "[Fortsetzung",
  "[Hinweise]", "[/Hinweise]", "[Infobox", "[/Infobox]",
  "[Karten", "[/Karten]",
  "[Lösung:", "[Loesung:", "[/Lösung]", "[/Loesung]",
  "[Mathe-Deckblatt", "[/Mathe-Deckblatt]", "[Mini-AB]", "[/Mini-AB]",
  "[Notenspiegel]", "[Notentabelle]", "[Referenz]", "[/Referenz]",
  "[Rechengitter", "[Schreiblinien", "[Schuelerfelder", "[Schülerfelder",
  "[Seitenumbruch]", "[Tippbox", "[/Tippbox]", "[Unterschriften]",
  "[Version]", "[Versionen]", "[/Versionen]",
  "[Wahr-Falsch-Layout]", "[/Wahr-Falsch-Layout]", "[Warnbox", "[/Warnbox]",
}

local function marker_text(block)
  if block.t ~= "Para" then
    return nil
  end
  local text = stringify(block):gsub("(%[/?)[Ee]ingabetabelle", "%1Eingabetabelle")
  -- Ein echter Marker-Absatz enthaelt genau ein Klammerpaar; verschmolzene
  -- Marker wie "[abstand 1cm]\n[Eingabetabelle 1cm]" enthalten "] [" und
  -- werden darueber als Text mit Marker erkannt (siehe block_marker_in_text).
  if text:match("^%[[^%[%]]*%]$") then
    return text
  end
  return nil
end

local function block_marker_in_text(block)
  if block.t ~= "Para" then
    return nil
  end
  local text = stringify(block):gsub("(%[/?)[Ee]ingabetabelle", "%1Eingabetabelle")
  for _, prefix in ipairs(BLOCK_MARKER_PREFIXES) do
    if text:find(prefix, 1, true) then
      return prefix
    end
  end
  return nil
end

local function split_marker_args(value)
  local parts = {}
  for part in (value .. "|"):gmatch("(.-)%|") do
    local cleaned = part:gsub("^%s+", ""):gsub("%s+$", "")
    table.insert(parts, cleaned)
  end
  return parts
end

local function parse_karten_marker(inner)
  local parts = split_marker_args(inner)
  local titel = nil
  local spalten = 3
  for index, part in ipairs(parts) do
    if index == 1 and part ~= "" and not part:match("^[%w_]+%s*=") then
      titel = part
    else
      local name, value = part:match("^([%w_]+)%s*=%s*(.+)$")
      if part == "" then
        -- leerer Teil vor der ersten Option: [Karten | spalten=4]
      elseif name == nil then
        error("Karten: Unbekannte Angabe \"" .. part .. "\" – nur Titel und Optionen wie spalten=3 sind zulässig.")
      elseif name == "spalten" then
        local count = tonumber(value)
        if count == nil or count ~= math.floor(count) or count < 1 or count > 6 then
          error("Karten: spalten muss eine ganze Zahl zwischen 1 und 6 sein, z. B. [Karten: Paare gesucht | spalten=3].")
        end
        spalten = count
      else
        error("Karten: Unbekannte Option " .. name .. " – nur spalten= ist zulässig.")
      end
    end
  end
  return titel, spalten
end

local function parse_karten_item(item)
  local inlines = {}
  for _, part in ipairs(item) do
    if part.t ~= "Plain" and part.t ~= "Para" then
      error("Karten: Jede Karte darf nur Text und Formeln enthalten, z. B. \"- A: $a^2 \\cdot a^3$\".")
    end
    for _, inline in ipairs(part.content) do
      table.insert(inlines, inline)
    end
  end
  local label = nil
  if #inlines >= 1 and inlines[1].t == "Str" then
    local candidate = inlines[1].text:match("^([^:%s]+):$")
    if candidate ~= nil and #candidate <= 4 then
      label = candidate
      local rest = {}
      local start = 2
      if inlines[2] ~= nil and inlines[2].t == "Space" then
        start = 3
      end
      for position = start, #inlines do
        table.insert(rest, inlines[position])
      end
      inlines = rest
    end
  end
  return label, inlines
end

local function karten_raw(list, spalten)
  local cells = {}
  for _, item in ipairs(list.content) do
    local label, inlines = parse_karten_item(item)
    if #inlines == 0 then
      error("Karten: Jede Karte braucht einen Inhalt, z. B. \"- A: $a^2 \\cdot a^3$\".")
    end
    if TARGET == "latex" then
      local body = pandoc.write(pandoc.Pandoc({ pandoc.Plain(inlines) }), "latex")
        :gsub("^%s+", ""):gsub("%s+$", "")
      table.insert(cells, "\\kartezelle{" .. latex_string(label or "") .. "}{" .. body .. "}")
    else
      local body = pandoc.write(pandoc.Pandoc({ pandoc.Plain(inlines) }), "typst")
        :gsub("^%s+", ""):gsub("%s+$", "")
      table.insert(cells, "karte(" .. (label ~= nil and typst_string(label) or "none") .. ", [" .. body .. "])")
    end
  end
  if TARGET == "latex" then
    local rows = {}
    for position, cell in ipairs(cells) do
      local row = math.floor((position - 1) / spalten) + 1
      rows[row] = (rows[row] ~= nil and rows[row] .. " & " or "") .. cell
    end
    local lines = {}
    for row_index, row in ipairs(rows) do
      if row_index < #rows then
        table.insert(lines, row .. " \\\\")
      else
        table.insert(lines, row)
      end
    end
    -- tabularx kann nicht in ein eigenes Environment gewickelt werden,
    -- weil es im Quelltext nach \end{tabularx} sucht; der Aufruf steht deshalb direkt hier.
    return raw("\\noindent\\setlength{\\tabcolsep}{2mm}\\renewcommand{\\arraystretch}{1.45}%\n"
      .. "\\begin{tabularx}{\\linewidth}{@{}*{" .. spalten .. "}{X}@{}}%\n"
      .. table.concat(lines, "\n") .. "\n\\end{tabularx}\\par\\vspace{0.35em}")
  end
  return raw("#kartengrid(" .. spalten .. ",\n" .. table.concat(cells, ",\n") .. ",)")
end

local function normalize_grid_cell_size(value, rows, old_height_syntax)
  value = (value or "0.5"):gsub(",", "."):gsub("^%s+", ""):gsub("%s+$", "")

  if old_height_syntax then
    local height_cm = value:match("^([%d%.]+)%s*cm$")
    local row_count = tonumber(rows)
    if height_cm ~= nil and row_count ~= nil and row_count > 0 then
      return string.format("%.4gcm", tonumber(height_cm) / row_count)
    end
  end

  if value:match("[a-zA-Z]") then
    return value
  end
  return value .. "cm"
end

local function parse_task_header(block)
  if block.t ~= "Header" or block.level ~= 2 then
    return nil
  end

  local text = stringify(block)
  local nr, title, points = text:match("^Aufgabe%s+([^:]+):%s*(.-)%s*%[(%d+)%s*P%.?%]$")
  if nr == nil then
    nr, title, points = text:match("^Aufgabe%s+([^%-]+)%s*%-%s*(.-)%s*%[(%d+)%s*P%.?%]$")
  end

  if nr == nil then
    return nil
  end

  return nr:gsub("^%s+", ""):gsub("%s+$", ""), title, points
end

local function parse_part_header(block)
  if block.t ~= "Header" or block.level ~= 3 then
    return nil
  end

  local text = stringify(block)
  local nr, points = text:match("^([%w%.]+)%)%s*%[(%d+)%s*P%.?%]$")
  if nr == nil then
    nr, points = text:match("^Teil%s+([%w%.]+)%s*%[(%d+)%s*P%.?%]$")
  end

  if nr == nil then
    return nil
  end

  return nr, points
end

local function typst_float_grid(side, width, text, figure_stack)
  local columns
  if side == "right" then
    columns = "(1fr, " .. width .. ")"
  else
    columns = "(" .. width .. ", 1fr)"
  end
  return "#grid(\n"
    .. "  columns: " .. columns .. ",\n"
    .. "  column-gutter: 14pt,\n"
    .. "  align: top,\n"
    .. "  [\n" .. text .. "\n  ],\n"
    .. "  [\n" .. figure_stack .. "\n  ],\n"
    .. ")"
end

local function latex_float_blocks(side, fraction, text, payload)
  local text_fraction = 0.97 - fraction
  local blocks = {}
  if side == "right" then
    table.insert(blocks, raw("\\noindent\\begin{minipage}[t]{" .. string.format("%.4f", text_fraction) .. "\\linewidth}"))
    table.insert(blocks, raw(text))
    table.insert(blocks, raw("\\end{minipage}\\hfill\\begin{minipage}[t]{" .. string.format("%.4f", fraction) .. "\\linewidth}\\centering"))
    for _, part in ipairs(payload) do
      table.insert(blocks, part)
    end
    table.insert(blocks, raw("\\end{minipage}\\par"))
  else
    table.insert(blocks, raw("\\noindent\\begin{minipage}[t]{" .. string.format("%.4f", fraction) .. "\\linewidth}\\centering"))
    for _, part in ipairs(payload) do
      table.insert(blocks, part)
    end
    table.insert(blocks, raw("\\end{minipage}\\hfill\\begin{minipage}[t]{" .. string.format("%.4f", text_fraction) .. "\\linewidth}"))
    table.insert(blocks, raw(text))
    table.insert(blocks, raw("\\end{minipage}\\par"))
  end
  return blocks
end

local function grab_float_text(blocks, start_index)
  local text_blocks = {}
  local index = start_index
  while index <= #blocks do
    local candidate = blocks[index]
    local collect = false
    if candidate.t == "Para" and marker_text(candidate) == nil then
      collect = true
    elseif candidate.t == "Plain" or candidate.t == "OrderedList" or candidate.t == "BulletList" or candidate.t == "Table" then
      collect = true
    end
    if not collect then
      break
    end
    table.insert(text_blocks, candidate)
    index = index + 1
  end
  return text_blocks, index
end

local function resolve_float_placeholder(block, blocks, start_index)
  if block.format ~= TARGET then
    return nil, start_index
  end
  if TARGET == "typst" then
    local side, width, figure_stack = block.text:match("^// ABBILDUNG%-FLOAT (%a+) (%S+)\n(.*)$")
    if side == nil then
      return nil, start_index
    end
    local text_blocks, next_index = grab_float_text(blocks, start_index)
    if #text_blocks == 0 then
      return { raw("#align(center)[\n" .. figure_stack .. "\n]") }, start_index
    end
    local text = pandoc.write(pandoc.Pandoc(text_blocks), "typst"):gsub("^%s+", ""):gsub("%s+$", "")
    return { raw(typst_float_grid(side, width, text, figure_stack)) }, next_index
  end
  local side, fraction_text = block.text:match("^%%%s*ABBILDUNG%-FLOAT (%a+) (%S+)%s*$")
  if side == nil then
    return nil, start_index
  end
  local payload = {}
  local index = start_index
  while index <= #blocks do
    local candidate = blocks[index]
    index = index + 1
    if candidate.t == "RawBlock" and candidate.format == "latex" and candidate.text:match("^%%%s*ABBILDUNG%-FLOAT%-END%s*$") then
      break
    end
    table.insert(payload, candidate)
  end
  local text_blocks, next_index = grab_float_text(blocks, index)
  if #text_blocks == 0 then
    return payload, next_index
  end
  local text = pandoc.write(pandoc.Pandoc(text_blocks), "latex")
  return latex_float_blocks(side, tonumber(fraction_text) or 0.34, text, payload), next_index
end

local function process_author_syntax(blocks)
  local output = {}
  local open_task = false
  local open_part = false
  local open_version_grid = false
  local version_count = 0
  local open_foerderbereich = false
  local open_kartensatz = false
  local karten_spalten = 3

  local function push(block)
    table.insert(output, block)
  end

  local function close_part()
    if open_part then
      push(raw(close_call("teil")))
      open_part = false
    end
  end

  local function close_task()
    close_part()
    if open_task then
      push(raw(close_call("aufgabe")))
      open_task = false
    end
  end

  local function close_foerderbereich()
    if open_foerderbereich then
      push(raw(close_call("foerderbereich")))
      open_foerderbereich = false
    end
  end

  local index = 1
  while index <= #blocks do
    local block = blocks[index]
    index = index + 1
    local task_nr, task_title, task_points = parse_task_header(block)
    if task_nr ~= nil then
      close_task()
      push(raw(begin_call("aufgabe", call_args({
        quote(task_nr),
        quote(task_title),
        value_arg(task_points),
      }))))
      open_task = true
      goto continue
    end

    local part_nr, part_points = parse_part_header(block)
    if part_nr ~= nil then
      close_part()
      push(raw(begin_call("teil", call_args({
        quote(part_nr),
        value_arg(part_points),
      }))))
      open_part = true
      goto continue
    end

    if block.t == "RawBlock" and block.format == TARGET then
      local resolved, next_index = resolve_float_placeholder(block, blocks, index)
      if resolved ~= nil then
        index = next_index
        for _, part in ipairs(resolved) do
          push(part)
        end
        goto continue
      end
    end

    local marker = marker_text(block)
    if marker ~= nil then
      local cover_args = marker:match("^%[Deckblatt:%s*(.-)%]$")
      if cover_args ~= nil then
        local parts = split_marker_args(cover_args)
        push(raw(macro_call("cover_header", call_args({
          quote(parts[1] or ""),
          quote(parts[2] or ""),
          quote(parts[3] or ""),
        }))))
        goto continue
      end

      local grading_total = marker:match("^%[Bewertungsfelder:%s*(.-)%]$")
      if grading_total ~= nil then
        push(raw(macro_call("grading_fields", call_args({ quote(grading_total) }))))
        goto continue
      end

      local vertical_spacing = marker:match("^%[[Aa]bstand%s+(.-)%]$")
      if vertical_spacing ~= nil or marker == "[abstand]" or marker == "[Abstand]" then
        local amount, unit = (vertical_spacing or ""):match("^(%d+[.,]?%d*)%s*(%a+)$")
        if amount == nil or (unit ~= "cm" and unit ~= "mm" and unit ~= "pt") then
          error("Abstand: Bitte einen nicht negativen Abstand in cm, mm oder pt angeben, z. B. [abstand 1cm].")
        end
        local spacing = amount:gsub(",", ".") .. unit
        if TARGET == "latex" then
          push(raw("\\par\\vspace*{" .. spacing .. "}"))
        else
          push(raw("#v(" .. spacing .. ", weak: false)"))
        end
        goto continue
      end

      local box_height = marker:match("^%[Antwortkasten:%s*(.-)%]$")
      if box_height ~= nil then
        if TARGET == "latex" then
          push(raw("\\antwortkasten{" .. box_height .. "}"))
        else
          push(raw("#antwortkasten(height: " .. box_height .. ")"))
        end
        goto continue
      end

      local math_cover_args = marker:match("^%[Mathe%-Deckblatt:%s*(.-)%]$")
      if math_cover_args ~= nil then
        local parts = split_marker_args(math_cover_args)
        push(raw(begin_call("title_page", call_args({
          quote(parts[1] or ""),
          quote(parts[2] or ""),
        }))))
        goto continue
      end

      local writing_lines = marker == "[Schreiblinien]" and "1"
        or marker:match("^%[Schreiblinien%s+(.-)%]$")
      if writing_lines ~= nil then
        local count = tonumber(writing_lines)
        if not writing_lines:match("^%d+$") or count < 1 or count > 30 then
          error("Schreiblinien: Bitte 1 bis 30 Zeilen angeben, z. B. [Schreiblinien 2].")
        end
        if TARGET == "latex" then
          push(raw("\\par\\noindent\\begin{minipage}{\\linewidth}\\color{black!40}"
            .. string.rep("\\vbox to 8mm{\\vfill\\hrule height 0.4pt}", count)
            .. "\\end{minipage}\\par"))
        else
          push(raw("#block(above: 0pt, below: 0pt, width: 100%)["
            .. "#stack(dir: ttb, spacing: 0pt, ..range(" .. count .. ").map(index => "
            .. "block(width: 100%, height: 8mm, place(bottom, "
            .. "line(length: 100%, stroke: 0.4pt + rgb(\"#999999\"))))))]"))
        end
        goto continue
      end

      local grid_args = marker:match("^%[Rechengitter%s+(.-)%]$")
      local old_grid_args = nil
      if grid_args == nil then
        old_grid_args = marker:match("^%[Rechengitter:%s*(.-)%]$")
        grid_args = old_grid_args
      end
      if grid_args ~= nil then
        local parts = split_marker_args(grid_args)
        local cell_size = normalize_grid_cell_size(parts[1], parts[2], old_grid_args ~= nil)
        local rows = parts[2] or "10"
        local cols = parts[3]
        if TARGET == "latex" then
          if cols == nil or cols == "" then
            cols = "36"
          end
          push(raw("\\answergrid{" .. cell_size .. "}{" .. rows .. "}{" .. cols .. "}"))
        else
          local args = "cell_size: " .. cell_size .. ", rows: " .. rows
          if cols ~= nil and cols ~= "" then
            args = args .. ", cols: " .. cols
          end
          push(raw("#answer_grid(" .. args .. ")"))
        end
        goto continue
      end

      local fort_nr, fort_title = marker:match("^%[Fortsetzung%s+([^:]+):%s*(.-)%]$")
      if fort_nr ~= nil then
        close_part()
        push(raw(macro_call("fortsetzung", call_args({ quote(fort_nr), quote(fort_title) }))))
        goto continue
      end

      local foerderplan_args = marker:match("^%[Förderplan%-Kopf:%s*(.-)%]$")
      if foerderplan_args ~= nil then
        local parts = split_marker_args(foerderplan_args)
        push(raw(macro_call("foerderplan_kopf", call_args({
          quote(parts[1] or ""),
          quote(parts[2] or ""),
          quote(parts[3] or ""),
          quote(parts[4] or ""),
          quote(parts[5] or ""),
          quote(parts[6] or ""),
        }))))
        goto continue
      end

      local foerderbereich_titel = marker:match("^%[Förderbereich:%s*(.-)%]$")
      if foerderbereich_titel ~= nil then
        close_foerderbereich()
        if TARGET == "latex" then
          push(raw(begin_call("foerderbereich", quote(foerderbereich_titel))))
        else
          local sticky = ""
          if foerderbereich_titel == "Weiterarbeit" then
            sticky = ", sticky: true"
          end
          push(raw("#foerderbereich(" .. typst_string(foerderbereich_titel) .. sticky .. ")["))
        end
        open_foerderbereich = true
        goto continue
      end

      if marker == "[/Förderbereich]" then
        close_foerderbereich()
        goto continue
      end

      if marker == "[Unterschriften]" then
        close_foerderbereich()
        push(raw(macro_call("unterschriften", "")))
        goto continue
      end

      local student_spacing = marker:match("^%[Schuelerfelder%s+(.-)%]$")
        or marker:match("^%[Schülerfelder%s+(.-)%]$")
      if student_spacing ~= nil then
        local centimeters = student_spacing:match("^(%d+[.,]?%d*)%s*cm$")
        if centimeters == nil then
          error("Schülerfelder: Bitte einen nicht negativen Abstand in cm angeben, z. B. [Schülerfelder 1cm].")
        end
        local spacing = centimeters:gsub(",", ".") .. "cm"
        if TARGET == "latex" then
          push(raw("\\par\\vspace*{" .. spacing .. "}"))
        else
          push(raw("#v(" .. spacing .. ", weak: false)"))
        end
      end

      if student_spacing ~= nil or marker == "[Schuelerfelder]" or marker == "[Schülerfelder]" then
        push(raw(macro_call("student_fields", "")))
        goto continue
      elseif marker == "[Notenspiegel]" then
        push(raw(macro_call("notenspiegel_table", "")))
        goto continue
      elseif marker == "[Seitenumbruch]" then
        close_task()
        if TARGET == "latex" then
          push(raw("\\exampagebreak"))
        else
          push(raw("#pagebreak()"))
        end
        goto continue
      elseif marker == "[/Mathe-Deckblatt]" then
        push(raw(close_call("title_page")))
        goto continue
      elseif marker == "[Notentabelle]" then
        push(raw(macro_call("note_table", "")))
        goto continue
      elseif marker == "[Mini-AB]" then
        push(raw(begin_call("mini_ab", "")))
        goto continue
      elseif marker == "[/Mini-AB]" then
        push(raw(close_call("mini_ab")))
        goto continue
      elseif marker:match("^%[Karten:?%s*(.-)%]$") then
        local karten_inner = marker:match("^%[Karten:?%s*(.-)%]$")
        local karten_titel
        karten_titel, karten_spalten = parse_karten_marker(karten_inner)
        if TARGET == "latex" then
          push(raw(begin_call("kartensatz", "{" .. latex_string(karten_titel or "") .. "}")))
        else
          push(raw(begin_call("kartensatz", call_args({
            karten_titel ~= nil and quote(karten_titel) or "none",
          }))))
        end
        open_kartensatz = true
        goto continue
      elseif marker == "[/Karten]" then
        push(raw(close_call("kartensatz")))
        open_kartensatz = false
        goto continue
      elseif marker == "[Beweistabelle]" then
        push(raw(begin_call("proof_table", "")))
        goto continue
      elseif marker == "[/Beweistabelle]" then
        push(raw(close_call("proof_table")))
        goto continue
      elseif marker == "[Hinweise]" then
        push(raw(begin_call("hinweis", "")))
        goto continue
      elseif marker == "[/Hinweise]" then
        push(raw(close_call("hinweis")))
        goto continue
      elseif marker == "[Referenz]" then
        push(raw(begin_call("referenz", "")))
        goto continue
      elseif marker == "[/Referenz]" then
        push(raw(close_call("referenz")))
        goto continue
      elseif marker:match("^%[Infobox:%s*(.-)%]$") or marker == "[Infobox]" then
        local titel = marker:match("^%[Infobox:%s*(.-)%]$") or "Info"
        push(raw(begin_call("infobox", quote(titel))))
        goto continue
      elseif marker == "[/Infobox]" then
        push(raw(close_call("infobox")))
        goto continue
      elseif marker:match("^%[Warnbox:%s*(.-)%]$") or marker == "[Warnbox]" then
        local titel = marker:match("^%[Warnbox:%s*(.-)%]$") or "Warnung"
        push(raw(begin_call("warnbox", quote(titel))))
        goto continue
      elseif marker == "[/Warnbox]" then
        push(raw(close_call("warnbox")))
        goto continue
      elseif marker:match("^%[Tippbox:%s*(.-)%]$") or marker == "[Tippbox]" then
        local titel = marker:match("^%[Tippbox:%s*(.-)%]$") or "Tipp"
        push(raw(begin_call("tippbox", quote(titel))))
        goto continue
      elseif marker == "[/Tippbox]" then
        push(raw(close_call("tippbox")))
        goto continue
      elseif marker:match("^%[Erwartungshorizont:%s*(.-)%]$") then
        local titel = marker:match("^%[Erwartungshorizont:%s*(.-)%]$")
        push(raw(begin_call("erwartungshorizont", quote(titel))))
        goto continue
      elseif marker == "[/Erwartungshorizont]" then
        push(raw(close_call("erwartungshorizont")))
        goto continue
      elseif marker:match("^%[Lösung:%s*(.-)%]$") or marker:match("^%[Loesung:%s*(.-)%]$") then
        local nr = marker:match("^%[Lösung:%s*(.-)%]$") or marker:match("^%[Loesung:%s*(.-)%]$")
        push(raw(begin_call("loesung", quote(nr))))
        goto continue
      elseif marker == "[/Lösung]" or marker == "[/Loesung]" then
        push(raw(close_call("loesung")))
        goto continue
      elseif marker == "[Wahr-Falsch-Layout]" then
        push(raw(begin_call("wahr_falsch_layout", "")))
        goto continue
      elseif marker == "[/Wahr-Falsch-Layout]" then
        push(raw(close_call("wahr_falsch_layout")))
        goto continue
      elseif marker:match("^%[Eingabetabelle%s+(.-)%]$") or marker == "[Eingabetabelle]" then
        local row_height = marker:match("^%[Eingabetabelle%s+(.-)%]$") or ""
        local amount, unit = row_height:match("^(%d+[.,]?%d*)%s*(%a+)$")
        if row_height ~= "" and (amount == nil or tonumber((amount:gsub(",", "."))) <= 0 or (unit ~= "cm" and unit ~= "mm" and unit ~= "pt")) then
          error("Eingabetabelle: Bitte eine positive Zeilenhöhe in cm, mm oder pt angeben, z. B. [Eingabetabelle 1.2cm].")
        end
        local args = ""
        if amount ~= nil then
          if TARGET == "latex" then
            local unit_pt = { cm = 28.4528, mm = 2.84528, pt = 1 }
            local extra = tonumber((amount:gsub(",", "."))) * unit_pt[unit] - 17
            if extra < 0 then
              extra = 0
            end
            args = "[" .. string.format("%.2fpt", extra) .. "]"
          else
            args = "row-height: " .. amount:gsub(",", ".") .. unit
          end
        end
        push(raw(begin_call("input_table", args)))
        goto continue
      elseif marker == "[/Eingabetabelle]" then
        push(raw(close_call("input_table")))
        goto continue
      elseif marker == "[Code-Hinweis]" then
        push(raw(begin_call("code_hinweis", "")))
        goto continue
      elseif marker == "[/Code-Hinweis]" then
        push(raw(close_call("code_hinweis")))
        goto continue
      elseif marker == "[Versionen]" then
        open_version_grid = true
        version_count = 0
        goto continue
      elseif marker == "[Version]" and open_version_grid then
        version_count = version_count + 1
        if version_count == 1 then
          if TARGET == "latex" then
            push(raw("\\begin{versionen}\\begin{versionleft}"))
          else
            push(raw("#versionen(["))
          end
        else
          if TARGET == "latex" then
            push(raw("\\end{versionleft}\\begin{versionright}"))
          else
            push(raw("], ["))
          end
        end
        goto continue
      elseif marker == "[/Versionen]" and open_version_grid then
        if TARGET == "latex" then
          push(raw("\\end{versionright}\\end{versionen}"))
        else
          push(raw("])"))
        end
        open_version_grid = false
        version_count = 0
        goto continue
      end
    end

    local stray_marker = block_marker_in_text(block)
    if stray_marker ~= nil then
      error("Der Marker " .. stray_marker .. " …] muss in einem eigenen Absatz stehen: "
        .. "bitte Leerzeilen vor und nach dem Marker einfügen, damit er nicht Teil "
        .. "eines Textabsatzes wird.")
    end
    if open_kartensatz and block.t == "BulletList" then
      push(karten_raw(block, karten_spalten))
      goto continue
    end
    push(block)
    ::continue::
  end

  close_task()
  close_foerderbereich()
  return output
end

local function diagnose_content(blocks, model_width)
  local content = pandoc.Div(blocks):walk({
    RawInline = function(inline)
      if inline.format == "html" and inline.text:match("^<br%s*/?>$") then
        return pandoc.LineBreak()
      end
    end,
    Str = function(inline)
      if inline.text == "🙂" or inline.text == "😐" or inline.text == "😕" then
        return pandoc.RawInline("typst", '#text(font: "Noto Color Emoji", size: 14pt)[' .. inline.text .. ']')
      end
    end,
    Image = function(image)
      local mime, contents = pandoc.mediabag.lookup(image.src)
      if mime == "image/svg+xml" and contents ~= nil then
        local width = model_width or "48mm"
        if contents:find('width="460"', 1, true) then
          contents = contents:gsub('font%-size="16"', 'font-size="26"')
        end
        return pandoc.RawInline("typst", "#image(bytes(" .. typst_string(contents) .. "), width: " .. width .. ")")
      end
    end,
  })
  return pandoc.write(pandoc.Pandoc(content.content), "typst"):gsub("%s+$", "")
end

local function diagnose_task(blocks)
  local model = nil
  local content = pandoc.Div(blocks):walk({Image = function(image)
    if model == nil then
      model = image
      return {}
    end
  end})
  if model == nil then
    return diagnose_content(blocks)
  end
  local width = model.caption and pandoc.utils.stringify(model.caption):find("vierhundertfeld", 1, true) and "36mm" or "48mm"
  return "#grid(columns: (51mm, 1fr), column-gutter: 8pt, align: left + horizon, ["
    .. diagnose_content({pandoc.Plain({model})}, width) .. "], [" .. diagnose_content(content.content) .. "])"
end

local markdown_includes = {}

local function column_width_percent(value)
  if value == nil or value == "" then
    return nil
  end
  local amount = value:match("^(%d+[.,]?%d*)%%$") or value:match("^(%d+[.,]?%d*)$")
  if amount == nil then
    error('Spalten: Breite als Prozentwert angeben, z. B. width="55%".')
  end
  local percent = tonumber((amount:gsub(",", ".")))
  if percent <= 0 or percent >= 100 then
    error('Spalten: Breite zwischen 0 und 100 Prozent angeben, z. B. width="55%".')
  end
  return percent
end

-- Optionale Trennlinien zwischen den Spalten (nur Typst).
-- Aktiviert als Klasse `trennlinien`/`column-lines` am columns-Div oder als
-- Attribut `trennlinien="gestrichelt"` bzw. `lines="dotted"` usw.
local function column_separator(el)
  local value = attr(el, "trennlinien", attr(el, "lines", nil))
  if value == nil and (has_class(el, "trennlinien") or has_class(el, "column-lines")) then
    return "dashed"
  end
  if value == nil then
    return nil
  end
  value = value:lower():gsub("^%s+", ""):gsub("%s+$", "")
  if value == "" or value == "ja" or value == "true" or value == "1"
    or value == "gestrichelt" or value == "dashed" then
    return "dashed"
  end
  if value == "gepunktet" or value == "dotted" then
    return "dotted"
  end
  if value == "durchgezogen" or value == "solid" then
    return "solid"
  end
  if value == "nein" or value == "false" or value == "0" or value == "none" or value == "aus" then
    return nil
  end
  error('Spalten: Unbekannter Wert fuer trennlinien, z. B. trennlinien="gestrichelt".')
end

local student_dialog_renderer
local mini_diagnose_renderer
local function process_div(el)
  if has_class(el, "mini-karte") or has_class(el, "mini-auswertung") then
    if not mini_diagnose_renderer then
      local directory = PANDOC_SCRIPT_FILE:match("^(.*[/\\])") or ""
      mini_diagnose_renderer = dofile(directory .. "mini-diagnose.lua")
    end
    return mini_diagnose_renderer(el, TARGET)
  end
  if has_class(el, "schuelerdialog") then
    if not student_dialog_renderer then
      local directory = PANDOC_SCRIPT_FILE:match("^(.*[/\\])") or ""
      student_dialog_renderer = dofile(directory .. "student-dialog.lua")
    end
    return student_dialog_renderer(el)
  end
  if TARGET == "typst" and has_class(el, "zusammenhalten") then
    local blocks = {raw("#block(breakable: false)[")}
    for _, block in ipairs(el.content) do table.insert(blocks, block) end
    table.insert(blocks, raw("]"))
    return blocks
  end

  if has_class(el, "markdown-einbinden") then
    local source = attr(el, "datei", nil)
    if source == nil or markdown_includes[source] then
      error("Markdown einbinden: Datei fehlt oder wird rekursiv eingebunden.")
    end
    local file, message = io.open(source, "r")
    if file == nil then
      error("Markdown einbinden: " .. message)
    end
    local contents = file:read("*a")
    file:close()
    markdown_includes[source] = true
    local included = pandoc.read(contents, "markdown")
    included = included:walk({Inlines = Inlines})
    included = included:walk({Div = process_div})
    markdown_includes[source] = nil
    return process_author_syntax(included.blocks)
  end

  if TARGET == "typst" and has_class(el, "selbstdiagnose-hinweis") then
    return {raw("#hinweiskasten([])[" .. diagnose_content(el.content) .. "]")}
  end

  if TARGET == "typst" and has_class(el, "selbstdiagnose-legende") then
    local entries = {}
    for _, block in ipairs(el.content) do
      if block.t == "BulletList" then
        for index, item in ipairs(block.content) do
          table.insert(entries, "rect(fill: laune.at(" .. (index - 1) .. ").hell, radius: 3pt, inset: 6pt)["
            .. diagnose_content(item) .. "]")
        end
      end
    end
    return {raw("#block(above: 4pt, below: 7pt)[#set text(size: 8.4pt)\n#grid(columns: (1fr, 1fr, 1fr), gutter: 6pt, " .. table.concat(entries, ", ") .. ")] ")}
  end

  if TARGET == "typst" and has_class(el, "selbstdiagnose") then
    local rows = {}
    local headings = {}
    for _, block in ipairs(el.content) do
      if block.t == "Table" then
        if #block.head.rows > 0 then
          for _, cell in ipairs(block.head.rows[1].cells) do
            table.insert(headings, "[" .. diagnose_content(cell.contents) .. "]")
          end
        end
        for _, body in ipairs(block.bodies) do
          for _, row in ipairs(body.body) do
            if #row.cells ~= 6 then
              error("Selbstdiagnose: Erwartet sechs Spalten: Nummer, Kompetenz, Beispiel und drei Einschätzungen.")
            end
            table.insert(rows, "zeile([" .. diagnose_content(row.cells[1].contents) .. "], ["
              .. diagnose_content(row.cells[2].contents) .. "], [" .. diagnose_task(row.cells[3].contents) .. "])")
          end
        end
      end
    end
    if #rows == 0 or #headings ~= 6 then
      error("Selbstdiagnose: Erwartet eine Markdown-Tabelle mit sechs Spalten und mindestens einer Aufgabe.")
    end
    return {raw("#diagnose_tabelle((" .. table.concat(rows, ",\n") .. ",), schriftgroesse: 10pt, zellrand: 5pt, kopf: (" .. table.concat(headings, ", ") .. "))")}
  end

  if has_class(el, "asset-center") then
    local blocks
    if TARGET == "latex" then
      blocks = { raw("\\begin{center}") }
      for _, block in ipairs(el.content) do
        table.insert(blocks, block)
      end
      table.insert(blocks, raw("\\end{center}"))
    else
      blocks = { raw("#align(center)[") }
      for _, block in ipairs(el.content) do
        table.insert(blocks, block)
      end
      table.insert(blocks, raw("]"))
    end
    return blocks
  end

  if el.attributes["layout-ncol"] ~= nil then
    local cols = el.attributes["layout-ncol"]
    if TARGET == "latex" then
      local blocks = { raw("\\begin{multicols}{" .. cols .. "}") }
      for _, block in ipairs(el.content) do
        table.insert(blocks, block)
      end
      table.insert(blocks, raw("\\end{multicols}"))
      return blocks
    end
  end

  if has_class(el, "version-grid") then
    local versions = {}
    for _, block in ipairs(el.content) do
      if block.t == "Div" and has_class(block, "version") then
        table.insert(versions, block)
      end
    end

    if #versions >= 2 then
      local blocks
      if TARGET == "latex" then
        blocks = { raw("\\begin{versionen}\\begin{versionleft}") }
      else
        blocks = { raw("#versionen([") }
      end
      for _, block in ipairs(versions[1].content) do
        table.insert(blocks, block)
      end
      if TARGET == "latex" then
        table.insert(blocks, raw("\\end{versionleft}\\begin{versionright}"))
      else
        table.insert(blocks, raw("], ["))
      end
      for _, block in ipairs(versions[2].content) do
        table.insert(blocks, block)
      end
      if TARGET == "latex" then
        table.insert(blocks, raw("\\end{versionright}\\end{versionen}"))
      else
        table.insert(blocks, raw("])"))
      end
      return blocks
    end
  end

  if has_class(el, "aufgabe") then
    local args = call_args({
      quote(attr(el, "nr", "")),
      quote(attr(el, "titel", "")),
      points_arg(el.attributes["punkte"]),
    })
    el = strip_figure_captions(el)
    return wrap_block("aufgabe", args, el.content)
  end

  if has_class(el, "fortsetzung") then
    local args = call_args({
      quote(attr(el, "nr", "")),
      quote(attr(el, "titel", "")),
    })
    return { raw(macro_call("fortsetzung", args)) }
  end

  if has_class(el, "teil") then
    local args = call_args({
      quote(attr(el, "nr", "")),
      value_arg(attr(el, "punkte", "0")),
    })
    return wrap_block("teil", args, el.content)
  end

  if has_class(el, "kasten") then
    if TARGET == "latex" then
      return { raw("\\antwortkasten{" .. attr(el, "height", "1cm") .. "}") }
    end
    return { raw("#antwortkasten(height: " .. attr(el, "height", "1cm") .. ")") }
  end

  if has_class(el, "hinweis-gedreht") then
    if TARGET == "latex" then
      return wrap_block("hinweis", "", el.content)
    end
    return wrap_block("hinweis_gedreht", "", el.content)
  end

  if has_class(el, "hinweis") then
    return wrap_block("hinweis", "", el.content)
  end

  if has_class(el, "box") or has_class(el, "farbbox") then
    local color = farbbox_color(attr(el, "farbe", "blau"))
    if TARGET == "latex" then
      return wrap_block("farbbox", quote(color), el.content)
    end
    return wrap_block("farbbox", 'rgb("' .. color .. '"),', el.content)
  end

  if has_class(el, "code-hint") then
    return wrap_block("code_hinweis", "", el.content)
  end

  if has_class(el, "pagebreak") then
    if TARGET == "latex" then
      return { raw("\\newpage") }
    end
    return { raw("#pagebreak()") }
  end

  if has_class(el, "cover") then
    local args = call_args({
      quote(attr(el, "title", "")),
      quote(attr(el, "subtitle", "")),
      quote(attr(el, "subtext", "")),
    })
    return { raw(macro_call("cover_header", args)) }
  end

  if has_class(el, "student-fields") then
    return { raw(macro_call("student_fields", "")) }
  end

  if has_class(el, "grading-fields") then
    return { raw(macro_call("grading_fields", call_args({ quote(attr(el, "total", "50")) }))) }
  end

  if has_class(el, "columns") or has_class(el, "spalten") then
    local cells = {}
    for _, child in ipairs(el.content) do
      if child.t == "Div" and (has_class(child, "column") or has_class(child, "spalte")) then
        table.insert(cells, child)
      end
    end

    if #cells >= 2 then
      local percents = {}
      local given_total = 0
      local unspecified = 0
      for _, cell in ipairs(cells) do
        local percent = column_width_percent(attr(cell, "width", attr(cell, "breite", nil)))
        table.insert(percents, percent)
        if percent == nil then
          unspecified = unspecified + 1
        else
          given_total = given_total + percent
        end
      end
      if given_total >= 100 then
        error("Spalten: Die angegebenen Breiten muessen zusammen unter 100 Prozent bleiben.")
      end
      local default_percent = unspecified > 0 and (100 - given_total) / unspecified or nil

      local blocks = {}
      if TARGET == "latex" then
        local gutter = 0.02 * (#cells - 1)
        for i, cell in ipairs(cells) do
          local fraction = ((percents[i] or default_percent) / 100) * (1 - gutter)
          local opening = "\\noindent\\begin{minipage}[t]{" .. string.format("%.4f", fraction) .. "\\linewidth}"
          -- \hfill muss in derselben Pandoc-RawBlock wie das umschliessende
          -- \end{minipage}/\begin{minipage} stehen: separate RawBlocks
          -- erzeugen eine Leerzeile dazwischen, die \hfill als Absatzende
          -- kappt und Spalten untereinander statt nebeneinander setzt.
          if i == 1 then
            table.insert(blocks, raw(opening))
          else
            table.insert(blocks, raw("\\end{minipage}\n\\hfill\n" .. opening))
          end
          for _, part in ipairs(cell.content) do
            table.insert(blocks, part)
          end
        end
        table.insert(blocks, raw("\\end{minipage}"))
        table.insert(blocks, raw("\\par"))
      else
        local separator = column_separator(el)
        local specs = {}
        for i = 1, #cells do
          table.insert(specs, string.format("%.4gfr", percents[i] or default_percent))
          if separator and i < #cells then
            table.insert(specs, "0pt")
          end
        end
        table.insert(blocks, raw(
          "#grid(columns: (" .. table.concat(specs, ", ") .. "), column-gutter: "
            .. (separator and "5pt" or "10pt")
            .. ", align: top, stroke: none,"
        ))
        for i, cell in ipairs(cells) do
          table.insert(blocks, raw("["))
          for _, part in ipairs(cell.content) do
            table.insert(blocks, part)
          end
          table.insert(blocks, raw("],"))
          if separator and i < #cells then
            local dash = separator == "solid" and "" or (', dash: "' .. separator .. '"')
            table.insert(blocks, raw(
              "grid.cell(stroke: (left: (paint: rgb(\"#9ca3af\"), thickness: 0.5pt" .. dash .. ")))[],"
            ))
          end
        end
        table.insert(blocks, raw(")"))
      end
      return blocks
    end
  end

  if has_class(el, "columns-2") then
    return wrap_block("columns_two", "", el.content)
  end

  if has_class(el, "input-table") then
    return wrap_block("input_table", "", el.content)
  end

  if has_class(el, "notenspiegel") then
    return { raw(macro_call("notenspiegel_table", "")) }
  end

  if has_class(el, "reference") or has_class(el, "referenz") then
    return wrap_block("referenz", "", el.content)
  end

  if has_class(el, "abbildungen") then
    local mode = nil
    if has_class(el, "list-abc") then
      mode = "abc"
    elseif has_class(el, "list-123") then
      mode = "123"
    end

    local images = {}
    el:walk({ Image = function(img) table.insert(images, img) end })

    local count = #images
    if count == 0 then
      return nil
    end

    local cols = tonumber(attr(el, "cols", nil)) or math.min(count, 3)

    local float_side = float_side_of(attr(el, "float", nil))
    local text_blocks = {}
    if float_side ~= nil then
      for _, block in ipairs(el.content) do
        local has_image = false
        block:walk({ Image = function(_) has_image = true end })
        if not has_image then
          table.insert(text_blocks, block)
        end
      end
    end

    local blocks = {}

    if float_side ~= nil then
      local figure_width = attr(el, "breite", attr(el, "width", "34%"))
      if TARGET == "latex" then
        local fraction = 0.34
        local pct = figure_width:match("^(%d+[.,]?%d*)%%$")
        if pct ~= nil then
          fraction = tonumber((pct:gsub(",", "."))) / 100
        end
        local payload = {}
        for i, img in ipairs(images) do
          local label = abbildungen_label(i, mode)
          img.caption = (label ~= nil) and { pandoc.Str(label) } or {}
          if i > 1 then
            table.insert(payload, raw("\\par\\vspace{0.6em}"))
          end
          table.insert(payload, pandoc.Plain({ img }))
          if label ~= nil then
            table.insert(payload, raw("\\par\\vspace{0.15em}\\textbf{" .. label .. "}"))
          end
        end
        if #text_blocks > 0 then
          local text = pandoc.write(pandoc.Pandoc(text_blocks), "latex")
          return latex_float_blocks(float_side, fraction, text, payload)
        end
        table.insert(blocks, raw("% ABBILDUNG-FLOAT " .. float_side .. " " .. string.format("%.4f", fraction)))
        for _, part in ipairs(payload) do
          table.insert(blocks, part)
        end
        table.insert(blocks, raw("% ABBILDUNG-FLOAT-END"))
        return blocks
      else
        local figure_cells = {}
        for i, img in ipairs(images) do
          local label = abbildungen_label(i, mode)
          img.caption = (label ~= nil) and { pandoc.Str(label) } or {}
          local mime, contents = pandoc.mediabag.lookup(img.src)
          local cell
          if mime == "image/svg+xml" and contents ~= nil then
            cell = "#box(image(bytes(" .. typst_string(contents) .. "), width: 100%))"
          else
            cell = pandoc.write(pandoc.Pandoc({ pandoc.Plain({ img }) }), "typst")
            cell = cell:gsub("^%s+", ""):gsub("%s+$", "")
          end
          if label ~= nil then
            cell = cell .. "\n#align(center)[#text(weight: \"bold\")[" .. label .. "]]"
          end
          table.insert(figure_cells, cell)
        end
        local figure_stack = table.concat(figure_cells, "\n#v(10pt)\n")
        if #text_blocks > 0 then
          local text = pandoc.write(pandoc.Pandoc(text_blocks), "typst"):gsub("^%s+", ""):gsub("%s+$", "")
          return { raw(typst_float_grid(float_side, figure_width, text, figure_stack)) }
        end
        return { raw("// ABBILDUNG-FLOAT " .. float_side .. " " .. figure_width .. "\n" .. figure_stack) }
      end
    end

    if TARGET == "latex" then
      local cell_width = string.format("%.4f", 1 / cols - 0.02 * (cols - 1))
      table.insert(blocks, raw("\\begin{center}%"))
      for i, img in ipairs(images) do
        local col_in_row = (i - 1) % cols
        if col_in_row == 0 and i > 1 then
          table.insert(blocks, raw("\\par\\vspace{0.4em}"))
        end
        local label = abbildungen_label(i, mode)
        img.caption = (label ~= nil) and { pandoc.Str(label) } or {}
        table.insert(blocks, raw("\\begin{minipage}[t]{" .. cell_width .. "\\linewidth}\\centering"))
        table.insert(blocks, pandoc.Plain({ img }))
        local cell = ""
        if label ~= nil then
          cell = cell .. "\\par\\vspace{0.15em}\\textbf{" .. label .. "}"
        end
        cell = cell .. "\\end{minipage}"
        if col_in_row < cols - 1 and i < count then
          cell = cell .. "\\hfill"
        end
        table.insert(blocks, raw(cell))
      end
      table.insert(blocks, raw("\\end{center}"))
    else
      local col_spec = string.rep("1fr, ", cols):gsub(", $", "")
      local cells = {}
      for i, img in ipairs(images) do
        local label = abbildungen_label(i, mode)
        img.caption = (label ~= nil) and { pandoc.Str(label) } or {}
        local mime, contents = pandoc.mediabag.lookup(img.src)
        local cell
        if mime == "image/svg+xml" and contents ~= nil then
          cell = "#box(image(bytes(" .. typst_string(contents) .. "), width: " .. attr(img, "width", "80%") .. "))"
        else
          cell = pandoc.write(pandoc.Pandoc({ pandoc.Plain({ img }) }), "typst")
          cell = cell:gsub("^%s+", ""):gsub("%s+$", "")
        end
        if label ~= nil then
          cell = cell .. "\n#align(center)[#text(weight: \"bold\")[" .. label .. "]]"
        end
        table.insert(cells, "[" .. cell .. "]")
      end
      table.insert(blocks, raw(
        "#grid(columns: (" .. col_spec .. "), column-gutter: 10pt, row-gutter: 8pt,\n"
        .. table.concat(cells, ",\n") .. ",\n)"
      ))
    end

    return blocks
  end

end

local function parse_broken_fence(el)
  local inlines = el.content
  if inlines == nil or #inlines < 2 then
    return nil
  end
  if not (inlines[1].t == "Str" and inlines[1].text == ":::") then
    return nil
  end
  local last = inlines[#inlines]
  if not (last.t == "Str" and last.text == ":::") then
    return nil
  end

  local header_end = nil
  for i = 2, #inlines do
    if inlines[i].t == "SoftBreak" or inlines[i].t == "LineBreak" then
      header_end = i
      break
    end
  end
  if header_end == nil then
    return nil
  end

  local classes = {}
  for i = 2, header_end - 1 do
    local inline = inlines[i]
    if inline.t == "Str" then
      local token = inline.text:gsub("^%.", "")
      if token ~= "" then
        table.insert(classes, token)
      end
    end
  end
  if #classes == 0 then
    return nil
  end

  local content_end = #inlines - 1
  if content_end >= header_end and (inlines[content_end].t == "SoftBreak" or inlines[content_end].t == "LineBreak") then
    content_end = content_end - 1
  end
  if content_end < header_end then
    return nil
  end

  local inner = {}
  for i = header_end + 1, content_end do
    table.insert(inner, inlines[i])
  end

  return pandoc.Div({ pandoc.Plain(inner) }, pandoc.Attr("", classes, {}))
end

local function recover_broken_fence(el)
  local div = parse_broken_fence(el)
  if div == nil then
    return nil
  end
  return process_div(div) or { div }
end

function Div(el)
  return process_div(el)
end

function Para(el)
  return recover_broken_fence(el)
end

function Plain(el)
  return recover_broken_fence(el)
end

function Span(el)
  if has_class(el, "zusatz") then
    if TARGET == "typst" then
      local result = pandoc.List({raw_inline('#text(fill: rgb("#c62828"))[')})
      result:extend(el.content)
      result:insert(raw_inline("]"))
      return result
    elseif TARGET == "latex" then
      local result = pandoc.List({raw_inline("{\\color[HTML]{C62828}")})
      result:extend(el.content)
      result:insert(raw_inline("}"))
      return result
    else
      el.attributes["style"] = (el.attributes["style"] or "") .. ";color:#c62828"
      return el
    end
  end
  if has_class(el, "antwortlinie") then
    return raw_inline(macro_call("antwortlinie", ""))
  end
end

-- Markdown may parse underscores in digit patterns as emphasis. Restore those
-- delimiters only for this model, where each underscore means one empty card.
local function digit_puzzle_marker_text(inlines)
  local parts = {}
  for _, item in ipairs(inlines) do
    if item.t == "Emph" then
      table.insert(parts, "_" .. digit_puzzle_marker_text(item.content) .. "_")
    elseif item.t == "Strong" then
      table.insert(parts, "__" .. digit_puzzle_marker_text(item.content) .. "__")
    elseif item.t == "Space" or item.t == "SoftBreak" or item.t == "LineBreak" then
      table.insert(parts, " ")
    else
      table.insert(parts, pandoc.utils.stringify(item))
    end
  end
  return table.concat(parts)
end

function Inlines(inlines)
  if #inlines == 1 and inlines[1].t == "Str" and inlines[1].text == "[Antwortlinie]" then
    return { raw_inline(macro_call("antwortlinie", "")) }
  end
  if #inlines == 1 and inlines[1].t == "Str" and (inlines[1].text == "[Platz]" or inlines[1].text == "[platz]") then
    return { raw_inline(macro_call("platz", "")) }
  end
  local result = pandoc.List()
  local index = 1
  while index <= #inlines do
    local inline = inlines[index]
    if inline.t == "Str" and inline.text == "[Uhr]" then
      result:insert(raw_inline(macro_call("uhr", "")))
      index = index + 1
    elseif inline.t == "Str" and (inline.text == "[Punkte" or inline.text == "[punkte" or inline.text == "[Einheitskreis" or inline.text == "[Skizze" or inline.text == "[Modell" or inline.text == "[Rot" or inline.text == "[Koordinatensystem" or inline.text == "[antwortlinie" or inline.text == "[Antwortlinie" or inline.text == "[platz" or inline.text == "[Platz") then
      local marker = pandoc.List({ inline })
      local is_answer_line = inline.text == "[antwortlinie" or inline.text == "[Antwortlinie" or inline.text == "[platz" or inline.text == "[Platz" or inline.text == "[Punkte" or inline.text == "[punkte"
      local last = index + 1
      while last <= #inlines do
        marker:insert(inlines[last])
        if inlines[last].t == "Str" and (inlines[last].text:match("%]$") or (is_answer_line and inlines[last].text:find("]", 1, true))) then
          break
        end
        last = last + 1
      end
      local marker_text = pandoc.utils.stringify(marker)
      if marker_text:match("^%[Modell%s+ziffernraetsel%s") then
        marker_text = digit_puzzle_marker_text(marker)
      end
      local args = marker_text:match("^%[Einheitskreis%s+(.-)%]$")
      local geometry_args = marker_text:match("^%[Skizze%s+(.-)%]$")
      local model_args = marker_text:match("^%[Modell%s+(.-)%]$")
      local rot_args = marker_text:match("^%[Rot%s+(.-)%]$")
      local coords_args = marker_text:match("^%[Koordinatensystem%s+(.-)%]$")
      local answer_width, answer_suffix = marker_text:match("^%[[Aa]ntwortlinie%s+(.-)%](.*)$")
      local platz_width, platz_suffix = marker_text:match("^%[[Pp]latz%s+(.-)%](.*)$")
      local points, points_suffix = marker_text:match("^%[[Pp]unkte%s+(.-)%](.*)$")
      if points ~= nil then
        local number = tonumber((points:gsub(",", ".")))
        if not (points:match("^%d+$") or points:match("^%d+[.,]%d+$")) or not number or number == math.huge then
          error("Punkte: Bitte eine nicht negative Zahl angeben, z. B. [Punkte 1] oder [Punkte 0,5].")
        end
        local label = string.format("%g", number):gsub("%.", ",") .. " P."
        if TARGET == "latex" then
          result:insert(raw_inline("\\textcolor[HTML]{1565C0}{\\textbf{" .. label .. "}}"))
        else
          result:insert(raw_inline('#text(fill: rgb("' .. BLUE .. '"), weight: "bold")[' .. label .. ']'))
        end
        if points_suffix ~= "" then result:insert(pandoc.Str(points_suffix)) end
        index = last + 1
      elseif platz_width ~= nil then
        local amount, unit = platz_width:match("^(%d+[.,]?%d*)%s*(%a+)$")
        if amount == nil or tonumber((amount:gsub(",", "."))) <= 0 or (unit ~= "cm" and unit ~= "mm" and unit ~= "pt") then
          error("Platz: Bitte eine positive Breite in cm, mm oder pt angeben, z. B. [Platz 1.5cm].")
        end
        local width = amount:gsub(",", ".") .. unit
        if TARGET == "latex" then
          result:insert(raw_inline("\\platz[" .. width .. "]"))
        else
          result:insert(raw_inline("#platz(width: " .. width .. ")"))
        end
        if platz_suffix ~= "" then
          result:insert(pandoc.Str(platz_suffix))
        end
        index = last + 1
      elseif answer_width ~= nil then
        local fill_keyword = answer_width == "füllend" or answer_width == "fuellend"
        local width = nil
        if fill_keyword then
          width = TARGET == "latex" and "\\linewidth" or "100%"
        else
          local amount, unit = answer_width:match("^(%d+[.,]?%d*)%s*(%a+)$")
          if amount == nil or tonumber((amount:gsub(",", "."))) <= 0 or (unit ~= "cm" and unit ~= "mm" and unit ~= "pt") then
            error("Antwortlinie: Bitte eine positive Breite in cm, mm oder pt angeben oder füllend nutzen, z. B. [antwortlinie 1cm].")
          end
          width = amount:gsub(",", ".") .. unit
        end
        if TARGET == "latex" then
          result:insert(raw_inline("\\antwortlinie[" .. width .. "]"))
        else
          result:insert(raw_inline("#antwortlinie(width: " .. width .. ")"))
        end
        if answer_suffix ~= "" then
          result:insert(pandoc.Str(answer_suffix))
        end
        index = last + 1
      elseif args ~= nil then
        result:insert(unit_circle_image(args))
        index = last + 1
      elseif geometry_args ~= nil then
        result:insert(geometry_image(geometry_args))
        index = last + 1
      elseif model_args ~= nil then
        result:insert(arithmetic_image(model_args))
        index = last + 1
      elseif rot_args ~= nil then
        result:insert(red_text(rot_args))
        index = last + 1
      elseif coords_args ~= nil then
        result:insert(coordinate_system_image(coords_args))
        index = last + 1
      else
        result:insert(inline)
        index = index + 1
      end
    else
      result:insert(inline)
      index = index + 1
    end
  end
  return result
end

function Str(el)
  if el.text == "[Punkte]" or el.text == "[punkte]" then
    error("Punkte: Bitte eine nicht negative Zahl angeben, z. B. [Punkte 1] oder [Punkte 0,5].")
  end
  if el.text == "[Antwortlinie]" or el.text == "[antwortlinie]" then
    return raw_inline(macro_call("antwortlinie", ""))
  end
  if el.text == "[Platz]" or el.text == "[platz]" then
    return raw_inline(macro_call("platz", ""))
  end
end

function Pandoc(doc)
  doc.blocks = process_author_syntax(doc.blocks)
  -- Ein einzelner Schuelerfelder-Block gehoert in den
  -- Seitenkopf. Die Makroausgabe bleibt fuer fremde Templates kompatibel:
  -- nur unsere Templates werten diese Metadaten aus und unterdruecken dort
  -- das bisherige Feld im Fliesstext. Eigene Deckblaetter, Mini-ABs und mehrfache Felder
  -- behalten ihre lokale Position. Ein expliziter Abstand bleibt erhalten.
  local fields = 0
  local local_fields = false
  for _, block in ipairs(doc.blocks) do
    if block.t == "RawBlock" and block.format == TARGET then
      if block.text == macro_call("student_fields", "") then
        fields = fields + 1
      end
      if block.text:find("#mini_ab()", 1, true) or block.text:find("\\begin{miniab}", 1, true) then
        local_fields = true
      end
      if block.text:find("#title_page(", 1, true) or block.text:find("\\begin{mathedeckblatt}", 1, true) then
        local_fields = true
      end
    end
  end
  local position = pandoc.utils.stringify(doc.meta["student-fields-position"] or "")
  doc.meta["student-fields-header"] = fields == 1 and not local_fields and position ~= "body"
  return doc
end
