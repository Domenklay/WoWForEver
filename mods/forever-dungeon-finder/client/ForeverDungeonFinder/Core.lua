local ADDON_NAME = ...
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
    { map = 189, name = "Монастырь Алого ордена", range = "26–45", zone = "Тирисфальские леса", desc = "Комплекс Алого ордена. На первом этапе используется общий вход карты." },
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

local filtered = {}
local selected
local offset = 0
local ROWS = 12

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

local function partyCount()
    if IsInRaid and IsInRaid() then
        return GetNumGroupMembers and GetNumGroupMembers() or 0, true
    end
    if IsInGroup and IsInGroup() then
        return GetNumGroupMembers and GetNumGroupMembers() or 0, false
    end
    return 1, false
end

local function isLeader()
    if not IsInGroup or not IsInGroup() then
        return true
    end
    return UnitIsGroupLeader and UnitIsGroupLeader("player")
end

local frame = CreateFrame("Frame", "ForeverDungeonFinderFrame", UIParent)
frame:SetSize(780, 530)
frame:SetPoint("CENTER")
frame:SetFrameStrata("DIALOG")
frame:SetClampedToScreen(true)
frame:SetMovable(true)
frame:EnableMouse(true)
frame:RegisterForDrag("LeftButton")
frame:SetScript("OnDragStart", frame.StartMoving)
frame:SetScript("OnDragStop", frame.StopMovingOrSizing)
frame:Hide()

local shadow = frame:CreateTexture(nil, "BACKGROUND")
shadow:SetPoint("TOPLEFT", -5, 5)
shadow:SetPoint("BOTTOMRIGHT", 5, -5)
shadow:SetColorTexture(0, 0, 0, 0.60)

local bg = frame:CreateTexture(nil, "BACKGROUND", nil, 1)
bg:SetAllPoints()
bg:SetColorTexture(0.035, 0.045, 0.060, 0.98)

local header = frame:CreateTexture(nil, "ARTWORK")
header:SetPoint("TOPLEFT", 1, -1)
header:SetPoint("TOPRIGHT", -1, -1)
header:SetHeight(58)
header:SetColorTexture(0.055, 0.075, 0.105, 1)

local divider = frame:CreateTexture(nil, "ARTWORK")
divider:SetPoint("TOPLEFT", 292, -68)
divider:SetPoint("BOTTOMLEFT", 292, 20)
divider:SetWidth(1)
divider:SetColorTexture(0.20, 0.27, 0.35, 0.8)

local title = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
title:SetPoint("TOPLEFT", 24, -17)
title:SetText("Поиск подземелий")
title:SetTextColor(0.90, 0.95, 1.00)

local subtitle = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
subtitle:SetPoint("TOPLEFT", title, "BOTTOMLEFT", 0, -3)
subtitle:SetText("WoW Forever • мгновенный вход без очереди")
subtitle:SetTextColor(0.48, 0.62, 0.78)

local close = CreateFrame("Button", nil, frame, "UIPanelCloseButton")
close:SetPoint("TOPRIGHT", -7, -7)

local search = CreateFrame("EditBox", nil, frame, "InputBoxTemplate")
search:SetSize(244, 28)
search:SetPoint("TOPLEFT", 22, -79)
search:SetAutoFocus(false)
search:SetMaxLetters(40)
search:SetTextInsets(8, 8, 0, 0)

local searchHint = frame:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
searchHint:SetPoint("LEFT", search, "LEFT", 9, 0)
searchHint:SetText("Поиск...")
searchHint:SetTextColor(0.42, 0.48, 0.55)

local listCaption = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
listCaption:SetPoint("TOPLEFT", 24, -116)
listCaption:SetText("ДОСТУПНЫЕ ПОДЗЕМЕЛЬЯ")
listCaption:SetTextColor(0.48, 0.62, 0.78)

local rows = {}
for i = 1, ROWS do
    local row = CreateFrame("Button", nil, frame)
    row:SetSize(252, 30)
    row:SetPoint("TOPLEFT", 20, -137 - ((i - 1) * 31))

    row.bg = row:CreateTexture(nil, "BACKGROUND")
    row.bg:SetAllPoints()
    row.bg:SetColorTexture(0.055, 0.070, 0.090, i % 2 == 0 and 0.75 or 0.48)

    row.name = row:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    row.name:SetPoint("LEFT", 9, 2)
    row.name:SetPoint("RIGHT", -58, 2)
    row.name:SetJustifyH("LEFT")
    row.name:SetTextColor(0.88, 0.91, 0.94)

    row.level = row:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
    row.level:SetPoint("RIGHT", -8, 0)
    row.level:SetTextColor(0.50, 0.60, 0.70)

    row:SetScript("OnEnter", function(self)
        self.bg:SetColorTexture(0.11, 0.18, 0.26, 0.95)
    end)
    row:SetScript("OnLeave", function(self)
        local active = self.data and selected == self.data
        if active then
            self.bg:SetColorTexture(0.10, 0.24, 0.36, 0.95)
        else
            self.bg:SetColorTexture(0.055, 0.070, 0.090, i % 2 == 0 and 0.75 or 0.48)
        end
    end)
    rows[i] = row
