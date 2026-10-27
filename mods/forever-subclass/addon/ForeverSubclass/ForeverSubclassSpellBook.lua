-- Active subclass page for WoW Forever 1.60.x PlayerSpells spellbook.
-- This is deliberately an addon-owned page: subclass spells are server-authoritative
-- and are not falsely inserted into C_SpellBook as native learned spells.

local RESPONSE = "FSR1"
local classInfo = {
    [1]={name="Воин",token="WARRIOR"}, [2]={name="Паладин",token="PALADIN"},
    [3]={name="Охотник",token="HUNTER"}, [4]={name="Разбойник",token="ROGUE"},
    [5]={name="Жрец",token="PRIEST"}, [7]={name="Шаман",token="SHAMAN"},
    [8]={name="Маг",token="MAGE"}, [9]={name="Чернокнижник",token="WARLOCK"},
    [11]={name="Друид",token="DRUID"},
}

local state, pending
local spellBook, tab, panel, title, subtitle, emptyText
local rows = {}
local hookedNativeSetTab = false
local built = false
local customOpen = false

local function debug(text)
    if _G.ForeverSubclassDebugAdd then _G.ForeverSubclassDebugAdd("SPELLBOOK "..tostring(text)) end
end

local function send(payload)
    if _G.ForeverSubclassDirectSend then
        debug("TX "..payload)
        return _G.ForeverSubclassDirectSend(payload, true)
    end
    return false
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

local function setClassIcon(texture, token)
    texture:SetTexture("Interface\\GLUES\\CHARACTERCREATE\\UI-CHARACTERCREATE-CLASSES")
    local c = CLASS_ICON_TCOORDS and CLASS_ICON_TCOORDS[token]
    if c then texture:SetTexCoord(c[1],c[2],c[3],c[4])
    else texture:SetTexture(134400); texture:SetTexCoord(0,1,0,1) end
end

local function selectedSpells()
    local out = {}
    if not state or not state.active or state.active == 0 then return out end
    for _, sp in pairs(state.spells or {}) do
        if sp.selected then table.insert(out, sp) end
    end
    table.sort(out, function(a,b)
        if (a.level or 0) == (b.level or 0) then return a.id < b.id end
        return (a.level or 0) < (b.level or 0)
    end)
    return out
end

local function hideCustomPage()
    customOpen = false
    if panel then panel:Hide() end
    if spellBook and spellBook.PagedSpellsFrame then spellBook.PagedSpellsFrame:Show() end
    if tab and tab.glow then tab.glow:Hide() end
end

local function showCustomPage()
    if not state or not state.active or state.active == 0 then return end
    customOpen = true
    if spellBook and spellBook.PagedSpellsFrame then spellBook.PagedSpellsFrame:Hide() end
    if panel then panel:Show() end
    if tab and tab.glow then tab.glow:Show() end
    if panel and panel.Refresh then panel:Refresh() end
    send("status")
end

local function ensureRow(index)
    if rows[index] then return rows[index] end
    local b = CreateFrame("Button", nil, panel)
    b:SetSize(330, 74)
    local col = (index - 1) % 2
    local row = math.floor((index - 1) / 2)
    b:SetPoint("TOPLEFT", 125 + col * 360, -150 - row * 92)
    b:RegisterForClicks("LeftButtonUp")

    local iconBorder = b:CreateTexture(nil, "BORDER")
    iconBorder:SetTexture("Interface\\Buttons\\UI-Quickslot2")
    iconBorder:SetSize(58,58)
    iconBorder:SetPoint("LEFT", 0, 0)
    b.icon = b:CreateTexture(nil, "ARTWORK")
    b.icon:SetSize(48,48)
    b.icon:SetPoint("CENTER", iconBorder)

    b.name = b:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
    b.name:SetPoint("TOPLEFT", 70, -12)
    b.name:SetPoint("RIGHT", -5, 0)
    b.name:SetJustifyH("LEFT")

    b.meta = b:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    b.meta:SetPoint("TOPLEFT", b.name, "BOTTOMLEFT", 0, -6)
    b.meta:SetPoint("RIGHT", -5, 0)
    b.meta:SetJustifyH("LEFT")

    b:SetHighlightTexture("Interface\\Buttons\\ButtonHilight-Square", "ADD")
    b:SetScript("OnEnter", function(self)
        if self.spell and GameTooltip then
            GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
            GameTooltip:SetSpellByID(self.spell.id)
            GameTooltip:AddLine(" ")
            GameTooltip:AddLine("ЛКМ: применить способность подкласса", 0.95,0.78,0.20, true)
            GameTooltip:Show()
        end
    end)
    b:SetScript("OnLeave", function() if GameTooltip then GameTooltip:Hide() end end)
    b:SetScript("OnClick", function(self)
        if self.spell then send("cast "..self.spell.id) end
    end)
    rows[index] = b
    return b
