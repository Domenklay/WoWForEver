local ADDON = ...
local BASE_REQ, BASE_RES = "FEC1", "FER1"
local TALENT_REQ, TALENT_RES = "FET1", "FTR1"
local SERVER_TARGET = "SERVER"
local Catalog = ForeverEncyclopediaTalentCatalog

local main, content, bookDock
local tabs = {}
local currentTab = 1
local currentBranch = "knowledge"
local selectedCreature = 1
local selectedTalentKey = "identify_name"
local selectedAppearanceKey = "living_book"
local locationIndex = 1
local dynamic = {}
local creatureModel, appearanceModel
local creatureModelEntry, appearanceModelEntry
local creatureRotation, appearanceRotation = 0.3, 0.25
local creatureZoom, appearanceZoom = 1.35, 1.25
local creatureDragging, appearanceDragging = false, false
local dragX, dragRotation
local pendingInfoEntry
local infoQueue = {}

local state = {
    online = false,
    creatures = 0, items = 0, zones = 0, total = 0,
    map = 0, zone = 0, area = 0,
    knowledgeTotal = 0, knowledgeSpent = 0, knowledgeAvailable = 0,
    catalog = {}, catalogLoaded = false, catalogPage = 1, catalogPages = 1,
    catalogTotal = 0, catalogKnown = 0, catalogZoneTotal = 0, catalogZoneKnown = 0,
    recentZones = {}, recentZonesLoaded = false,
    ranks = {}, abilityMask = 0, mana = 0, maxMana = 100, infoLevel = 0,
    appearances = {}, selectedAppearance = "living_book",
    creatureInfo = {},
}

local CREATURE_TYPES = {
    [1]="Зверь", [2]="Драконид", [3]="Демон", [4]="Элементаль", [5]="Великан",
    [6]="Нежить", [7]="Гуманоид", [8]="Существо", [9]="Механизм", [10]="Существо",
    [11]="Тотем", [12]="Спутник",
}
local CLASSIFICATIONS = {
    [0]="Обычный", [1]="Элита", [2]="Редкая элита", [3]="Мировой босс", [4]="Редкий",
}

local function registerPrefixes()
    if C_ChatInfo and C_ChatInfo.RegisterAddonMessagePrefix then
        pcall(C_ChatInfo.RegisterAddonMessagePrefix, BASE_REQ)
        pcall(C_ChatInfo.RegisterAddonMessagePrefix, BASE_RES)
        pcall(C_ChatInfo.RegisterAddonMessagePrefix, TALENT_REQ)
        pcall(C_ChatInfo.RegisterAddonMessagePrefix, TALENT_RES)
    end
end

local function send(prefix, payload)
    registerPrefixes()
    if C_ChatInfo and C_ChatInfo.SendAddonMessage then
        return pcall(C_ChatInfo.SendAddonMessage, prefix, payload, "WHISPER", SERVER_TARGET)
    end
    return false
end

local function requestBaseStatus() send(BASE_REQ, "status") end
local function requestTalentStatus() send(TALENT_REQ, "status") end
local function requestCatalog(page) send(BASE_REQ, "catalog " .. tostring(page or 1) .. " 0 0 -1") end
local function requestZones() state.recentZones = {}; state.recentZonesLoaded = false; send(BASE_REQ, "recent 3") end

local function zoneName()
    local name = GetRealZoneText and GetRealZoneText() or ""
    if name ~= "" then return name end
    return state.zone > 0 and ("Зона " .. state.zone) or "Неизвестная зона"
end

