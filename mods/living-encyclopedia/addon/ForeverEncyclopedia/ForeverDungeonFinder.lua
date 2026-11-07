-- WoW Forever Dungeon Finder: native Group Finder tab, release 0.3.0.
-- Only the stock LFG window is used; server validation is authoritative.
if _G.ForeverDungeonPortalTab then return end

local PREFIX = "FDF"

local DUNGEONS = {
    { map = 389, name = "Огненная пропасть", range = "13–18", zone = "Оргриммар", desc = "Короткое подземелье под Оргриммаром." },
    { map = 36,  name = "Мёртвые копи", range = "17–26", zone = "Западный Край", desc = "Шахты Братства Справедливости и пиратская бухта." },
    { map = 43,  name = "Пещеры Стенаний", range = "17–24", zone = "Степи", desc = "Извилистые пещеры друидов Клыка." },
    { map = 33,  name = "Крепость Тёмного Клыка", range = "22–30", zone = "Серебряный бор", desc = "Проклятая крепость над деревней Погребальных Костров." },
    { map = 48,  name = "Непроглядная Пучина", range = "20–30", zone = "Ясеневый лес", desc = "Затопленные руины и служители древних сил." },
    { map = 34,  name = "Тюрьма", range = "22–30", zone = "Штормград", desc = "Подземная тюрьма Штормграда." },
    { map = 90,  name = "Гномреган", range = "29–38", zone = "Дун Морог", desc = "Павшая технологическая столица гномов." },
    { map = 47,  name = "Лабиринты Иглошкурых", range = "29–38", zone = "Степи", desc = "Колючий лабиринт племени Иглошкурых." },
    { map = 189, name = "Монастырь Алого ордена", range = "26–45", zone = "Тирисфальские леса", desc = "Комплекс Алого ордена. Пока используется общий вход карты; отдельные крылья добавим следующим слоем." },
    { map = 129, name = "Курганы Иглошкурых", range = "37–46", zone = "Степи", desc = "Некрополь Иглошкурых, захваченный Плетью." },
    { map = 70,  name = "Ульдаман", range = "41–51", zone = "Бесплодные земли", desc = "Древнее хранилище титанов." },
    { map = 209, name = "Зул'Фаррак", range = "44–54", zone = "Танарис", desc = "Город песчаных троллей среди пустыни." },
    { map = 349, name = "Мародон", range = "46–55", zone = "Пустоши", desc = "Осквернённые пещеры и владения принцессы Терадрас." },
    { map = 109, name = "Затонувший храм", range = "50–60", zone = "Болото Печали", desc = "Храм Атал'Хаккара, поглощённый болотом." },
    { map = 230, name = "Глубины Чёрной горы", range = "52–60", zone = "Чёрная гора", desc = "Огромный город Чёрного Железа под горой." },
    { map = 229, name = "Вершина Чёрной горы", range = "55–60", zone = "Чёрная гора", desc = "Верхние залы Чёрной горы и логово орков Чёрной Вершины." },
    { map = 429, name = "Забытый Город", range = "55–60", zone = "Фералас", desc = "Эльфийский город Эльдре'Талас." },
    { map = 289, name = "Некроситет", range = "58–60", zone = "Западные Чумные земли", desc = "Школа некромантии в Каэр Дарроу." },
    { map = 329, name = "Стратхольм", range = "58–60", zone = "Восточные Чумные земли", desc = "Павший город, разделённый между Алым орденом и Плетью." },
}

local function registerPrefix()
    if C_ChatInfo and C_ChatInfo.RegisterAddonMessagePrefix then
        return C_ChatInfo.RegisterAddonMessagePrefix(PREFIX)
    elseif RegisterAddonMessagePrefix then
        return RegisterAddonMessagePrefix(PREFIX)
    end
end

local function sendAddon(text, channel, target)
    if C_ChatInfo and C_ChatInfo.SendAddonMessage then
        return C_ChatInfo.SendAddonMessage(PREFIX, text, channel, target)
    elseif SendAddonMessage then
        return SendAddonMessage(PREFIX, text, channel, target)
    end
end

local function inGroup()
    return IsInGroup and IsInGroup()
end

