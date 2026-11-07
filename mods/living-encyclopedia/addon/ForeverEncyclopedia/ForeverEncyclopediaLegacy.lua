-- WoW Forever 70658: a real fourth page of Blizzard_LegacySystem.
-- We extend LegacySystemFrame.Pages/Tabs; the three native pages remain untouched.
-- All knowledge, creature and talent values come from the existing FEC1/FET1/FEB1
-- server status bridge; this file never invents collectible records or talent effects.
local bridge = _G.ForeverEncyclopediaUIBridge
if not bridge or not bridge.state or not bridge.catalog then return end

local state, catalog = bridge.state, bridge.catalog
local host, page, tab
local mode, branch, selectedNode = "talents", "protection", "aegis_unlock"
local selectedCreature = 1
local selectedAppearance = "living_book"
local pendingBuy = false
local ui = {}
local objects = {}
local pendingRefresh = false

local GOLD = {0.82, 0.59, 0.24}
local PALE = {0.96, 0.87, 0.72}
local MUTED = {0.67, 0.61, 0.53}
local GREEN = {0.38, 0.88, 0.43}
local RED = {0.91, 0.45, 0.38}
local BROWN = {0.10, 0.065, 0.037}
local DEEP = {0.046, 0.030, 0.022}

local function remember(o)
    objects[#objects + 1] = o
    return o
end

local function wipeView()
    for i = 1, #objects do objects[i]:Hide() end
    wipe(objects)
end

local function solid(parent, layer, rgba)
    local t = parent:CreateTexture(nil, layer or "BACKGROUND")
    t:SetTexture("Interface\\Buttons\\WHITE8X8")
    t:SetVertexColor(rgba[1], rgba[2], rgba[3], rgba[4] or 1)
    return t
end

local function edge(f, color)
    local r, g, b = color[1], color[2], color[3]
    local lines = {}
    local function one(pt1,pt2,w,h)
        local t = solid(f, "BORDER", {r,g,b,0.95})
        t:SetPoint(pt1,f,pt1,0,0)
        t:SetPoint(pt2,f,pt2,0,0)
        if w then t:SetWidth(w) end
        if h then t:SetHeight(h) end
        lines[#lines+1] = t
    end
    one("TOPLEFT","TOPRIGHT",nil,2)
    one("BOTTOMLEFT","BOTTOMRIGHT",nil,2)
    one("TOPLEFT","BOTTOMLEFT",2,nil)
    one("TOPRIGHT","BOTTOMRIGHT",2,nil)
    return lines
end

local function frame(parent, x, y, w, h, color)
    local f = remember(CreateFrame("Frame",nil,parent))
    f:SetPoint("TOPLEFT",parent,"TOPLEFT",x,-y)
    f:SetSize(w,h)
    local background=solid(f,"BACKGROUND",color or DEEP)
    background:SetAllPoints()
    edge(f,GOLD)
    return f
end

local function font(parent,x,y,w,text,style,color,align)
    local f = parent:CreateFontString(nil,"OVERLAY",style or "GameFontNormal")
    f:SetPoint("TOPLEFT",parent,"TOPLEFT",x,-y)
    f:SetWidth(w)
    f:SetJustifyH(align or "LEFT")
    f:SetText(text or "")
    if color then f:SetTextColor(unpack(color)) end
    return f
end

local function label(parent,x,y,w,text,style,color,align)
    local f = remember(CreateFrame("Frame",nil,parent))
    f:SetPoint("TOPLEFT",parent,"TOPLEFT",x,-y)
    f:SetSize(w,34)
    font(f,0,0,w,text,style,color,align)
    return f
end

local function button(parent,x,y,w,h,text,selected,fn)
    local b=remember(CreateFrame("Button",nil,parent))
    b:SetSize(w,h)
    b:SetPoint("TOPLEFT",parent,"TOPLEFT",x,-y)
    local bg=solid(b,"BACKGROUND",selected and {0.29,0.16,0.043,1} or BROWN)
    bg:SetAllPoints()
    edge(b,selected and {0.94,0.68,0.19} or GOLD)
    local word=font(b,0,math.floor((h-18)/2),w,text,"GameFontHighlight",PALE,"CENTER")
    b:SetScript("OnEnter",function()
        bg:SetVertexColor(0.22,0.14,0.07,1)
        word:SetTextColor(1,0.93,0.73)
    end)
    b:SetScript("OnLeave",function()
        bg:SetVertexColor(selected and 0.29 or BROWN[1],selected and 0.16 or BROWN[2],
                          selected and 0.043 or BROWN[3],1)
        word:SetTextColor(unpack(PALE))
    end)
    b:SetScript("OnClick",fn)
    return b
end

local function emblem(parent,x,y,w,h,path)
    local f=remember(CreateFrame("Frame",nil,parent))
    f:SetPoint("TOPLEFT",parent,"TOPLEFT",x,-y)
    f:SetSize(w,h)
    local bg=solid(f,"BACKGROUND",{0.13,0.077,0.038,1})
    bg:SetAllPoints()
    edge(f,GOLD)
    local icon=f:CreateTexture(nil,"ARTWORK")
    icon:SetPoint("TOPLEFT",f,"TOPLEFT",4,-4)
    icon:SetPoint("BOTTOMRIGHT",f,"BOTTOMRIGHT",-4,4)
    icon:SetTexture(path)
    icon:SetTexCoord(0.08,0.92,0.08,0.92)
    return f,icon
end

local function heading(parent,x,y,w,text)
    label(parent,x,y,w,text,"GameFontNormalLarge",{1,0.80,0.34},"CENTER")
    local line=solid(parent,"ARTWORK",{0.62,0.42,0.15,0.88})
    line:SetPoint("TOPLEFT",parent,"TOPLEFT",x,-(y+25))
    line:SetSize(w,2)
end

local function tooltip(owner,name,description,more)
    GameTooltip:SetOwner(owner,"ANCHOR_RIGHT")
    GameTooltip:AddLine(name or "",1,0.80,0.30)
    if description and description~="" then
        GameTooltip:AddLine(description,0.86,0.84,0.77,true)
    end
    if more then GameTooltip:AddLine(more,0.52,0.86,0.60,true) end
    GameTooltip:Show()
end

local function selectMode(nextMode)
    mode=nextMode
    pendingBuy=false
    if mode=="collection" then bridge.RequestStatus() end
    if mode=="creatures" then bridge.RequestCatalog(state.catalogPage or 1) end
    if mode=="zones" then bridge.RequestZones() end
    _G.ForeverEncyclopediaLegacy.Refresh("view")
end

local function talent(key)
    for _, n in ipairs(catalog.nodes) do if n.key==key then return n end end
end

local function checkPrereq(n)
    return not n.req or (state.ranks[n.req] or 0)>=(n.reqRank or 1)
end

local function drawLine(parent,x,y,w,h,on)
    local t=solid(parent,"ARTWORK",on and {0.73,0.56,0.23,0.90} or {0.27,0.23,0.18,0.85})
    t:SetPoint("TOPLEFT",parent,"TOPLEFT",x,-y)
    t:SetSize(math.max(2,w),math.max(2,h))
end

local function drawLink(parent,from,to,enabled)
    -- Square elbow connectors, in the same direction as the native Legacy tree.
    local aY=-from.y-25
    local bY=-to.y+25
    local mid=(aY+bY)/2
    local top=math.min(aY,mid)
    local bottom=math.max(aY,mid)
    drawLine(parent,from.x-1,-bottom,2,bottom-top,enabled)
    drawLine(parent,math.min(from.x,to.x),-mid,math.abs(from.x-to.x),2,enabled)
    local top2=math.min(mid,bY)
    local bottom2=math.max(mid,bY)
    drawLine(parent,to.x-1,-bottom2,2,bottom2-top2,enabled)
end

local function node(parent,x,y,n)
    local rank=state.ranks[n.key] or 0
    local eligible=n.implemented and checkPrereq(n)
    local full=rank>=n.max
    local chosen=selectedNode==n.key
    local b=remember(CreateFrame("Button",nil,parent))
    b:SetPoint("CENTER",parent,"TOPLEFT",x,-y)
    b:SetSize(49,49)
    local bg=solid(b,"BACKGROUND",{0.030,0.029,0.027,1})
    bg:SetAllPoints()
    edge(b,(full or (rank>0) or eligible) and GREEN or {0.32,0.29,0.25})
    local icon=b:CreateTexture(nil,"ARTWORK")
    icon:SetPoint("TOPLEFT",b,"TOPLEFT",4,-4)
    icon:SetPoint("BOTTOMRIGHT",b,"BOTTOMRIGHT",-4,4)
    icon:SetTexture(n.icon)
    icon:SetTexCoord(0.08,0.92,0.08,0.92)
    icon:SetDesaturated(not eligible and rank==0)
    icon:SetAlpha((eligible or rank>0) and 1 or 0.36)
    font(b,23,32,42,rank.."/"..n.max,"GameFontNormalSmall",
                       (eligible or rank>0) and PALE or MUTED,"CENTER")
    if chosen then
        local glow=b:CreateTexture(nil,"OVERLAY")
        glow:SetAllPoints()
        glow:SetTexture("Interface\\Buttons\\UI-ActionButton-Border")
        glow:SetBlendMode("ADD")
        glow:SetVertexColor(1,0.74,0.20,0.90)
    end
    label(parent,x-67,y+29,134,n.name,"GameFontNormalSmall",eligible and PALE or MUTED,"CENTER")
    b:SetScript("OnClick",function()
        selectedNode=n.key
        pendingBuy=false
        _G.ForeverEncyclopediaLegacy.Refresh("view")
    end)
    b:SetScript("OnEnter",function()
        local desc=n.desc
        if catalog.EffectPreview then
            local now,following=catalog.EffectPreview(n,rank,state.ranks,state.maxMana)
            desc=desc.."\nСейчас: "..tostring(now)
            if not full then desc=desc.."\nСлед. ранг: "..tostring(following) end
        end
        tooltip(b,n.name,desc,n.implemented and "Нажмите, чтобы выбрать" or "В разработке. Покупка недоступна")
    end)
    b:SetScript("OnLeave",function() GameTooltip:Hide() end)
end

local function category(parent,x,y,w,h,title,stat,icon,action,locked,small)
    local b=remember(CreateFrame("Button",nil,parent))
    b:SetSize(w,h)
    b:SetPoint("TOPLEFT",parent,"TOPLEFT",x,-y)
    local bg=solid(b,"BACKGROUND",locked and {0.060,0.055,0.052,1} or {0.13,0.078,0.036,1})
    bg:SetAllPoints()
    edge(b,locked and {0.35,0.33,0.30} or {0.72,0.49,0.18})
    local size=small and 29 or 67
    local ii=b:CreateTexture(nil,"ARTWORK")
    ii:SetSize(size,size)
    ii:SetPoint("TOPLEFT",b,"TOPLEFT",small and 7 or 17,-(small and 10 or 19))
    ii:SetTexture(icon)
    ii:SetTexCoord(0.08,0.92,0.08,0.92)
    ii:SetDesaturated(locked)
    ii:SetAlpha(locked and 0.45 or 1)
    local inset=small and 43 or 98
    font(b,inset,small and 12 or 28,w-inset-6,title,small and "GameFontNormalSmall" or "GameFontHighlight",locked and MUTED or PALE)
    font(b,inset,small and 37 or 66,w-inset-8,stat,"GameFontNormalSmall",locked and MUTED or GREEN)
    if action then
        b:SetScript("OnClick",action)
        b:SetScript("OnEnter",function()
            bg:SetVertexColor(0.24,0.15,0.06,1)
            tooltip(b,title,stat,"Открыть записи")
        end)
        b:SetScript("OnLeave",function()
            bg:SetVertexColor(0.13,0.078,0.036,1)
            GameTooltip:Hide()
        end)
    else
        b:Disable()
        b:SetScript("OnEnter",function() tooltip(b,title,"Пока нет серверных данных для подробного каталога.") end)
        b:SetScript("OnLeave",function() GameTooltip:Hide() end)
    end
    return b
end

local function creatureCount()
    if state.catalogTotal and state.catalogTotal>0 then
        return (state.catalogKnown or 0).."/"..state.catalogTotal.." встречено"
    end
    return (state.creatures or 0).." открыто"
end

local COLLECTION = {
    {key="creatures",title="Существа",icon="Interface\\Icons\\Ability_Hunter_Pet_Bear"},
    {key="items",title="Предметы",icon="Interface\\Icons\\INV_Misc_Bag_10"},
    {key="zones",title="Локации",icon="Interface\\Icons\\INV_Misc_Map_01"},
    {key="rare",title="Редкости",icon="Interface\\Icons\\INV_Misc_Gem_Diamond_01"},
}
local function collectionStat(key)
    if key=="creatures" then return creatureCount() end
    if key=="items" then return (state.items or 0).." открыто" end
    if key=="zones" then return (state.zones or 0).." открыто" end
    return "Каталог ещё не доступен"
end

local function smallCollections(parent,x,y)
    heading(parent,x,y,285,"Собранные знания")
    for i,cat in ipairs(COLLECTION) do
        local col=(i-1)%2
        local row=math.floor((i-1)/2)
        category(parent,x+5+col*143,y+43+row*77,137,69,cat.title,collectionStat(cat.key),
                 cat.icon,cat.key~="rare" and function() selectMode(cat.key) end or nil,
                 cat.key=="rare",true)
    end
end

local function selectedTalentDetail(parent,x,y,w)
    local n=talent(selectedNode)
    if not n or n.branch~=branch then
        for _,candidate in ipairs(catalog.nodes) do
            if candidate.branch==branch then n=candidate; selectedNode=n.key; break end
        end
    end
    if not n then return end
    local rank=state.ranks[n.key] or 0
    local cost=rank<n.max and ForeverEncyclopediaTalentCost(n,rank) or 0
    local meets=checkPrereq(n)
    label(parent,x,y,w,n.name,"GameFontHighlight",PALE)
    local now,nextValue="",""
    if catalog.EffectPreview then now,nextValue=catalog.EffectPreview(n,rank,state.ranks,state.maxMana) end
    label(parent,x,y+27,w,"Ранг "..rank.."/"..n.max.. "  •  "..tostring(now),
          "GameFontNormalSmall",GREEN)
    local detail=label(parent,x,y+54,w,n.desc,"GameFontNormalSmall",MUTED)
    detail:SetHeight(55)
    if n.req then
        local requirement=talent(n.req)
        label(parent,x,y+114,w,"Нужно: "..(requirement and requirement.name or n.req).." ("..(n.reqRank or 1)..")",
              "GameFontNormalSmall",MUTED)
    end
    local status
    if not n.implemented then status="В разработке"
    elseif rank>=n.max then status="Максимальный ранг"
    elseif not meets then status="Требуется предыдущий талант"
    elseif state.knowledgeAvailable<cost then status="Не хватает знаний"
    elseif pendingBuy then status="Ожидание ответа сервера"
    else status="След. ранг: "..tostring(nextValue).."  •  цена "..cost end
    label(parent,x,y+143,w,status,"GameFontNormalSmall",n.implemented and GREEN or RED)
    local buy=button(parent,x+5,y+169,w-10,26,"Изучить за "..cost.." знаний",false,function()
        if pendingBuy or not n.implemented or rank>=n.max or not meets or state.knowledgeAvailable<cost then return end
        pendingBuy=true
        bridge.BuyTalent(n.key) -- server validates prerequisite, budget, rank and combat restrictions
        _G.ForeverEncyclopediaLegacy.Refresh("view")
    end)
    if not n.implemented or rank>=n.max or not meets or state.knowledgeAvailable<cost or pendingBuy then buy:Disable() end
end

local function drawTalentView()
    local left=frame(page,13,63,554,444,DEEP)
    local right=frame(page,580,63,307,444,DEEP)
    heading(left,12,10,530,"Таланты книги")
    label(left,18,38,520,"Выберите одну из пяти веток. Каждый узел — настоящий талант.",
          "GameFontNormalSmall",MUTED)
    for i,key in ipairs(catalog.order) do
        local d=catalog.branches[key]
        local x=9+(i-1)*108
        local b=button(left,x,61,103,52,"",key==branch,function()
            branch=key
            selectedNode=nil
            pendingBuy=false
            _G.ForeverEncyclopediaLegacy.Refresh("view")
        end)
        local icon=b:CreateTexture(nil,"ARTWORK")
        icon:SetSize(27,27); icon:SetPoint("TOP",b,"TOP",0,-2)
        icon:SetTexture(d.icon)
        font(b,0,31,103,d.name,"GameFontNormalSmall",PALE,"CENTER")
        -- The top icon is visual; click target is the full 103x52 tab.
    end
    local xPositions={102,276,450}
    local positions={}
    for _,n in ipairs(catalog.nodes) do
        if n.branch==branch then
            positions[n.key]={x=xPositions[n.col],y=151+(n.tier-1)*60}
        end
    end
    for _,n in ipairs(catalog.nodes) do
        if n.branch==branch and n.req and positions[n.req] and positions[n.key] then
            drawLink(left,positions[n.req],positions[n.key],checkPrereq(n))
        end
    end
    for _,n in ipairs(catalog.nodes) do
        if n.branch==branch and positions[n.key] then
            node(left,positions[n.key].x,positions[n.key].y,n)
        end
    end
    smallCollections(right,10,8)
    selectedTalentDetail(right,17,213,274)
end

local function drawCollectionView()
    local base=frame(page,13,63,874,444,DEEP)
    heading(base,18,12,838,"Собранные знания")
    label(base,28,48,798,"Знания всей учётной записи. Нажмите на категорию, чтобы открыть реальные записи.",
          "GameFontNormalSmall",MUTED)
    label(base,28,76,790,"Открытий: "..(state.total or 0).."    •    Накоплено знаний: "..(state.knowledgeTotal or 0)..
        "    •    Свободно: "..(state.knowledgeAvailable or 0),
        "GameFontHighlight",PALE)
    for i,cat in ipairs(COLLECTION) do
        local col=(i-1)%2
        local row=math.floor((i-1)/2)
        category(base,20+col*433,120+row*155,411,142,cat.title,collectionStat(cat.key),
                 cat.icon,cat.key~="rare" and function() selectMode(cat.key) end or nil,
                 cat.key=="rare")
    end
end

local function drawArchiveHeading(base,title,desc)
    heading(base,15,12,840,title)
    label(base,28,48,800,desc,"GameFontNormalSmall",MUTED)
    button(base,16,383,140,32,"Назад к коллекции",false,function() selectMode("collection") end)
end

local function drawCreatureView()
    local base=frame(page,13,63,874,444,DEEP)
    drawArchiveHeading(base,"Архив существ","Показываются только записи, доступные через серверный каталог.")
    local list=frame(base,16,82,465,292,BROWN)
    local detail=frame(base,496,82,360,292,BROWN)
    if not state.catalogLoaded then
        label(list,18,18,420,"Получаю записи с сервера…","GameFontHighlight",PALE)
        return
    end
    for i,rec in ipairs(state.catalog or {}) do
        if i>7 then break end
        local name=rec.known and (rec.name~="" and rec.name or "Запись "..rec.entry) or "???"
        local b=button(list,10,8+(i-1)*39,445,34,name,i==selectedCreature,function()
            selectedCreature=i
            if rec.known then bridge.RequestCreatureInfo(rec.entry) end
            _G.ForeverEncyclopediaLegacy.Refresh("view")
        end)
        local badge=font(b,333,9,105,rec.known and "Встречено" or "Неизвестно",
                         "GameFontNormalSmall",rec.known and GREEN or MUTED,"RIGHT")
    end
    local rec=state.catalog[selectedCreature]
    if rec then
        local info=state.creatureInfo[rec.entry] or {}
        label(detail,16,18,326,rec.known and (rec.name or "Запись") or "Неизвестное существо",
              "GameFontHighlight",PALE)
        label(detail,16,61,326,rec.known and "Открыто в бестиарии" or "Не встречено",
              "GameFontNormal",rec.known and GREEN or MUTED)
        label(detail,16,93,326,rec.known and ("Номер записи: "..rec.entry) or "Сведения скрыты до открытия",
              "GameFontNormalSmall",MUTED)
        if rec.known and state.infoLevel>=3 then
            label(detail,16,127,326,"Уровни: "..(info.minLevel or "?").."–"..(info.maxLevel or "?"),
                  "GameFontNormalSmall",MUTED)
        else
            label(detail,16,127,326,"Дополнительные сведения открываются талантами Познания.",
                  "GameFontNormalSmall",MUTED)
        end
    else
        label(detail,16,16,326,"Пока нет записей на этой странице.","GameFontNormal",MUTED)
    end
    label(base,286,394,270,"Страница "..(state.catalogPage or 1).." из "..(state.catalogPages or 1),
          "GameFontNormalSmall",MUTED,"CENTER")
    local prev=button(base,575,382,125,33,"Назад",false,function()
        if state.catalogPage>1 then bridge.RequestCatalog(state.catalogPage-1) end
    end)
    local nextPage=button(base,709,382,125,33,"Далее",false,function()
        if state.catalogPage<state.catalogPages then bridge.RequestCatalog(state.catalogPage+1) end
    end)
    if state.catalogPage<=1 then prev:Disable() end
    if state.catalogPage>=state.catalogPages then nextPage:Disable() end
end

local function drawZoneView()
    local base=frame(page,13,63,874,444,DEEP)
    drawArchiveHeading(base,"Изученные локации",
        "Открытия привязаны к учётной записи. Здесь показаны последние записи сервера.")
    if not state.recentZonesLoaded then
        label(base,30,114,780,"Получаю список локаций…","GameFontHighlight",PALE)
        return
    end
    if #state.recentZones==0 then
        label(base,30,114,780,"Пока нет изученных локаций.","GameFontNormal",MUTED)
        return
    end
    for i,rec in ipairs(state.recentZones) do
        if i>10 then break end
        local col=(i-1)%2
        local row=math.floor((i-1)/2)
        local title=bridge.AreaName(rec.entry) or ("Локация "..(rec.entry or 0))
        category(base,20+col*425,99+row*56,408,50,title,
                 "Открыта", "Interface\\Icons\\INV_Misc_Map_01",nil,false,true)
    end
end

local function drawItemView()
    local base=frame(page,13,63,874,444,DEEP)
    drawArchiveHeading(base,"Коллекция предметов","Количество открытий получено от сервера.")
    local b=frame(base,80,117,710,200,BROWN)
    local icon=b:CreateTexture(nil,"ARTWORK")
    icon:SetTexture("Interface\\Icons\\INV_Misc_Bag_10")
    icon:SetSize(95,95); icon:SetPoint("TOP",b,"TOP",0,-17)
    label(b,22,126,660,(state.items or 0).." уникальных предметов изучено",
          "GameFontHighlightLarge",PALE,"CENTER")
    label(b,22,160,660,"Сервер пока не отправляет постраничный перечень предметов.",
          "GameFontNormalSmall",MUTED,"CENTER")
end

local function drawAppearanceView()
    local base=frame(page,13,63,874,444,DEEP)
    heading(base,12,12,850,"Облики Живой книги")
    label(base,25,46,816,"Внешний вид не меняет силу и не расходует ману. Открытия проверяет сервер.",
          "GameFontNormalSmall",MUTED)
    for i,a in ipairs(catalog.appearances or {}) do
        local col=(i-1)%2
        local row=math.floor((i-1)/2)
        local x=16+col*427
        local y=86+row*111
        local unlocked=state.appearances[a.key] and state.appearances[a.key].unlocked
        local b=frame(base,x,y,408,101,unlocked and BROWN or DEEP)
        emblem(b,13,10,76,76,"Interface\\Icons\\INV_Misc_Book_09")
        label(b,114,19,274,a.name,"GameFontHighlight",unlocked and PALE or MUTED)
        label(b,114,47,274,unlocked and "Открыт" or ("Требуется знаний: "..a.threshold),
              "GameFontNormalSmall",unlocked and GREEN or MUTED)
        if state.selectedAppearance==a.key then
            label(b,114,72,270,"Используется","GameFontNormalSmall",GREEN)
        elseif unlocked then
            button(b,116,66,190,30,"Выбрать облик",false,function()
                bridge.SelectAppearance(a.key)
            end)
        else
            label(b,114,72,274,"Недоступен","GameFontNormalSmall",MUTED)
        end
    end
end

local function render()
    if not page or not page:IsShown() then return end
    wipeView()
    if not ui.shell then
        ui.shell=solid(page,"BACKGROUND",{0.053,0.033,0.020,1})
        ui.shell:SetAllPoints()
    end
    local header=frame(page,13,6,874,48,BROWN)
    label(header,14,8,266,"Живая энциклопедия","GameFontNormalLarge",PALE)
    label(header,280,12,277,"Знания: "..(state.knowledgeAvailable or 0)..
        "   •   Мана: "..(state.mana or 0).."/"..(state.maxMana or 100),
        "GameFontNormalSmall",GOLD)
    button(header,565,5,102,36,"Таланты",mode=="talents",function() selectMode("talents") end)
    button(header,676,5,102,36,"Коллекция",mode~="talents" and mode~="appearance",function() selectMode("collection") end)
    button(header,787,5,79,36,"Облики",mode=="appearance",function() selectMode("appearance") end)
    if mode=="talents" then drawTalentView()
    elseif mode=="collection" then drawCollectionView()
    elseif mode=="creatures" then drawCreatureView()
    elseif mode=="zones" then drawZoneView()
    elseif mode=="items" then drawItemView()
    else drawAppearanceView() end
end

local function install()
    if host and page and tab then return true end
    local parent = _G.LegacySystemFrame
    if not parent or not parent.Pages or not parent.Tabs or not parent.LegacyTreeTab then return false end
    if not parent.SelectPage or not parent.SetTitle then return false end
    if _G.ForeverEncyclopediaLegacyTab then
        tab=_G.ForeverEncyclopediaLegacyTab
        page=_G.ForeverEncyclopediaLegacyPage
        host=parent
        return tab~=nil and page~=nil
    end
    host=parent
    -- Native LegacySystemFrameTabMixin supplies the exact border/hover art and
    -- mouse handling used by the existing three tabs.
    tab=CreateFrame("Frame","ForeverEncyclopediaLegacyTab",host,"LegacySystemTabTemplate")
    tab:SetID(4)
    tab:SetPoint("TOPLEFT",host.LegacyTreeTab,"BOTTOMLEFT",0,-2)
    tab.tooltipText="Живая энциклопедия"
    tab.iconTexture="Interface\\Icons\\INV_Misc_Book_09"
    if tab.Icon then tab.Icon:SetTexture(tab.iconTexture) end
    if tab.SetCustomOnMouseUpHandler then
        tab:SetCustomOnMouseUpHandler(function(_,mouse,inside)
            if mouse=="LeftButton" and inside then host:SelectPage(4) end
        end)
    else
        tab:SetScript("OnMouseUp",function(_,mouse)
            if mouse=="LeftButton" then host:SelectPage(4) end
        end)
    end
    page=CreateFrame("Frame","ForeverEncyclopediaLegacyPage",host)
    page:SetPoint("TOPLEFT",host,"TOPLEFT",5,-36)
    page:SetPoint("BOTTOMRIGHT",host,"BOTTOMRIGHT",-5,5)
    page:SetFrameLevel(host:GetFrameLevel()+101)
    page:EnableMouse(true)
    page:Hide()
    page:SetScript("OnShow",function()
        host:SetTitle("Живая энциклопедия")
        pendingBuy=false
        bridge.RequestStatus()
        render()
    end)
    table.insert(host.Tabs,tab)
    table.insert(host.Pages,page)
    tab:SetChecked(false)
    return true
end

local function loadNative()
    if install() then return true end
    if C_AddOns and C_AddOns.LoadAddOn then pcall(C_AddOns.LoadAddOn,"Blizzard_LegacySystem") end
    return install()
end

_G.ForeverEncyclopediaLegacy = {
    Install=install,
    Open=function()
        if not loadNative() then return false end
        if InCombatLockdown and InCombatLockdown() then
            if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cffffd275[Энциклопедия]|r Откройте книгу вне боя.") end
            return true
        end
        if host:IsShown() and host.currentPage==4 then
            HideUIPanel(host)
        else
            if not host:IsShown() then ShowUIPanel(host) end
            host:SelectPage(4)
        end
        return true
    end,
    Refresh=function(kind)
        if not page or not page:IsShown() then return end
        if kind=="mana" then
            -- Re-render only when values change, not on every C_Timer tick.
            if not pendingRefresh then
                pendingRefresh=true
                C_Timer.After(0.05,function()
                    pendingRefresh=false
                    if page and page:IsShown() then render() end
                end)
            end
        else
            if kind=="talents" then pendingBuy=false end
            render()
        end
    end,
}

local events=CreateFrame("Frame")
events:RegisterEvent("ADDON_LOADED")
events:RegisterEvent("PLAYER_LOGIN")
events:SetScript("OnEvent",function(_,e,name)
    if e=="PLAYER_LOGIN" or (e=="ADDON_LOADED" and name=="Blizzard_LegacySystem") then
        install()
    end
end)
if _G.LegacySystemFrame then install() end