local function addDynamic(obj)
    dynamic[#dynamic + 1] = obj
    return obj
end

local function clearDynamic()
    for _, obj in ipairs(dynamic) do
        if obj.Hide then obj:Hide() end
    end
    wipe(dynamic)
end

local function colorTexture(parent, layer, r,g,b,a)
    local t = parent:CreateTexture(nil, layer or "BACKGROUND")
    t:SetColorTexture(r,g,b,a or 1)
    return t
end

local function border(frame, r,g,b,a)
    local edges = {}
    local top = colorTexture(frame, "BORDER", r,g,b,a); top:SetPoint("TOPLEFT"); top:SetPoint("TOPRIGHT"); top:SetHeight(1); edges[#edges+1]=top
    local bottom = colorTexture(frame, "BORDER", r,g,b,a); bottom:SetPoint("BOTTOMLEFT"); bottom:SetPoint("BOTTOMRIGHT"); bottom:SetHeight(1); edges[#edges+1]=bottom
    local left = colorTexture(frame, "BORDER", r,g,b,a); left:SetPoint("TOPLEFT"); left:SetPoint("BOTTOMLEFT"); left:SetWidth(1); edges[#edges+1]=left
    local right = colorTexture(frame, "BORDER", r,g,b,a); right:SetPoint("TOPRIGHT"); right:SetPoint("BOTTOMRIGHT"); right:SetWidth(1); edges[#edges+1]=right
    return edges
end

local function panel(parent, x,y,w,h)
    local f = addDynamic(CreateFrame("Frame", nil, parent))
    f:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
    f:SetSize(w,h)
    local bg = colorTexture(f, "BACKGROUND", 0.055,0.035,0.020,0.97); bg:SetAllPoints()
    local upper = colorTexture(f, "BACKGROUND", 0.12,0.075,0.032,0.22); upper:SetPoint("TOPLEFT",f,"TOPLEFT",2,-2); upper:SetPoint("TOPRIGHT",f,"TOPRIGHT",-2,-2); upper:SetHeight(math.floor(h*0.42))
    border(f, 0.35,0.22,0.075,0.95)
    return f
end

local function text(parent, x,y,w,value,font,r,g,b,justify)
    local fs = parent:CreateFontString(nil,"OVERLAY",font or "GameFontNormal")
    fs:SetPoint("TOPLEFT",parent,"TOPLEFT",x,y)
    if w then fs:SetWidth(w) end
    fs:SetJustifyH(justify or "LEFT")
    fs:SetText(value or "")
    if r then fs:SetTextColor(r,g,b) end
    return fs
end

local function raisedButton(parent, x,y,w,h,label,onclick,selected)
    local b = addDynamic(CreateFrame("Button",nil,parent))
    b:SetPoint("TOPLEFT",parent,"TOPLEFT",x,y); b:SetSize(w,h)
    local base = colorTexture(b,"BACKGROUND", selected and 0.24 or 0.11, selected and 0.14 or 0.065, selected and 0.045 or 0.027,0.98); base:SetAllPoints()
    local top = colorTexture(b,"BACKGROUND",0.30,0.18,0.055,selected and 0.54 or 0.32); top:SetPoint("TOPLEFT",b,"TOPLEFT",2,-2); top:SetPoint("TOPRIGHT",b,"TOPRIGHT",-2,-2); top:SetHeight(math.max(6,math.floor(h*0.44)))
    local bottom = colorTexture(b,"BACKGROUND",0.025,0.014,0.008,0.74); bottom:SetPoint("BOTTOMLEFT",b,"BOTTOMLEFT",2,2); bottom:SetPoint("BOTTOMRIGHT",b,"BOTTOMRIGHT",-2,2); bottom:SetHeight(math.max(6,math.floor(h*0.38)))
    local edges = border(b, selected and 0.82 or 0.42, selected and 0.52 or 0.27, selected and 0.13 or 0.08,1)
    local shine = colorTexture(b,"BORDER",0.95,0.72,0.30,0.22); shine:SetPoint("TOPLEFT",b,"TOPLEFT",3,-3); shine:SetPoint("TOPRIGHT",b,"TOPRIGHT",-3,-3); shine:SetHeight(1)
    local fs = b:CreateFontString(nil,"OVERLAY","GameFontHighlight")
    fs:SetPoint("CENTER",b,"CENTER",0,0); fs:SetText(label or "")
    fs:SetTextColor(selected and 1 or 0.86, selected and 0.80 or 0.80, selected and 0.40 or 0.70)
    b:SetScript("OnEnter",function() base:SetColorTexture(0.20,0.115,0.035,1) end)
    b:SetScript("OnLeave",function() base:SetColorTexture(selected and 0.24 or 0.11, selected and 0.14 or 0.065, selected and 0.045 or 0.027,0.98) end)
    b:SetScript("OnClick",onclick)
    return b
end

local function abilityUnlocked(bit)
    return bit32 and bit32.band(state.abilityMask,bit) ~= 0 or (state.abilityMask % (bit*2) >= bit)
end

local function setCreatureModel(entry)
    entry = tonumber(entry)
    if not creatureModel or not entry or entry <= 0 then return end
    creatureModelEntry = entry
    creatureRotation = 0.3
    creatureZoom = 1.35
    creatureModel:ClearModel()
    pcall(function()
        creatureModel:SetCreature(entry)
        creatureModel:SetPortraitZoom(0)
        creatureModel:SetCamDistanceScale(creatureZoom)
        creatureModel:SetRotation(creatureRotation,false)
        creatureModel:RefreshCamera()
    end)
end

local function setAppearanceModel(entry)
    entry = tonumber(entry)
    if not appearanceModel or not entry or entry <= 0 then return end
    appearanceModelEntry = entry
    appearanceRotation = 0.25
    appearanceZoom = 1.25
    appearanceModel:ClearModel()
    pcall(function()
        appearanceModel:SetCreature(entry)
        appearanceModel:SetPortraitZoom(0)
        appearanceModel:SetCamDistanceScale(appearanceZoom)
        appearanceModel:SetRotation(appearanceRotation,false)
        appearanceModel:RefreshCamera()
    end)
end

local function requestCreatureInfo(entry)
    entry = tonumber(entry)
    if not entry or entry <= 0 or state.infoLevel <= 0 then return end
    pendingInfoEntry = entry
    send(TALENT_REQ, "creature " .. tostring(entry))
end

local Draw

local function creatureDisplay(rec)
    if not rec then return "???", "Неизвестное существо", nil end
    local info = state.creatureInfo[rec.entry]
    local name = rec.name ~= "" and rec.name or (info and info.name) or "???"
    local ctype = rec.creatureType and rec.creatureType > 0 and rec.creatureType or (info and info.creatureType) or 0
    local classification = rec.classification and rec.classification > 0 and rec.classification or (info and info.classification) or 0
    local meta = ctype > 0 and (CREATURE_TYPES[ctype] or "Существо") or "Неизвестное существо"
    if classification > 0 then meta = meta .. "  •  " .. (CLASSIFICATIONS[classification] or "") end
    return name, meta, info
end

local function drawCreatureTab()
    local left = panel(content, 10,-10,360,474)
    local right = panel(content, 382,-10,554,474)
    text(left,16,-14,320,zoneName(),"GameFontHighlightLarge",1,0.86,0.60)
    local pct = state.catalogZoneTotal > 0 and math.floor(state.catalogZoneKnown*100/state.catalogZoneTotal) or 0
    text(left,16,-44,320,string.format("Встречено %d из %d  •  %d%%",state.catalogZoneKnown,state.catalogZoneTotal,pct),"GameFontNormalSmall",0.75,0.68,0.57)

    local y=-76
    if not state.catalogLoaded then
        text(left,16,y,320,"Синхронизация каталога…","GameFontNormal",0.72,0.66,0.58)
    else
        for i,rec in ipairs(state.catalog) do
            local name = creatureDisplay(rec)
            local row = raisedButton(left,14,y-(i-1)*38,314,34,name,function()
                selectedCreature=i
                requestCreatureInfo(rec.entry)
                Draw()
            end,i==selectedCreature)
            local st = row:CreateFontString(nil,"OVERLAY","GameFontNormalSmall")
            st:SetPoint("RIGHT",row,"RIGHT",-8,0); st:SetText(rec.known and "Встречено" or "Не встречено")
            st:SetTextColor(rec.known and 0.45 or 0.58,rec.known and 0.82 or 0.53,rec.known and 0.44 or 0.45)
        end
    end
    text(left,112,-443,136,string.format("Страница %d / %d",state.catalogPage,state.catalogPages),"GameFontNormalSmall",0.72,0.65,0.55,"CENTER")
    local prev=raisedButton(left,14,-432,84,28,"Назад",function() if state.catalogPage>1 then requestCatalog(state.catalogPage-1) end end,false)
    local nextb=raisedButton(left,248,-432,84,28,"Далее",function() if state.catalogPage<state.catalogPages then requestCatalog(state.catalogPage+1) end end,false)
    if state.catalogPage<=1 then prev:Disable() end
    if state.catalogPage>=state.catalogPages then nextb:Disable() end
    left:EnableMouseWheel(true)
    left:SetScript("OnMouseWheel",function(_,d)
        if d<0 and state.catalogPage<state.catalogPages then requestCatalog(state.catalogPage+1)
        elseif d>0 and state.catalogPage>1 then requestCatalog(state.catalogPage-1) end
    end)

    local rec=state.catalog[selectedCreature]
    if not rec then text(right,24,-24,500,"Выберите запись слева.","GameFontHighlight",0.9,0.82,0.68); return end
    local name,meta,info=creatureDisplay(rec)
    text(right,24,-20,500,name,"GameFontHighlightLarge",1,0.88,0.62)
    text(right,24,-51,500,meta,"GameFontNormal",0.80,0.68,0.48)

    local plate=addDynamic(CreateFrame("Frame",nil,right)); plate:SetPoint("TOPLEFT",right,"TOPLEFT",24,-88); plate:SetSize(190,156)
    local pbg=colorTexture(plate,"BACKGROUND",0.008,0.008,0.007,0.96); pbg:SetAllPoints(); border(plate,0.45,0.28,0.09,0.95)
    creatureModel=CreateFrame("PlayerModel",nil,plate); creatureModel:SetPoint("TOPLEFT",plate,"TOPLEFT",5,-5); creatureModel:SetPoint("BOTTOMRIGHT",plate,"BOTTOMRIGHT",-5,5); creatureModel:SetKeepModelOnHide(true)
    creatureModel:EnableMouse(true); creatureModel:EnableMouseWheel(true)
    creatureModel:SetScript("OnMouseDown",function(_,button) if button=="LeftButton" then creatureDragging=true; dragX=GetCursorPosition(); dragRotation=creatureRotation end end)
    creatureModel:SetScript("OnMouseUp",function() creatureDragging=false end)
    creatureModel:SetScript("OnUpdate",function() if creatureDragging then local x=GetCursorPosition(); creatureRotation=dragRotation+(x-dragX)*0.012; creatureModel:SetRotation(creatureRotation,false) end end)
    creatureModel:SetScript("OnMouseWheel",function(_,d) creatureZoom=math.max(0.8,math.min(2.0,creatureZoom-d*0.10)); creatureModel:SetCamDistanceScale(creatureZoom); creatureModel:RefreshCamera() end)
    setCreatureModel(rec.entry)

    text(right,238,-98,280,rec.known and "Запись встречена" or "Запись ещё не встречена","GameFontHighlight",rec.known and 0.52 or 0.86,rec.known and 0.82 or 0.68,rec.known and 0.45 or 0.42)
    text(right,238,-130,280,"Встречается: "..zoneName(),"GameFontNormal",0.82,0.76,0.66)
    if info and state.infoLevel>=3 then text(right,238,-162,280,string.format("Уровни: %d–%d",info.minLevel or 0,info.maxLevel or 0),"GameFontNormal",0.82,0.76,0.66) end

    text(right,24,-276,500,"Архивные сведения","GameFontHighlight",0.98,0.82,0.54)
    local lines={
        {1,"Название и тип", state.infoLevel>=1}, {2,"Класс угрозы",state.infoLevel>=2}, {3,"Уровни и параметры",state.infoLevel>=3},
        {4,"Способности",state.infoLevel>=4}, {5,"Сопротивления",state.infoLevel>=5}, {6,"Полезный лут",state.infoLevel>=6},
        {7,"Ареал обитания",state.infoLevel>=7}, {8,"Редкие примечания",state.infoLevel>=8},
    }
    for i,row in ipairs(lines) do
        local yy=-307-(i-1)*18
        text(right,24,yy,480,(row[3] and "✓ " or "• ")..row[2],"GameFontNormalSmall",row[3] and 0.55 or 0.56,row[3] and 0.80 or 0.51,row[3] and 0.48 or 0.44)
    end
    if state.infoLevel==0 then
        text(right,280,-420,240,"Первый уровень Познания стоит всего 1 очко.","GameFontNormalSmall",0.92,0.72,0.40)
    end
end

local function drawLocationTab()
    local left=panel(content,10,-10,360,474); local right=panel(content,382,-10,554,474)
    text(left,16,-14,320,"Изученные локации","GameFontHighlightLarge",1,0.86,0.60)
    text(left,16,-44,320,"Последние открытия аккаунта","GameFontNormalSmall",0.72,0.65,0.55)
    if not state.recentZonesLoaded then text(left,16,-84,320,"Получаю список…","GameFontNormal",0.72,0.66,0.58)
    else
        for i,rec in ipairs(state.recentZones) do
            raisedButton(left,14,-76-(i-1)*38,314,34,"Локация "..tostring(rec.entry),function() locationIndex=i; Draw() end,i==locationIndex)
        end
    end
    text(right,24,-20,500,zoneName(),"GameFontHighlightLarge",1,0.88,0.62)
    text(right,24,-58,500,"Архив исследования мира","GameFontNormal",0.80,0.68,0.48)
    text(right,24,-108,500,"Новые зоны открываются один раз на аккаунт и дают 3 очка знаний.","GameFontNormal",0.82,0.76,0.66)
    text(right,24,-150,500,"Позже здесь появится прогресс существ, особых мест и архивных заметок по каждой зоне.","GameFontNormal",0.72,0.67,0.58)
end

local function nodeByKey(key)
    for _,node in ipairs(Catalog.nodes) do if node.key==key then return node end end
end

local function prereqMet(node)
    if not node.req then return true end
    return (state.ranks[node.req] or 0) >= (node.reqRank or 1)
end

local function drawConnector(tree,node,positions)
    if not node.req or not positions[node.req] or not positions[node.key] then return end
    local a,b=positions[node.req],positions[node.key]
    local col={0.34,0.23,0.09,0.9}
    local midY=(a.y+b.y)/2
    local v1=colorTexture(tree,"ARTWORK",unpack(col)); v1:SetPoint("TOPLEFT",tree,"TOPLEFT",a.x-1,a.y-30); v1:SetSize(2,math.max(1,a.y-midY))
    local h=colorTexture(tree,"ARTWORK",unpack(col)); h:SetPoint("TOPLEFT",tree,"TOPLEFT",math.min(a.x,b.x),midY); h:SetSize(math.abs(a.x-b.x)+2,2)
    local v2=colorTexture(tree,"ARTWORK",unpack(col)); v2:SetPoint("TOPLEFT",tree,"TOPLEFT",b.x-1,midY); v2:SetSize(2,math.max(1,math.abs(midY-(b.y+30))))
end

local function drawTalentTab()
    local tree=panel(content,10,-10,672,474); local detail=panel(content,694,-10,242,474)
    for i,key in ipairs(Catalog.order) do
        local meta=Catalog.branches[key]
        raisedButton(tree,12+(i-1)*128,-12,120,30,meta.name,function() currentBranch=key; Draw() end,currentBranch==key)
    end
    local positions={}
    local xs={100,316,532}
    for _,node in ipairs(Catalog.nodes) do if node.branch==currentBranch then positions[node.key]={x=xs[node.col],y=-76-(node.tier-1)*88} end end
    for _,node in ipairs(Catalog.nodes) do if node.branch==currentBranch then drawConnector(tree,node,positions) end end

    for _,node in ipairs(Catalog.nodes) do
        if node.branch==currentBranch then
            local p=positions[node.key]; local rank=state.ranks[node.key] or 0; local maxed=rank>=node.max; local available=prereqMet(node)
            local b=addDynamic(CreateFrame("Button",nil,tree)); b:SetPoint("CENTER",tree,"TOPLEFT",p.x,p.y); b:SetSize(60,60)
            local bg=colorTexture(b,"BACKGROUND",maxed and 0.16 or available and 0.11 or 0.045,maxed and 0.12 or available and 0.075 or 0.040,0.025,0.98); bg:SetAllPoints()
            border(b,maxed and 0.70 or available and 0.48 or 0.22,maxed and 0.52 or available and 0.32 or 0.18,maxed and 0.15 or 0.10,1)
            local icon=b:CreateTexture(nil,"ARTWORK"); icon:SetPoint("TOPLEFT",b,"TOPLEFT",5,-5); icon:SetPoint("BOTTOMRIGHT",b,"BOTTOMRIGHT",-5,5); icon:SetTexture(node.icon); icon:SetDesaturated(not available and rank==0); icon:SetAlpha(available or rank>0 and 1 or 0.38)
            local badge=b:CreateFontString(nil,"OVERLAY","GameFontNormalSmall"); badge:SetPoint("BOTTOMRIGHT",b,"BOTTOMRIGHT",-3,3); badge:SetText(rank.."/"..node.max); badge:SetTextColor(1,0.86,0.55)
            b:SetScript("OnClick",function() selectedTalentKey=node.key; Draw() end)
            b:SetScript("OnEnter",function() GameTooltip:SetOwner(b,"ANCHOR_RIGHT"); GameTooltip:AddLine(node.name,1,0.82,0.42); GameTooltip:AddLine(node.desc,0.82,0.82,0.82,true); GameTooltip:Show() end)
            b:SetScript("OnLeave",function() GameTooltip:Hide() end)
            text(tree,p.x-68,p.y-35,136,node.name,"GameFontNormalSmall",0.82,0.76,0.66,"CENTER")
        end
    end

    local node=nodeByKey(selectedTalentKey)
    if not node or node.branch~=currentBranch then for _,n in ipairs(Catalog.nodes) do if n.branch==currentBranch then node=n; selectedTalentKey=n.key; break end end end
    if node then
        local rank=state.ranks[node.key] or 0; local maxed=rank>=node.max; local cost=maxed and 0 or ForeverEncyclopediaTalentCost(node,rank)
        text(detail,18,-18,205,node.name,"GameFontHighlightLarge",1,0.86,0.60)
        text(detail,18,-55,205,string.format("Ранг %d / %d",rank,node.max),"GameFontNormal",0.82,0.72,0.55)
        text(detail,18,-92,205,node.desc,"GameFontNormal",0.78,0.72,0.64)
        if node.req then
            local req=nodeByKey(node.req); text(detail,18,-230,205,"Требуется: "..(req and req.name or node.req).." "..(node.reqRank or 1),"GameFontNormalSmall",0.72,0.62,0.50)
        end
        text(detail,18,-278,205,"Доступно знаний: "..state.knowledgeAvailable,"GameFontNormal",0.88,0.75,0.48)
        if maxed then text(detail,18,-314,205,"Максимальный ранг","GameFontHighlight",0.50,0.82,0.46)
        elseif not prereqMet(node) then text(detail,18,-314,205,"Сначала изучите предыдущий узел.","GameFontNormalSmall",0.82,0.48,0.40)
        else
            text(detail,18,-314,205,"Стоимость следующего: "..cost,"GameFontHighlight",0.95,0.78,0.43)
            local buy=raisedButton(detail,18,-356,205,38,"Изучить",function() send(TALENT_REQ,"buy "..node.key) end,false)
            if state.knowledgeAvailable<cost then buy:Disable() end
        end
    end
end

local function drawAppearanceTab()
    local left=panel(content,10,-10,590,474); local right=panel(content,612,-10,324,474)
    text(left,16,-14,550,"Облики Живой книги","GameFontHighlightLarge",1,0.86,0.60)
    text(left,16,-44,550,"Облик не меняет боевую силу. Пороги — коллекционные цели.","GameFontNormalSmall",0.72,0.65,0.55)
    for i,a in ipairs(Catalog.appearances) do
        local col=(i-1)%2; local row=math.floor((i-1)/2); local x=16+col*278; local y=-76-row*126
        local card=addDynamic(CreateFrame("Button",nil,left)); card:SetPoint("TOPLEFT",left,"TOPLEFT",x,y); card:SetSize(264,112)
        local bg=colorTexture(card,"BACKGROUND",0.075,0.045,0.022,0.98); bg:SetAllPoints(); border(card,selectedAppearanceKey==a.key and 0.80 or 0.38,selectedAppearanceKey==a.key and 0.50 or 0.24,0.08,1)
        local mini=CreateFrame("PlayerModel",nil,card); mini:SetPoint("TOPLEFT",card,"TOPLEFT",6,-6); mini:SetSize(104,78); mini:SetKeepModelOnHide(true); mini:EnableMouse(false)
        pcall(function() mini:SetCreature(a.creature); mini:SetPortraitZoom(0); mini:SetCamDistanceScale(1.45); mini:RefreshCamera() end)
        local unlocked=state.appearances[a.key] and state.appearances[a.key].unlocked
        if not unlocked then local shade=colorTexture(card,"ARTWORK",0,0,0,0.48); shade:SetPoint("TOPLEFT",mini,"TOPLEFT"); shade:SetPoint("BOTTOMRIGHT",mini,"BOTTOMRIGHT") end
        text(card,120,-16,132,a.name,"GameFontHighlight",0.94,0.84,0.66)
        text(card,120,-46,132,unlocked and "Доступен" or ("Требуется: "..a.threshold),"GameFontNormalSmall",unlocked and 0.48 or 0.72,unlocked and 0.82 or 0.56,unlocked and 0.44 or 0.42)
        if state.selectedAppearance==a.key then text(card,120,-70,132,"Используется","GameFontNormalSmall",0.96,0.72,0.28) end
        card:SetScript("OnClick",function() selectedAppearanceKey=a.key; Draw() end)
    end
    local chosen
    for _,a in ipairs(Catalog.appearances) do if a.key==selectedAppearanceKey then chosen=a break end end
    chosen=chosen or Catalog.appearances[1]
    text(right,20,-18,284,chosen.name,"GameFontHighlightLarge",1,0.86,0.60)
    text(right,20,-53,284,chosen.source,"GameFontNormal",0.78,0.70,0.59)
    local plate=addDynamic(CreateFrame("Frame",nil,right)); plate:SetPoint("TOPLEFT",right,"TOPLEFT",34,-92); plate:SetSize(256,236)
    local bg=colorTexture(plate,"BACKGROUND",0.008,0.008,0.007,0.97); bg:SetAllPoints(); border(plate,0.45,0.28,0.09,0.95)
    appearanceModel=CreateFrame("PlayerModel",nil,plate); appearanceModel:SetPoint("TOPLEFT",plate,"TOPLEFT",6,-6); appearanceModel:SetPoint("BOTTOMRIGHT",plate,"BOTTOMRIGHT",-6,6); appearanceModel:SetKeepModelOnHide(true); appearanceModel:EnableMouse(true); appearanceModel:EnableMouseWheel(true)
    appearanceModel:SetScript("OnMouseDown",function(_,button) if button=="LeftButton" then appearanceDragging=true; dragX=GetCursorPosition(); dragRotation=appearanceRotation end end)
    appearanceModel:SetScript("OnMouseUp",function() appearanceDragging=false end)
    appearanceModel:SetScript("OnUpdate",function() if appearanceDragging then local x=GetCursorPosition(); appearanceRotation=dragRotation+(x-dragX)*0.012; appearanceModel:SetRotation(appearanceRotation,false) end end)
    appearanceModel:SetScript("OnMouseWheel",function(_,d) appearanceZoom=math.max(0.8,math.min(2.0,appearanceZoom-d*0.10)); appearanceModel:SetCamDistanceScale(appearanceZoom); appearanceModel:RefreshCamera() end)
    setAppearanceModel(chosen.creature)
    local unlocked=state.appearances[chosen.key] and state.appearances[chosen.key].unlocked
    if unlocked then
        raisedButton(right,60,-356,204,38,state.selectedAppearance==chosen.key and "Используется" or "Выбрать",function() if state.selectedAppearance~=chosen.key then send(TALENT_REQ,"appearance "..chosen.key) end end,state.selectedAppearance==chosen.key)
    else
        text(right,30,-364,264,"Облик откроется при накоплении "..chosen.threshold.." знаний.","GameFontNormalSmall",0.72,0.58,0.44,"CENTER")
    end
end

Draw=function()
    if not main then return end
    clearDynamic(); creatureModel=nil; appearanceModel=nil
    for i,b in ipairs(tabs) do b._selected=(i==currentTab) end
    if currentTab==1 then drawCreatureTab()
    elseif currentTab==2 then drawLocationTab()
    elseif currentTab==3 then drawTalentTab()
    else drawAppearanceTab() end
end

local function switchTab(index)
    currentTab=index; Draw()
    if index==1 then requestCatalog(1)
    elseif index==2 then requestZones()
    elseif index==3 or index==4 then requestTalentStatus() end
end

local function updateHeader()
    if not main then return end
    main.status:SetText(state.online and "Архив синхронизирован" or "Нет связи с архивом")
    main.status:SetTextColor(state.online and 0.42 or 0.88,state.online and 0.82 or 0.42,state.online and 0.48 or 0.36)
    main.stats:SetText(string.format("Знания %d   •   Существа %d   •   Предметы %d   •   Локации %d",state.knowledgeAvailable,state.creatures,state.items,state.zones))
    main.zone:SetText(zoneName())
end

local function createMain()
    if main then return end
    main=CreateFrame("Frame","ForeverEncyclopediaV2Frame",UIParent,"BasicFrameTemplateWithInset")
    main:SetSize(980,640); main:SetPoint("CENTER"); main:SetMovable(true); main:SetClampedToScreen(true); main:EnableMouse(true); main:RegisterForDrag("LeftButton"); main:SetScript("OnDragStart",main.StartMoving); main:SetScript("OnDragStop",main.StopMovingOrSizing); main:Hide()
    main.TitleText:SetText("Живая энциклопедия")
    local bg=main:CreateTexture(nil,"BACKGROUND"); bg:SetPoint("TOPLEFT",main,"TOPLEFT",10,-34); bg:SetPoint("BOTTOMRIGHT",main,"BOTTOMRIGHT",-10,10); bg:SetColorTexture(0.038,0.025,0.016,0.985)
    local header=main:CreateTexture(nil,"BACKGROUND",nil,1); header:SetPoint("TOPLEFT",main,"TOPLEFT",10,-34); header:SetPoint("TOPRIGHT",main,"TOPRIGHT",-10,-34); header:SetHeight(48); header:SetColorTexture(0.085,0.050,0.022,0.98)
    main.status=text(main,24,-49,230,"Нет связи","GameFontNormalSmall",0.8,0.4,0.35)
    main.stats=text(main,280,-49,420,"","GameFontNormalSmall",0.82,0.75,0.63,"CENTER")
    main.zone=text(main,720,-49,230,"","GameFontHighlight",0.93,0.85,0.70,"RIGHT")
    local labels={"Существа","Локации","Таланты","Облики"}
    for i,label in ipairs(labels) do
        local b=raisedButton(main,26+(i-1)*232,-91,216,34,label,function() switchTab(i) end,i==currentTab); tabs[i]=b
    end
    content=CreateFrame("Frame",nil,main); content:SetPoint("TOPLEFT",main,"TOPLEFT",16,-132); content:SetSize(948,486)
    local ver=text(main,0,-616,950,"Forever Encyclopedia V2 • talents 0.7","GameFontNormalSmall",0.46,0.40,0.33,"RIGHT")
    main:SetScript("OnShow",function() requestBaseStatus(); requestTalentStatus(); if currentTab==1 then requestCatalog(state.catalogPage) elseif currentTab==2 then requestZones() end end)
    updateHeader(); Draw()
end

local function createBookDock()
    if bookDock then return end
    if _G.ForeverEncyclopediaBookDock then _G.ForeverEncyclopediaBookDock:Hide() end
    bookDock=CreateFrame("Frame","ForeverEncyclopediaV2BookDock",UIParent); bookDock:SetSize(184,62); bookDock:SetFrameStrata("MEDIUM")
    if QuickJoinToastButton then bookDock:SetPoint("RIGHT",QuickJoinToastButton,"LEFT",-8,0)
    elseif FriendsMicroButton then bookDock:SetPoint("RIGHT",FriendsMicroButton,"LEFT",-8,0)
    elseif ChatFrameMenuButton then bookDock:SetPoint("LEFT",ChatFrameMenuButton,"RIGHT",8,0)
    else bookDock:SetPoint("BOTTOMLEFT",UIParent,"BOTTOMLEFT",24,180) end
    local bg=colorTexture(bookDock,"BACKGROUND",0.04,0.025,0.015,0.95); bg:SetAllPoints(); border(bookDock,0.36,0.23,0.08,0.95)
    local book=CreateFrame("Button",nil,bookDock); book:SetPoint("LEFT",bookDock,"LEFT",6,0); book:SetSize(48,48)
    local bi=book:CreateTexture(nil,"ARTWORK"); bi:SetPoint("TOPLEFT",book,"TOPLEFT",5,-5); bi:SetPoint("BOTTOMRIGHT",book,"BOTTOMRIGHT",-5,5); bi:SetTexture("Interface\\Icons\\INV_Misc_Book_09")
    book:SetScript("OnClick",function() createMain(); if main:IsShown() then main:Hide() else main:Show() end end)
    local mana=CreateFrame("StatusBar",nil,bookDock); mana:SetPoint("TOPLEFT",bookDock,"TOPLEFT",60,-9); mana:SetSize(116,11); mana:SetStatusBarTexture("Interface\\TargetingFrame\\UI-StatusBar"); mana:SetStatusBarColor(0.12,0.33,0.78); local mb=colorTexture(mana,"BACKGROUND",0.015,0.015,0.025,1); mb:SetAllPoints()
    local mt=mana:CreateFontString(nil,"OVERLAY","GameFontNormalSmall"); mt:SetPoint("CENTER")
    bookDock.mana=mana; bookDock.manaText=mt
    local abilities={{1,"Interface\\Icons\\Spell_Holy_PowerWordShield","Охранная печать"},{2,"Interface\\Icons\\Spell_Holy_Heal","Целительная пометка"},{4,"Interface\\Icons\\Spell_Arcane_Arcane01","Тактическая подсказка"}}
    bookDock.abilities={}
    for i,a in ipairs(abilities) do
        local b=CreateFrame("Button",nil,bookDock); b:SetSize(30,30); b:SetPoint("TOPLEFT",bookDock,"TOPLEFT",60+(i-1)*38,-27)
        local ib=colorTexture(b,"BACKGROUND",0.08,0.05,0.025,1); ib:SetAllPoints(); border(b,0.34,0.22,0.08,1)
        local icon=b:CreateTexture(nil,"ARTWORK"); icon:SetPoint("TOPLEFT",b,"TOPLEFT",3,-3); icon:SetPoint("BOTTOMRIGHT",b,"BOTTOMRIGHT",-3,3); icon:SetTexture(a[2])
        b:SetScript("OnEnter",function() GameTooltip:SetOwner(b,"ANCHOR_TOP"); GameTooltip:AddLine(a[3],1,0.82,0.42); GameTooltip:AddLine(abilityUnlocked(a[1]) and "Изучено деревом талантов." or "Не изучено.",0.75,0.75,0.75); GameTooltip:Show() end); b:SetScript("OnLeave",function() GameTooltip:Hide() end)
        bookDock.abilities[i]={bit=a[1],icon=icon}
    end
end

local function updateBookDock()
    if not bookDock then return end
    bookDock.mana:SetMinMaxValues(0,math.max(1,state.maxMana)); bookDock.mana:SetValue(math.min(state.mana,state.maxMana)); bookDock.manaText:SetText(state.mana.." / "..state.maxMana)
    for _,a in ipairs(bookDock.abilities) do a.icon:SetAlpha(abilityUnlocked(a.bit) and 1 or 0.25) end
end

local function parseBase(msg)
    if msg:sub(1,8)=="CATHEAD|" then
        local _,zone,page,pages,total,known,zoneTotal,zoneKnown=strsplit("|",msg)
        state.catalog={}; state.catalogLoaded=false; state.catalogPage=tonumber(page) or 1; state.catalogPages=tonumber(pages) or 1; state.catalogTotal=tonumber(total) or 0; state.catalogKnown=tonumber(known) or 0; state.catalogZoneTotal=tonumber(zoneTotal) or 0; state.catalogZoneKnown=tonumber(zoneKnown) or 0; selectedCreature=1
    elseif msg:sub(1,4)=="CAT|" then
        local _,entry,known,ctype,class,name=strsplit("|",msg)
        state.catalog[#state.catalog+1]={entry=tonumber(entry) or 0,known=tonumber(known)==1,creatureType=tonumber(ctype) or 0,classification=tonumber(class) or 0,name=name or ""}
    elseif msg=="CATEND" then
        state.catalogLoaded=true; state.online=true; selectedCreature=math.min(selectedCreature,#state.catalog); if selectedCreature<1 then selectedCreature=1 end
        for _,rec in ipairs(state.catalog) do if state.infoLevel>0 and not state.creatureInfo[rec.entry] then infoQueue[#infoQueue+1]=rec.entry end end
        if not pendingInfoEntry and #infoQueue>0 then local e=table.remove(infoQueue,1); requestCreatureInfo(e) end
        if main and main:IsShown() and currentTab==1 then Draw() end
    else
        local tag,a,b,c,d,e,f=strsplit(" ",msg)
        if tag=="STATE" then state.total=tonumber(a) or 0; state.creatures=tonumber(b) or 0; state.items=tonumber(c) or 0; state.zones=tonumber(d) or 0; state.online=true
        elseif tag=="KNOW" then state.knowledgeTotal=tonumber(a) or 0; state.knowledgeSpent=tonumber(b) or 0; state.knowledgeAvailable=tonumber(c) or 0
        elseif tag=="CURRENT" then state.map=tonumber(a) or 0; state.zone=tonumber(b) or 0; state.area=tonumber(c) or 0
        elseif tag=="BOOK" then if state.maxMana<=100 then state.mana=tonumber(a) or 0; state.maxMana=tonumber(b) or 100 end
        elseif tag=="REC" and tonumber(a)==3 then state.recentZones[#state.recentZones+1]={entry=tonumber(b) or 0,map=tonumber(c) or 0,zone=tonumber(d) or 0}
        elseif tag=="RECEND" and tonumber(a)==3 then state.recentZonesLoaded=true; if main and main:IsShown() and currentTab==2 then Draw() end
        elseif tag=="END" then state.online=true end
        updateHeader(); updateBookDock()
    end
end

local function parseTalent(msg)
    if msg:sub(1,7)=="POINTS|" then local _,t,s,a=strsplit("|",msg); state.knowledgeTotal=tonumber(t) or 0; state.knowledgeSpent=tonumber(s) or 0; state.knowledgeAvailable=tonumber(a) or 0; state.ranks={}
    elseif msg:sub(1,5)=="RANK|" then local _,key,rank=strsplit("|",msg); state.ranks[key]=tonumber(rank) or 0
    elseif msg:sub(1,5)=="BOOK|" then local _,mask,mana,maxMana,info=strsplit("|",msg); state.abilityMask=tonumber(mask) or 0; state.mana=tonumber(mana) or 0; state.maxMana=tonumber(maxMana) or 100; state.infoLevel=tonumber(info) or 0
    elseif msg:sub(1,11)=="APPEARANCE|" then local _,key,u,threshold=strsplit("|",msg); state.appearances[key]={unlocked=tonumber(u)==1,threshold=tonumber(threshold) or 0}
    elseif msg:sub(1,9)=="SELECTED|" then local _,key=strsplit("|",msg); state.selectedAppearance=key or "living_book"
    elseif msg:sub(1,9)=="CREATURE|" then local _,entry,level=strsplit("|",msg); pendingInfoEntry=tonumber(entry) or pendingInfoEntry; if pendingInfoEntry then state.creatureInfo[pendingInfoEntry]=state.creatureInfo[pendingInfoEntry] or {}; state.creatureInfo[pendingInfoEntry].level=tonumber(level) or 0 end
    elseif msg:sub(1,6)=="CBASE|" then local _,name,ctype,class,minLevel,maxLevel=strsplit("|",msg); if pendingInfoEntry then local ci=state.creatureInfo[pendingInfoEntry] or {}; ci.name=name or ""; ci.creatureType=tonumber(ctype) or 0; ci.classification=tonumber(class) or 0; ci.minLevel=tonumber(minLevel) or 0; ci.maxLevel=tonumber(maxLevel) or 0; state.creatureInfo[pendingInfoEntry]=ci end
    elseif msg=="CEND" then pendingInfoEntry=nil; if #infoQueue>0 then local e=table.remove(infoQueue,1); requestCreatureInfo(e) end
    elseif msg:sub(1,7)=="BOUGHT|" then requestTalentStatus()
    elseif msg:sub(1,6)=="ERROR|" then local _,err=strsplit("|",msg); if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cffff8040[Энциклопедия]|r "..(err or "Ошибка")) end
    elseif msg=="END" then state.online=true end
    updateHeader(); updateBookDock(); if main and main:IsShown() then Draw() end
end

SLASH_FOREVERENCYCLOPEDIAV2_1="/ency"
SLASH_FOREVERENCYCLOPEDIAV2_2="/encyclopedia"
SlashCmdList["FOREVERENCYCLOPEDIAV2"]=function() createMain(); if main:IsShown() then main:Hide() else main:Show() end end

local events=CreateFrame("Frame")
events:RegisterEvent("ADDON_LOADED"); events:RegisterEvent("PLAYER_LOGIN"); events:RegisterEvent("PLAYER_ENTERING_WORLD"); events:RegisterEvent("ZONE_CHANGED_NEW_AREA"); events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent",function(_,event,...)
    if event=="ADDON_LOADED" then local name=...; if name~=ADDON then return end; registerPrefixes(); return end
    if event=="CHAT_MSG_ADDON" then local prefix,msg=...; if prefix==BASE_RES then parseBase(tostring(msg or "")) elseif prefix==TALENT_RES then parseTalent(tostring(msg or "")) end; return end
    if event=="PLAYER_LOGIN" then createBookDock() end
    if event=="ZONE_CHANGED_NEW_AREA" then state.catalogLoaded=false; state.catalog={}; state.catalogPage=1 end
    C_Timer.After(1,function() requestBaseStatus(); requestTalentStatus(); if main and main:IsShown() then if currentTab==1 then requestCatalog(1) elseif currentTab==2 then requestZones() end end end)
end)
