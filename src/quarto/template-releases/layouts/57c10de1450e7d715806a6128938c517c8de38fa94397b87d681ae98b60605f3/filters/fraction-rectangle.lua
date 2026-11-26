-- Rechteckanteile mit fester Bezugseinheit und gebundenen Beschriftungen.
return function(args, target)
  local options = {}
  for field in args:gmatch('|([^|]+)') do
    local key, value = field:match('^%s*([%a]+)%s*=%s*(.-)%s*$')
    if not key or not ({werte=true,raster=true,bildbreite=true,beschriftung=true,texte=true})[key] then
      error('Modell bruchrechteck: Unbekannte Option: ' .. field)
    end
    options[key] = value
  end
  if options.raster and options.raster ~= 'ja' and options.raster ~= 'nein' and options.raster ~= 'gestrichelt' then
    error('Modell bruchrechteck: raster muss ja, nein oder gestrichelt sein.')
  end
  if options.beschriftung and options.beschriftung ~= 'ja' and options.beschriftung ~= 'nein' then
    error('Modell bruchrechteck: beschriftung muss ja oder nein sein.')
  end
  if options.bildbreite then
    local size = tonumber(options.bildbreite:match('^(%d+%.?%d*)mm$'))
    if not size or size < 10 or size > 250 then error('Modell bruchrechteck: bildbreite muss 10–250mm sein.') end
  end
  local function split(value)
    local result={}
    for item in (value..','):gmatch('(.-),') do result[#result+1]=item:match('^%s*(.-)%s*$') end
    return result
  end
  local texts=options.texte and split(options.texte) or nil
  local values, width = {}, 12
  for _,item in ipairs(split(options.werte or '1/2')) do
    local blank=item == '?' or item == '_' or item == 'leer'
    local a,b=item:match('^(%d+)/(%d+)$')
    if not a then a,b=item:match('^(%d+)$'),'1' end
    a,b=tonumber(a),tonumber(b)
    if not blank and (not a or not b or b < 1 or b > 64 or a < 0 or a > 8*b) then
      error('Modell bruchrechteck: werte erwartet ? oder Brüche/Zahlen von 0 bis 8, Nenner 1–64.')
    end
    local units=blank and 1 or math.max(1,math.ceil(a/b))
    values[#values+1]={a=a,b=b,blank=blank,units=units,x=width,label=item}
    width=width+units*50+30
  end
  if #values < 1 or #values > 12 then error('Modell bruchrechteck: 1–12 Werte erforderlich.') end
  if texts and #texts ~= #values then error('Modell bruchrechteck: texte braucht einen Eintrag pro Wert.') end
  width=width-18
  local height=options.beschriftung == 'ja' and 150 or 120
  if texts then height=190 end
  local parts={string.format('<svg xmlns="http://www.w3.org/2000/svg" width="%g" height="%g" viewBox="0 0 %g %g">',width,height,width,height)}
  local function escape(value)
    return value:gsub('&','&amp;'):gsub('<','&lt;'):gsub('>','&gt;'):gsub('"','&quot;')
  end
  local function label(x,y,value,class)
    if value == '_' or value == '?' or value == 'leer' then
      parts[#parts+1]=string.format('<rect class="%s" x="%g" y="%g" width="40" height="20" fill="#eeeeee"/>',class,x-20,y-16)
    else
      local base,exponent=value:match('^(.-)%^([+-]?%d+)$')
      local content=base and (escape(base)..'<tspan baseline-shift="super" font-size="17">'..escape(exponent)..'</tspan>') or escape(value)
      parts[#parts+1]=string.format('<text class="%s" x="%g" y="%g" text-anchor="middle" font-family="DejaVu Sans, sans-serif" font-size="24" fill="#172033">%s</text>',class,x,y,content)
    end
  end
  for index,v in ipairs(values) do
    local attributes=v.blank and 'class="blank"' or string.format('class="fraction" data-numerator="%d" data-denominator="%d"',v.a,v.b)
    parts[#parts+1]='<g '..attributes..'>'
    local cols=1
    if not v.blank then
      for c=2,math.floor(math.sqrt(v.b))+1 do if v.b%c == 0 then cols=c end end
    end
    local rows=v.blank and 1 or v.b/cols
    for u=0,v.units-1 do
      local x,y=v.x+u*50,12
      local count=v.blank and 0 or math.max(0,math.min(v.b,v.a-u*v.b))
      parts[#parts+1]=string.format('<rect class="whole" x="%g" y="%g" width="50" height="100" fill="white" stroke="#82919c"%s/>',x,y,v.blank and '' or ' stroke-dasharray="3 3"')
      for cell=0,count-1 do
        parts[#parts+1]=string.format('<rect class="part" x="%g" y="%g" width="%g" height="%g" fill="#c4e5ef"/>',x+(cell%cols)*50/cols,y+100-(math.floor(cell/cols)+1)*100/rows,50/cols,100/rows)
      end
      if not v.blank and (options.raster == 'ja' or options.raster == 'gestrichelt') then
        local dash=options.raster == 'gestrichelt' and ' stroke-dasharray="3 3"' or ''
        for c=1,cols-1 do parts[#parts+1]=string.format('<path class="division" d="M %g %g v 100" stroke="#82919c" stroke-width="0.8"%s/>',x+c*50/cols,y,dash) end
        for r=1,rows-1 do parts[#parts+1]=string.format('<path class="division" d="M %g %g h 50" stroke="#82919c" stroke-width="0.8"%s/>',x,y+r*100/rows,dash) end
      end
      if count > 0 then
        local fullrows,rest=math.floor(count/cols),count%cols
        if fullrows>0 then parts[#parts+1]=string.format('<rect x="%g" y="%g" width="50" height="%g" fill="none" stroke="#167aa1" stroke-width="1.5"/>',x,y+100-fullrows*100/rows,fullrows*100/rows) end
        if rest>0 then parts[#parts+1]=string.format('<rect x="%g" y="%g" width="%g" height="%g" fill="none" stroke="#167aa1" stroke-width="1.5"/>',x,y+100-(fullrows+1)*100/rows,rest*50/cols,100/rows) end
      end
    end
    local center=v.x+v.units*25
    if options.beschriftung == 'ja' then label(center,143,v.label,'value-label') end
    if texts then label(center,180,texts[index],'custom-label') end
    parts[#parts+1]='</g>'
  end
  parts[#parts+1]='</svg>'
  local svg=table.concat(parts,'\n')
  local filename='bruchrechteck-'..pandoc.utils.sha1(svg)
  if target == 'latex' then
    filename=filename..'.pdf'
    pandoc.mediabag.insert(filename,'application/pdf',pandoc.pipe('rsvg-convert',{'--format=pdf'},svg))
  else filename=filename..'.svg';pandoc.mediabag.insert(filename,'image/svg+xml',svg) end
  return pandoc.Image({pandoc.Str('Rechteckmodell: '..(options.werte or '1/2'))},filename,'',pandoc.Attr('',{},{width=options.bildbreite or '100%'}))
end
