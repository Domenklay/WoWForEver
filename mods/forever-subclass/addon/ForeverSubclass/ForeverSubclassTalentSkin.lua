-- Talent-style presentation for ForeverSubclass.
-- Gameplay and state still live in ForeverSubclassTalentTab/DirectTransport.
-- This file only replaces the rough prototype controls with a more native-looking UI.

local classIds = {
    ["Воин"] = 1, ["Паладин"] = 2, ["Охотник"] = 3,
    ["Разбойник"] = 4, ["Жрец"] = 5, ["Шаман"] = 7,
    ["Маг"] = 8, ["Чернокнижник"] = 9, ["Друид"] = 11,
}

local classInfo = {
    [1]  = { name="Воин", token="WARRIOR" },
    [2]  = { name="Паладин", token="PALADIN" },
    [3]  = { name="Охотник", token="HUNTER" },
    [4]  = { name="Разбойник", token="ROGUE" },
    [5]  = { name="Жрец", token="PRIEST" },
    [7]  = { name="Шаман", token="SHAMAN" },
    [8]  = { name="Маг", token="MAGE" },
    [9]  = { name="Чернокнижник", token="WARLOCK" },
    [11] = { name="Друид", token="DRUID" },
}

local classOrder = {1,2,3,4,5,7,8,9,11}
local built = false
local cards = {}
local originalClassButtons = {}
local originalActions = {}
local actionButtons = {}
local heading, subheading, leftTitle, rightTitle
local leftPanel, rightPanel
local elapsed = 0
local styledRows = setmetatable({}, { __mode = "k" })

local function getText(widget)
    if not widget or not widget.GetText then return nil end
    local ok, value = pcall(widget.GetText, widget)
    return ok and value or nil
end