local function partyState()
    if IsInRaid and IsInRaid() then
        return GetNumGroupMembers and GetNumGroupMembers() or 0, true, false
    end
    if inGroup() then
        local count = GetNumGroupMembers and GetNumGroupMembers() or 0
        local leader = UnitIsGroupLeader and UnitIsGroupLeader("player") or false
        return count, false, leader
    end
    return 1, false, true
end



-- In-place, opaque dungeon panel of Blizzard's existing Group Finder.
-- The client only submits FDF requests; authority is retained server-side.
local picked, host, pane, portal, redraw = DUNGEONS[1], nil, nil, nil, nil
local entries, searchText, page = {}, "", 0
local rows, PAGE_SIZE = {}, 9
local lastRequest = -100
local oldUiNames = {
    "ForeverDungeonFinderFrame", "ForeverDungeonFinderMinimapButton",
    "ForeverDungeonFinderGroupFinderTab", "ForeverDungeonFinderGroupFinderPane",
}

local function notice(message)
    if DEFAULT_CHAT_FRAME then
        DEFAULT_CHAT_FRAME:AddMessage("|cffffd275[WoW Forever]|r " .. message)
    end
end

local function hideOutdatedUi()
    -- Old standalone AddOns can remain on disk and reload after Encyclopedia.
    -- Remove their visible duplicate frames, without touching user files.
    for _, name in ipairs(oldUiNames) do
        local old = _G[name]
        if old and old.Hide and old ~= portal and old ~= pane then
            old:Hide()
            if old.EnableMouse then old:EnableMouse(false) end
            if old.HookScript and not old.foreverNativeHidden then
                old.foreverNativeHidden = true
                old:HookScript("OnShow", function(f) f:Hide() end)
            end
        end
    end
end

local function requestEntry(group)
    if not picked then return end
    if GetTime and GetTime() - lastRequest < 2 then return end
    local count, raid, leader = partyState()
    if group and (count < 2 or count > 5 or raid or not leader) then
        notice("Вход группой доступен только лидеру обычной группы из 2–5 игроков.")
        return
    end
    local player = UnitName("player")
    if not player then return end
    local mode = group and "GROUP:" or "SOLO:"
    local result = sendAddon(mode .. picked.map, group and "PARTY" or "WHISPER", group and nil or player)
    if result == false then
        notice("Не удалось передать запрос в worldserver.")
    else
        if GetTime then lastRequest = GetTime() end
        notice("Запрос передан. Для переноса нужен включённый серверный модуль DungeonFinder.")
    end
end

local function findHost()
    local panel = _G.PVEFrame or _G.LFGParentFrame or _G.GroupFinderFrame
        or _G.LookingForGroupFrame or _G.LFGFrame
    if panel and panel.GetWidth and panel.GetHeight and panel:GetWidth() >= 330 then
        return panel
    end
end

local function plain(parent, layer, r, g, b, alpha)
    -- WHITE8X8 is always present on client build 70658.  SetBackdrop is not
    -- reliable for an opaque background on this client, so never depend on it.
    local t = parent:CreateTexture(nil, layer or "BACKGROUND")
    t:SetTexture("Interface\\Buttons\\WHITE8X8")
    t:SetVertexColor(r, g, b, alpha or 1)
    return t
end

local function label(parent, text, style, x, y, width, rgb)
    local f = parent:CreateFontString(nil, "OVERLAY", style)
    f:SetPoint("TOPLEFT", parent, "TOPLEFT", x, -y)
    f:SetWidth(width)
    f:SetJustifyH("LEFT")
    f:SetText(text or "")
    if rgb then f:SetTextColor(rgb[1], rgb[2], rgb[3]) end
    return f
end

local GOLD, IVORY, GREY = {1, 0.80, 0.26}, {0.95, 0.88, 0.75}, {0.66, 0.72, 0.77}
local function border(parent, x, y, width, height)
    local t = plain(parent, "ARTWORK", 0.54, 0.37, 0.16, 0.83)
    t:SetPoint("TOPLEFT", parent, "TOPLEFT", x, -y)
    t:SetSize(width, height)
    return t
end

