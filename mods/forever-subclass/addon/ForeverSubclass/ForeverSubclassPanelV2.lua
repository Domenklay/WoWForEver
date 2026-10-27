-- Self-contained talent-style subclass panel for WoW Forever 1.60.x.
-- Parses FSR1 directly and sends all actions through ForeverSubclassDirectSend.
-- The server remains authoritative; this file only renders and requests state.

local RESPONSE = "FSR1"
local classOrder = {1,2,3,4,5,7,8,9,11}
local classInfo = {
    [1]={name="Воин",token="WARRIOR"}, [2]={name="Паладин",token="PALADIN"},
    [3]={name="Охотник",token="HUNTER"}, [4]={name="Разбойник",token="ROGUE"},
    [5]={name="Жрец",token="PRIEST"}, [7]={name="Шаман",token="SHAMAN"},
    [8]={name="Маг",token="MAGE"}, [9]={name="Чернокнижник",token="WARLOCK"},
    [11]={name="Друид",token="DRUID"},
}
local powerNames = {[0]="Мана",[1]="Ярость",[3]="Энергия"}
local errors = {
    ["module disabled or unsupported primary class"]="Модуль подклассов выключен или основной класс не поддерживается.",
    ["primary class has not reached subclass unlock level"]="Подкласс открывается с 10-го уровня.",
    ["subclass can only be switched in a rest area"]="Менять подкласс можно только в городе или таверне.",
    ["cannot edit in combat or while casting"]="Нельзя менять подкласс в бою, после смерти или во время заклинания.",
    ["class has not been learned"]="Сначала изучите этот путь.",
    ["spell unavailable or not enough power"]="Способность недоступна или не хватает ресурса.",
    ["subclass level is too low for this spell"]="Уровень подкласса недостаточен для этой способности.",
    ["not enough subclass ability slots"]="Не хватает свободных слотов способностей.",
    ["no active subclass"]="Сначала активируйте подкласс.",
    ["selection unchanged"]="Изменений нет.",
}

local root, left, right, header
local cards, spellNodes = {}, {}
local selectedClass
local state, pending
local titleText, detailText, statusText, noticeText, xpText, resourceBar
local learnButton, activeButton, xpButton, clearButton
local spellGrid, emptySpells
local serverSeen = false
local lastRequest = 0
local built = false

local function send(payload)
    if _G.ForeverSubclassDirectSend then
        lastRequest = GetTime and GetTime() or 0
        return _G.ForeverSubclassDirectSend(payload, true)
    end
    if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cffff5555[Подклассы]|r Транспорт FSC1 ещё не загружен.") end
    return false
end

local function className(id)
    return classInfo[id] and classInfo[id].name or ("Класс "..tostring(id or 0))
end

local function spellName(id)
    if C_Spell and C_Spell.GetSpellName then return C_Spell.GetSpellName(id) or ("Заклинание "..id) end
    if GetSpellInfo then return GetSpellInfo(id) or ("Заклинание "..id) end
    return "Заклинание "..id
end

local function spellTexture(id)
    if C_Spell and C_Spell.GetSpellTexture then return C_Spell.GetSpellTexture(id) end
    if GetSpellTexture then return GetSpellTexture(id) end
    return 134400
end

local function makeBackdrop(parent, alpha)
    local template = BackdropTemplateMixin and "BackdropTemplate" or nil
    local f = CreateFrame("Frame", nil, parent, template)
    if f.SetBackdrop then
        f:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=true,tileSize=16,edgeSize=12,insets={left=3,right=3,top=3,bottom=3}})
        f:SetBackdropColor(0.018,0.018,0.018,alpha or 0.95)
        f:SetBackdropBorderColor(0.43,0.32,0.14,0.95)
    end
    return f
end

local function label(parent, font, text)
    local f = parent:CreateFontString(nil,"OVERLAY",font or "GameFontHighlight")
    f:SetText(text or "")
    return f
end

local function setClassIcon(texture, token)
    texture:SetTexture("Interface\\GLUES\\CHARACTERCREATE\\UI-CHARACTERCREATE-CLASSES")
    local c = CLASS_ICON_TCOORDS and CLASS_ICON_TCOORDS[token]
    if c then texture:SetTexCoord(c[1],c[2],c[3],c[4]) else texture:SetTexture(134400);texture:SetTexCoord(0,1,0,1) end
