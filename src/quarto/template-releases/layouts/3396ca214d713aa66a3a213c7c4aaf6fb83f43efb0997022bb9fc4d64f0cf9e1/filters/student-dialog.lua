-- Compact, topic-independent learner dialogues. Loaded lazily by exam.lua.
local function has_class(el, wanted)
  for _, class in ipairs(el.classes) do if class == wanted then return true end end
  return false
end

local function quoted(value)
  return pandoc.json.encode(value)
end

local function portrait(style, shirt, hair_color, skin_color)
  local skin = skin_color or (style == 'zopf' and '#bd825b' or (style == 'locken' and '#8b5c43' or '#ecc49c'))
  local hair = style == 'brille' and '#b47c3e' or (style == 'kurz' and '#65513e' or '#382c32')
  hair = hair_color or hair
  local parts = {
    '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="140" viewBox="0 0 120 140">',
    '<g stroke="#384751" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round">',
    '<path d="M25 94Q60 77 95 94L106 135H14Z" fill="' .. shirt .. '"/>',
    '<path d="M45 82V94Q60 104 75 94V82" fill="' .. skin .. '"/>',
    '<ellipse cx="33" cy="54" rx="5" ry="8" fill="' .. skin .. '"/>',
    '<ellipse cx="87" cy="54" rx="5" ry="8" fill="' .. skin .. '"/>',
    '<ellipse cx="60" cy="52" rx="28" ry="34" fill="' .. skin .. '"/>',
  }
  if style == 'zopf' then
    table.insert(parts, '<path d="M84 29Q114 30 110 63L99 83Q91 58 94 40Z" fill="' .. hair .. '"/>')
    table.insert(parts, '<path d="M32 44Q20 16 52 13Q91 8 91 45L79 32Q60 43 48 30Z" fill="' .. hair .. '"/>')
    table.insert(parts, '<path d="M91 33L99 36" stroke="#ddaf59" stroke-width="5"/>')
  elseif style == 'locken' then
    table.insert(parts, '<path d="M32 45Q15 34 28 23Q23 8 40 11Q48 0 60 9Q76 0 83 14Q103 14 94 32Q102 46 86 48L80 31Q62 41 41 30Z" fill="' .. hair .. '"/>')
  else
    table.insert(parts, '<path d="M32 43Q22 15 49 12Q70 4 84 21L96 21L85 34L91 46L79 35Q62 43 49 29L40 45Z" fill="' .. hair .. '"/>')
  end
  table.insert(parts, '<path d="M47 49H51M69 49H73" stroke-width="2.5"/>')
  table.insert(parts, '<path d="M59 52L56 61H61" fill="none" stroke="#9f725b" stroke-width="1.3"/>')
  table.insert(parts, '<path d="M49 70Q60 79 72 69" fill="none"/>')
  if style == 'brille' then
    table.insert(parts, '<circle cx="47" cy="52" r="10" fill="none" stroke="#4b5965"/><circle cx="73" cy="52" r="10" fill="none" stroke="#4b5965"/><path d="M57 51H63M35 49L38 50M83 50L88 48" fill="none"/>')
  end
  table.insert(parts, '<path d="M28 104L21 126M90 101L100 111L111 93" fill="none" stroke="#e9f1ed" stroke-width="5"/>')
  table.insert(parts, '<path d="M108 96L108 85Q110 81 113 85L114 90L117 87Q121 89 117 94L113 100Z" fill="' .. skin .. '"/>')
  table.insert(parts, '<path d="M35 123H71" stroke="white" opacity="0.35" stroke-width="3"/>')
  table.insert(parts, '</g></svg>')
  return table.concat(parts)
end

local function image_body(blocks)
  -- Generated model SVGs live in the mediabag. Embed bytes rather than a
  -- temporary media path when serializing nested content to raw Typst.
  local content = pandoc.Div(blocks):walk({
    Figure = function(figure) return figure.content end,
    Image = function(img)
      local mime, bytes = pandoc.mediabag.lookup(img.src)
      if mime == 'image/svg+xml' and bytes then
        return pandoc.RawInline('typst', '#image(bytes(' .. quoted(bytes) .. '), width: ' .. (img.attributes.width or '100%') .. ')')
      end
    end,
  })
  return pandoc.write(pandoc.Pandoc(content.content), 'typst'):gsub('%s+$', '')
