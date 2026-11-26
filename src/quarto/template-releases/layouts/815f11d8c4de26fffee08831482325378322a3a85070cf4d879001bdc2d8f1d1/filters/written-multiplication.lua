-- Place-value aligned worked multiplication; independent of worksheet designs.
return function(args)
  local options = {}
  for field in args:gmatch('|([^|]+)') do
    local key, value = field:match('^%s*([%a]+)%s*=%s*(.-)%s*$')
    if not key or not ({aufgabe=true, nullzeile=true, bildbreite=true, gruppen=true})[key] then
      error('Modell schriftlich: Unbekannte Option: ' .. field)
    end
    options[key] = value
  end
  local task = (options.aufgabe or ''):gsub('%s+', ''):gsub('·', '*'):gsub('×', '*')
  local left, right = task:match('^(%d+)%*(%d+)$')
  if not left or #left > 6 or #right > 6 or (#left > 1 and left:sub(1,1) == '0') or (#right > 1 and right:sub(1,1) == '0') then
    error('Modell schriftlich: aufgabe braucht zwei natürliche Faktoren mit je 1–6 Ziffern, z. B. 356*17.')
  end
  local size = options.bildbreite or '65mm'
  local mm = tonumber(size:match('^(%d+%.?%d*)mm$'))
  if not mm or mm < 10 or mm > 250 then error('Modell schriftlich: bildbreite muss zwischen 10mm und 250mm liegen.') end
  local zero = options.nullzeile or 'nein'
  if zero ~= 'ja' and zero ~= 'nein' then error('Modell schriftlich: nullzeile muss ja oder nein sein.') end
  local grouping = options.gruppen or 'keine'
  if grouping ~= 'keine' and grouping ~= 'zeilen' then error('Modell schriftlich: gruppen muss keine oder zeilen sein.') end
  local rows = {}
  for i = 1, #right do
    local digit = tonumber(right:sub(i,i))
    if digit ~= 0 or zero == 'ja' then
      table.insert(rows, {value = tonumber(left) * digit, place = #right-i})
    end
  end
  if #right == 1 and right ~= '0' then rows = {} end
  local result = string.format('%.0f', tonumber(left) * tonumber(right))
  local columns = math.max(#left + 1 + #right, #result) + 1
  local width, height = columns * 28 + 12, (#rows + 2) * 28 + 12
  local parts = {string.format('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">', width,height,width,height)}
  for x=0,columns do table.insert(parts,string.format('<path d="M %g 6 V %g" stroke="#cbd5dc" stroke-width="0.8"/>',6+x*28,height-6)) end
  for y=0,#rows+2 do table.insert(parts,string.format('<path d="M 6 %g H %g" stroke="#cbd5dc" stroke-width="0.8"/>',6+y*28,width-6)) end
  local function digits(value, row, shift, class, color)
    color = color or '#35516c'
    for i=1,#value do
      local place = #value-i+shift
      table.insert(parts,string.format('<text class="%s" data-stelle="%d" x="%g" y="%g" text-anchor="middle" font-family="DejaVu Sans Mono, monospace" font-size="20" fill="%s">%s</text>',class,place,6+(columns-1-place+0.5)*28,6+row*28+21,color,(value:sub(i,i) == '*' and '·' or value:sub(i,i))))
    end
  end
  digits(left .. '*' .. right,0,0,'aufgabenziffer')
  local colors = {'#c62828', '#1565c0', '#2e7d32', '#8a6d00'}
  for i,row in ipairs(rows) do
    local color = grouping == 'zeilen' and colors[(i-1) % #colors+1] or nil
    digits(row.value == 0 and string.rep('0', #left) or string.format('%.0f',row.value),i,row.place,'teilprodukt',color)
  end
  local y=6+(#rows+1)*28
  table.insert(parts,string.format('<path d="M 6 %g H %g" stroke="#35516c" stroke-width="1.8"/>',y,width-6))
  digits(result,#rows+1,0,'ergebnisziffer')
  table.insert(parts,'</svg>')
  local svg=table.concat(parts,'\n')
  local latex=FORMAT:match('latex') or FORMAT:match('pdf')
  local filename='schriftlich-' .. pandoc.utils.sha1(svg) .. (latex and '.pdf' or '.svg')
  pandoc.mediabag.insert(filename,latex and 'application/pdf' or 'image/svg+xml',latex and pandoc.pipe('rsvg-convert',{'--format=pdf'},svg) or svg)
  return pandoc.Image({pandoc.Str(left .. ' mal ' .. right .. ' schriftlich')},filename,'',pandoc.Attr('',{},{width=size}))
end
