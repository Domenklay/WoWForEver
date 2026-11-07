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
local selectedCreatureEntry
local creatureSearch = ""
local creatureType = 0
local creatureLocation = 0
local activeMonsterFilter = "all"
local selectedItem = 1
local selectedAppearance = "living_book"
local pendingBuy = false
local ui = {}
local objects = {}
local scrollPositions = {}
local activeScrolls = {}

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
    for key, scroll in pairs(activeScrolls) do
        if scroll.GetVerticalScroll then scrollPositions[key]=scroll:GetVerticalScroll() end
    end
    wipe(activeScrolls)
    for i = 1, #objects do objects[i]:Hide() end
    wipe(objects)
    ui.archivePopup=nil
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

-- Native ScrollFrame clips its child, preserving the visible page and
-- position when a server response redraws the current archive.
local function scrollArea(parent,x,y,w,h,key,childHeight)
    local scroll=remember(CreateFrame("ScrollFrame",nil,parent,"UIPanelScrollFrameTemplate"))
    scroll:SetPoint("TOPLEFT",parent,"TOPLEFT",x,-y)
    scroll:SetSize(w,h)
    local child=CreateFrame("Frame",nil,scroll)
    child:SetSize(w-28,math.max(h,childHeight or h))
    scroll:SetScrollChild(child)
    if scroll.SetVerticalScroll then
        scroll:SetVerticalScroll(math.min(scrollPositions[key] or 0,math.max(0,child:GetHeight()-h)))
    end
    scroll:EnableMouseWheel(true)
    scroll:SetScript("OnMouseWheel",function(self,delta)
        local maxOffset=math.max(0,child:GetHeight()-h)
        local nextOffset=math.max(0,math.min(maxOffset,(self:GetVerticalScroll() or 0)-delta*44))
        self:SetVerticalScroll(nextOffset)
        scrollPositions[key]=nextOffset
    end)
    activeScrolls[key]=scroll
    return child,scroll
end

local function paragraph(parent,x,y,w,text,style,color,spacing)
    local f=font(parent,x,y,w,text,style or "GameFontNormalSmall",color or MUTED)
    if f.SetWordWrap then f:SetWordWrap(true) end
    local measured=f.GetStringHeight and f:GetStringHeight() or 17
    return y+math.max(17,measured or 17)+(spacing or 9)
end

