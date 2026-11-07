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


-- Integrated version: NO separate dungeon window, movable frame, minimap button
-- or retail LFG queue calls.  This is an in-place panel of the stock LFG window.
local picked = DUNGEONS[1]
local host, pane, tab, refresh
local filterText, visible, page = "", {}, 0
local perPage = 8
local rows = {}
local lastRequest = -100

local function notify(message)
    if DEFAULT_CHAT_FRAME then
        DEFAULT_CHAT_FRAME:AddMessage("|cffffd275[WoW Forever]|r " .. message)
    end
end

local function canRequest()
    if not GetTime then return true end
    if GetTime() - lastRequest < 2 then return false end
    lastRequest = GetTime()
    return true
end

local function sendRequest(mode)
    if not picked or not canRequest() then return end
    local count, raid, leader = partyState()
    if mode == "GROUP" and (count < 2 or count > 5 or raid or not leader) then
        notify("Для входа группой нужен лидер обычной группы из 2–5 игроков.")
        return
    end
    local name = UnitName("player")
    if not name then return end
    local ok
    if mode == "SOLO" then
        ok = sendAddon("SOLO:" .. picked.map, "WHISPER", name)
    else
        ok = sendAddon("GROUP:" .. picked.map, "PARTY")
    end
    if ok == false then
        notify("Не удалось передать запрос на телепортацию.")
    else
        notify("Запрос входа отправлен. Если серверный модуль отключён, перенос не состоится.")
    end
end

-- Prefer a stock Group Finder frame, not the custom full-screen dungeon frame.
-- Classic/Forever UI names differ, so installation is retried after lazy loads.
local function findHost()
    local frame = _G.LFGParentFrame or _G.PVEFrame or _G.GroupFinderFrame
        or _G.LookingForGroupFrame or _G.LFGFrame
    if frame and frame.GetWidth and frame.GetHeight then return frame end
    if _G.LFGListFrame and _G.LFGListFrame.GetParent then
        local parent = _G.LFGListFrame:GetParent()
        return parent or _G.LFGListFrame
    end
end

local function font(parent, text, style, x, y, width, color)
    local obj = parent:CreateFontString(nil, "OVERLAY", style)
    obj:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
    obj:SetWidth(width)
    obj:SetJustifyH("LEFT")
    obj:SetText(text or "")
    if color then obj:SetTextColor(color[1], color[2], color[3]) end
    return obj
end

-- Lua 5.1 string.lower only handles ASCII in WoW; fold Russian UTF-8
-- as well so searching "зул" matches "Зул'Фаррак".
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

local GOLD = {1, 0.82, 0.19}
local IVORY = {0.93, 0.88, 0.76}
local MUTED = {0.69, 0.71, 0.74}

local function decorate(frame)
    if frame.SetBackdrop then
        frame:SetBackdrop({
            bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background",
            edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border",
            tile = true, tileSize = 32, edgeSize = 22,
            insets = { left = 9, right = 9, top = 9, bottom = 9 },
        })
        frame:SetBackdropColor(0.05, 0.035, 0.025, 1)
    else
        local bg = frame:CreateTexture(nil, "BACKGROUND")
        bg:SetAllPoints()
        bg:SetTexture("Interface\\DialogFrame\\UI-DialogBox-Background")
    end
end