end

local function refresh()
    if not built then return end
    local active = state and state.active and state.active ~= 0 and state.active or nil
    local info = active and classInfo[active] or nil

    tab:SetShown(info ~= nil)
    if not info then
        hideCustomPage()
        return
    end

    setClassIcon(tab.icon, info.token)
    tab.tooltipTitle = info.name.." — подкласс"
    local level = state.classes and state.classes[active] and state.classes[active].level or 1
    title:SetText(info.name.." — подкласс")
    subtitle:SetText("Уровень "..level..". Здесь показаны способности, выбранные в Таланты → Подкласс.")

    local list = selectedSpells()
    for i, sp in ipairs(list) do
        local b = ensureRow(i)
        b.spell = sp
        b.icon:SetTexture(spellTexture(sp.id))
        b.name:SetText(spellName(sp.id))
        b.meta:SetText("ур. "..tostring(sp.level or 1).."   |   ЛКМ — применить")
        b:Show()
    end
    for i = #list + 1, #rows do rows[i]:Hide(); rows[i].spell=nil end

    if #list == 0 then
        emptyText:SetText("Выбранных способностей нет.\nОткройте Таланты → Подкласс и выберите способности.")
        emptyText:Show()
    else emptyText:Hide() end
end

local function build()
    spellBook = _G.PlayerSpellsFrame and _G.PlayerSpellsFrame.SpellBookFrame
    if not spellBook or not spellBook.CategoryTabSystem then return false end
    if built then return true end

    tab = CreateFrame("Button", "ForeverSubclassSpellBookTab", spellBook)
    tab:SetSize(44,44)
    tab:SetPoint("LEFT", spellBook.CategoryTabSystem, "RIGHT", 8, 0)
    tab:RegisterForClicks("LeftButtonUp")
    local border = tab:CreateTexture(nil,"BORDER")
    border:SetTexture("Interface\\Buttons\\UI-Quickslot2")
    border:SetAllPoints()
    tab.icon = tab:CreateTexture(nil,"ARTWORK")
    tab.icon:SetSize(35,35)
    tab.icon:SetPoint("CENTER")
    tab.glow = tab:CreateTexture(nil,"OVERLAY")
    tab.glow:SetTexture("Interface\\Buttons\\UI-ActionButton-Border")
    tab.glow:SetBlendMode("ADD")
    tab.glow:SetAllPoints()
    tab.glow:Hide()
    tab:SetScript("OnClick", showCustomPage)
    tab:SetScript("OnEnter", function(self)
        if GameTooltip then
            GameTooltip:SetOwner(self,"ANCHOR_BOTTOM")
            GameTooltip:SetText(self.tooltipTitle or "Подкласс")
            GameTooltip:AddLine("Открыть способности активного подкласса",1,1,1,true)
            GameTooltip:Show()
        end
    end)
    tab:SetScript("OnLeave", function() if GameTooltip then GameTooltip:Hide() end end)
    tab:Hide()

    panel = CreateFrame("Frame", "ForeverSubclassSpellBookPanel", spellBook)
    panel:SetPoint("TOPLEFT", spellBook, "TOPLEFT", 0, -52)
    panel:SetPoint("BOTTOMRIGHT", spellBook, "BOTTOMRIGHT", 0, 0)
    panel:EnableMouse(false)
    panel:SetFrameLevel(spellBook.PagedSpellsFrame:GetFrameLevel() + 1)

    title = panel:CreateFontString(nil,"OVERLAY","GameFontNormalHuge")
    title:SetPoint("TOPLEFT", 94, -55)
    title:SetText("Подкласс")
    subtitle = panel:CreateFontString(nil,"OVERLAY","GameFontHighlight")
    subtitle:SetPoint("TOPLEFT", title, "BOTTOMLEFT", 0, -10)
    subtitle:SetWidth(650)
    subtitle:SetJustifyH("LEFT")

    local line = panel:CreateTexture(nil,"ARTWORK")
    line:SetColorTexture(0.40,0.22,0.08,0.55)
    line:SetPoint("TOPLEFT", 80, -118)
    line:SetSize(680,2)

    emptyText = panel:CreateFontString(nil,"OVERLAY","GameFontHighlightLarge")
    emptyText:SetPoint("CENTER", -180, 20)
    emptyText:SetWidth(620)
    emptyText:SetJustifyH("CENTER")

    local hint = panel:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
    hint:SetPoint("BOTTOMLEFT", 94, 48)
    hint:SetText("Способности здесь серверные. ЛКМ применяет выбранную способность; состав меняется во вкладке Подкласс в талантах.")

    panel.Refresh = refresh
    panel:Hide()

    if not hookedNativeSetTab and hooksecurefunc then
        hookedNativeSetTab = true
        hooksecurefunc(spellBook, "SetTab", function()
            if customOpen then hideCustomPage() end
        end)
    end
    if spellBook.HookScript then
        spellBook:HookScript("OnShow", function() send("status"); refresh() end)
        spellBook:HookScript("OnHide", hideCustomPage)
    end

    built = true
    refresh()
    debug("integration built")
    return true
