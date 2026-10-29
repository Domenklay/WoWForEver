local ADDON = ...
local BASE_REQ, BASE_RES = "FEC1", "FER1"
local TAL_REQ, TAL_RES = "FET1", "FTR1"
local SERVER_TARGET = "SERVER"
local Catalog = ForeverEncyclopediaTalentCatalog

local ui, content, dock
local tabButtons = {}
local dynamic = {}
local currentTab = 1
local currentBranch = "knowledge"
local selectedCreature = 1
local selectedTalent = "identify_name"
local selectedAppearance = "living_book"
local selectedLocation = 1
local creatureModel, appearanceModel
local creatureRotation, creatureZoom = 0.30, 1.35
local appearanceRotation, appearanceZoom = 0.25, 1.25
local dragStartX, dragStartRotation
local creatureDragging, appearanceDragging = false, false
local pendingCreatureInfo
local infoQueue = {}
local talentBatch = false
local Draw

local state = {
    online=false,
    total=0, creatures=0, items=0, zones=0,
    map=0, zone=0, area=0,
    knowledgeTotal=0, knowledgeSpent=0, knowledgeAvailable=0,
    catalog={}, catalogLoaded=false, catalogPage=1, catalogPages=1,
    catalogTotal=0, catalogKnown=0, catalogZoneTotal=0, catalogZoneKnown=0,
    recentZones={}, recentZonesLoaded=false,
    ranks={}, abilityMask=0, mana=0, maxMana=100, infoLevel=0,
    appearances={}, selectedAppearance="living_book",
    creatureInfo={},
}

local CREATURE_TYPES={
    [1]="Зверь",[2]="Драконид",[3]="Демон",[4]="Элементаль",[5]="Великан",[6]="Нежить",
    [7]="Гуманоид",[8]="Существо",[9]="Механизм",[10]="Существо",[11]="Тотем",[12]="Спутник",
}
local CLASSIFICATIONS={[0]="Обычный",[1]="Элита",[2]="Редкая элита",[3]="Мировой босс",[4]="Редкий"}

local function registerPrefixes()
    if C_ChatInfo and C_ChatInfo.RegisterAddonMessagePrefix then
        for _,p in ipairs({BASE_REQ,BASE_RES,TAL_REQ,TAL_RES}) do pcall(C_ChatInfo.RegisterAddonMessagePrefix,p) end
    end
end

local function send(prefix,payload)
    registerPrefixes()
    if C_ChatInfo and C_ChatInfo.SendAddonMessage then
        return pcall(C_ChatInfo.SendAddonMessage,prefix,payload,"WHISPER",SERVER_TARGET)
    end
    return false
end

local function requestBaseStatus() send(BASE_REQ,"status") end
local function requestTalentStatus() send(TAL_REQ,"status") end
local function requestCatalog(page) send(BASE_REQ,"catalog "..tostring(page or 1).." 0 0 -1") end
local function requestZones() state.recentZones={}; state.recentZonesLoaded=false; send(BASE_REQ,"recent 3") end

local function zoneName()
    local z=GetRealZoneText and GetRealZoneText() or ""
    if z~="" then return z end
    return state.zone>0 and ("Зона "..state.zone) or "Неизвестная зона"
end

local function areaName(id)
    if C_Map and C_Map.GetAreaInfo then local ok,n=pcall(C_Map.GetAreaInfo,id); if ok and n and n~="" then return n end end
    if GetAreaInfo then local ok,n=pcall(GetAreaInfo,id); if ok and n and n~="" then return n end end
    return nil
end