end

local function makeGoldButton(parent, text, width)
    local template = BackdropTemplateMixin and "BackdropTemplate" or nil
    local b = CreateFrame("Button",nil,parent,template)
    b:SetSize(width or 130,31)
    if b.SetBackdrop then
        b:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=true,tileSize=16,edgeSize=9,insets={left=3,right=3,top=3,bottom=3}})
    end
    b.label=label(b,"GameFontNormal",text);b.label:SetPoint("CENTER")
    b:SetScript("OnEnter",function(self) if self._enabled~=false and self.SetBackdropBorderColor then self:SetBackdropBorderColor(1,0.78,0.20,1) end end)
    b:SetScript("OnLeave",function(self)
        if not self.SetBackdropBorderColor then return end
        if self._enabled==false then self:SetBackdropBorderColor(0.18,0.18,0.18,0.9) else self:SetBackdropBorderColor(0.52,0.39,0.14,1) end
    end)
    return b
end

local function enableButton(b, enabled)
    b._enabled = enabled and true or false
    b:EnableMouse(enabled and true or false)
    if b.label then
        if enabled then b.label:SetTextColor(1,0.82,0.24,1) else b.label:SetTextColor(0.42,0.42,0.42,1) end
    end
    if b.SetBackdrop then
        if enabled then b:SetBackdropColor(0.075,0.057,0.025,0.98);b:SetBackdropBorderColor(0.52,0.39,0.14,1)
        else b:SetBackdropColor(0.025,0.025,0.025,0.92);b:SetBackdropBorderColor(0.18,0.18,0.18,0.9) end
    end
end

local function createCard(id,index)
    local info=classInfo[id]
    local template=BackdropTemplateMixin and "BackdropTemplate" or nil
    local b=CreateFrame("Button",nil,left,template)
    b:SetSize(137,72)
    local col=(index-1)%3;local row=math.floor((index-1)/3)
    b:SetPoint("TOPLEFT",12+col*143,-70-row*78)
    if b.SetBackdrop then
        b:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=true,tileSize=16,edgeSize=10,insets={left=3,right=3,top=3,bottom=3}})
        b:SetBackdropColor(0.035,0.035,0.035,0.96);b:SetBackdropBorderColor(0.28,0.24,0.16,0.95)
    end
    local iconBorder=b:CreateTexture(nil,"BORDER");iconBorder:SetTexture("Interface\\Buttons\\UI-Quickslot2");iconBorder:SetSize(49,49);iconBorder:SetPoint("LEFT",7,0)
    local icon=b:CreateTexture(nil,"ARTWORK");icon:SetSize(40,40);icon:SetPoint("CENTER",iconBorder);setClassIcon(icon,info.token)
    local name=label(b,"GameFontNormal",info.name);name:SetPoint("TOPLEFT",58,-15);name:SetPoint("RIGHT",-5,0);name:SetJustifyH("LEFT")
    local sub=label(b,"GameFontHighlightSmall","Не изучен");sub:SetPoint("TOPLEFT",name,"BOTTOMLEFT",0,-5);sub:SetPoint("RIGHT",-5,0);sub:SetJustifyH("LEFT")
    local glow=b:CreateTexture(nil,"OVERLAY");glow:SetTexture("Interface\\Buttons\\UI-ActionButton-Border");glow:SetBlendMode("ADD");glow:SetAllPoints(iconBorder);glow:Hide()
    b:SetScript("OnClick",function() selectedClass=id; if root and root.Refresh then root:Refresh() end end)
    b:SetScript("OnEnter",function(self) if self.SetBackdropBorderColor then self:SetBackdropBorderColor(0.82,0.64,0.23,1) end end)
    b:SetScript("OnLeave",function(self)
        if not self.SetBackdropBorderColor then return end
        if self._selected then self:SetBackdropBorderColor(0.96,0.73,0.18,1)
        elseif self._active then self:SetBackdropBorderColor(0.20,0.72,0.34,1)
        elseif self._primary then self:SetBackdropBorderColor(0.46,0.55,0.72,1)
        else self:SetBackdropBorderColor(0.28,0.24,0.16,0.95) end
    end)
    cards[id]={frame=b,status=sub,glow=glow}
