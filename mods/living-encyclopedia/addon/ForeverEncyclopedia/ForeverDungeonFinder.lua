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
local entries, searchText = {}, ""
local rows, ROW_HEIGHT = {}, 32
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

-- This client uses Blizzard_GroupFinder_VanillaStyle (Forever 70658).
-- It has real Listing/Browsing/WhoListing right-hand tabs and a native page
-- switcher. Do not guess from unrelated PVEFrame or retail GroupFinder frames.
local function findHost()
    local frame = _G.LFGParentFrame
    if not frame or not frame.WhoListingTab or not frame.UpdateTabs
        or not _G.LFGListingFrame or not _G.LFGBrowseFrame
        or not _G.LFGWhoListFrame or not PanelTemplates_SetTab
        or not hooksecurefunc then
        return nil
    end
    return frame
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

    -- Add the fourth page exactly as the Book added its native Legacy page.
    -- This is the real Forever/Vanilla Group Finder side-tab template, including
    -- built-in golden border, selected glow, mouse handler and 30px icon.
    portal = CreateFrame("Frame", "ForeverDungeonPortalTab", host, "LFGVanillaRightTabTemplate")
    portal:SetID(4)
    portal.tooltipText = "Вход в подземелье"
    portal.iconTexture = "Interface\\Icons\\Spell_Arcane_PortalStormWind"
    if portal.Icon then portal.Icon:SetTexture(portal.iconTexture) end
    portal:SetPoint("TOPLEFT", host.WhoListingTab, "BOTTOMLEFT", 0, -2)
    if host.WhoListingTab.GetWidth and host.WhoListingTab.GetHeight then
        portal:SetSize(host.WhoListingTab:GetWidth(), host.WhoListingTab:GetHeight())
    end
    host.DungeonPortalTab = portal

    -- The three Blizzard LFG pages use PortraitFrameTemplateNoCloseButton,
    -- filling the WHOLE 458x535 LFGParentFrame. Reuse their actual chrome,
    -- title bar and dimensions instead of a smaller, unstyled custom rectangle.
    pane = CreateFrame("Frame", "ForeverDungeonFinderPane", host, "PortraitFrameTemplateNoCloseButton")
    pane:SetAllPoints(host)
    pane:SetFrameLevel(host:GetFrameLevel() + 101)
    pane:EnableMouse(true)
    if pane.SetTitle then pane:SetTitle("Поиск группы") end

    -- Keep the inherited Blizzard border/portrait/title visible. Only fill
    -- the content well beneath the real header. The page itself covers the
    -- ENTIRE stock window and can no longer appear shorter than other tabs.
    local bg = plain(pane, "BACKGROUND", 0.070, 0.046, 0.031, 1)
    bg:SetPoint("TOPLEFT", pane, "TOPLEFT", 11, -57)
    bg:SetPoint("BOTTOMRIGHT", pane, "BOTTOMRIGHT", -10, 35)
    pane.opaqueBackground = bg

    local inner = plain(pane, "BORDER", 0.115, 0.071, 0.037, 1)
    inner:SetPoint("TOPLEFT", pane, "TOPLEFT", 15, -61)
    inner:SetPoint("BOTTOMRIGHT", pane, "BOTTOMRIGHT", -14, 40)

    local width = math.max(325, host:GetWidth())
    local height = math.max(400, host:GetHeight())
    border(pane, 12, 56, width - 23, 2)
    border(pane, 12, height - 39, width - 23, 2)
    border(pane, 12, 57, 2, height - 96)
    border(pane, width - 13, 57, 2, height - 96)

    local split = math.floor(width * 0.455)
    local leftW = split - 31
    local rightX = split + 12
    local rightW = width - rightX - 18
    if rightW < 130 then rightW = 130 end

    local listBg = plain(pane, "ARTWORK", 0.050, 0.036, 0.025, 0.97)
    listBg:SetPoint("TOPLEFT", pane, "TOPLEFT", 17, -114)
    listBg:SetPoint("BOTTOMLEFT", pane, "BOTTOMLEFT", 17, 47)
    listBg:SetWidth(split - 15)
    local rule = plain(pane, "ARTWORK", 0.52, 0.35, 0.15, 0.81)
    rule:SetPoint("TOPLEFT", pane, "TOPLEFT", split + 1, -60)
    rule:SetPoint("BOTTOMLEFT", pane, "BOTTOMLEFT", split + 1, 46)
    rule:SetWidth(1)

    local search = CreateFrame("EditBox", nil, pane, "InputBoxTemplate")
    search:SetSize(leftW, 23)
    search:SetPoint("TOPLEFT", pane, "TOPLEFT", 21, -68)
    search:SetAutoFocus(false)
    search:SetMaxLetters(48)
    if search.SetTextInsets then search:SetTextInsets(6, 6, 0, 0) end
    local hint = label(pane, "Поиск...", "GameFontDisableSmall", 31, 74, leftW - 15, GREY)
    if hint.EnableMouse then hint:EnableMouse(false) end
    label(pane, "ДОСТУПНЫЕ ПОДЗЕМЕЛЬЯ", "GameFontNormalSmall", 21, 100, split - 19, GOLD)

    -- Native WoW ScrollFrame: all dungeons are in one continuous list.
    -- The built-in UIPanelScrollFrameTemplate provides a real scroll bar,
    -- while mouse-wheel scrolling remains usable with the pointer over rows.
    local scroller = CreateFrame("ScrollFrame", "ForeverDungeonListScrollFrame", pane, "UIPanelScrollFrameTemplate")
    scroller:SetPoint("TOPLEFT", pane, "TOPLEFT", 20, -123)
    scroller:SetPoint("BOTTOMLEFT", pane, "BOTTOMLEFT", 20, 53)
    scroller:SetWidth(split - 53)
    scroller:EnableMouseWheel(true)
    local listChild = CreateFrame("Frame", "ForeverDungeonListContent", scroller)
    listChild:SetWidth(split - 53)
    listChild:SetHeight(#DUNGEONS * ROW_HEIGHT)
    scroller:SetScrollChild(listChild)

    for i = 1, #DUNGEONS do
        local row = CreateFrame("Button", nil, listChild)
        row:SetSize(split - 54, ROW_HEIGHT - 1)
        row:SetPoint("TOPLEFT", listChild, "TOPLEFT", 0, -(i - 1) * ROW_HEIGHT)
        row:SetFrameLevel(scroller:GetFrameLevel() + 2)
        local shade = plain(row, "BACKGROUND", 0.11, 0.075, 0.049, 0.58)
        shade:SetAllPoints()
        local rowName = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
        rowName:SetPoint("LEFT", row, "LEFT", 3, 0)
        rowName:SetPoint("RIGHT", row, "RIGHT", -36, 0)
        rowName:SetJustifyH("LEFT")
        local rowLvl = row:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
        rowLvl:SetPoint("RIGHT", row, "RIGHT", -2, 0)
        row.shade, row.title, row.level = shade, rowName, rowLvl
        rows[i] = row
    end

    scroller:SetScript("OnMouseWheel", function(self, delta)
        local range = self:GetVerticalScrollRange() or 0
        local pos = self:GetVerticalScroll() or 0
        self:SetVerticalScroll(math.max(0, math.min(range, pos - delta * ROW_HEIGHT * 3)))
    end)

    local dungeonName = label(pane, "", "GameFontNormalLarge", rightX, 70, rightW, GOLD)
    local region = label(pane, "", "GameFontHighlightSmall", rightX, 100, rightW, GREY)
    border(pane, rightX, 126, rightW, 1)
    local levelText = label(pane, "", "GameFontNormalSmall", rightX, 141, rightW, IVORY)
    local description = label(pane, "", "GameFontHighlightSmall", rightX, 170, rightW, IVORY)
    description:SetJustifyV("TOP")
    local scaling = label(pane, "Уровни противников подстраиваются под персонажа.", "GameFontHighlightSmall", rightX, 226, rightW, GREY)
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
        listChild:SetHeight(math.max(1, #entries * ROW_HEIGHT))
        if scroller.UpdateScrollChildRect then scroller:UpdateScrollChildRect() end
        for i, row in ipairs(rows) do
            local d = entries[i]
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
        scroller:SetVerticalScroll(0)
        update()
    end)
    search:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    search:SetScript("OnEnterPressed", function(self) self:ClearFocus() end)
    solo:SetScript("OnClick", function() requestEntry(false) end)
    together:SetScript("OnClick", function() requestEntry(true) end)

    -- The native right tabs call LFGParentFrame_SetActiveTab(), which sets
    -- host.selectedTab and calls host:UpdateTabs().  Observe that ONE native
    -- update method rather than hooking buttons with different names/views.
    local function syncNativePage()
        if not pane or not portal then return end
        local selected = host.selectedTab == 4
        portal:SetChecked(selected)
        pane:SetShown(selected)
        if selected then
            hideOutdatedUi()
            update()
        end
    end
    hooksecurefunc(host, "UpdateTabs", syncNativePage)

    local function selectDungeon()
        -- Same native path as LFGParentFrame_SetActiveTab(1..3), but index 4.
        PanelTemplates_SetTab(host, 4)
        LFGListingFrame:Hide()
        LFGBrowseFrame:Hide()
        LFGWhoListFrame:Hide()
        host:UpdateTabs()
    end
    if portal.SetCustomOnMouseUpHandler then
        portal:SetCustomOnMouseUpHandler(function(_, button, inside)
            if button == "LeftButton" and inside then selectDungeon() end
        end)
    else
        -- The exact Forever template supports SetCustomOnMouseUpHandler,
        -- but preserve keyboard and mouse activation if a client differs.
        portal:SetScript("OnMouseUp", function(_, button)
            if button == "LeftButton" then selectDungeon() end
        end)
    end

    pane.open = selectDungeon
    pane.close = function() pane:Hide() end
    host:HookScript("OnHide", function() pane:Hide() end)
    pane:Hide()
    hideOutdatedUi()
    update()
    return true
end

local function openNative()
    if not install() then
        -- Forever's stock LFG lives in Blizzard_GroupFinder_VanillaStyle,
        -- not Blizzard_GroupFinder (retail).
        if C_AddOns and C_AddOns.LoadAddOn then
            pcall(C_AddOns.LoadAddOn, "Blizzard_GroupFinder_VanillaStyle")
        elseif LoadAddOn then
            pcall(LoadAddOn, "Blizzard_GroupFinder_VanillaStyle")
        end
    end
    if not install() then
        notice("Штатные вкладки поиска группы ещё не загружены. Откройте «Поиск группы» и повторите /fd.")
        return
    end
    if not host:IsShown() then
        if ShowUIPanel then ShowUIPanel(host) else host:Show() end
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