local function addDynamic(o) dynamic[#dynamic+1]=o return o end
local function clearDynamic() for _,o in ipairs(dynamic) do if o.Hide then o:Hide() end end wipe(dynamic); creatureModel=nil; appearanceModel=nil end

local function tex(parent,layer,r,g,b,a)
    local t=parent:CreateTexture(nil,layer or "BACKGROUND"); t:SetColorTexture(r,g,b,a or 1); return t
end

local function addBorder(frame,r,g,b,a)
    local e={}
    local t=tex(frame,"BORDER",r,g,b,a); t:SetPoint("TOPLEFT"); t:SetPoint("TOPRIGHT"); t:SetHeight(1); e[#e+1]=t
    local d=tex(frame,"BORDER",r,g,b,a); d:SetPoint("BOTTOMLEFT"); d:SetPoint("BOTTOMRIGHT"); d:SetHeight(1); e[#e+1]=d
    local l=tex(frame,"BORDER",r,g,b,a); l:SetPoint("TOPLEFT"); l:SetPoint("BOTTOMLEFT"); l:SetWidth(1); e[#e+1]=l
    local rr=tex(frame,"BORDER",r,g,b,a); rr:SetPoint("TOPRIGHT"); rr:SetPoint("BOTTOMRIGHT"); rr:SetWidth(1); e[#e+1]=rr
    return e
end

local function fs(parent,x,y,w,s,font,r,g,b,justify)
    local f=parent:CreateFontString(nil,"OVERLAY",font or "GameFontNormal")
    f:SetPoint("TOPLEFT",parent,"TOPLEFT",x,y); if w then f:SetWidth(w) end; f:SetJustifyH(justify or "LEFT"); f:SetText(s or "")
    if r then f:SetTextColor(r,g,b) end
    return f
end

local function panel(parent,x,y,w,h)
    local p=addDynamic(CreateFrame("Frame",nil,parent)); p:SetPoint("TOPLEFT",parent,"TOPLEFT",x,y); p:SetSize(w,h)
    local bg=tex(p,"BACKGROUND",0.052,0.033,0.019,0.98); bg:SetAllPoints()
    local upper=tex(p,"BACKGROUND",0.15,0.09,0.035,0.18); upper:SetPoint("TOPLEFT",p,"TOPLEFT",2,-2); upper:SetPoint("TOPRIGHT",p,"TOPRIGHT",-2,-2); upper:SetHeight(math.floor(h*0.40))
    addBorder(p,0.35,0.22,0.075,0.95)
    return p
end

local function raised(parent,x,y,w,h,label,onclick,selected,persistent)
    local b=CreateFrame("Button",nil,parent); if not persistent then addDynamic(b) end
    b:SetPoint("TOPLEFT",parent,"TOPLEFT",x,y); b:SetSize(w,h); b._selected=selected and true or false
    local base=tex(b,"BACKGROUND",0.11,0.065,0.027,0.98); base:SetAllPoints()
    local top=tex(b,"BACKGROUND",0.30,0.18,0.055,0.32); top:SetPoint("TOPLEFT",b,"TOPLEFT",2,-2); top:SetPoint("TOPRIGHT",b,"TOPRIGHT",-2,-2); top:SetHeight(math.max(6,math.floor(h*0.44)))
    local bottom=tex(b,"BACKGROUND",0.025,0.014,0.008,0.74); bottom:SetPoint("BOTTOMLEFT",b,"BOTTOMLEFT",2,2); bottom:SetPoint("BOTTOMRIGHT",b,"BOTTOMRIGHT",-2,2); bottom:SetHeight(math.max(6,math.floor(h*0.38)))
    local edges=addBorder(b,0.42,0.27,0.08,1)
    local shine=tex(b,"BORDER",0.95,0.72,0.30,0.22); shine:SetPoint("TOPLEFT",b,"TOPLEFT",3,-3); shine:SetPoint("TOPRIGHT",b,"TOPRIGHT",-3,-3); shine:SetHeight(1)
    local labelText=b:CreateFontString(nil,"OVERLAY","GameFontHighlight"); labelText:SetPoint("CENTER"); labelText:SetText(label or "")
    local function recolor(hover)
        local sel=b._selected
        base:SetColorTexture(hover and 0.20 or (sel and 0.24 or 0.11),hover and 0.115 or (sel and 0.14 or 0.065),hover and 0.035 or (sel and 0.045 or 0.027),1)
        labelText:SetTextColor(sel and 1 or 0.86,sel and 0.80 or 0.80,sel and 0.40 or 0.70)
        for _,edge in ipairs(edges) do edge:SetColorTexture(sel and 0.82 or 0.42,sel and 0.52 or 0.27,sel and 0.13 or 0.08,1) end
    end
    b.SetEncySelected=function(_,v) b._selected=v and true or false; recolor(false) end
    b:SetScript("OnEnter",function() recolor(true) end); b:SetScript("OnLeave",function() recolor(false) end); b:SetScript("OnClick",onclick); recolor(false)
    return b
end

local function abilityUnlocked(bit)
    if bit32 then return bit32.band(state.abilityMask,bit)~=0 end
    return state.abilityMask%(bit*2)>=bit
end

local function nodeByKey(key) for _,n in ipairs(Catalog.nodes) do if n.key==key then return n end end end
local function prereqMet(n) return not n.req or (state.ranks[n.req] or 0)>=(n.reqRank or 1) end

local function requestCreatureInfo(entry)
    entry=tonumber(entry); if not entry or entry<=0 or state.infoLevel<=0 then return end
    pendingCreatureInfo=entry; send(TAL_REQ,"creature "..entry)
end

local function queueCatalogInfo()
    wipe(infoQueue)
    if state.infoLevel<=0 then return end
    for _,rec in ipairs(state.catalog) do if not state.creatureInfo[rec.entry] then infoQueue[#infoQueue+1]=rec.entry end end
    if not pendingCreatureInfo and #infoQueue>0 then requestCreatureInfo(table.remove(infoQueue,1)) end
end

local function creatureDisplay(rec)
    if not rec then return "???","Неизвестное существо",nil end
    local info=state.creatureInfo[rec.entry]
    local name=rec.name~="" and rec.name or (info and info.name) or "???"
    local typ=(rec.creatureType or 0)>0 and rec.creatureType or (info and info.creatureType) or 0
    local cl=(rec.classification or 0)>0 and rec.classification or (info and info.classification) or 0
    local meta=typ>0 and (CREATURE_TYPES[typ] or "Существо") or "Неизвестное существо"
    if cl>0 then meta=meta.."  •  "..(CLASSIFICATIONS[cl] or "") end
    return name,meta,info
end

local function setupModel(model,entry,zoom,rotation)
    model:ClearModel()
    pcall(function() model:SetCreature(entry); model:SetPortraitZoom(0); model:SetCamDistanceScale(zoom); model:SetRotation(rotation,false); model:RefreshCamera() end)
end

local function drawCreatureTab()
    local left=panel(content,10,-10,360,474); local right=panel(content,382,-10,554,474)
    fs(left,16,-14,320,zoneName(),"GameFontHighlightLarge",1,0.86,0.60)
    local pct=state.catalogZoneTotal>0 and math.floor(state.catalogZoneKnown*100/state.catalogZoneTotal) or 0
    fs(left,16,-44,320,string.format("Встречено %d из %d  •  %d%%",state.catalogZoneKnown,state.catalogZoneTotal,pct),"GameFontNormalSmall",0.75,0.68,0.57)
    if not state.catalogLoaded then fs(left,16,-82,320,"Синхронизация каталога…","GameFontNormal",0.72,0.66,0.58) else
        for i,rec in ipairs(state.catalog) do
            local name=creatureDisplay(rec)
            local row=raised(left,14,-76-(i-1)*38,314,34,name,function() selectedCreature=i; if not state.creatureInfo[rec.entry] then requestCreatureInfo(rec.entry) end; Draw() end,i==selectedCreature,false)
            local s=row:CreateFontString(nil,"OVERLAY","GameFontNormalSmall"); s:SetPoint("RIGHT",row,"RIGHT",-8,0); s:SetText(rec.known and "Встречено" or "Не встречено"); s:SetTextColor(rec.known and 0.45 or 0.58,rec.known and 0.82 or 0.53,rec.known and 0.44 or 0.45)
        end
    end
    fs(left,112,-443,136,string.format("Страница %d / %d",state.catalogPage,state.catalogPages),"GameFontNormalSmall",0.72,0.65,0.55,"CENTER")
    local prev=raised(left,14,-432,84,28,"Назад",function() if state.catalogPage>1 then requestCatalog(state.catalogPage-1) end end,false,false)
    local nextb=raised(left,248,-432,84,28,"Далее",function() if state.catalogPage<state.catalogPages then requestCatalog(state.catalogPage+1) end end,false,false)
    if state.catalogPage<=1 then prev:Disable() end; if state.catalogPage>=state.catalogPages then nextb:Disable() end
    left:EnableMouseWheel(true); left:SetScript("OnMouseWheel",function(_,d) if d<0 and state.catalogPage<state.catalogPages then requestCatalog(state.catalogPage+1) elseif d>0 and state.catalogPage>1 then requestCatalog(state.catalogPage-1) end end)

    local rec=state.catalog[selectedCreature]; if not rec then fs(right,24,-24,500,"Выберите запись слева.","GameFontHighlight",0.9,0.82,0.68); return end
    local name,meta,info=creatureDisplay(rec)
    fs(right,24,-20,500,name,"GameFontHighlightLarge",1,0.88,0.62); fs(right,24,-51,500,meta,"GameFontNormal",0.80,0.68,0.48)
    local plate=addDynamic(CreateFrame("Frame",nil,right)); plate:SetPoint("TOPLEFT",right,"TOPLEFT",24,-86); plate:SetSize(192,158); local pbg=tex(plate,"BACKGROUND",0.006,0.006,0.006,0.98); pbg:SetAllPoints(); addBorder(plate,0.45,0.28,0.09,0.95)
    creatureModel=CreateFrame("PlayerModel",nil,plate); creatureModel:SetPoint("TOPLEFT",plate,"TOPLEFT",5,-5); creatureModel:SetPoint("BOTTOMRIGHT",plate,"BOTTOMRIGHT",-5,5); creatureModel:SetKeepModelOnHide(true); creatureModel:EnableMouse(true); creatureModel:EnableMouseWheel(true)
    creatureRotation,creatureZoom=0.30,1.35; setupModel(creatureModel,rec.entry,creatureZoom,creatureRotation)
    creatureModel:SetScript("OnMouseDown",function(_,b) if b=="LeftButton" then creatureDragging=true; dragStartX=GetCursorPosition(); dragStartRotation=creatureRotation end end); creatureModel:SetScript("OnMouseUp",function() creatureDragging=false end)
    creatureModel:SetScript("OnUpdate",function() if creatureDragging then local x=GetCursorPosition(); creatureRotation=dragStartRotation+(x-dragStartX)*0.012; creatureModel:SetRotation(creatureRotation,false) end end)
    creatureModel:SetScript("OnMouseWheel",function(_,d) creatureZoom=math.max(0.85,math.min(2.0,creatureZoom-d*0.10)); creatureModel:SetCamDistanceScale(creatureZoom); creatureModel:RefreshCamera() end)

    fs(right,238,-96,286,rec.known and "Запись встречена" or "Запись ещё не встречена","GameFontHighlight",rec.known and 0.52 or 0.86,rec.known and 0.82 or 0.68,rec.known and 0.45 or 0.42)
    fs(right,238,-128,286,"Встречается: "..zoneName(),"GameFontNormal",0.82,0.76,0.66)
    if info and state.infoLevel>=3 then fs(right,238,-160,286,string.format("Уровни: %d–%d",info.minLevel or 0,info.maxLevel or 0),"GameFontNormal",0.82,0.76,0.66) end
    fs(right,24,-270,500,"Архивные сведения","GameFontHighlight",0.98,0.82,0.54)
    local rows={{1,"Название и тип"},{2,"Класс угрозы"},{3,"Уровни и параметры"},{4,"Способности"},{5,"Сопротивления"},{6,"Полезный лут"},{7,"Ареал обитания"},{8,"Редкие примечания"}}
    for i,r in ipairs(rows) do local unlocked=state.infoLevel>=r[1]; fs(right,24,-300-(i-1)*18,480,(unlocked and "✓ " or "• ")..r[2],"GameFontNormalSmall",unlocked and 0.55 or 0.56,unlocked and 0.80 or 0.51,unlocked and 0.48 or 0.44) end
    if state.infoLevel==0 then fs(right,270,-420,250,"Первый уровень Познания стоит всего 1 очко.","GameFontNormalSmall",0.92,0.72,0.40) end
end

local function drawLocationTab()
    local left=panel(content,10,-10,360,474); local right=panel(content,382,-10,554,474)
    fs(left,16,-14,320,"Изученные локации","GameFontHighlightLarge",1,0.86,0.60); fs(left,16,-44,320,"Последние открытия аккаунта","GameFontNormalSmall",0.72,0.65,0.55)
    if not state.recentZonesLoaded then fs(left,16,-84,320,"Получаю список…","GameFontNormal",0.72,0.66,0.58) else
        for i,rec in ipairs(state.recentZones) do local title=areaName(rec.entry) or ("Локация "..rec.entry); raised(left,14,-76-(i-1)*38,314,34,title,function() selectedLocation=i; Draw() end,i==selectedLocation,false) end
    end
    fs(right,24,-20,500,zoneName(),"GameFontHighlightLarge",1,0.88,0.62); fs(right,24,-58,500,"Архив исследования мира","GameFontNormal",0.80,0.68,0.48)
    fs(right,24,-108,500,"Новые зоны открываются один раз на аккаунт и дают 3 очка знаний.","GameFontNormal",0.82,0.76,0.66)
    fs(right,24,-150,500,"Следующий этап этой вкладки — общий прогресс зоны, особые места и архивные заметки.","GameFontNormal",0.72,0.67,0.58)
end

local function drawTalentConnector(tree,n,pos)
    if not n.req or not pos[n.req] or not pos[n.key] then return end
    local a,b=pos[n.req],pos[n.key]; local mid=(a.y+b.y)/2
    local v1=tex(tree,"ARTWORK",0.34,0.23,0.09,0.9); v1:SetPoint("TOPLEFT",tree,"TOPLEFT",a.x-1,a.y-30); v1:SetSize(2,math.max(1,math.abs(a.y-mid)))
    local h=tex(tree,"ARTWORK",0.34,0.23,0.09,0.9); h:SetPoint("TOPLEFT",tree,"TOPLEFT",math.min(a.x,b.x),mid); h:SetSize(math.max(2,math.abs(a.x-b.x)),2)
    local v2=tex(tree,"ARTWORK",0.34,0.23,0.09,0.9); v2:SetPoint("TOPLEFT",tree,"TOPLEFT",b.x-1,mid); v2:SetSize(2,math.max(1,math.abs(mid-(b.y+30))))
end

local function drawTalentTab()
    local tree=panel(content,10,-10,672,474); local detail=panel(content,694,-10,242,474)
    for i,key in ipairs(Catalog.order) do local m=Catalog.branches[key]; raised(tree,12+(i-1)*128,-12,120,30,m.name,function() currentBranch=key; Draw() end,currentBranch==key,false) end
    local xs={100,316,532}; local pos={}
    for _,n in ipairs(Catalog.nodes) do if n.branch==currentBranch then pos[n.key]={x=xs[n.col],y=-76-(n.tier-1)*88} end end
    for _,n in ipairs(Catalog.nodes) do if n.branch==currentBranch then drawTalentConnector(tree,n,pos) end end
    for _,n in ipairs(Catalog.nodes) do if n.branch==currentBranch then
        local p=pos[n.key]; local rank=state.ranks[n.key] or 0; local available=prereqMet(n); local maxed=rank>=n.max
        local b=addDynamic(CreateFrame("Button",nil,tree)); b:SetPoint("CENTER",tree,"TOPLEFT",p.x,p.y); b:SetSize(60,60)
        local bg=tex(b,"BACKGROUND",maxed and 0.16 or available and 0.11 or 0.045,maxed and 0.12 or available and 0.075 or 0.040,0.025,0.98); bg:SetAllPoints(); addBorder(b,maxed and 0.70 or available and 0.48 or 0.22,maxed and 0.52 or available and 0.32 or 0.18,0.10,1)
        local icon=b:CreateTexture(nil,"ARTWORK"); icon:SetPoint("TOPLEFT",b,"TOPLEFT",5,-5); icon:SetPoint("BOTTOMRIGHT",b,"BOTTOMRIGHT",-5,5); icon:SetTexture(n.icon); icon:SetDesaturated((not available) and rank==0); icon:SetAlpha((available or rank>0) and 1 or 0.38)
        local badge=b:CreateFontString(nil,"OVERLAY","GameFontNormalSmall"); badge:SetPoint("BOTTOMRIGHT",b,"BOTTOMRIGHT",-3,3); badge:SetText(rank.."/"..n.max); badge:SetTextColor(1,0.86,0.55)
        b:SetScript("OnClick",function() selectedTalent=n.key; Draw() end); b:SetScript("OnEnter",function() GameTooltip:SetOwner(b,"ANCHOR_RIGHT"); GameTooltip:AddLine(n.name,1,0.82,0.42); GameTooltip:AddLine(n.desc,0.82,0.82,0.82,true); GameTooltip:Show() end); b:SetScript("OnLeave",function() GameTooltip:Hide() end)
        fs(tree,p.x-68,p.y-35,136,n.name,"GameFontNormalSmall",0.82,0.76,0.66,"CENTER")
    end end
    local n=nodeByKey(selectedTalent); if not n or n.branch~=currentBranch then for _,candidate in ipairs(Catalog.nodes) do if candidate.branch==currentBranch then n=candidate; selectedTalent=candidate.key; break end end end
    if n then
        local rank=state.ranks[n.key] or 0; local maxed=rank>=n.max; local cost=maxed and 0 or ForeverEncyclopediaTalentCost(n,rank)
        fs(detail,18,-18,205,n.name,"GameFontHighlightLarge",1,0.86,0.60); fs(detail,18,-55,205,string.format("Ранг %d / %d",rank,n.max),"GameFontNormal",0.82,0.72,0.55); fs(detail,18,-92,205,n.desc,"GameFontNormal",0.78,0.72,0.64)
        if n.req then local req=nodeByKey(n.req); fs(detail,18,-230,205,"Требуется: "..(req and req.name or n.req).." "..(n.reqRank or 1),"GameFontNormalSmall",0.72,0.62,0.50) end
        fs(detail,18,-278,205,"Доступно знаний: "..state.knowledgeAvailable,"GameFontNormal",0.88,0.75,0.48)
        if maxed then fs(detail,18,-314,205,"Максимальный ранг","GameFontHighlight",0.50,0.82,0.46)
        elseif not prereqMet(n) then fs(detail,18,-314,205,"Сначала изучите предыдущий узел.","GameFontNormalSmall",0.82,0.48,0.40)
        else fs(detail,18,-314,205,"Стоимость следующего: "..cost,"GameFontHighlight",0.95,0.78,0.43); local buy=raised(detail,18,-356,205,38,"Изучить",function() send(TAL_REQ,"buy "..n.key) end,false,false); if state.knowledgeAvailable<cost then buy:Disable() end end
    end
end

local function drawAppearanceTab()
    local left=panel(content,10,-10,590,474); local right=panel(content,612,-10,324,474)
    fs(left,16,-14,550,"Облики Живой книги","GameFontHighlightLarge",1,0.86,0.60); fs(left,16,-44,550,"Облики не меняют боевую силу книги.","GameFontNormalSmall",0.72,0.65,0.55)
    for i,a in ipairs(Catalog.appearances) do
        local col=(i-1)%2; local row=math.floor((i-1)/2); local x=16+col*278; local y=-76-row*126
        local card=addDynamic(CreateFrame("Button",nil,left)); card:SetPoint("TOPLEFT",left,"TOPLEFT",x,y); card:SetSize(264,112); local bg=tex(card,"BACKGROUND",0.070,0.042,0.020,0.98); bg:SetAllPoints(); addBorder(card,selectedAppearance==a.key and 0.80 or 0.38,selectedAppearance==a.key and 0.50 or 0.24,0.08,1)
        local mp=CreateFrame("PlayerModel",nil,card); mp:SetPoint("TOPLEFT",card,"TOPLEFT",6,-6); mp:SetSize(106,80); mp:SetKeepModelOnHide(true); mp:EnableMouse(false); setupModel(mp,a.creature,1.45,0.25)
        local unlocked=state.appearances[a.key] and state.appearances[a.key].unlocked
        if not unlocked then local shade=tex(card,"ARTWORK",0,0,0,0.48); shade:SetPoint("TOPLEFT",mp,"TOPLEFT"); shade:SetPoint("BOTTOMRIGHT",mp,"BOTTOMRIGHT") end
        fs(card,120,-16,132,a.name,"GameFontHighlight",0.94,0.84,0.66); fs(card,120,-46,132,unlocked and "Доступен" or ("Требуется: "..a.threshold),"GameFontNormalSmall",unlocked and 0.48 or 0.72,unlocked and 0.82 or 0.56,unlocked and 0.44 or 0.42)
        if state.selectedAppearance==a.key then fs(card,120,-70,132,"Используется","GameFontNormalSmall",0.96,0.72,0.28) end
        card:SetScript("OnClick",function() selectedAppearance=a.key; Draw() end)
    end
    local chosen=Catalog.appearances[1]; for _,a in ipairs(Catalog.appearances) do if a.key==selectedAppearance then chosen=a break end end
    fs(right,20,-18,284,chosen.name,"GameFontHighlightLarge",1,0.86,0.60); fs(right,20,-53,284,chosen.source,"GameFontNormal",0.78,0.70,0.59)
    local plate=addDynamic(CreateFrame("Frame",nil,right)); plate:SetPoint("TOPLEFT",right,"TOPLEFT",34,-92); plate:SetSize(256,236); local bg=tex(plate,"BACKGROUND",0.006,0.006,0.006,0.98); bg:SetAllPoints(); addBorder(plate,0.45,0.28,0.09,0.95)
    appearanceModel=CreateFrame("PlayerModel",nil,plate); appearanceModel:SetPoint("TOPLEFT",plate,"TOPLEFT",6,-6); appearanceModel:SetPoint("BOTTOMRIGHT",plate,"BOTTOMRIGHT",-6,6); appearanceModel:SetKeepModelOnHide(true); appearanceModel:EnableMouse(true); appearanceModel:EnableMouseWheel(true); appearanceRotation,appearanceZoom=0.25,1.25; setupModel(appearanceModel,chosen.creature,appearanceZoom,appearanceRotation)
    appearanceModel:SetScript("OnMouseDown",function(_,b) if b=="LeftButton" then appearanceDragging=true; dragStartX=GetCursorPosition(); dragStartRotation=appearanceRotation end end); appearanceModel:SetScript("OnMouseUp",function() appearanceDragging=false end)
    appearanceModel:SetScript("OnUpdate",function() if appearanceDragging then local x=GetCursorPosition(); appearanceRotation=dragStartRotation+(x-dragStartX)*0.012; appearanceModel:SetRotation(appearanceRotation,false) end end)
    appearanceModel:SetScript("OnMouseWheel",function(_,d) appearanceZoom=math.max(0.85,math.min(2.0,appearanceZoom-d*0.10)); appearanceModel:SetCamDistanceScale(appearanceZoom); appearanceModel:RefreshCamera() end)
    local unlocked=state.appearances[chosen.key] and state.appearances[chosen.key].unlocked
    if unlocked then raised(right,60,-356,204,38,state.selectedAppearance==chosen.key and "Используется" or "Выбрать",function() if state.selectedAppearance~=chosen.key then send(TAL_REQ,"appearance "..chosen.key) end end,state.selectedAppearance==chosen.key,false)
    else fs(right,30,-364,264,"Откроется при накоплении "..chosen.threshold.." знаний.","GameFontNormalSmall",0.72,0.58,0.44,"CENTER") end
end

Draw=function()
    if not ui then return end
    clearDynamic()
    for i,b in ipairs(tabButtons) do b:SetEncySelected(i==currentTab) end
    if currentTab==1 then drawCreatureTab() elseif currentTab==2 then drawLocationTab() elseif currentTab==3 then drawTalentTab() else drawAppearanceTab() end
end

local function updateHeader()
    if not ui then return end
    ui.status:SetText(state.online and "Архив синхронизирован" or "Нет связи с архивом"); ui.status:SetTextColor(state.online and 0.42 or 0.88,state.online and 0.82 or 0.42,state.online and 0.48 or 0.36)
    ui.stats:SetText(string.format("Знания %d   •   Существа %d   •   Предметы %d   •   Локации %d",state.knowledgeAvailable,state.creatures,state.items,state.zones)); ui.zone:SetText(zoneName())
end

local function switchTab(i)
    currentTab=i; Draw(); if i==1 then requestCatalog(1) elseif i==2 then requestZones() else requestTalentStatus() end
end

local function createUI()
    if ui then return end
    ui=CreateFrame("Frame","ForeverEncyclopediaV21Frame",UIParent,"BasicFrameTemplateWithInset"); ui:SetSize(980,640); ui:SetPoint("CENTER"); ui:SetMovable(true); ui:SetClampedToScreen(true); ui:EnableMouse(true); ui:RegisterForDrag("LeftButton"); ui:SetScript("OnDragStart",ui.StartMoving); ui:SetScript("OnDragStop",ui.StopMovingOrSizing); ui:Hide(); ui.TitleText:SetText("Живая энциклопедия")
    local bg=ui:CreateTexture(nil,"BACKGROUND"); bg:SetPoint("TOPLEFT",ui,"TOPLEFT",10,-34); bg:SetPoint("BOTTOMRIGHT",ui,"BOTTOMRIGHT",-10,10); bg:SetColorTexture(0.036,0.023,0.014,0.99)
    local head=ui:CreateTexture(nil,"BACKGROUND",nil,1); head:SetPoint("TOPLEFT",ui,"TOPLEFT",10,-34); head:SetPoint("TOPRIGHT",ui,"TOPRIGHT",-10,-34); head:SetHeight(48); head:SetColorTexture(0.085,0.050,0.022,0.98)
    ui.status=fs(ui,24,-49,230,"Нет связи","GameFontNormalSmall",0.8,0.4,0.35); ui.stats=fs(ui,280,-49,420,"","GameFontNormalSmall",0.82,0.75,0.63,"CENTER"); ui.zone=fs(ui,720,-49,230,"","GameFontHighlight",0.93,0.85,0.70,"RIGHT")
    local labels={"Существа","Локации","Таланты","Облики"}; for i,label in ipairs(labels) do tabButtons[i]=raised(ui,26+(i-1)*232,-91,216,34,label,function() switchTab(i) end,i==currentTab,true) end
    content=CreateFrame("Frame",nil,ui); content:SetPoint("TOPLEFT",ui,"TOPLEFT",16,-132); content:SetSize(948,486)
    fs(ui,0,-616,950,"Forever Encyclopedia 0.7.1 V2.1","GameFontNormalSmall",0.46,0.40,0.33,"RIGHT")
    ui:SetScript("OnShow",function() requestBaseStatus(); requestTalentStatus(); if currentTab==1 then requestCatalog(state.catalogPage) elseif currentTab==2 then requestZones() end end)
    updateHeader(); Draw()
end

local function createDock()
    if dock then return end
    if _G.ForeverEncyclopediaBookDock then _G.ForeverEncyclopediaBookDock:Hide() end
    if _G.ForeverEncyclopediaV2BookDock then _G.ForeverEncyclopediaV2BookDock:Hide() end
    dock=CreateFrame("Frame","ForeverEncyclopediaV21BookDock",UIParent); dock:SetSize(184,62); dock:SetFrameStrata("MEDIUM")
    if QuickJoinToastButton then dock:SetPoint("RIGHT",QuickJoinToastButton,"LEFT",-8,0) elseif FriendsMicroButton then dock:SetPoint("RIGHT",FriendsMicroButton,"LEFT",-8,0) elseif ChatFrameMenuButton then dock:SetPoint("LEFT",ChatFrameMenuButton,"RIGHT",8,0) else dock:SetPoint("BOTTOMLEFT",UIParent,"BOTTOMLEFT",24,180) end
    local bg=tex(dock,"BACKGROUND",0.04,0.025,0.015,0.95); bg:SetAllPoints(); addBorder(dock,0.36,0.23,0.08,0.95)
    local book=CreateFrame("Button",nil,dock); book:SetPoint("LEFT",dock,"LEFT",6,0); book:SetSize(48,48); local bi=book:CreateTexture(nil,"ARTWORK"); bi:SetPoint("TOPLEFT",book,"TOPLEFT",5,-5); bi:SetPoint("BOTTOMRIGHT",book,"BOTTOMRIGHT",-5,5); bi:SetTexture("Interface\\Icons\\INV_Misc_Book_09"); book:SetScript("OnClick",function() createUI(); if ui:IsShown() then ui:Hide() else ui:Show() end end)
    dock.mana=CreateFrame("StatusBar",nil,dock); dock.mana:SetPoint("TOPLEFT",dock,"TOPLEFT",60,-9); dock.mana:SetSize(116,11); dock.mana:SetStatusBarTexture("Interface\\TargetingFrame\\UI-StatusBar"); dock.mana:SetStatusBarColor(0.12,0.33,0.78); local mb=tex(dock.mana,"BACKGROUND",0.015,0.015,0.025,1); mb:SetAllPoints(); dock.manaText=dock.mana:CreateFontString(nil,"OVERLAY","GameFontNormalSmall"); dock.manaText:SetPoint("CENTER")
    local defs={{1,"Interface\\Icons\\Spell_Holy_PowerWordShield","Охранная печать"},{2,"Interface\\Icons\\Spell_Holy_Heal","Целительная пометка"},{4,"Interface\\Icons\\Spell_Arcane_Arcane01","Тактическая подсказка"}}; dock.abilities={}
    for i,a in ipairs(defs) do local b=CreateFrame("Button",nil,dock); b:SetSize(30,30); b:SetPoint("TOPLEFT",dock,"TOPLEFT",60+(i-1)*38,-27); local bb=tex(b,"BACKGROUND",0.08,0.05,0.025,1); bb:SetAllPoints(); addBorder(b,0.34,0.22,0.08,1); local icon=b:CreateTexture(nil,"ARTWORK"); icon:SetPoint("TOPLEFT",b,"TOPLEFT",3,-3); icon:SetPoint("BOTTOMRIGHT",b,"BOTTOMRIGHT",-3,3); icon:SetTexture(a[2]); b:SetScript("OnEnter",function() GameTooltip:SetOwner(b,"ANCHOR_TOP"); GameTooltip:AddLine(a[3],1,0.82,0.42); GameTooltip:AddLine(abilityUnlocked(a[1]) and "Изучено деревом талантов." or "Не изучено.",0.75,0.75,0.75); GameTooltip:Show() end); b:SetScript("OnLeave",function() GameTooltip:Hide() end); dock.abilities[i]={bit=a[1],icon=icon} end
end

local function updateDock()
    if not dock then return end
    dock.mana:SetMinMaxValues(0,math.max(1,state.maxMana)); dock.mana:SetValue(math.min(state.mana,state.maxMana)); dock.manaText:SetText(state.mana.." / "..state.maxMana); for _,a in ipairs(dock.abilities) do a.icon:SetAlpha(abilityUnlocked(a.bit) and 1 or 0.25) end
end

local function parseBase(msg)
    if msg:sub(1,8)=="CATHEAD|" then local _,zone,page,pages,total,known,zoneTotal,zoneKnown=strsplit("|",msg); state.catalog={}; state.catalogLoaded=false; state.catalogPage=tonumber(page) or 1; state.catalogPages=tonumber(pages) or 1; state.catalogTotal=tonumber(total) or 0; state.catalogKnown=tonumber(known) or 0; state.catalogZoneTotal=tonumber(zoneTotal) or 0; state.catalogZoneKnown=tonumber(zoneKnown) or 0; selectedCreature=1
    elseif msg:sub(1,4)=="CAT|" then local _,entry,known,ctype,class,name=strsplit("|",msg); state.catalog[#state.catalog+1]={entry=tonumber(entry) or 0,known=tonumber(known)==1,creatureType=tonumber(ctype) or 0,classification=tonumber(class) or 0,name=name or ""}
    elseif msg=="CATEND" then state.catalogLoaded=true; state.online=true; selectedCreature=math.min(math.max(1,selectedCreature),math.max(1,#state.catalog)); queueCatalogInfo(); if ui and ui:IsShown() and currentTab==1 then Draw() end
    else
        local tag,a,b,c,d,e,f=strsplit(" ",msg)
        if tag=="STATE" then state.total=tonumber(a) or 0; state.creatures=tonumber(b) or 0; state.items=tonumber(c) or 0; state.zones=tonumber(d) or 0; state.online=true
        elseif tag=="KNOW" then state.knowledgeTotal=tonumber(a) or 0; state.knowledgeSpent=tonumber(b) or 0; state.knowledgeAvailable=tonumber(c) or 0
        elseif tag=="CURRENT" then state.map=tonumber(a) or 0; state.zone=tonumber(b) or 0; state.area=tonumber(c) or 0
        elseif tag=="BOOK" and state.maxMana<=100 then state.mana=tonumber(a) or 0; state.maxMana=tonumber(b) or 100
        elseif tag=="REC" and tonumber(a)==3 then state.recentZones[#state.recentZones+1]={entry=tonumber(b) or 0,map=tonumber(c) or 0,zone=tonumber(d) or 0}
        elseif tag=="RECEND" and tonumber(a)==3 then state.recentZonesLoaded=true; if ui and ui:IsShown() and currentTab==2 then Draw() end
        elseif tag=="END" then state.online=true end
        updateHeader(); updateDock()
    end
end

local function parseTalent(msg)
    if msg:sub(1,7)=="POINTS|" then local _,t,s,a=strsplit("|",msg); state.knowledgeTotal=tonumber(t) or 0; state.knowledgeSpent=tonumber(s) or 0; state.knowledgeAvailable=tonumber(a) or 0; state.ranks={}; talentBatch=true
    elseif msg:sub(1,5)=="RANK|" then local _,k,r=strsplit("|",msg); state.ranks[k]=tonumber(r) or 0
    elseif msg:sub(1,5)=="BOOK|" then local _,mask,mana,maxMana,info=strsplit("|",msg); local oldInfo=state.infoLevel; state.abilityMask=tonumber(mask) or 0; state.mana=tonumber(mana) or 0; state.maxMana=tonumber(maxMana) or 100; state.infoLevel=tonumber(info) or 0; if state.infoLevel>oldInfo then queueCatalogInfo() end
    elseif msg:sub(1,11)=="APPEARANCE|" then local _,k,u,thr=strsplit("|",msg); state.appearances[k]={unlocked=tonumber(u)==1,threshold=tonumber(thr) or 0}
    elseif msg:sub(1,9)=="SELECTED|" then local _,k=strsplit("|",msg); state.selectedAppearance=k or "living_book"
    elseif msg:sub(1,9)=="CREATURE|" then local _,entry,level=strsplit("|",msg); pendingCreatureInfo=tonumber(entry) or pendingCreatureInfo; if pendingCreatureInfo then state.creatureInfo[pendingCreatureInfo]=state.creatureInfo[pendingCreatureInfo] or {}; state.creatureInfo[pendingCreatureInfo].level=tonumber(level) or 0 end
    elseif msg:sub(1,6)=="CBASE|" then local _,name,ctype,class,minL,maxL=strsplit("|",msg); if pendingCreatureInfo then local ci=state.creatureInfo[pendingCreatureInfo] or {}; ci.name=name or ""; ci.creatureType=tonumber(ctype) or 0; ci.classification=tonumber(class) or 0; ci.minLevel=tonumber(minL) or 0; ci.maxLevel=tonumber(maxL) or 0; state.creatureInfo[pendingCreatureInfo]=ci end
    elseif msg=="CEND" then pendingCreatureInfo=nil; if #infoQueue>0 then requestCreatureInfo(table.remove(infoQueue,1)) elseif ui and ui:IsShown() and currentTab==1 then Draw() end
    elseif msg:sub(1,7)=="BOUGHT|" then requestTalentStatus()
    elseif msg:sub(1,6)=="ERROR|" then local _,err=strsplit("|",msg); if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cffff8040[Энциклопедия]|r "..(err or "Ошибка")) end
    elseif msg=="END" then talentBatch=false; state.online=true; updateHeader(); updateDock(); if ui and ui:IsShown() then Draw() end; return end
    if not talentBatch then updateHeader(); updateDock() end
end

SLASH_FOREVERENCYCLOPEDIAV21_1="/ency"; SLASH_FOREVERENCYCLOPEDIAV21_2="/encyclopedia"
SlashCmdList["FOREVERENCYCLOPEDIAV21"]=function() createUI(); if ui:IsShown() then ui:Hide() else ui:Show() end end

local events=CreateFrame("Frame"); events:RegisterEvent("ADDON_LOADED"); events:RegisterEvent("PLAYER_LOGIN"); events:RegisterEvent("PLAYER_ENTERING_WORLD"); events:RegisterEvent("ZONE_CHANGED_NEW_AREA"); events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent",function(_,event,...)
    if event=="ADDON_LOADED" then local name=...; if name~=ADDON then return end; registerPrefixes(); return end
    if event=="CHAT_MSG_ADDON" then local p,m=...; if p==BASE_RES then parseBase(tostring(m or "")) elseif p==TAL_RES then parseTalent(tostring(m or "")) end; return end
    if event=="PLAYER_LOGIN" then createDock() end
    if event=="ZONE_CHANGED_NEW_AREA" then state.catalog={}; state.catalogLoaded=false; state.catalogPage=1; selectedCreature=1 end
    C_Timer.After(1.0,function() requestBaseStatus(); requestTalentStatus(); if ui and ui:IsShown() then if currentTab==1 then requestCatalog(1) elseif currentTab==2 then requestZones() end end end)
end)