end

local function clearSpellNodes()
    for _,node in ipairs(spellNodes) do node:Hide() end
end

local function getVisibleSpells(s)
    local out,best={},{}
    if not s or not s.active or s.active==0 or not s.classes[s.active] then return out end
    local level=s.classes[s.active].level or 1
    for _,sp in pairs(s.spells or {}) do
        if sp.level<=level and (not best[sp.root] or best[sp.root].level<sp.level) then best[sp.root]=sp end
    end
    for _,sp in pairs(s.spells or {}) do
        if (best[sp.root] and best[sp.root].id==sp.id) or sp.selected then table.insert(out,sp) end
    end
    table.sort(out,function(a,b) if a.level==b.level then return a.id<b.id end return a.level<b.level end)
    return out
end

local function makeSpellNode(index)
    local template=BackdropTemplateMixin and "BackdropTemplate" or nil
    local n=CreateFrame("Button",nil,spellGrid,template)
    n:SetSize(154,112)
    local col=(index-1)%4;local row=math.floor((index-1)/4)
    n:SetPoint("TOPLEFT",8+col*160,-8-row*118)
    if n.SetBackdrop then
        n:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=true,tileSize=16,edgeSize=10,insets={left=3,right=3,top=3,bottom=3}})
    end
    local iconBorder=n:CreateTexture(nil,"BORDER");iconBorder:SetTexture("Interface\\Buttons\\UI-Quickslot2");iconBorder:SetSize(51,51);iconBorder:SetPoint("TOP",0,-8)
    n.icon=n:CreateTexture(nil,"ARTWORK");n.icon:SetSize(42,42);n.icon:SetPoint("CENTER",iconBorder)
    n.name=label(n,"GameFontNormalSmall","");n.name:SetPoint("TOPLEFT",5,-62);n.name:SetPoint("RIGHT",-5,0);n.name:SetJustifyH("CENTER");n.name:SetWordWrap(false)
    n.meta=label(n,"GameFontHighlightSmall","");n.meta:SetPoint("TOPLEFT",5,-81);n.meta:SetPoint("RIGHT",-5,0);n.meta:SetJustifyH("CENTER")
    n.check=n:CreateTexture(nil,"OVERLAY");n.check:SetTexture("Interface\\Buttons\\UI-CheckBox-Check");n.check:SetSize(28,28);n.check:SetPoint("TOPRIGHT",-2,-2);n.check:Hide()
    n:SetScript("OnClick",function(self)
        if not self.spell then return end
        send((self.spell.selected and "remove " or "select ")..self.spell.id)
    end)
    n:SetScript("OnEnter",function(self)
        if self.spell and GameTooltip then
            GameTooltip:SetOwner(self,"ANCHOR_RIGHT");GameTooltip:SetSpellByID(self.spell.id)
            GameTooltip:AddLine(" ")
            GameTooltip:AddLine(self.spell.selected and "Нажмите, чтобы убрать из подкласса" or "Нажмите, чтобы выбрать способность",1,0.82,0.2,true)
            GameTooltip:Show()
        end
    end)
    n:SetScript("OnLeave",function() if GameTooltip then GameTooltip:Hide() end end)
    spellNodes[index]=n
    return n
end