end

return function(el)
  local target = (FORMAT:match('latex') or FORMAT:match('pdf')) and 'latex' or 'typst'
  local presets = {brille = true, kurz = true, locken = true, zopf = true, keine = true}
  local colors = {'#2a7169', '#426a9c', '#875989', '#a06c36'}
  if #el.content < 1 or #el.content > 4 then error('Schülerdialog: Ein Dialog braucht 1–4 Beiträge.') end
  local people = {}
  for _, child in ipairs(el.content) do
    if child.t ~= 'Div' or not has_class(child, 'dialogbeitrag') then
      error('Schülerdialog: Beiträge als ::: {.dialogbeitrag name="Mia" figur="brille"} anlegen.')
    end
    local name = child.attributes.name or ''
    if name:match('^%s*$') then error('Schülerdialog: Jeder Beitrag braucht einen Namen.') end
    local style = child.attributes.figur or ({'brille', 'kurz', 'locken', 'zopf'})[#people + 1]
    if not presets[style] then error('Schülerdialog: figur muss brille, kurz, locken, zopf oder keine sein.') end
    local color = child.attributes.farbe or colors[#people + 1]
    if not color or not color:match('^#%x%x%x%x%x%x$') then error('Schülerdialog: farbe muss ein Hex-Code wie #2a7169 sein.') end
    local hair = child.attributes.haarfarbe
    if hair and not hair:match('^#%x%x%x%x%x%x$') then error('Schülerdialog: haarfarbe muss ein Hex-Code sein.') end
    local skin = child.attributes.hautfarbe
    if skin and not skin:match('^#%x%x%x%x%x%x$') then error('Schülerdialog: hautfarbe muss ein Hex-Code sein.') end
    local first = child.content[1]
    if not first or (first.t ~= 'Para' and first.t ~= 'Plain') or pandoc.utils.stringify(first):match('^%s*$') then
      error('Schülerdialog: Der erste Absatz jedes Beitrags enthält den gesprochenen Text.')
    end
    local image_in_quote = false
    first:walk({Image = function() image_in_quote = true end})
    if image_in_quote then error('Schülerdialog: Zuerst den gesprochenen Text schreiben; Bilder und Modelle folgen als eigener Absatz darunter.') end
    local rest = {}
    for i = 2, #child.content do table.insert(rest, child.content[i]) end
    table.insert(people, {name = name, style = style, color = color, hair = hair, skin = skin, quote = first, body = rest})
  end

  if target == 'latex' then
    local output = {pandoc.RawBlock('latex', '\\par\\smallskip\\noindent')}
    local fraction = (1 - 0.025 * (#people - 1)) / #people
    for i, person in ipairs(people) do
      if i > 1 then table.insert(output, pandoc.RawBlock('latex', '\\hfill')) end
      table.insert(output, pandoc.RawBlock('latex', '\\begin{minipage}[t]{' .. string.format('%.4f', fraction) .. '\\linewidth}\\vspace{0pt}\\small\n\\fcolorbox[HTML]{' .. person.color:sub(2) .. '}{FFFFFF}{\\begin{minipage}{\\dimexpr\\linewidth-2\\fboxsep-2\\fboxrule\\relax}'))
      table.insert(output, person.quote)
      table.insert(output, pandoc.RawBlock('latex', '\\end{minipage}}\\par\\smallskip'))
      local speaker = pandoc.List()
      if person.style ~= 'keine' then
        local svg = portrait(person.style, person.color, person.hair, person.skin)
        local file = 'dialogfigur-' .. pandoc.utils.sha1(svg) .. '.pdf'
        pandoc.mediabag.insert(file, 'application/pdf', pandoc.pipe('rsvg-convert', {'--format=pdf'}, svg))
        speaker:insert(pandoc.Image({}, file, '', pandoc.Attr('', {}, {width = '9mm'})))
        speaker:insert(pandoc.Space())
      end
      speaker:insert(pandoc.Strong({pandoc.Str(person.name)}))
      table.insert(output, pandoc.Para(speaker))
      for _, block in ipairs(person.body) do table.insert(output, block) end
      table.insert(output, pandoc.RawBlock('latex', '\\end{minipage}'))
    end
    table.insert(output, pandoc.RawBlock('latex', '\\par\\smallskip'))
    return output
  end

  -- Opt-in layout: portrait and speech share a row; examples follow directly.
  if el.attributes.layout == 'kompakt' then
    local columns = {}
    for _, person in ipairs(people) do
      local speaker = '#text(weight: "bold", fill: rgb(' .. quoted(person.color) .. '), ' .. quoted(person.name .. ':') .. ') '
      local speech = '[' .. speaker .. image_body({person.quote}) .. ']'
      local head = speech
      if person.style ~= 'keine' then
        head = '#grid(columns: (6mm, 1fr), column-gutter: 3pt, align: top, [#image(bytes(' .. quoted(portrait(person.style, person.color, person.hair, person.skin)) .. '), width: 6mm)], ' .. speech .. ')'
      end
      table.insert(columns, '[#block(width: 100%)[\n' .. head .. '\n]\n' .. image_body(person.body) .. '\n]')
    end
    return pandoc.RawBlock('typst', '#block(above: 3pt, below: 4pt, breakable: false)[\n#set text(size: 10pt)\n#set par(leading: 0.25em, spacing: 2pt)\n#set block(above: 3pt, below: 3pt)\n#grid(columns: (' .. string.rep('1fr, ', #people) .. '), column-gutter: 8pt, align: top, ' .. table.concat(columns, ', ') .. ')\n]')
  end

  local quotes, color_values = {}, {}
  for _, person in ipairs(people) do
    table.insert(quotes, '[' .. image_body({person.quote}) .. ']')
    table.insert(color_values, 'rgb(' .. quoted(person.color) .. ')')
  end
  local spec = string.rep('1fr, ', #people):gsub(', $', '')
  local code = '#block(above: 6pt, below: 8pt, breakable: false)[\n#set text(size: 10pt)\n#set par(leading: 0.35em, spacing: 3pt)\n#layout(size => {\nlet quotes = (' .. table.concat(quotes, ', ') .. ',)\nlet colors = (' .. table.concat(color_values, ', ') .. ',)\nlet column = (size.width - 8pt * ' .. (#people - 1) .. ') / ' .. #people .. '\nlet height = calc.max(..quotes.map(q => measure(block(width: column, inset: 7pt)[#q]).height))\ngrid(columns: (' .. spec .. '), column-gutter: 8pt, row-gutter: 5pt, align: top,\n..quotes.enumerate().map(((i, q)) => rect(width: 100%, height: height, inset: 7pt, radius: 5pt, stroke: 0.7pt + colors.at(i), fill: white)[#q]),'
  local output = {pandoc.RawBlock('typst', code)}
  for _, person in ipairs(people) do
    local tail = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="14" viewBox="0 0 24 14"><path d="M1 1H22L6 13Z" fill="white" stroke="' .. person.color .. '" stroke-width="1.1"/></svg>'
    local start = '[#block(width: 100%, height: 13mm)[\n#place(top + left, dx: 4mm, dy: -3mm, image(bytes(' .. quoted(tail) .. '), width: 5mm, height: 3mm))\n'
    if person.style == 'keine' then
      table.insert(output, pandoc.RawBlock('typst', start .. '#v(2mm)\n#text(weight: "bold", fill: rgb(' .. quoted(person.color) .. '), ' .. quoted(person.name) .. ')\n]],'))
    else
      table.insert(output, pandoc.RawBlock('typst', start .. '#grid(columns: (11mm, 1fr), column-gutter: 2mm, align: horizon, ['))
      local svg = portrait(person.style, person.color, person.hair, person.skin)
      local file = 'dialogfigur-' .. pandoc.utils.sha1(svg) .. '.svg'
      pandoc.mediabag.insert(file, 'image/svg+xml', svg)
      table.insert(output, pandoc.Plain({pandoc.Image({}, file, '', pandoc.Attr('', {}, {width = '10mm', height = '12mm'}))}))
      table.insert(output, pandoc.RawBlock('typst', '], [#text(weight: "bold", fill: rgb(' .. quoted(person.color) .. '), ' .. quoted(person.name) .. ')])\n]],'))
    end
  end
  for _, person in ipairs(people) do
    table.insert(output, pandoc.RawBlock('typst', '['))
    for _, block in ipairs(person.body) do table.insert(output, block) end
    table.insert(output, pandoc.RawBlock('typst', '],'))
  end
  table.insert(output, pandoc.RawBlock('typst', ')\n})\n]'))
  return output
end