local function modelPreview(parent,x,y,w,h,creatureID,key)
    local plate=frame(parent,x,y,w,h,{0.017,0.016,0.018,1})
    if not creatureID or tonumber(creatureID)==0 then
        label(plate,10,math.floor(h/2)-10,w-20,"3D-образ ещё не открыт",
              "GameFontNormalSmall",MUTED,"CENTER")
        return nil
    end
    local model=CreateFrame("PlayerModel",nil,plate)
    model:SetPoint("TOPLEFT",plate,"TOPLEFT",5,-5)
    model:SetPoint("BOTTOMRIGHT",plate,"BOTTOMRIGHT",-5,5)
    if model.SetKeepModelOnHide then model:SetKeepModelOnHide(true) end
    model:EnableMouse(true)
    model:EnableMouseWheel(true)
    local rotation,zoom=0.30,1.30
    local ok=pcall(function()
        model:ClearModel()
        model:SetCreature(creatureID)
        if model.SetPortraitZoom then model:SetPortraitZoom(0) end
        model:SetCamDistanceScale(zoom)
        model:SetRotation(rotation,false)
        model:RefreshCamera()
    end)
    if not ok then
        label(plate,9,math.floor(h/2)-10,w-18,"3D-модель недоступна",
              "GameFontNormalSmall",MUTED,"CENTER")
    end
    local dragX,dragRotation
    model:SetScript("OnMouseDown",function(_,mouse)
        if mouse=="LeftButton" then
            dragX=GetCursorPosition()
            dragRotation=rotation
        end
    end)
    model:SetScript("OnMouseUp",function() dragX=nil end)
    model:SetScript("OnHide",function() dragX=nil end)
    model:SetScript("OnUpdate",function()
        if dragX then
            rotation=dragRotation+(GetCursorPosition()-dragX)*0.012
            model:SetRotation(rotation,false)
        end
    end)
    model:SetScript("OnMouseWheel",function(_,delta)
        zoom=math.max(0.70,math.min(2.25,zoom-delta*0.12))
        model:SetCamDistanceScale(zoom)
        model:RefreshCamera()
    end)
    model:SetScript("OnEnter",function()
        GameTooltip:SetOwner(model,"ANCHOR_RIGHT")
        GameTooltip:AddLine("3D-предпросмотр",1,0.8,0.3)
        GameTooltip:AddLine("Мышь: вращение. Колесо: масштаб.",0.85,0.83,0.75,true)
        GameTooltip:Show()
    end)
    model:SetScript("OnLeave",function() GameTooltip:Hide() end)
    return model
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
    if mode=="creatures" then
        if bridge.RequestFullCatalog and not state.catalogAllLoading
            and (not state.catalogAllLoaded or state.catalogAllZone~=state.zone) then
            bridge.RequestFullCatalog()
        elseif not bridge.RequestFullCatalog then
            bridge.RequestCatalog(1)
        end
        if state.archiveSupported and not state.archiveLoading and not state.archiveLoaded
            and bridge.RequestFullArchive then bridge.RequestFullArchive() end
    end
    if mode=="zones" then bridge.RequestZones() end
    if mode=="items" and bridge.RequestItems then bridge.RequestItems() end
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
    -- Connect nodes *around* their icon bounds rather than through labels.
    if to.y>from.y+12 then
        local y1=from.y+25
        local y2=to.y-25
        local mid=(y1+y2)/2
        drawLine(parent,from.x-1,y1,2,math.max(2,mid-y1),enabled)
        drawLine(parent,math.min(from.x,to.x),mid,math.abs(from.x-to.x),2,enabled)
        drawLine(parent,to.x-1,mid,2,math.max(2,y2-mid),enabled)
    elseif math.abs(to.y-from.y)<16 then
        drawLine(parent,math.min(from.x,to.x)+25,from.y-1,math.max(2,math.abs(from.x-to.x)-50),2,enabled)
    end
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
    local badge=font(b,15,32,33,rank.."/"..n.max,"GameFontNormalSmall",
                     (eligible or rank>0) and PALE or MUTED,"RIGHT")
    if badge.SetMaxLines then badge:SetMaxLines(1) end
    if chosen then
        local glow=b:CreateTexture(nil,"OVERLAY")
        glow:SetAllPoints()
        glow:SetTexture("Interface\\Buttons\\UI-ActionButton-Border")
        glow:SetBlendMode("ADD")
        glow:SetVertexColor(1,0.74,0.20,0.90)
    end
    local title=font(parent,x-71,y+37,142,n.name,"GameFontNormalSmall",
                     eligible and PALE or MUTED,"CENTER")
    if title.SetWordWrap then title:SetWordWrap(true) end
    if title.SetMaxLines then title:SetMaxLines(2) end
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
    local maxed=rank>=n.max
    local meets=checkPrereq(n)
    local cost=not maxed and ForeverEncyclopediaTalentCost(n,rank) or nil
    local now,nextValue="",""
    if catalog.EffectPreview then now,nextValue=catalog.EffectPreview(n,rank,state.ranks,state.maxMana) end
    local y0=y
    y=paragraph(parent,x,y,w,n.name,"GameFontHighlight",PALE,12)
    y=paragraph(parent,x,y,w,"Ранг "..rank.."/"..n.max,"GameFontNormalSmall",GOLD,5)
    y=paragraph(parent,x,y,w,"Сейчас: "..tostring(now),"GameFontNormalSmall",GREEN,10)
    if not maxed then
        y=paragraph(parent,x,y,w,"Следующий ранг: "..tostring(nextValue),
                    "GameFontNormalSmall",GREEN,12)
    end
    y=paragraph(parent,x,y,w,n.desc,"GameFontNormalSmall",MUTED,15)
    if n.req then
        local requirement=talent(n.req)
        y=paragraph(parent,x,y,w,"Требуется: "..(requirement and requirement.name or n.req)..
                    " ("..(n.reqRank or 1)..")","GameFontNormalSmall",MUTED,11)
    end
    if not n.implemented then
        y=paragraph(parent,x,y,w,"В разработке. Покупка закрыта.","GameFontNormalSmall",RED,12)
    elseif maxed then
        y=paragraph(parent,x,y,w,"Максимальный ранг изучен.","GameFontNormalSmall",GREEN,12)
    elseif not meets then
        y=paragraph(parent,x,y,w,"Не выполнено требование предыдущего таланта.","GameFontNormalSmall",RED,12)
    elseif state.knowledgeAvailable<cost then
        y=paragraph(parent,x,y,w,"Недостаточно знаний. Нужно: "..cost,"GameFontNormalSmall",RED,12)
    elseif pendingBuy then
        y=paragraph(parent,x,y,w,"Ожидание подтверждения сервера…","GameFontNormalSmall",GOLD,12)
    else
        y=paragraph(parent,x,y,w,"Стоимость: "..cost.." знаний","GameFontNormalSmall",PALE,9)
        button(parent,x,y,w-6,32,"Изучить за "..cost.." знаний",false,function()
            if pendingBuy or rank>=n.max or not n.implemented or not meets or state.knowledgeAvailable<cost then return end
            pendingBuy=true
            bridge.BuyTalent(n.key)
            _G.ForeverEncyclopediaLegacy.Refresh("view")
        end)
        y=y+40
    end
    return math.max(220,y-y0+18)