local function install()
    if tab then return true end
    local root = findHost()
    if not root or not root.CreateTexture then return false end
    if root.GetWidth and root:GetWidth() < 330 then return false end
    host = root

    tab = CreateFrame("CheckButton", "ForeverDungeonPortalTab", host)
    tab:SetSize(43, 43)
    tab:SetFrameLevel(host:GetFrameLevel() + 30)
    tab:RegisterForClicks("LeftButtonUp")
    tab:SetHitRectInsets(0, 0, 0, 0)
    local icon = tab:CreateTexture(nil, "ARTWORK")
    icon:SetPoint("TOPLEFT", 5, -5)
    icon:SetPoint("BOTTOMRIGHT", -5, 5)
    icon:SetTexture("Interface\\Icons\\Spell_Arcane_PortalStormWind")
    icon:SetTexCoord(0.08, 0.92, 0.08, 0.92)
    local outline = tab:CreateTexture(nil, "OVERLAY")
    outline:SetAllPoints()
    outline:SetTexture("Interface\\Buttons\\UI-Quickslot2")
    local glow = tab:CreateTexture(nil, "OVERLAY")
    glow:SetPoint("TOPLEFT", -8, 8)
    glow:SetPoint("BOTTOMRIGHT", 8, -8)
    glow:SetTexture("Interface\\Buttons\\UI-ActionButton-Border")
    glow:SetBlendMode("ADD")
    glow:SetVertexColor(1, 0.72, 0.10)
    glow:Hide()

    -- Slot between the damage and guide role icons on Classic's LFG row.
    -- Fall back to the same row's proportional position on other UIs.
    local damage = _G.LFGListFrameRoleButtonDPS or _G.LFGFrameRoleCheckButtonDPS
        or _G.LFDQueueFrameRoleButtonDPS or _G.LFGListFrameRoleButtonDamage
    local guide = _G.LFGListFrameRoleButtonGuide or _G.LFGFrameRoleCheckButtonGuide
        or _G.LFDQueueFrameRoleButtonGuide
    if damage and guide and damage.GetCenter and guide.GetCenter then
        local dx, dy = damage:GetCenter()
        local gx, gy = guide:GetCenter()
        if dx and gx and dy and gy and gx > dx and gx - dx > 57 then
            tab:SetPoint("CENTER", damage, "CENTER", (gx - dx) / 2, (gy - dy) / 2)
        end
    end
    if not tab:GetNumPoints() or tab:GetNumPoints() == 0 then
        tab:SetPoint("TOPLEFT", host, "TOPLEFT", math.max(290, math.min(355, math.floor(host:GetWidth() * 0.745))), -78)
    end

    tab:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
        GameTooltip:AddLine("Вход в подземелье", 1, 0.82, 0.19)
        GameTooltip:AddLine("Соло или готовой группой, без очереди", 0.93, 0.88, 0.76)
        GameTooltip:Show()
    end)
    tab:SetScript("OnLeave", function() GameTooltip:Hide() end)

    -- All finder content stays INSIDE its parent and below the native role row.
    pane = CreateFrame("Frame", "ForeverDungeonFinderPane", host)
    pane:SetPoint("TOPLEFT", host, "TOPLEFT", 20, -166)
    pane:SetPoint("BOTTOMRIGHT", host, "BOTTOMRIGHT", -19, 51)
    pane:SetFrameLevel(host:GetFrameLevel() + 22)
    pane:EnableMouse(true)
    pane:EnableMouseWheel(true)
    decorate(pane)
    pane:Hide()

    -- Column sizes are based on the stock 470-wide Group Finder layout.
    local splitX = math.floor(math.max(345, host:GetWidth() - 40) * 0.46)
    local leftW = splitX - 24
    local rightX = splitX + 15
    local rightW = math.max(145, host:GetWidth() - 68 - rightX)

    local search = CreateFrame("EditBox", nil, pane, "InputBoxTemplate")
    search:SetSize(leftW, 24)
    search:SetPoint("TOPLEFT", 19, -18)
    search:SetAutoFocus(false)
    search:SetMaxLetters(48)
    if search.SetTextInsets then search:SetTextInsets(6, 6, 0, 0) end
    local searchHint = font(pane, "Поиск...", "GameFontDisableSmall", 29, -25, leftW - 20, MUTED)
    if searchHint.EnableMouse then searchHint:EnableMouse(false) end

    font(pane, "ПОДЗЕМЕЛЬЯ", "GameFontNormalSmall", 20, -54, leftW, GOLD)
    local divider = pane:CreateTexture(nil, "ARTWORK")
    divider:SetTexture("Interface\\Buttons\\WHITE8X8")
    divider:SetVertexColor(0.53, 0.35, 0.15, 0.75)
    divider:SetPoint("TOPLEFT", pane, "TOPLEFT", splitX, -18)
    divider:SetPoint("BOTTOMLEFT", pane, "BOTTOMLEFT", splitX, 13)
    divider:SetWidth(1)

    for i = 1, perPage do
        local row = CreateFrame("Button", nil, pane)
        row:SetPoint("TOPLEFT", 18, -78 - (i - 1) * 25)
        row:SetSize(leftW + 3, 24)
        row:SetFrameLevel(pane:GetFrameLevel() + 2)
        local bg = row:CreateTexture(nil, "BACKGROUND")
        bg:SetAllPoints()
        bg:SetTexture("Interface\\Buttons\\WHITE8X8")
        local title = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
        title:SetPoint("LEFT", row, "LEFT", 4, 0)
        title:SetPoint("RIGHT", row, "RIGHT", -42, 0)
        title:SetJustifyH("LEFT")
        local level = row:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
        level:SetPoint("RIGHT", row, "RIGHT", -3, 0)
        row.background, row.title, row.level = bg, title, level
        rows[i] = row
    end

    local leftPrev = CreateFrame("Button", nil, pane, "UIPanelButtonTemplate")
    leftPrev:SetSize(64, 23)
    leftPrev:SetPoint("BOTTOMLEFT", 18, 16)
    leftPrev:SetText("Назад")
    local leftNext = CreateFrame("Button", nil, pane, "UIPanelButtonTemplate")
    leftNext:SetSize(64, 23)
    leftNext:SetPoint("LEFT", leftPrev, "RIGHT", 6, 0)
    leftNext:SetText("Далее")

    local detailName = font(pane, "", "GameFontNormalLarge", rightX, -22, rightW, GOLD)
    local detailZone = font(pane, "", "GameFontHighlightSmall", rightX, -53, rightW, MUTED)
    local rule = pane:CreateTexture(nil, "ARTWORK")
    rule:SetTexture("Interface\\Buttons\\WHITE8X8")
    rule:SetVertexColor(0.53, 0.35, 0.15, 0.75)
    rule:SetPoint("TOPLEFT", pane, "TOPLEFT", rightX, -80)
    rule:SetPoint("TOPRIGHT", pane, "TOPRIGHT", -15, -80)
    rule:SetHeight(1)

    local detailRange = font(pane, "", "GameFontNormalSmall", rightX, -95, rightW, IVORY)
    local detailDesc = font(pane, "", "GameFontHighlightSmall", rightX, -125, rightW, IVORY)
    detailDesc:SetJustifyV("TOP")
    local scaling = font(pane, "Уровень противника подстраивается под игрока.", "GameFontHighlightSmall", rightX, -172, rightW, MUTED)
    scaling:SetJustifyV("TOP")

    local party = CreateFrame("Frame", nil, pane)
    party:SetPoint("BOTTOMLEFT", pane, "BOTTOMLEFT", rightX - 4, 77)
    party:SetPoint("BOTTOMRIGHT", pane, "BOTTOMRIGHT", -12, 77)
    party:SetHeight(66)
    decorate(party)
    font(party, "ТЕКУЩИЙ СОСТАВ", "GameFontNormalSmall", 12, -8, rightW - 12, GOLD)
    local partyInfo = font(party, "", "GameFontHighlightSmall", 12, -27, rightW - 15, IVORY)
    partyInfo:SetJustifyV("TOP")

    local solo = CreateFrame("Button", nil, pane, "UIPanelButtonTemplate")
    solo:SetSize(math.max(83, math.floor((rightW - 8) / 2)), 27)
    solo:SetPoint("BOTTOMLEFT", pane, "BOTTOMLEFT", rightX, 23)
    solo:SetText("Войти соло")
    local group = CreateFrame("Button", nil, pane, "UIPanelButtonTemplate")
    group:SetSize(math.max(84, math.floor((rightW - 8) / 2)), 27)
    group:SetPoint("LEFT", solo, "RIGHT", 5, 0)
    group:SetText("Группой")

    local function refreshRows()
        wipe(visible)
        local needle = foldRu(filterText)
        for _, entry in ipairs(DUNGEONS) do
            if needle == "" or string.find(foldRu(entry.name .. " " .. entry.zone), needle, 1, true) then
                table.insert(visible, entry)
            end
        end
        local pages = math.max(1, math.ceil(#visible / perPage))
        page = math.max(0, math.min(page, pages - 1))
        leftPrev:SetEnabled(page > 0)
        leftNext:SetEnabled(page < pages - 1)
        for i, row in ipairs(rows) do
            local entry = visible[page * perPage + i]
            row.data = entry
            if entry then
                row:Show()
                row.title:SetText(entry.name)
                row.level:SetText(entry.range)
                if entry == picked then
                    row.background:SetVertexColor(0.14, 0.27, 0.41, 0.98)
                    row.title:SetTextColor(1, 0.83, 0.29)
                else
                    row.background:SetVertexColor(0.12, 0.08, 0.06, i % 2 == 0 and 0.72 or 0.40)
                    row.title:SetTextColor(0.93, 0.88, 0.76)
                end
            else
                row:Hide()
            end
        end
        detailName:SetText(picked.name)
        detailZone:SetText(picked.zone)
        detailRange:SetText("Исходный уровень: " .. picked.range)
        detailDesc:SetText(picked.desc)

        local count, raid, leader = partyState()
        if raid then
            partyInfo:SetText("Рейд: только одиночный вход.")
        elseif count <= 1 then
            partyInfo:SetText("Без группы. Доступен вход соло.")
        elseif not leader then
            partyInfo:SetText("В группе " .. count .. " чел. Ждём лидера.")
        else
            partyInfo:SetText("Группа " .. count .. " чел. Можно войти вместе.")
        end
        group:SetEnabled(count >= 2 and count <= 5 and not raid and leader)
    end
    refresh = refreshRows

    for i, row in ipairs(rows) do
        row:SetScript("OnClick", function(self)
            if self.data then picked = self.data; refreshRows() end
        end)
        row:SetScript("OnEnter", function(self)
            if self.data and self.data ~= picked then
                self.background:SetVertexColor(0.24, 0.20, 0.12, 0.88)
            end
        end)
        row:SetScript("OnLeave", function() refreshRows() end)
    end
    search:SetScript("OnTextChanged", function(self)
        filterText = self:GetText() or ""
        if filterText == "" then searchHint:Show() else searchHint:Hide() end
        page = 0
        refreshRows()
    end)
    search:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    search:SetScript("OnEnterPressed", function(self) self:ClearFocus() end)
    leftPrev:SetScript("OnClick", function() page = page - 1; refreshRows() end)
    leftNext:SetScript("OnClick", function() page = page + 1; refreshRows() end)
    pane:SetScript("OnMouseWheel", function(_, delta)
        page = page - (delta > 0 and 1 or -1)
        refreshRows()
    end)
    solo:SetScript("OnClick", function() sendRequest("SOLO") end)
    group:SetScript("OnClick", function() sendRequest("GROUP") end)

    local function closePane()
        pane:Hide()
        tab:SetChecked(false)
        glow:Hide()
    end
    local function openPane()
        refreshRows()
        pane:Show()
        tab:SetChecked(true)
        glow:Show()
    end
    tab:SetScript("OnClick", function()
        if pane:IsShown() then closePane() else openPane() end
    end)
    host:HookScript("OnHide", closePane)
    for _, name in ipairs({
        "PVEFrameTab1", "PVEFrameTab2", "PVEFrameTab3",
        "LFGParentFrameTab1", "LFGParentFrameTab2", "LFGParentFrameTab3",
        "GroupFinderFrameGroupButton", "GroupFinderFrameLFGListBrowserButton",
    }) do
        local native = _G[name]
        if native and native.HookScript then
            native:HookScript("OnClick", closePane)
        end
    end
    pane.openPane = openPane
    pane.closePane = closePane
    refreshRows()
    return true
end

local function openNative()
    if not install() then
        -- Blizzard can load GroupFinder lazily; request its frame on demand.
        if C_AddOns and C_AddOns.LoadAddOn then
            pcall(C_AddOns.LoadAddOn, "Blizzard_GroupFinder")
        elseif LoadAddOn then
            pcall(LoadAddOn, "Blizzard_GroupFinder")
        end
    end
    if not install() then
        notify("Откройте стандартное окно «Поиск группы» и попробуйте /fd ещё раз.")
        return
    end
    if not host:IsShown() then
        if PVEFrame_ShowFrame then
            pcall(PVEFrame_ShowFrame, "GroupFinderFrame")
        end
        if not host:IsShown() and ShowUIPanel then
            ShowUIPanel(host)
        end
        if not host:IsShown() then host:Show() end
    end
    pane.openPane()
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
    if event == "PLAYER_LOGIN" then
        registerPrefix()
    end
    if event == "GROUP_ROSTER_UPDATE" then
        if pane and pane:IsShown() and refresh then refresh() end
    else
        install()
    end
end)
if IsLoggedIn and IsLoggedIn() then registerPrefix(); install() end