local function refresh()
    if not root or not root:IsShown() then return end
    if not state then
        titleText:SetText("Подкласс")
        detailText:SetText("Получаем состояние персонажа…")
        statusText:SetText(serverSeen and "|cff45d66bСервер подключен|r" or "|cffffc31aСоединение с сервером…|r")
        clearSpellNodes();emptySpells:Show();emptySpells:SetText("Ожидание данных от сервера…")
        return
    end
    serverSeen=true
    if not selectedClass or selectedClass==state.primary then
        selectedClass=(state.active and state.active~=0 and state.active) or (state.primary~=5 and 5 or 8)
    end
    local primary=className(state.primary);local active=(state.active and state.active~=0) and className(state.active) or "не выбран"
    titleText:SetText(primary.."  |cff9b9b9b→|r  "..active)
    detailText:SetText(string.format("Основной класс %d ур.   •   Подкласс %s   •   Эффективность %.1f%%   •   Слоты %d/%d",
        state.classes[state.primary] and state.classes[state.primary].level or (UnitLevel and UnitLevel("player") or 0), active,
        (state.efficiency or 0)/100, state.used or 0, state.budget or 8))
    statusText:SetText("|cff45d66bСервер подключен|r")

    local target=state.classes[state.xpTarget]
    if target then xpText:SetText("Опыт → "..className(state.xpTarget).."   ур. "..target.level.."   "..target.xp.." / "..target.next)
    else xpText:SetText("") end

    for _,id in ipairs(classOrder) do
        local c=cards[id];local p=state.classes[id]
        local primaryFlag=id==state.primary;local activeFlag=id==state.active;local xpFlag=id==state.xpTarget;local selected=id==selectedClass
        local text
        if primaryFlag then text="Основной · ур. "..(p and p.level or UnitLevel("player"))
        elseif activeFlag then text="Активный · ур. "..(p and p.level or 1)
        elseif p then text="Изучен · ур. "..p.level
        else text="Не изучен" end
        if xpFlag and not primaryFlag then text=text.." · XP" end
        c.status:SetText(text);c.frame._selected=selected;c.frame._active=activeFlag;c.frame._primary=primaryFlag
        if selected then c.frame:SetBackdropBorderColor(0.96,0.73,0.18,1);c.glow:Show()
        elseif activeFlag then c.frame:SetBackdropBorderColor(0.20,0.72,0.34,1);c.glow:Hide()
        elseif primaryFlag then c.frame:SetBackdropBorderColor(0.46,0.55,0.72,1);c.glow:Hide()
        else c.frame:SetBackdropBorderColor(0.28,0.24,0.16,0.95);c.glow:Hide() end
    end

    local learned=state.classes[selectedClass]~=nil;local isPrimary=selectedClass==state.primary;local playerLevel=UnitLevel and UnitLevel("player") or 80
    enableButton(learnButton,playerLevel>=10 and not isPrimary and not learned)
    enableButton(activeButton,not isPrimary and learned and selectedClass~=state.active)
    enableButton(xpButton,learned and selectedClass~=state.xpTarget)
    enableButton(clearButton,state.active and state.active~=0)

    if state.power and state.active and state.active~=0 then
        resourceBar:SetMinMaxValues(0,math.max(1,state.power.max));resourceBar:SetValue(state.power.current)
        if state.power.kind==1 then resourceBar:SetStatusBarColor(0.72,0.10,0.10)
        elseif state.power.kind==3 then resourceBar:SetStatusBarColor(0.82,0.68,0.10)
        else resourceBar:SetStatusBarColor(0.10,0.34,0.85) end
        resourceBar.text:SetText((powerNames[state.power.kind] or "Ресурс").."   "..state.power.current.." / "..state.power.max)
        resourceBar:Show()
    else resourceBar:Hide() end

    clearSpellNodes()
    local visible=getVisibleSpells(state)
    if #visible==0 then
        emptySpells:Show()
        if not state.active or state.active==0 then emptySpells:SetText("Сначала изучите и активируйте второй класс.")
        else emptySpells:SetText("Для текущего уровня подкласса пока нет доступных способностей.") end
    else
        emptySpells:Hide()
        for i,sp in ipairs(visible) do
            local n=spellNodes[i] or makeSpellNode(i);n.spell=sp;n.icon:SetTexture(spellTexture(sp.id));n.name:SetText(spellName(sp.id))
            n.meta:SetText("ур. "..sp.level.."  •  "..(powerNames[sp.power] or "ресурс").." "..sp.cost)
            n.check:SetShown(sp.selected)
            if n.SetBackdrop then
                if sp.selected then n:SetBackdropColor(0.035,0.095,0.040,0.96);n:SetBackdropBorderColor(0.20,0.82,0.36,1)
                else n:SetBackdropColor(0.028,0.028,0.028,0.96);n:SetBackdropBorderColor(0.34,0.28,0.17,0.95) end
            end
            n:Show()
        end
    end

    noticeText:SetText("Выберите путь слева. Способности справа нажимаются как узлы талантов; зелёная рамка означает выбранный слот.")