end

local function drawTalentView()
    local left=frame(page,13,63,554,444,DEEP)
    local right=frame(page,580,63,307,444,DEEP)
    heading(left,12,10,530,"Таланты книги")
    label(left,18,38,516,"Пять веток знаний. Прокрутите древо вниз для изучения.",
          "GameFontNormalSmall",MUTED)
    for i,key in ipairs(catalog.order) do
        local d=catalog.branches[key]
        local x=9+(i-1)*108
        local b=button(left,x,61,103,53,"",key==branch,function()
            branch=key
            selectedNode=nil
            pendingBuy=false
            scrollPositions["talent-"..key]=0
            _G.ForeverEncyclopediaLegacy.Refresh("view")
        end)
        local icon=b:CreateTexture(nil,"ARTWORK")
        icon:SetSize(25,25)
        icon:SetPoint("TOP",b,"TOP",0,-3)
        icon:SetTexture(d.icon)
        font(b,3,31,97,d.name,"GameFontNormalSmall",PALE,"CENTER")
    end

    local nodes=scrollArea(left,14,127,525,301,"talent-"..branch,659)
    local xPositions={83,247,410}
    local positions={}
    for _,n in ipairs(catalog.nodes) do
        if n.branch==branch then
            positions[n.key]={x=xPositions[n.col],y=43+(n.tier-1)*111}
        end
    end
    for _,n in ipairs(catalog.nodes) do
        if n.branch==branch and n.req and positions[n.req] and positions[n.key] then
            drawLink(nodes,positions[n.req],positions[n.key],checkPrereq(n))
        end
    end
    for _,n in ipairs(catalog.nodes) do
        if n.branch==branch and positions[n.key] then
            node(nodes,positions[n.key].x,positions[n.key].y,n)
        end
    end

    smallCollections(right,10,8)
    local details,viewport=scrollArea(right,17,218,282,215,"detail-"..branch,560)
    local height=selectedTalentDetail(details,3,7,238)
    if height then details:SetHeight(math.max(215,height)) end
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

local MONSTER_TYPES = {
    {value=0,name="Все типы"},
    {value=1,name="Звери"},
    {value=2,name="Дракониды"},
    {value=3,name="Демоны"},
    {value=4,name="Элементали"},
    {value=5,name="Великаны"},
    {value=6,name="Нежить"},
    {value=7,name="Гуманоиды"},
    {value=8,name="Существа"},
    {value=9,name="Механизмы"},
    {value=10,name="Непонятные"},
    {value=11,name="Тотемы"},
    {value=12,name="Спутники"},
}
local function archiveRecordName(rec)
    if not rec.known then return "???" end
    return rec.name and rec.name~="" and rec.name or ("Запись #"..tostring(rec.entry))