end

local up = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
up:SetSize(30, 22)
up:SetPoint("BOTTOMLEFT", 205, 27)
up:SetText("▲")

local down = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
down:SetSize(30, 22)
down:SetPoint("LEFT", up, "RIGHT", 4, 0)
down:SetText("▼")

local detailTitle = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalHuge")
detailTitle:SetPoint("TOPLEFT", 320, -91)
detailTitle:SetPoint("RIGHT", -28, 0)
detailTitle:SetJustifyH("LEFT")
detailTitle:SetText("Выберите подземелье")
detailTitle:SetTextColor(0.92, 0.96, 1.00)

local detailZone = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
detailZone:SetPoint("TOPLEFT", detailTitle, "BOTTOMLEFT", 0, -9)
detailZone:SetTextColor(0.47, 0.66, 0.84)

local line = frame:CreateTexture(nil, "ARTWORK")
line:SetPoint("TOPLEFT", 320, -150)
line:SetPoint("TOPRIGHT", -30, -150)
line:SetHeight(1)
line:SetColorTexture(0.20, 0.27, 0.35, 0.8)

local levelLabel = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
levelLabel:SetPoint("TOPLEFT", 320, -174)
levelLabel:SetText("Исходный диапазон:")
levelLabel:SetTextColor(0.62, 0.68, 0.74)

local levelValue = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
levelValue:SetPoint("LEFT", levelLabel, "RIGHT", 8, 0)
levelValue:SetTextColor(0.84, 0.90, 0.96)

local scaling = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
scaling:SetPoint("TOPLEFT", 320, -205)
scaling:SetText("Уровень врагов масштабируется персонально под каждого игрока.")
scaling:SetTextColor(0.48, 0.76, 0.94)
scaling:SetWidth(420)
scaling:SetJustifyH("LEFT")

local desc = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
desc:SetPoint("TOPLEFT", 320, -246)
desc:SetWidth(420)
desc:SetJustifyH("LEFT")
desc:SetJustifyV("TOP")
desc:SetTextColor(0.72, 0.76, 0.80)

local groupPanel = frame:CreateTexture(nil, "BACKGROUND", nil, 2)
groupPanel:SetPoint("BOTTOMLEFT", 315, 86)
groupPanel:SetPoint("BOTTOMRIGHT", -25, 86)
groupPanel:SetHeight(82)
groupPanel:SetColorTexture(0.050, 0.065, 0.085, 0.95)

local groupTitle = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
groupTitle:SetPoint("TOPLEFT", groupPanel, "TOPLEFT", 14, -12)
groupTitle:SetText("ТЕКУЩИЙ СОСТАВ")
groupTitle:SetTextColor(0.48, 0.62, 0.78)

local groupInfo = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
groupInfo:SetPoint("TOPLEFT", groupTitle, "BOTTOMLEFT", 0, -9)
groupInfo:SetPoint("RIGHT", groupPanel, "RIGHT", -14, 0)
groupInfo:SetJustifyH("LEFT")
groupInfo:SetTextColor(0.84, 0.87, 0.90)

local enter = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
enter:SetSize(210, 38)
enter:SetPoint("BOTTOMRIGHT", -25, 28)
enter:SetText("Войти сейчас")

local note = frame:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
note:SetPoint("RIGHT", enter, "LEFT", -14, 0)
note:SetPoint("LEFT", 320, 0)
note:SetJustifyH("RIGHT")
note:SetText("Без очереди и подбора игроков")
note:SetTextColor(0.45, 0.50, 0.56)

local function refreshGroup()
    local count, raid = partyCount()
    if raid then
        groupInfo:SetText("Рейдовая группа не поддерживается для прямого входа.")
        enter:Disable()
        enter:SetText("Недоступно для рейда")
        return
    end

    if count <= 1 then
        groupInfo:SetText("Соло • будет создан ваш экземпляр подземелья")
        enter:SetEnabled(selected ~= nil)
        enter:SetText("Войти соло")
        return
    end

    if not isLeader() then
        groupInfo:SetText(string.format("Группа: %d игроков • вход запускает только лидер", count))
        enter:Disable()
        enter:SetText("Ожидание лидера")
        return
    end

    groupInfo:SetText(string.format("Группа: %d игроков • вся текущая группа войдёт вместе", count))
    enter:SetEnabled(selected ~= nil)
    enter:SetText(string.format("Войти группой (%d)", count))
end

local function refreshDetails()
    if not selected then
        detailTitle:SetText("Выберите подземелье")
        detailZone:SetText("")
        levelValue:SetText("—")
        desc:SetText("Выберите подземелье слева. Поиск группы не запускается — вход происходит сразу для вас или вашей текущей группы.")
    else
        detailTitle:SetText(selected.name)
        detailZone:SetText(selected.zone)
        levelValue:SetText(selected.range)
        desc:SetText(selected.desc)
    end
    refreshGroup()