local function classIdFromText(text)
    if not text then return nil end
    text = text:gsub("^>%s*", "")
    for name, id in pairs(classIds) do
        if text:sub(1, #name) == name then return id end
    end
end

local function walk(root, buttons, fonts, depth)
    if not root or depth > 8 then return end
    if root.GetRegions then
        for _, region in ipairs({root:GetRegions()}) do
            if region and region.GetObjectType and region:GetObjectType() == "FontString" then
                table.insert(fonts, region)
            end
        end
    end
    if not root.GetChildren then return end
    for _, child in ipairs({root:GetChildren()}) do
        if child and child.GetObjectType and child:GetObjectType() == "Button" then
            table.insert(buttons, child)
        end
        walk(child, buttons, fonts, depth + 1)
    end
end

local function makeBackdrop(parent)
    local template = BackdropTemplateMixin and "BackdropTemplate" or nil
    local frame = CreateFrame("Frame", nil, parent, template)
    if frame.SetBackdrop then
        frame:SetBackdrop({
            bgFile="Interface\\Tooltips\\UI-Tooltip-Background",
            edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",
            tile=true, tileSize=16, edgeSize=12,
            insets={left=3,right=3,top=3,bottom=3},
        })
        frame:SetBackdropColor(0.025, 0.025, 0.025, 0.88)
        frame:SetBackdropBorderColor(0.42, 0.32, 0.14, 0.92)
    end
    return frame
end

local function runOriginal(button)
    if not button then return end
    local handler = button.GetScript and button:GetScript("OnClick")
    if handler then
        local ok, err = pcall(handler, button, "LeftButton", false)
        if not ok and DEFAULT_CHAT_FRAME then
            DEFAULT_CHAT_FRAME:AddMessage("|cffff5555[Подклассы]|r " .. tostring(err))
        end
    end
end

local function setClassIcon(texture, token)
    texture:SetTexture("Interface\\GLUES\\CHARACTERCREATE\\UI-CHARACTERCREATE-CLASSES")
    local coords = CLASS_ICON_TCOORDS and CLASS_ICON_TCOORDS[token]
    if coords then
        texture:SetTexCoord(coords[1], coords[2], coords[3], coords[4])
    else
        texture:SetTexture(134400)
        texture:SetTexCoord(0,1,0,1)
    end
end

local function createCard(parent, id, index)
    local info = classInfo[id]
    local template = BackdropTemplateMixin and "BackdropTemplate" or nil
    local card = CreateFrame("Button", nil, parent, template)
    card:SetSize(136, 68)
    local col = (index - 1) % 3
    local row = math.floor((index - 1) / 3)
    card:SetPoint("TOPLEFT", 12 + col * 142, -42 - row * 76)
    card:EnableMouse(true)
    if card.RegisterForClicks then card:RegisterForClicks("AnyUp") end

    if card.SetBackdrop then
        card:SetBackdrop({
            bgFile="Interface\\Tooltips\\UI-Tooltip-Background",
            edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",
            tile=true, tileSize=16, edgeSize=10,
            insets={left=3,right=3,top=3,bottom=3},
        })
        card:SetBackdropColor(0.045, 0.045, 0.045, 0.95)
        card:SetBackdropBorderColor(0.31, 0.26, 0.17, 0.95)
    end

    local iconBorder = card:CreateTexture(nil, "BORDER")
    iconBorder:SetTexture("Interface\\Buttons\\UI-Quickslot2")
    iconBorder:SetSize(47, 47)
    iconBorder:SetPoint("LEFT", 7, 0)

    local icon = card:CreateTexture(nil, "ARTWORK")
    icon:SetSize(38, 38)
    icon:SetPoint("CENTER", iconBorder, "CENTER", 0, 0)
    setClassIcon(icon, info.token)

    local name = card:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    name:SetPoint("TOPLEFT", 57, -13)
    name:SetPoint("RIGHT", -6, 0)
    name:SetJustifyH("LEFT")
    name:SetText(info.name)

    local status = card:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    status:SetPoint("TOPLEFT", name, "BOTTOMLEFT", 0, -5)
    status:SetPoint("RIGHT", -6, 0)
    status:SetJustifyH("LEFT")
    status:SetText("Не изучен")

    local selectedGlow = card:CreateTexture(nil, "OVERLAY")
    selectedGlow:SetTexture("Interface\\Buttons\\UI-ActionButton-Border")
    selectedGlow:SetBlendMode("ADD")
    selectedGlow:SetAllPoints(iconBorder)
    selectedGlow:Hide()

    card:SetScript("OnEnter", function(self)
        if self.SetBackdropBorderColor then self:SetBackdropBorderColor(0.82,0.66,0.25,1) end
    end)
    card:SetScript("OnLeave", function(self)
        if self._selected then
            if self.SetBackdropBorderColor then self:SetBackdropBorderColor(0.95,0.72,0.18,1) end
        elseif self._active then
            if self.SetBackdropBorderColor then self:SetBackdropBorderColor(0.22,0.72,0.34,1) end
        else
            if self.SetBackdropBorderColor then self:SetBackdropBorderColor(0.31,0.26,0.17,0.95) end
        end
    end)
    card:SetScript("OnClick", function()
        runOriginal(originalClassButtons[id])
    end)

    cards[id] = { frame=card, status=status, glow=selectedGlow }
end

local function makeAction(parent, key, text, x, width)
    local template = BackdropTemplateMixin and "BackdropTemplate" or nil
    local button = CreateFrame("Button", nil, parent, template)
    button:SetSize(width or 128, 31)
    button:SetPoint("BOTTOMLEFT", x, 13)
    button:EnableMouse(true)
    if button.RegisterForClicks then button:RegisterForClicks("AnyUp") end
    if button.SetBackdrop then
        button:SetBackdrop({
            bgFile="Interface\\Tooltips\\UI-Tooltip-Background",
            edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",
            tile=true,tileSize=16,edgeSize=9,
            insets={left=3,right=3,top=3,bottom=3},
        })
        button:SetBackdropColor(0.08,0.065,0.035,0.96)
        button:SetBackdropBorderColor(0.55,0.42,0.16,1)
    end
    local label=button:CreateFontString(nil,"OVERLAY","GameFontNormal")
    label:SetPoint("CENTER")
    label:SetText(text)
    button.label=label
    button:SetScript("OnEnter",function(self)
        if self.SetBackdropColor then self:SetBackdropColor(0.16,0.12,0.045,1) end
        if self.SetBackdropBorderColor then self:SetBackdropBorderColor(0.95,0.74,0.22,1) end
    end)
    button:SetScript("OnLeave",function(self)
        if self._enabled == false then
            if self.SetBackdropColor then self:SetBackdropColor(0.03,0.03,0.03,0.75) end
            if self.SetBackdropBorderColor then self:SetBackdropBorderColor(0.20,0.20,0.20,0.8) end
        else
            if self.SetBackdropColor then self:SetBackdropColor(0.08,0.065,0.035,0.96) end
            if self.SetBackdropBorderColor then self:SetBackdropBorderColor(0.55,0.42,0.16,1) end
        end
    end)
    button:SetScript("OnClick",function()
        if button._enabled ~= false then runOriginal(originalActions[key]) end
    end)
    actionButtons[key]=button
end

local function setActionEnabled(key, enabled)
    local b=actionButtons[key]
    if not b then return end
    b._enabled=enabled and true or false
    b:EnableMouse(enabled and true or false)
    if b.label then
        if enabled then b.label:SetTextColor(1,0.82,0.22,1)
        else b.label:SetTextColor(0.43,0.43,0.43,1) end
    end
    if b.SetBackdropColor then
        if enabled then
            b:SetBackdropColor(0.08,0.065,0.035,0.96)
            b:SetBackdropBorderColor(0.55,0.42,0.16,1)
        else
            b:SetBackdropColor(0.03,0.03,0.03,0.75)
            b:SetBackdropBorderColor(0.20,0.20,0.20,0.8)
        end
    end
end

local actionNames = {
    ["Изучить"]="learn", ["Активировать"]="active",
    ["XP сюда"]="xp", ["Отключить"]="clear",
}

local function discoverOriginals(panel)
    local buttons, fonts = {}, {}
    walk(panel, buttons, fonts, 0)
    for _, button in ipairs(buttons) do
        if button ~= _G.ForeverSubclassTalentClickProxy then
            local text=getText(button)
            local id=classIdFromText(text)
            if id and not originalClassButtons[id] then
                originalClassButtons[id]=button
            elseif text and actionNames[text] then
                originalActions[actionNames[text]]=button
            end
        end
    end
    return fonts
end

local function hidePrototypeControls(fonts)
    for _, button in pairs(originalClassButtons) do
        button:SetAlpha(0)
        button:EnableMouse(false)
    end
    for _, button in pairs(originalActions) do
        button:SetAlpha(0)
        button:EnableMouse(false)
    end
    for _, font in ipairs(fonts or {}) do
        local text=font.GetText and font:GetText()
        if text == "Классы" or text == "Способности активного подкласса"
            or (text and text:find("Основной класс и его броня",1,true)) then
            font:Hide()
        end
    end
end

local function styleAbilityRows()
    local scroll=_G.ForeverSubclassTalentScroll
    if not scroll or not scroll.GetScrollChild then return end
    local content=scroll:GetScrollChild()
    if not content or not content.GetChildren then return end
    local visible={}
    for _, row in ipairs({content:GetChildren()}) do
        if row and row:IsShown() then table.insert(visible,row) end
    end
    table.sort(visible,function(a,b)
        local at=a.GetTop and a:GetTop() or 0
        local bt=b.GetTop and b:GetTop() or 0
        return at>bt
    end)
    for index,row in ipairs(visible) do
        if not styledRows[row] then
            styledRows[row]=true
            local bg=row:CreateTexture(nil,"BACKGROUND")
            bg:SetAllPoints()
            bg:SetColorTexture(0.025,0.025,0.025,0.76)
            local edge=row:CreateTexture(nil,"BORDER")
            edge:SetPoint("BOTTOMLEFT",4,0);edge:SetPoint("BOTTOMRIGHT",-4,0);edge:SetHeight(1)
            edge:SetColorTexture(0.40,0.31,0.14,0.55)
        end
        row:ClearAllPoints()
        row:SetPoint("TOPLEFT",4,-(index-1)*52)
        row:SetPoint("RIGHT",content,"RIGHT",-4,0)
        row:SetHeight(48)
        local children={row:GetChildren()}
        for _,child in ipairs(children) do
            if child and child.GetObjectType and child:GetObjectType()=="Button" then
                local t=getText(child)
                if t=="Каст" then child:SetText("Использовать") end
                child:SetHeight(26)
            end
        end
        if row.GetRegions then
            for _,region in ipairs({row:GetRegions()}) do
                if region and region.GetObjectType and region:GetObjectType()=="Texture" then
                    local w=region.GetWidth and region:GetWidth() or 0
                    local h=region.GetHeight and region:GetHeight() or 0
                    if w>=28 and w<=36 and h>=28 and h<=36 then region:SetSize(40,40) end
                end
            end
        end
    end
    content:SetHeight(math.max(240,#visible*52))
end

local function updateCards()
    for _,id in ipairs(classOrder) do
        local old=originalClassButtons[id]
        local card=cards[id]
        if old and card then
            local text=getText(old) or classInfo[id].name
            local selected=text:match("^>")~=nil
            local active=text:find("• активен",1,true)~=nil
            local primary=text:find("• основной",1,true)~=nil
            local xp=text:find("• XP",1,true)~=nil
            local level=text:match("ур%.%s*(%d+)")
            local unlearned=text:find("не изучен",1,true)~=nil
            local status
            if primary then status="Основной класс"
            elseif active then status="Активный" .. (level and (" · ур. "..level) or "")
            elseif unlearned then status="Не изучен"
            elseif level then status="Уровень "..level
            else status="Доступен" end
            if xp and not primary then status=status.." · получает XP" end
            card.status:SetText(status)
            card.frame._selected=selected
            card.frame._active=active
            if selected then
                if card.frame.SetBackdropBorderColor then card.frame:SetBackdropBorderColor(0.95,0.72,0.18,1) end
                card.glow:Show()
            elseif active then
                if card.frame.SetBackdropBorderColor then card.frame:SetBackdropBorderColor(0.22,0.72,0.34,1) end
                card.glow:Hide()
            else
                if card.frame.SetBackdropBorderColor then card.frame:SetBackdropBorderColor(0.31,0.26,0.17,0.95) end
                card.glow:Hide()
            end
        end
    end
    for key,old in pairs(originalActions) do
        setActionEnabled(key, old.IsEnabled and old:IsEnabled())
    end
end

local function build()
    local panel=_G.ForeverSubclassTalentPanel
    if not panel or built then return false end
    local fonts=discoverOriginals(panel)
    if not next(originalClassButtons) then return false end
    built=true

    hidePrototypeControls(fonts)

    leftPanel=makeBackdrop(panel)
    leftPanel:SetPoint("TOPLEFT",panel,"TOPLEFT",10,-58)
    leftPanel:SetPoint("BOTTOMLEFT",panel,"BOTTOMLEFT",10,52)
    leftPanel:SetWidth(446)
    leftPanel:SetFrameLevel(panel:GetFrameLevel()+3)

    rightPanel=makeBackdrop(panel)
    rightPanel:SetPoint("TOPLEFT",panel,"TOPLEFT",466,-58)
    rightPanel:SetPoint("BOTTOMRIGHT",panel,"BOTTOMRIGHT",-10,52)
    rightPanel:SetFrameLevel(panel:GetFrameLevel()+3)

    heading=leftPanel:CreateFontString(nil,"OVERLAY","GameFontNormalLarge")
    heading:SetPoint("TOPLEFT",12,-12)
    heading:SetText("Выберите второй путь")
    subheading=leftPanel:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
    subheading:SetPoint("TOPLEFT",heading,"BOTTOMLEFT",0,-4)
    subheading:SetWidth(410);subheading:SetJustifyH("LEFT")
    subheading:SetText("Класс развивается отдельно. Основной класс, броня и его способности сохраняются.")

    for index,id in ipairs(classOrder) do createCard(leftPanel,id,index) end

    makeAction(leftPanel,"learn","Изучить путь",12,128)
    makeAction(leftPanel,"active","Сделать активным",146,136)
    makeAction(leftPanel,"xp","Направить XP",288,128)

    local clear=CreateFrame("Button",nil,leftPanel)
    clear:SetSize(128,20);clear:SetPoint("BOTTOMLEFT",12,47)
    local clearText=clear:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
    clearText:SetPoint("LEFT");clearText:SetText("Отключить подкласс")
    clear:SetScript("OnEnter",function() clearText:SetTextColor(1,0.72,0.22,1) end)
    clear:SetScript("OnLeave",function() clearText:SetTextColor(1,1,1,1) end)
    clear:SetScript("OnClick",function() runOriginal(originalActions.clear) end)
    actionButtons.clear=clear

    rightTitle=rightPanel:CreateFontString(nil,"OVERLAY","GameFontNormalLarge")
    rightTitle:SetPoint("TOPLEFT",14,-13)
    rightTitle:SetText("Способности подкласса")
    local rightHelp=rightPanel:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
    rightHelp:SetPoint("TOPLEFT",rightTitle,"BOTTOMLEFT",0,-5)
    rightHelp:SetText("Выберите до 8 способностей. Требования уровня и ресурс проверяет сервер.")

    local scroll=_G.ForeverSubclassTalentScroll
    if scroll then
        scroll:SetParent(rightPanel)
        scroll:ClearAllPoints()
        scroll:SetPoint("TOPLEFT",10,-52)
        scroll:SetPoint("BOTTOMRIGHT",-28,12)
        scroll:SetFrameLevel(rightPanel:GetFrameLevel()+3)
    end

    if panel.HookScript then
        panel:HookScript("OnShow",function()
            discoverOriginals(panel)
            hidePrototypeControls({})
            updateCards();styleAbilityRows()
        end)
    end
    updateCards();styleAbilityRows()
    return true
end

local events=CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("ADDON_LOADED")
events:SetScript("OnEvent",function()
    if C_Timer and C_Timer.After then
        C_Timer.After(0,build)
        C_Timer.After(0.3,build)
        C_Timer.After(1.0,build)
    else build() end
end)
events:SetScript("OnUpdate",function(_,delta)
    elapsed=elapsed+delta
    if elapsed<0.25 then return end
    elapsed=0
    if not built then build() else
        discoverOriginals(_G.ForeverSubclassTalentPanel)
        updateCards();styleAbilityRows()
    end
end)