end
local function archiveRecords()
    local result,ids={},{}
    -- All known discoveries from account-wide archive (when supported).
    for _,r in ipairs(state.archiveAll or {}) do
        if r.entry and r.entry>0 then
            local record={
                entry=r.entry, name=r.name,known=true,
                creatureType=r.creatureType,classification=r.classification,
                zone=r.zone,map=r.map
            }
            result[#result+1]=record
            ids[r.entry]=record
        end
    end
    -- The original 70658 server knows about yet-undiscovered creatures
    -- only in the *current* zone; merge them without fabricating habitats.
    local zoneRecords=(state.catalogAll and #state.catalogAll>0) and state.catalogAll or state.catalog or {}
    for _,r in ipairs(zoneRecords) do
        local existing=ids[r.entry]
        if existing then
            existing.currentZone=state.catalogAllZone or state.zone
            if r.known and r.name and r.name~="" then existing.name=r.name end
        elseif r.entry and r.entry>0 then
            local record={
                entry=r.entry, name=r.name, known=r.known,
                creatureType=r.creatureType, classification=r.classification,
                zone=r.zone or state.catalogAllZone or state.zone,
                currentZone=state.catalogAllZone or state.zone,
                map=r.map or state.map
            }
            result[#result+1]=record
            ids[r.entry]=record
        end
    end
    table.sort(result,function(a,b)
        if a.known~=b.known then return a.known end
        local an=string.lower(archiveRecordName(a))
        local bn=string.lower(archiveRecordName(b))
        if an~=bn then return an<bn end
        return a.entry<b.entry
    end)
    return result
end
local function locationChoices(rows)
    local choices={}
    if state.archiveSupported then
        choices[#choices+1]={value=0,name="Все доступные зоны"}
    else
        choices[#choices+1]={value=0,name="Текущая зона"}
    end
    if state.zone and state.zone>0 and state.archiveSupported then
        choices[#choices+1]={value=-1,name="Текущая локация"}
    end
    local entries={}
    local seen={}
    for _,rec in ipairs(rows) do
        local zone=rec.zone or 0
        if zone>0 and not seen[zone] then
            seen[zone]=true
            entries[#entries+1]=zone
        end
    end
    table.sort(entries)
    for _,zone in ipairs(entries) do
        local name=bridge.AreaName(zone) or ("Зона #"..zone)
        choices[#choices+1]={value=zone,name=name}
    end
    return choices
end
local function filteredArchiveRecords(rows)
    local result={}
    local search=string.lower(creatureSearch)
    for _,rec in ipairs(rows) do
        local matches=creatureType==0 or rec.creatureType==creatureType
        if matches and creatureLocation~=0 then
            if creatureLocation==-1 then
                matches=(rec.currentZone==state.zone) or (rec.zone==state.zone)
            else
                matches=(rec.zone==creatureLocation) or (rec.currentZone==creatureLocation)
            end
        end
        if matches and activeMonsterFilter=="known" and not rec.known then matches=false end
        if matches and activeMonsterFilter=="unknown" and rec.known then matches=false end
        if matches and search~="" then
            matches=string.find(string.lower(archiveRecordName(rec)),search,1,true)~=nil
                or string.find(tostring(rec.entry),search,1,true)~=nil
        end
        if matches then result[#result+1]=rec end
    end
    return result
end
local function dropdown(parent,x,y,w,current,options,choose)
    local currentName=options[1] and options[1].name or "Нет данных"
    for _,option in ipairs(options) do
        if option.value==current then currentName=option.name; break end
    end
    local trigger=button(parent,x,y,w,29,currentName.."  ▾",false,function()
        if ui.archivePopup and ui.archivePopup:IsShown() then
            ui.archivePopup:Hide()
            ui.archivePopup=nil
            return
        end
        local count=math.min(7,#options)
        local menu=remember(CreateFrame("Frame",nil,parent))
        menu:SetFrameLevel(parent:GetFrameLevel()+20)
        menu:SetPoint("TOPLEFT",parent,"TOPLEFT",x,-(y+30))
        menu:SetSize(w,count*29+8)
        local bg=solid(menu,"BACKGROUND",{0.095,0.066,0.041,1})
        bg:SetAllPoints()
        edge(menu,GOLD)
        local start=1
        local menuButtons={}
        for n=1,count do
            local optionButton=button(menu,3,4+(n-1)*29,w-6,27,"",false,function()
                local chosen=options[start+n-1]
                if chosen then
                    ui.archivePopup=nil
                    choose(chosen.value)
                end
            end)
            menuButtons[n]=font(optionButton,6,6,w-18,"","GameFontNormalSmall",PALE)
            optionButton._optionIndex=n
            optionButton:SetScript("OnClick",function(self)
                local item=options[start+self._optionIndex-1]
                if item then
                    menu:Hide()
                    ui.archivePopup=nil
                    choose(item.value)
                end
            end)
        end
        local function updateMenu()
            for n,text in ipairs(menuButtons) do
                local item=options[start+n-1]
                text:SetText(item and item.name or "")
            end
        end
        menu:EnableMouseWheel(true)
        menu:SetScript("OnMouseWheel",function(_,delta)
            start=math.max(1,math.min(#options-count+1,start-delta))
            updateMenu()
        end)
        updateMenu()
        ui.archivePopup=menu
    end)
    return trigger
end

local function drawCreatureView()
    local base=frame(page,13,63,874,444,DEEP)
    drawArchiveHeading(base,"Архив существ",
        "Все загруженные записи без страниц. Поиск, тип существ и локация.")
    -- Shrink the chooser and use the extra width for the 3D model and notes.
    local list=frame(base,16,82,318,292,BROWN)
    local detail=frame(base,345,82,511,292,BROWN)

    local allRows=archiveRecords()
    local options=locationChoices(allRows)
    local records=filteredArchiveRecords(allRows)

    local input=remember(CreateFrame("EditBox",nil,list,"InputBoxTemplate"))
    input:SetPoint("TOPLEFT",list,"TOPLEFT",15,-9)
    input:SetSize(279,27)
    input:SetAutoFocus(false)
    input:SetText(creatureSearch)
    input:SetScript("OnEnterPressed",function(self)
        creatureSearch=self:GetText() or ""
        self:ClearFocus()
        scrollPositions["creature-list"]=0
        _G.ForeverEncyclopediaLegacy.Refresh("view")
    end)
    input:SetScript("OnEscapePressed",function(self)
        self:ClearFocus()
        creatureSearch=""
        scrollPositions["creature-list"]=0
        _G.ForeverEncyclopediaLegacy.Refresh("view")
    end)

    dropdown(list,9,44,142,creatureType,MONSTER_TYPES,function(value)
        creatureType=value; scrollPositions["creature-list"]=0
        _G.ForeverEncyclopediaLegacy.Refresh("view")
    end)
    dropdown(list,159,44,147,creatureLocation,options,function(value)
        creatureLocation=value; scrollPositions["creature-list"]=0
        _G.ForeverEncyclopediaLegacy.Refresh("view")
    end)
    local statusLabel=activeMonsterFilter=="known" and "Встреченные" or
        activeMonsterFilter=="unknown" and "Неизвестные" or "Все записи"
    button(list,9,77,120,24,statusLabel.." ▾",false,function()
        activeMonsterFilter=activeMonsterFilter=="all" and "known" or
            activeMonsterFilter=="known" and "unknown" or "all"
        scrollPositions["creature-list"]=0
        _G.ForeverEncyclopediaLegacy.Refresh("view")
    end)
    local totalLoaded=#allRows
    local loadInfo
    if state.catalogAllLoading or state.archiveLoading then
        local serverTotal=(state.catalogAllTotal or 0)+(state.archiveTotal or 0)
        loadInfo="Загрузка: "..totalLoaded.." / "..math.max(totalLoaded,serverTotal)
    else
        loadInfo="Показано: "..#records.." из "..totalLoaded
    end
    font(list,136,81,168,loadInfo,"GameFontNormalSmall",MUTED,"RIGHT")
    if not state.archiveSupported then
        font(list,11,265,297,"Другие зоны доступны после обновления worldserver",
             "GameFontNormalSmall",MUTED)
    end

    -- Only 6 row widgets exist regardless of the server catalogue size.
    -- They represent a virtual window onto one continuous scrollable list.
    local rowSize=39
    local viewHeight=state.archiveSupported and 177 or 151
    local contents,scroller=scrollArea(list,9,108,296,viewHeight-8,"creature-list",
                                    math.max(viewHeight,#records*rowSize+4))
    viewHeight=viewHeight-8
    local visibleCount=math.ceil(viewHeight/rowSize)+1
    local widgets={}
    for slot=1,visibleCount do
        local row=button(contents,2,4+(slot-1)*rowSize,259,35,"",false,function()
            local selected=widgets[slot] and widgets[slot].record
            if not selected then return end
            selectedCreatureEntry=selected.entry
            if selected.known then bridge.RequestCreatureInfo(selected.entry) end
            _G.ForeverEncyclopediaLegacy.Refresh("view")
        end)
        local title=font(row,7,8,192,"","GameFontNormalSmall",PALE)
        if title.SetMaxLines then title:SetMaxLines(1) end
        local badge=font(row,194,9,60,"","GameFontNormalSmall",GREEN,"RIGHT")
        widgets[slot]={frame=row,name=title,status=badge}
    end
    local function renderVisible(offset)
        local first=math.floor(math.max(0,offset or 0)/rowSize)
        for slot,widget in ipairs(widgets) do
            local index=first+slot
            local item=records[index]
            widget.record=item
            if item then
                widget.frame:Show()
                widget.frame:ClearAllPoints()
                widget.frame:SetPoint("TOPLEFT",contents,"TOPLEFT",2,-(4+(index-1)*rowSize))
                widget.name:SetText(archiveRecordName(item))
                widget.status:SetText(item.known and "Открыто" or "???")
                widget.status:SetTextColor(unpack(item.known and GREEN or MUTED))
            else
                widget.frame:Hide()
            end
        end
    end
    local offset=scroller:GetVerticalScroll() or 0
    renderVisible(offset)
    scroller:SetScript("OnVerticalScroll",function(self,scrollOffset)
        renderVisible(scrollOffset)
        scrollPositions["creature-list"]=scrollOffset
    end)
    scroller:SetScript("OnMouseWheel",function(self,delta)
        local max=math.max(0,contents:GetHeight()-viewHeight)
        local nextValue=math.max(0,math.min(max,(self:GetVerticalScroll() or 0)-delta*rowSize*2))
        self:SetVerticalScroll(nextValue)
        scrollPositions["creature-list"]=nextValue
        renderVisible(nextValue)
    end)

    local selected
    if selectedCreatureEntry then
        for _,rec in ipairs(records) do
            if rec.entry==selectedCreatureEntry then selected=rec; break end
        end
    end
    if not selected then selected=records[1] end
    if selected then
        selectedCreatureEntry=selected.entry
        local info=state.creatureInfo[selected.entry] or {}
        label(detail,12,8,485,archiveRecordName(selected),"GameFontHighlight",PALE,"CENTER")
        modelPreview(detail,14,35,483,174,selected.known and selected.entry or nil,"creature")
        local infoBody=scrollArea(detail,13,219,485,64,"creature-info",260)
        local y=paragraph(infoBody,5,7,445,
            selected.known and "Открыто в бестиарии" or "Ещё не встречено",
            "GameFontNormalSmall",selected.known and GREEN or MUTED,6)
        y=paragraph(infoBody,5,y,445,"Запись: #"..selected.entry,"GameFontNormalSmall",MUTED,5)
        if selected.zone and selected.zone>0 then
            y=paragraph(infoBody,5,y,445,
                (state.archiveSupported and "Место первой встречи: " or "Локация: ")..
                (bridge.AreaName(selected.zone) or "Зона #"..selected.zone),
                "GameFontNormalSmall",MUTED,5)
        end
        if selected.known then
            if state.infoLevel>=3 then
                y=paragraph(infoBody,5,y,445,
                    "Уровни: "..tostring(info.minLevel or "?").."–"..tostring(info.maxLevel or "?"),
                    "GameFontNormalSmall",PALE,5)
                y=paragraph(infoBody,5,y,445,
                    "Семейство: "..tostring(info.family or "?"),
                    "GameFontNormalSmall",MUTED,5)
            else
                y=paragraph(infoBody,5,y,445,
                    "Подробности открываются талантами Познания.",
                    "GameFontNormalSmall",MUTED,5)
            end
        end
        infoBody:SetHeight(math.max(64,y+10))
    else
        label(detail,16,24,479,
            state.catalogAllLoading and "Собираю каталог существ…" or
                "По выбранным фильтрам записей нет.",
            "GameFontNormal",MUTED,"CENTER")
    end
end

local function drawZoneView()
    local base=frame(page,13,63,874,444,DEEP)
    drawArchiveHeading(base,"Изученные локации","Последние открытия вашего аккаунта из серверного архива.")
    if not state.recentZonesLoaded then
        label(base,30,114,780,"Получаю список локаций…","GameFontHighlight",PALE)
        return
    end
    if #state.recentZones==0 then
        label(base,30,114,780,"Пока нет изученных локаций.","GameFontNormal",MUTED)
        return
    end
    local list=frame(base,18,94,835,271,BROWN)
    local rows=scrollArea(list,10,8,811,254,"zone-list",
                          math.max(254,math.ceil(#state.recentZones/2)*65+12))
    for i,rec in ipairs(state.recentZones) do
        local col=(i-1)%2
        local row=math.floor((i-1)/2)
        local title=bridge.AreaName(rec.entry) or ("Локация #"..(rec.entry or 0))
        local tile=button(rows,8+col*387,8+row*65,375,57,"",false,function()
            GameTooltip:Hide()
        end)
        font(tile,12,6,346,title,"GameFontHighlight",PALE)
        font(tile,12,30,346,"Изучена • карта "..tostring(rec.map or 0),
             "GameFontNormalSmall",GREEN)
        tile:SetScript("OnEnter",function()
            tooltip(tile,title,"Открыто для всей учётной записи.")
        end)
        tile:SetScript("OnLeave",function() GameTooltip:Hide() end)
    end
end

local function itemInfo(entry)
    -- The server exposes discovered item IDs, never a guessed or fake item list.
    -- C_Item may return nil for uncached items; display an honest ID meanwhile.
    local name,icon="Предмет #"..tostring(entry),"Interface\\Icons\\INV_Misc_Bag_10"
    if C_Item and C_Item.GetItemInfo then
        local ok,n=pcall(C_Item.GetItemInfo,entry)
        if ok and type(n)=="string" and n~="" then name=n end
    end
    if C_Item and C_Item.GetItemIconByID then
        local ok,i=pcall(C_Item.GetItemIconByID,entry)
        if ok and i then icon=i end
    end
    return name,icon
end

local function drawItemView()
    local base=frame(page,13,63,874,444,DEEP)
    drawArchiveHeading(base,"Коллекция предметов",
        (state.items or 0).." предметов изучено. Последние записи поступают с сервера.")
    local list=frame(base,16,82,474,292,BROWN)
    local detail=frame(base,504,82,353,292,BROWN)
    if not state.recentItemsLoaded then
        label(list,16,18,430,"Получаю последние предметы с сервера…","GameFontHighlight",PALE)
        return
    end
    if #state.recentItems==0 then
        label(list,16,18,430,"Пока нет открытых предметов.","GameFontNormal",MUTED)
        return
    end
    selectedItem=math.max(1,math.min(selectedItem,#state.recentItems))
    local rows=scrollArea(list,9,8,453,277,"item-list",
                          math.max(277,#state.recentItems*47+10))
    for i,rec in ipairs(state.recentItems) do
        local name,icon=itemInfo(rec.entry)
        local b=button(rows,5,5+(i-1)*47,418,41,"",i==selectedItem,function()
            selectedItem=i
            _G.ForeverEncyclopediaLegacy.Refresh("view")
        end)
        local t=b:CreateTexture(nil,"ARTWORK")
        t:SetTexture(icon)
        t:SetPoint("TOPLEFT",b,"TOPLEFT",5,-5)
        t:SetSize(31,31)
        local title=font(b,45,5,361,name,"GameFontNormalSmall",PALE)
        if title.SetMaxLines then title:SetMaxLines(1) end
        font(b,45,24,361,"Запись #"..rec.entry,"GameFontNormalSmall",MUTED)
    end
    local rec=state.recentItems[selectedItem]
    if rec then
        local name,icon=itemInfo(rec.entry)
        emblem(detail,17,23,95,95,icon)
        local itemTitle=font(detail,125,25,210,name,"GameFontHighlight",PALE)
        if itemTitle.SetWordWrap then itemTitle:SetWordWrap(true) end
        label(detail,125,97,210,"Запись #"..rec.entry,"GameFontNormalSmall",GREEN)
        local body=scrollArea(detail,15,137,329,146,"item-detail",230)
        local where=bridge.AreaName(rec.zone) or ("Зона #"..tostring(rec.zone or 0))
        local y=paragraph(body,4,8,290,"Впервые найдено: "..where,"GameFontNormalSmall",MUTED)
        y=paragraph(body,4,y,290,"Карта: "..tostring(rec.map or 0),
                    "GameFontNormalSmall",MUTED)
        y=paragraph(body,4,y,290,"Знания сохранены на учётной записи.",
                    "GameFontNormalSmall",GREEN)
        body:SetHeight(math.max(146,y+8))
    end
end

local function drawAppearanceView()
    local base=frame(page,13,63,874,444,DEEP)
    heading(base,12,12,850,"Облики Живой книги")
    label(base,25,46,816,"Облик влияет только на внешний вид. Выберите его для 3D-предпросмотра.",
          "GameFontNormalSmall",MUTED)
    local list=frame(base,16,82,407,347,BROWN)
    local detail=frame(base,437,82,421,347,BROWN)
    local appearances=catalog.appearances or {}
    local entries=scrollArea(list,9,9,387,329,"appearance-list",math.max(329,#appearances*79+10))
    local chosen
    for i,a in ipairs(appearances) do
        if a.key==selectedAppearance then chosen=a end
        local unlocked=state.appearances[a.key] and state.appearances[a.key].unlocked
        local b=button(entries,5,5+(i-1)*79,350,72,"",a.key==selectedAppearance,function()
            selectedAppearance=a.key
            _G.ForeverEncyclopediaLegacy.Refresh("view")
        end)
        local icon=b:CreateTexture(nil,"ARTWORK")
        icon:SetTexture("Interface\\Icons\\INV_Misc_Book_09")
        icon:SetSize(50,50)
        icon:SetPoint("TOPLEFT",b,"TOPLEFT",8,-11)
        if not unlocked then icon:SetDesaturated(true) end
        local title=font(b,70,11,266,a.name,"GameFontHighlight",unlocked and PALE or MUTED)
        if title.SetMaxLines then title:SetMaxLines(1) end
        font(b,70,40,266,unlocked and "Открыт" or
            ("Нужно накопить: "..a.threshold.." знаний"),
            "GameFontNormalSmall",unlocked and GREEN or MUTED)
    end
    chosen=chosen or appearances[1]
    if not chosen then
        label(detail,16,20,382,"В каталоге нет обликов.","GameFontNormal",MUTED)
        return
    end
    local unlocked=state.appearances[chosen.key] and state.appearances[chosen.key].unlocked
    label(detail,14,9,390,chosen.name,"GameFontHighlight",PALE,"CENTER")
    modelPreview(detail,14,40,393,219,chosen.creature,"appearance")
    label(detail,14,265,390,unlocked and "Облик открыт" or
          ("Для открытия нужно "..chosen.threshold.." знаний"),
          "GameFontNormalSmall",unlocked and GREEN or MUTED,"CENTER")
    if state.selectedAppearance==chosen.key then
        label(detail,14,301,390,"Используется","GameFontHighlight",GREEN,"CENTER")
    elseif unlocked then
        button(detail,79,296,267,36,"Выбрать облик",false,function()
            bridge.SelectAppearance(chosen.key) -- confirmed by server
        end)
    else
        label(detail,14,300,390,"Пока недоступен","GameFontNormalSmall",MUTED,"CENTER")
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
    ui.headerStat=font(header,280,12,277,"","GameFontNormalSmall",GOLD)
    ui.headerStat:SetText("Знания: "..(state.knowledgeAvailable or 0)..
        "   •   Мана: "..(state.mana or 0).."/"..(state.maxMana or 100))
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
            -- Native mana status is frequent: update only the existing header,
            -- rather than allocating new talent frames every regen tick.
            if ui.headerStat then
                ui.headerStat:SetText("Знания: "..(state.knowledgeAvailable or 0)..
                    "   •   Мана: "..(state.mana or 0).."/"..(state.maxMana or 100))
            end
        else
            if kind=="talents" then pendingBuy=false end
            if kind=="capabilities" and mode=="creatures" and state.archiveSupported
                and not state.archiveLoaded and not state.archiveLoading
                and bridge.RequestFullArchive then
                bridge.RequestFullArchive()
            end
            if kind=="zone" and mode=="creatures" and bridge.RequestFullCatalog then
                -- Refresh the full current-zone list after a zone transition.
                bridge.RequestFullCatalog()
                creatureLocation=0
            end
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