end

local function parse(text)
    local kind = text:match("^(%S+)")
    if kind == "STATE" then
        local p,a,x,u,b,e = text:match("^STATE%s+(%d+)%s+(%d+)%s+(%d+)%s+(%d+)%s+(%d+)%s+(%d+)")
        if not p then return end
        pending={primary=tonumber(p),active=tonumber(a),xpTarget=tonumber(x),used=tonumber(u),budget=tonumber(b),efficiency=tonumber(e),classes={},spells={}}
    elseif kind == "CLASS" and pending then
        local id,lvl,xp,nextxp=text:match("^CLASS%s+(%d+)%s+(%d+)%s+(%d+)%s+(%d+)")
        if id then pending.classes[tonumber(id)]={level=tonumber(lvl),xp=tonumber(xp),next=tonumber(nextxp)} end
    elseif kind == "SPELL" and pending then
        local id,root,lvl,sel,cost,power=text:match("^SPELL%s+(%d+)%s+(%d+)%s+(%d+)%s+(%d+)%s+(%d+)%s+(%-?%d+)")
        if id then pending.spells[tonumber(id)]={id=tonumber(id),root=tonumber(root),level=tonumber(lvl),selected=tonumber(sel)==1,cost=tonumber(cost),power=tonumber(power)} end
    elseif kind == "END" and pending then
        state=pending; pending=nil
        if build() then refresh() end
    end
end

local events=CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("ADDON_LOADED")
events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent", function(_, event, ...)
    if event=="CHAT_MSG_ADDON" then
        local prefix,text=...
        if prefix==RESPONSE then parse(text) end
        return
    end
    if C_Timer and C_Timer.After then
        C_Timer.After(0, build)
        C_Timer.After(0.5, function() if build() then send("status") end end)
    else
        build(); send("status")
    end
end)

events:SetScript("OnUpdate", function(self, elapsed)
    self.elapsed=(self.elapsed or 0)+elapsed
    if self.elapsed<0.5 then return end
    self.elapsed=0
    if build() then self:SetScript("OnUpdate",nil); send("status") end
end)