end

local function build()
    local parent=_G.ForeverSubclassTalentPanel
    if not parent or built then return false end
    built=true
    local template=BackdropTemplateMixin and "BackdropTemplate" or nil
    root=CreateFrame("Frame","ForeverSubclassPanelV2",parent,template)
    root:SetAllPoints(parent);root:SetFrameLevel(parent:GetFrameLevel()+120);root:EnableMouse(true)
    if root.SetBackdrop then
        root:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=true,tileSize=16,edgeSize=12,insets={left=3,right=3,top=3,bottom=3}})
        root:SetBackdropColor(0.012,0.012,0.012,0.985);root:SetBackdropBorderColor(0.47,0.34,0.12,1)
    end
    root.Refresh=refresh

    header=makeBackdrop(root,0.93);header:SetPoint("TOPLEFT",10,-10);header:SetPoint("TOPRIGHT",-10,-10);header:SetHeight(76);header:SetFrameLevel(root:GetFrameLevel()+1)
    titleText=label(header,"GameFontNormalLarge","Подкласс");titleText:SetPoint("TOPLEFT",14,-11)
    detailText=label(header,"GameFontHighlightSmall","Получаем состояние персонажа…");detailText:SetPoint("TOPLEFT",titleText,"BOTTOMLEFT",0,-7);detailText:SetWidth(750);detailText:SetJustifyH("LEFT")
    statusText=label(header,"GameFontHighlightSmall","|cffffc31aСоединение с сервером…|r");statusText:SetPoint("TOPRIGHT",-14,-14)
    xpText=label(header,"GameFontHighlightSmall","");xpText:SetPoint("BOTTOMRIGHT",-14,12)

    left=makeBackdrop(root,0.94);left:SetPoint("TOPLEFT",10,-94);left:SetPoint("BOTTOMLEFT",10,44);left:SetWidth(452);left:SetFrameLevel(root:GetFrameLevel()+1)
    local lt=label(left,"GameFontNormalLarge","Второй путь");lt:SetPoint("TOPLEFT",12,-12)
    local lh=label(left,"GameFontHighlightSmall","Класс качается отдельно, но основной класс и броня сохраняются.");lh:SetPoint("TOPLEFT",lt,"BOTTOMLEFT",0,-4);lh:SetWidth(420);lh:SetJustifyH("LEFT")
    for i,id in ipairs(classOrder) do createCard(id,i) end

    learnButton=makeGoldButton(left,"Изучить путь",128);learnButton:SetPoint("BOTTOMLEFT",12,13);learnButton:SetScript("OnClick",function() if learnButton._enabled~=false then send("learn "..selectedClass) end end)
    activeButton=makeGoldButton(left,"Сделать активным",136);activeButton:SetPoint("LEFT",learnButton,"RIGHT",7,0);activeButton:SetScript("OnClick",function() if activeButton._enabled~=false then send("active "..selectedClass) end end)
    xpButton=makeGoldButton(left,"Направить XP",128);xpButton:SetPoint("LEFT",activeButton,"RIGHT",7,0);xpButton:SetScript("OnClick",function() if xpButton._enabled~=false then send("xp "..selectedClass) end end)

    clearButton=CreateFrame("Button",nil,left);clearButton:SetSize(130,20);clearButton:SetPoint("BOTTOMLEFT",12,49)
    clearButton.label=label(clearButton,"GameFontHighlightSmall","Отключить подкласс");clearButton.label:SetPoint("LEFT")
    clearButton:SetScript("OnClick",function() if clearButton._enabled~=false then send("clear") end end)
    clearButton:SetScript("OnEnter",function() if clearButton._enabled~=false then clearButton.label:SetTextColor(1,0.72,0.22,1) end end)
    clearButton:SetScript("OnLeave",function() clearButton.label:SetTextColor(clearButton._enabled==false and 0.42 or 1,clearButton._enabled==false and 0.42 or 1,clearButton._enabled==false and 0.42 or 1,1) end)

    right=makeBackdrop(root,0.94);right:SetPoint("TOPLEFT",472,-94);right:SetPoint("BOTTOMRIGHT",-10,44);right:SetFrameLevel(root:GetFrameLevel()+1)
    local rt=label(right,"GameFontNormalLarge","Способности подкласса");rt:SetPoint("TOPLEFT",14,-12)
    local rh=label(right,"GameFontHighlightSmall","До 8 выбранных способностей. Нажмите на узел, чтобы добавить или убрать способность.");rh:SetPoint("TOPLEFT",rt,"BOTTOMLEFT",0,-4);rh:SetWidth(670);rh:SetJustifyH("LEFT")
    resourceBar=CreateFrame("StatusBar",nil,right);resourceBar:SetPoint("TOPRIGHT",-14,-13);resourceBar:SetSize(205,18);resourceBar:SetStatusBarTexture("Interface\\TARGETINGFRAME\\UI-StatusBar");resourceBar.text=label(resourceBar,"GameFontHighlightSmall","");resourceBar.text:SetPoint("CENTER");resourceBar:Hide()
    spellGrid=CreateFrame("Frame",nil,right);spellGrid:SetPoint("TOPLEFT",10,-57);spellGrid:SetPoint("BOTTOMRIGHT",-10,10)
    emptySpells=label(spellGrid,"GameFontHighlight","Сначала активируйте подкласс.");emptySpells:SetPoint("CENTER",0,25);emptySpells:SetWidth(520);emptySpells:SetJustifyH("CENTER")

    noticeText=label(root,"GameFontHighlightSmall","Подкласс доступен с 10-го уровня.");noticeText:SetPoint("BOTTOMLEFT",16,16);noticeText:SetPoint("RIGHT",-16,0);noticeText:SetJustifyH("LEFT")

    parent:HookScript("OnShow",function() root:Show();send("status");refresh() end)
    parent:HookScript("OnHide",function() root:Hide() end)
    if parent:IsShown() then root:Show();send("status");refresh() else root:Hide() end
    return true