end

local function refreshRows()
    local maxOffset = math.max(0, #filtered - ROWS)
    if offset > maxOffset then offset = maxOffset end
    if offset < 0 then offset = 0 end

    for i, row in ipairs(rows) do
        local data = filtered[offset + i]
        row.data = data
        if data then
            row:Show()
            row.name:SetText(data.name)
            row.level:SetText(data.range)
            if selected == data then
                row.bg:SetColorTexture(0.10, 0.24, 0.36, 0.95)
            else
                row.bg:SetColorTexture(0.055, 0.070, 0.090, i % 2 == 0 and 0.75 or 0.48)
            end
            row:SetScript("OnClick", function(self)
                selected = self.data
                refreshRows()
                refreshDetails()
            end)
        else
            row:Hide()
        end
    end

    up:SetEnabled(offset > 0)
    down:SetEnabled(offset < maxOffset)
end

local function applyFilter()
    wipe(filtered)
    local query = string.lower(search:GetText() or "")
    for _, dungeon in ipairs(DUNGEONS) do
        local haystack = string.lower(dungeon.name .. " " .. dungeon.zone)
        if query == "" or string.find(haystack, query, 1, true) then
            table.insert(filtered, dungeon)
        end
    end
    offset = 0
    refreshRows()
end

search:SetScript("OnTextChanged", function(self)
    searchHint:SetShown((self:GetText() or "") == "")
    applyFilter()
end)
search:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
search:SetScript("OnEnterPressed", function(self) self:ClearFocus() end)

up:SetScript("OnClick", function()
    offset = math.max(0, offset - 1)
    refreshRows()
end)
down:SetScript("OnClick", function()
    offset = math.min(math.max(0, #filtered - ROWS), offset + 1)
    refreshRows()
end)

frame:EnableMouseWheel(true)
frame:SetScript("OnMouseWheel", function(_, delta)
    if delta > 0 then
        offset = math.max(0, offset - 2)
    else
        offset = math.min(math.max(0, #filtered - ROWS), offset + 2)
    end
    refreshRows()
end)

enter:SetScript("OnClick", function()
    if not selected then return end

    if IsInRaid and IsInRaid() then
        return
    end

    local payload = "ENTER:" .. tostring(selected.map)
    if IsInGroup and IsInGroup() then
        if not isLeader() then return end
        sendAddon(payload, "PARTY")
    else
        local playerName = UnitName("player")
        if playerName then
            sendAddon(payload, "WHISPER", playerName)
        end
    end
end)

frame:SetScript("OnShow", function()
    refreshGroup()
end)

local eventFrame = CreateFrame("Frame")
eventFrame:RegisterEvent("PLAYER_LOGIN")
eventFrame:RegisterEvent("GROUP_ROSTER_UPDATE")
eventFrame:SetScript("OnEvent", function(_, event)
    if event == "PLAYER_LOGIN" then
        registerPrefix()
    elseif event == "GROUP_ROSTER_UPDATE" and frame:IsShown() then
        refreshGroup()
    end
end)

SLASH_FOREVERDUNGEONFINDER1 = "/fd"
SLASH_FOREVERDUNGEONFINDER2 = "/dungeon"
SlashCmdList.FOREVERDUNGEONFINDER = function()
    if frame:IsShown() then
        frame:Hide()
    else
        frame:Show()
        search:ClearFocus()
    end
end

local minimap = CreateFrame("Button", "ForeverDungeonFinderMinimapButton", Minimap)
minimap:SetSize(32, 32)
minimap:SetFrameStrata("MEDIUM")
minimap:SetPoint("TOPLEFT", Minimap, "TOPLEFT", -2, -4)
minimap:RegisterForClicks("LeftButtonUp")

local miniBg = minimap:CreateTexture(nil, "BACKGROUND")
miniBg:SetAllPoints()
miniBg:SetTexture("Interface\\Minimap\\MiniMap-TrackingBorder")

local miniIcon = minimap:CreateTexture(nil, "ARTWORK")
miniIcon:SetSize(18, 18)
miniIcon:SetPoint("CENTER", 0, 1)
miniIcon:SetTexture("Interface\\Icons\\INV_Misc_Map_01")
miniIcon:SetTexCoord(0.08, 0.92, 0.08, 0.92)

minimap:SetScript("OnClick", function()
    SlashCmdList.FOREVERDUNGEONFINDER()
end)
minimap:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_LEFT")
    GameTooltip:AddLine("Поиск подземелий", 0.90, 0.95, 1.00)
    GameTooltip:AddLine("Соло или текущая группа — без очереди.", 0.70, 0.76, 0.82)
    GameTooltip:Show()
end)
minimap:SetScript("OnLeave", function() GameTooltip:Hide() end)

for _, dungeon in ipairs(DUNGEONS) do
    table.insert(filtered, dungeon)
end
selected = filtered[1]
refreshRows()
refreshDetails()