-- Lua 5.1 string.lower does not fold Cyrillic text.  Match UTF-8 Russian
-- dungeon names and regions without modifying game locale/global functions.
local function foldRu(text)
    local result = string.lower(text or "")
    result = result:gsub("\208([\144-\159])", function(b)
        return "\208" .. string.char(string.byte(b) + 32)
    end)
    result = result:gsub("\208([\160-\175])", function(b)
        return "\209" .. string.char(string.byte(b) - 32)
    end)
    return result:gsub("Ё", "ё")
end

local function install()
    if portal then return true end
    local f = findHost()
    if not f then return false end
    host = f

    hideOutdatedUi()

    -- A fifth icon cannot fit into the client's 470px role row without
    -- overwriting the sword/guide controls.  The Group Finder has a persistent
    -- native right-hand strip of square navigation tabs on EVERY subpage.
    -- Put our portal into that strip, immediately below the existing buttons.
    -- Unlike the previous TOPLEFT x/y guess, this is never over the filters.
    portal = CreateFrame("CheckButton", "ForeverDungeonPortalTab", host)
    portal:SetSize(50, 50)
    portal:SetFrameLevel(host:GetFrameLevel() + 112)
    portal:RegisterForClicks("LeftButtonUp")
    portal:SetHitRectInsets(0, 0, 0, 0)

    local tile = plain(portal, "BACKGROUND", 0.115, 0.075, 0.040, 1)
    tile:SetAllPoints()
    local symbol = portal:CreateTexture(nil, "ARTWORK")
    symbol:SetPoint("TOPLEFT", portal, "TOPLEFT", 5, -5)
    symbol:SetPoint("BOTTOMRIGHT", portal, "BOTTOMRIGHT", -5, 5)
    symbol:SetTexture("Interface\\Icons\\Spell_Arcane_PortalStormWind")
    symbol:SetTexCoord(0.08, 0.92, 0.08, 0.92)

    local outer = portal:CreateTexture(nil, "OVERLAY")
    outer:SetAllPoints()
    outer:SetTexture("Interface\\Buttons\\UI-Quickslot2")
    outer:SetVertexColor(0.97, 0.77, 0.31, 1)
    border(portal, 2, 1, 46, 2)
    border(portal, 2, 47, 46, 2)
    border(portal, 1, 2, 2, 46)
    border(portal, 47, 2, 2, 46)

    local selectedGlow = portal:CreateTexture(nil, "OVERLAY")
    selectedGlow:SetPoint("TOPLEFT", portal, "TOPLEFT", -12, 12)
    selectedGlow:SetPoint("BOTTOMRIGHT", portal, "BOTTOMRIGHT", 12, -12)
    selectedGlow:SetTexture("Interface\\Buttons\\UI-ActionButton-Border")
    selectedGlow:SetBlendMode("ADD")
    selectedGlow:SetVertexColor(1, 0.70, 0.12, 0.85)
    selectedGlow:Hide()

    -- For clients exposing the sidebar buttons, attach to the LAST one.
    -- Check actual geometry: a similarly named bottom tab is not acceptable.
    local candidates = {
        "PVEFrameTab3", "LFGParentFrameTab3", "GroupFinderFrameTab3",
        "LFGFrameTab3", "PVEFrameTab4", "LFGParentFrameTab4",
    }
    local anchored = false
    for _, name in ipairs(candidates) do
        local native = _G[name]
        if native and native.GetLeft and native.GetWidth and host.GetRight then
            local left, right = native:GetLeft(), host:GetRight()
            local width, height = native:GetWidth(), native:GetHeight()
            if left and right and width and height
                and left >= right - 12 and width >= 34 and width <= 72
                and height >= 34 and height <= 72 then
                portal:SetPoint("TOPLEFT", native, "BOTTOMLEFT", 0, -6)
                anchored = true
                break
            end
        end
    end
    if not anchored then
        -- Observed WoW Forever 70658: three sidebar icons to the right
        -- of the 470px frame at roughly -95, -150 and -205 from its top.
        -- Fourth icon follows underneath (not across the top filter bar).
        portal:SetPoint("TOPLEFT", host, "TOPRIGHT", 4, -249)
    end
    portal:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
        GameTooltip:AddLine("Вход в подземелье", 1, 0.80, 0.26)
        GameTooltip:AddLine("Соло или текущей группой, без очереди", 0.93, 0.88, 0.76)
        GameTooltip:Show()
    end)
    portal:SetScript("OnLeave", function() GameTooltip:Hide() end)

    -- A full opaque panel is crucial: the old version was transparent and
    -- rendered over the native "Подземелья / Зоны и задания" categories.
    pane = CreateFrame("Frame", "ForeverDungeonFinderPane", host)
    pane:SetPoint("TOPLEFT", host, "TOPLEFT", 18, -135)
    pane:SetPoint("BOTTOMRIGHT", host, "BOTTOMRIGHT", -17, 48)
    pane:SetFrameLevel(host:GetFrameLevel() + 100)
    pane:EnableMouse(true)
    pane:EnableMouseWheel(true)

    local bg = plain(pane, "BACKGROUND", 0.070, 0.046, 0.031, 1)
    bg:SetAllPoints()
    pane.opaqueBackground = bg -- testable and independent of legacy SetBackdrop

    local inner = plain(pane, "BORDER", 0.115, 0.071, 0.037, 1)
    inner:SetPoint("TOPLEFT", pane, "TOPLEFT", 4, -4)
    inner:SetPoint("BOTTOMRIGHT", pane, "BOTTOMRIGHT", -4, 4)

    -- Natural WoW gold trim around the complete native-content rectangle.
    local width = math.max(325, host:GetWidth() - 35)
    local height = math.max(270, host:GetHeight() - 183)
    border(pane, 4, 3, width - 8, 2)
    border(pane, 4, height - 6, width - 8, 2)
    border(pane, 3, 4, 2, height - 8)
    border(pane, width - 5, 4, 2, height - 8)

    local split = math.floor(width * 0.455)
    local leftW = split - 31
    local rightX = split + 12
    local rightW = width - rightX - 18
    if rightW < 130 then rightW = 130 end

    local listBg = plain(pane, "ARTWORK", 0.050, 0.036, 0.025, 0.97)
    listBg:SetPoint("TOPLEFT", pane, "TOPLEFT", 10, -65)
    listBg:SetPoint("BOTTOMLEFT", pane, "BOTTOMLEFT", 10, 43)
    listBg:SetWidth(split - 15)
    local rule = plain(pane, "ARTWORK", 0.52, 0.35, 0.15, 0.81)
    rule:SetPoint("TOPLEFT", pane, "TOPLEFT", split + 1, -11)
    rule:SetPoint("BOTTOMLEFT", pane, "BOTTOMLEFT", split + 1, 11)
    rule:SetWidth(1)

    local search = CreateFrame("EditBox", nil, pane, "InputBoxTemplate")
    search:SetSize(leftW, 23)
    search:SetPoint("TOPLEFT", pane, "TOPLEFT", 17, -15)
    search:SetAutoFocus(false)
    search:SetMaxLetters(48)
    if search.SetTextInsets then search:SetTextInsets(6, 6, 0, 0) end
    local hint = label(pane, "Поиск...", "GameFontDisableSmall", 27, 21, leftW - 15, GREY)
    if hint.EnableMouse then hint:EnableMouse(false) end
    label(pane, "ДОСТУПНЫЕ ПОДЗЕМЕЛЬЯ", "GameFontNormalSmall", 15, 49, split - 16, GOLD)

    for i = 1, PAGE_SIZE do
        local row = CreateFrame("Button", nil, pane)
        row:SetSize(split - 20, 24)
        row:SetPoint("TOPLEFT", pane, "TOPLEFT", 13, -70 - (i - 1) * 25)
        row:SetFrameLevel(pane:GetFrameLevel() + 2)
        local shade = plain(row, "BACKGROUND", 0.11, 0.075, 0.049, 0.58)
        shade:SetAllPoints()
        local rowName = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
        rowName:SetPoint("LEFT", row, "LEFT", 4, 0)
        rowName:SetPoint("RIGHT", row, "RIGHT", -42, 0)
        rowName:SetJustifyH("LEFT")
        local rowLvl = row:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
        rowLvl:SetPoint("RIGHT", row, "RIGHT", -3, 0)
        row.shade, row.title, row.level = shade, rowName, rowLvl
        rows[i] = row
    end

    local prev = CreateFrame("Button", nil, pane, "UIPanelButtonTemplate")
    prev:SetSize(64, 22)
    prev:SetPoint("BOTTOMLEFT", pane, "BOTTOMLEFT", 14, 13)
    prev:SetText("Назад")
    local nextButton = CreateFrame("Button", nil, pane, "UIPanelButtonTemplate")
    nextButton:SetSize(64, 22)
    nextButton:SetPoint("LEFT", prev, "RIGHT", 5, 0)
    nextButton:SetText("Далее")
    local pagesLabel = label(pane, "", "GameFontDisableSmall", 147, height - 39, 40, GREY)

    local dungeonName = label(pane, "", "GameFontNormalLarge", rightX, 19, rightW, GOLD)
    local region = label(pane, "", "GameFontHighlightSmall", rightX, 49, rightW, GREY)
    border(pane, rightX, 77, rightW, 1)
    local levelText = label(pane, "", "GameFontNormalSmall", rightX, 91, rightW, IVORY)
    local description = label(pane, "", "GameFontHighlightSmall", rightX, 118, rightW, IVORY)
    description:SetJustifyV("TOP")
    local scaling = label(pane, "Уровни противников подстраиваются под персонажа.", "GameFontHighlightSmall", rightX, 166, rightW, GREY)
    scaling:SetJustifyV("TOP")

    local party = CreateFrame("Frame", nil, pane)
    party:SetPoint("BOTTOMLEFT", pane, "BOTTOMLEFT", rightX - 4, 74)
    party:SetPoint("BOTTOMRIGHT", pane, "BOTTOMRIGHT", -12, 74)
    party:SetHeight(61)
    party:SetFrameLevel(pane:GetFrameLevel() + 2)
    local partyFill = plain(party, "BACKGROUND", 0.083, 0.061, 0.040, 1)
    partyFill:SetAllPoints()
    local partyEdge = plain(party, "ARTWORK", 0.46, 0.33, 0.17, 1)
    partyEdge:SetPoint("TOPLEFT", 0, 0)
    partyEdge:SetPoint("TOPRIGHT", 0, 0)
    partyEdge:SetHeight(1)
    label(party, "ТЕКУЩИЙ СОСТАВ", "GameFontNormalSmall", 8, 7, rightW - 14, GOLD)
    local partyInfo = label(party, "", "GameFontHighlightSmall", 8, 27, rightW - 15, IVORY)
    partyInfo:SetJustifyV("TOP")

    local solo = CreateFrame("Button", nil, pane, "UIPanelButtonTemplate")
    solo:SetSize(math.max(75, math.floor((rightW - 6) / 2)), 29)
    solo:SetPoint("BOTTOMLEFT", pane, "BOTTOMLEFT", rightX, 21)
    solo:SetText("Войти соло")
    local together = CreateFrame("Button", nil, pane, "UIPanelButtonTemplate")
    together:SetSize(math.max(75, math.floor((rightW - 6) / 2)), 29)
    together:SetPoint("LEFT", solo, "RIGHT", 5, 0)
    together:SetText("Группой")

    local function update()
        wipe(entries)
        local query = foldRu(searchText)
        for _, dungeon in ipairs(DUNGEONS) do
            if query == "" or string.find(foldRu(dungeon.name .. " " .. dungeon.zone), query, 1, true) then
                table.insert(entries, dungeon)
            end
        end
        local pages = math.max(1, math.ceil(#entries / PAGE_SIZE))
        page = math.max(0, math.min(page, pages - 1))
        prev:SetEnabled(page > 0)
        nextButton:SetEnabled(page < pages - 1)
        pagesLabel:SetText(tostring(page + 1) .. "/" .. tostring(pages))
        for i, row in ipairs(rows) do
            local d = entries[page * PAGE_SIZE + i]
            row.data = d
            if d then
                row:Show()
                row.title:SetText(d.name)
                row.level:SetText(d.range)
                if d == picked then
                    row.shade:SetVertexColor(0.14, 0.27, 0.42, 1)
                    row.title:SetTextColor(1, 0.82, 0.28)
                else
                    row.shade:SetVertexColor(0.11, 0.075, 0.049, i % 2 == 0 and 0.90 or 0.62)
                    row.title:SetTextColor(0.95, 0.88, 0.77)
                end
            else
                row:Hide()
            end
        end

        dungeonName:SetText(picked.name)
        region:SetText(picked.zone)
        levelText:SetText("Уровень: " .. picked.range)
        description:SetText(picked.desc)

        local n, raid, leader = partyState()
        if raid then
            partyInfo:SetText("Рейд: только соло.")
        elseif n <= 1 then
            partyInfo:SetText("Вы без группы. Доступен вход соло.")
        elseif not leader then
            partyInfo:SetText("Игроков: " .. n .. ". Нужен лидер.")
        else
            partyInfo:SetText("Группа: " .. n .. ". Можно войти вместе.")
        end
        together:SetEnabled(n >= 2 and n <= 5 and not raid and leader)
    end
    redraw = update

    for _, row in ipairs(rows) do
        row:SetScript("OnClick", function(self)
            if self.data then picked = self.data; update() end
        end)
        row:SetScript("OnEnter", function(self)
            if self.data ~= picked and self.data then
                self.shade:SetVertexColor(0.31, 0.25, 0.14, 0.9)
            end
        end)
        row:SetScript("OnLeave", function() update() end)
    end
    search:SetScript("OnTextChanged", function(self)
        searchText = self:GetText() or ""
        if searchText == "" then hint:Show() else hint:Hide() end
        page = 0
        update()
    end)
    search:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    search:SetScript("OnEnterPressed", function(self) self:ClearFocus() end)
    prev:SetScript("OnClick", function() page = page - 1; update() end)
    nextButton:SetScript("OnClick", function() page = page + 1; update() end)
    pane:SetScript("OnMouseWheel", function(_, delta)
        page = page - (delta > 0 and 1 or -1)
        update()
    end)
    solo:SetScript("OnClick", function() requestEntry(false) end)
    together:SetScript("OnClick", function() requestEntry(true) end)

    local function close()
        pane:Hide()
        portal:SetChecked(false)
        selectedGlow:Hide()
    end
    local function open()
        hideOutdatedUi()
        update()
        pane:Show()
        portal:SetChecked(true)
        selectedGlow:Show()
    end
    pane.open = open
    pane.close = close
    portal:SetScript("OnClick", function()
        if pane:IsShown() then close() else open() end
    end)
    host:HookScript("OnHide", close)
    for _, name in ipairs({
        "PVEFrameTab1", "PVEFrameTab2", "PVEFrameTab3",
        "LFGParentFrameTab1", "LFGParentFrameTab2", "LFGParentFrameTab3",
        "GroupFinderFrameGroupButton", "GroupFinderFrameLFGListBrowserButton",
    }) do
        local other = _G[name]
        if other and other.HookScript then other:HookScript("OnClick", close) end
    end
    pane:Hide()
    hideOutdatedUi()
    update()
    return true
end

local function openNative()
    if not install() then
        if C_AddOns and C_AddOns.LoadAddOn then
            pcall(C_AddOns.LoadAddOn, "Blizzard_GroupFinder")
        elseif LoadAddOn then
            pcall(LoadAddOn, "Blizzard_GroupFinder")
        end
    end
    if not install() then
        notice("Откройте «Поиск группы», затем повторите /fd.")
        return
    end
    if not host:IsShown() then
        if PVEFrame_ShowFrame then pcall(PVEFrame_ShowFrame, "GroupFinderFrame") end
        if not host:IsShown() and ShowUIPanel then ShowUIPanel(host) end
        if not host:IsShown() then host:Show() end
    end
    pane.open()
end

SLASH_FOREVERDUNGEONFINDER1 = "/fd"
SLASH_FOREVERDUNGEONFINDER2 = "/dungeon"
SlashCmdList.FOREVERDUNGEONFINDER = openNative

local events = CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("PLAYER_ENTERING_WORLD")
events:RegisterEvent("ADDON_LOADED")
events:RegisterEvent("GROUP_ROSTER_UPDATE")
events:SetScript("OnEvent", function(_, event)
    if event == "PLAYER_LOGIN" then registerPrefix() end
    if event == "GROUP_ROSTER_UPDATE" then
        if pane and pane:IsShown() and redraw then redraw() end
    else
        install()
    end
    hideOutdatedUi()
    -- Old addon scripts can overwrite the common slash binding after load.
    SlashCmdList.FOREVERDUNGEONFINDER = openNative
end)
if IsLoggedIn and IsLoggedIn() then
    registerPrefix()
    install()
    hideOutdatedUi()
end