end

local events=CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN");events:RegisterEvent("ADDON_LOADED");events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent",function(_,event,...)
    if event~="CHAT_MSG_ADDON" then
        if C_Timer and C_Timer.After then C_Timer.After(0,build);C_Timer.After(0.3,build);C_Timer.After(1,build) else build() end
        return
    end
    local prefix,text=...
    if prefix~=RESPONSE then return end
    serverSeen=true
    local words={};for w in tostring(text):gmatch("%S+") do table.insert(words,w) end
    local kind=words[1]
    if kind=="ERROR" then
        local raw=tostring(text):sub(7);noticeText:SetText(errors[raw] or raw);if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cffff5555[Подклассы]|r "..(errors[raw] or raw)) end
        return
    elseif kind=="STATE" then
        pending={primary=tonumber(words[2]),active=tonumber(words[3]),xpTarget=tonumber(words[4]),used=tonumber(words[5]) or 0,budget=tonumber(words[6]) or 8,efficiency=tonumber(words[7]) or 0,classes={},spells={}}
    elseif pending and kind=="CLASS" then pending.classes[tonumber(words[2])]={level=tonumber(words[3]) or 1,xp=tonumber(words[4]) or 0,next=tonumber(words[5]) or 0}
    elseif pending and kind=="POWER" then pending.power={kind=tonumber(words[2]),current=tonumber(words[3]) or 0,max=tonumber(words[4]) or 1}
    elseif pending and kind=="SPELL" then
        local id=tonumber(words[2]);pending.spells[id]={id=id,root=tonumber(words[3]),level=tonumber(words[4]) or 1,selected=words[5]=="1",cost=tonumber(words[6]) or 0,power=tonumber(words[7])}
    elseif pending and kind=="END" then state=pending;pending=nil;refresh() end
end)

events:SetScript("OnUpdate",function(self,elapsed)
    self._elapsed=(self._elapsed or 0)+elapsed
    if self._elapsed<0.5 then return end
    self._elapsed=0
    if not built then build();return end
    if root and root:IsShown() and not state and GetTime and GetTime()-lastRequest>2.0 then send("status") end
end)
