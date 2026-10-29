local ADDON = ...
local REQUEST = "FEC1"
local RESPONSE = "FER1"
local SERVER_TARGET = "SERVER"

local frame
local db
local current = 1
local Draw
local dynamic = {}
local tabButtons = {}
local statusText
local statsText
local zoneText
local selectedCatalog = 1
local selectedLocation = 1
local selectedTalent = 1
local selectedAppearance = 1

local state = {
    total = 0,
    creatures = 0,
    items = 0,
    zones = 0,
    knowledgeTotal = 0,
    knowledgeSpent = 0,
    knowledgeAvailable = 0,
    rewardedDiscoveries = 0,
    map = 0,
    zone = 0,
    area = 0,
    online = false,
    recent = { [1] = {}, [2] = {}, [3] = {} },
    recentLoaded = { [1] = false, [2] = false, [3] = false },
    catalog = {},
    catalogLoaded = false,
    catalogZone = 0,
    catalogPage = 1,
    catalogPages = 1,
    catalogTotal = 0,
    catalogKnown = 0,
}

local lastStatus = 0
local waiting = false
local retriedSelf = false

local CREATURE_TYPES = {
    [1] = "Зверь", [2] = "Драконид", [3] = "Демон", [4] = "Элементаль",
    [5] = "Великан", [6] = "Нежить", [7] = "Гуманоид", [8] = "Существо",
    [9] = "Механизм", [10] = "Существо", [11] = "Тотем", [12] = "Спутник",
}

local CLASSIFICATIONS = {
    [1] = "Элита", [2] = "Редкая элита", [3] = "Мировой босс", [4] = "Редкий",
}

local TALENTS = {
    { "Защита", "Щиты и снижение входящего урона.", "Щит спутника ограничен 30% максимального здоровья владельца." },
    { "Исцеление", "Автоматическая помощь владельцу и малой группе.", "Базовый предел лечения 25% HP, талантами повышается до 40%." },
    { "Усиление", "Короткие полезные PvE-эффекты.", "Эта ветка будет подключена после базовых защитных способностей." },
    { "Мудрость", "Запас и восстановление маны спутника.", "Регенерация: +1 маны/5 сек в бою, +5 маны/5 сек вне боя." },
    { "Познание", "Бонусы за заполнение энциклопедии.", "Прогресс ветки будет связан с открытыми существами и локациями." },
}

local APPEARANCES = {
    { "Живая книга", "Базовый облик", true },
    { "Архивариус", "Награда за коллекцию", false },
    { "Дух знаний", "Редкое событие", false },
    { "Малый конструкт", "Особый торговец", false },
    { "Хранитель рун", "Достижение", false },
    { "???", "Неизвестный источник", false },
}

local function chat(msg)
    if DEFAULT_CHAT_FRAME then
        DEFAULT_CHAT_FRAME:AddMessage("|cff66ccff[Энциклопедия]|r " .. tostring(msg))
    end
end

local function later(delay, fn)
    if C_Timer and C_Timer.After then C_Timer.After(delay, fn) else fn() end
end

local function registerPrefixes()
    if C_ChatInfo and C_ChatInfo.RegisterAddonMessagePrefix then
        pcall(C_ChatInfo.RegisterAddonMessagePrefix, REQUEST)
        pcall(C_ChatInfo.RegisterAddonMessagePrefix, RESPONSE)
    end
end

local function sendRaw(payload, target, quiet)
    if not C_ChatInfo or not C_ChatInfo.SendAddonMessage then
        if not quiet then chat("Клиент не поддерживает addon-сообщения.") end
        return false
    end
    registerPrefixes()
    local ok, result = pcall(C_ChatInfo.SendAddonMessage, REQUEST, payload, "WHISPER", target or SERVER_TARGET)
    if not ok then
        if not quiet then chat("Не удалось отправить запрос серверу: " .. tostring(result)) end
        return false
    end
    return result ~= false
end

local function requestStatus(quiet)
    local ok = sendRaw("status", SERVER_TARGET, quiet)
    if ok then
        lastStatus = GetTime and GetTime() or 0
        waiting = true
        retriedSelf = false
    end
    return ok
end

local function requestRecent(kind, quiet)
    if kind < 1 or kind > 3 then return false end
    state.recent[kind] = {}
    state.recentLoaded[kind] = false
    return sendRaw("recent " .. tostring(kind), SERVER_TARGET, quiet)
end

local function requestCatalog(page, quiet)
    page = tonumber(page) or 1
    if page < 1 then page = 1 end
    state.catalog = {}
    state.catalogLoaded = false
    selectedCatalog = 1
    if Draw then Draw() end
    return sendRaw("catalog " .. tostring(page), SERVER_TARGET, quiet)
end

local function currentZoneName()
    local zone = GetRealZoneText and GetRealZoneText() or ""
    if zone and zone ~= "" then return zone end
    return state.zone > 0 and ("Зона " .. tostring(state.zone)) or "Неизвестная зона"
end

local function areaName(id)
    if C_Map and C_Map.GetAreaInfo then
        local ok, name = pcall(C_Map.GetAreaInfo, id)
        if ok and name and name ~= "" then return name end
    end
    if GetAreaInfo then
        local ok, name = pcall(GetAreaInfo, id)
        if ok and name and name ~= "" then return name end
    end
    return nil
end

local function addDynamic(object)
    dynamic[#dynamic + 1] = object
    return object
end

local function clearDynamic()
    for _, object in ipairs(dynamic) do object:Hide() end
    wipe(dynamic)
end

local function makePanel(parent, x, y, w, h, alpha)
    local p = addDynamic(CreateFrame("Frame", nil, parent or frame))
    p:SetPoint("TOPLEFT", parent or frame, "TOPLEFT", x, y)
    p:SetSize(w, h)
    local bg = p:CreateTexture(nil, "BACKGROUND")
    bg:SetAllPoints()
    bg:SetColorTexture(0.035, 0.043, 0.052, alpha or 0.92)
    local border = p:CreateTexture(nil, "BORDER")
    border:SetPoint("TOPLEFT", p, "TOPLEFT", 0, 0)
    border:SetPoint("TOPRIGHT", p, "TOPRIGHT", 0, 0)
    border:SetHeight(1)
    border:SetColorTexture(0.16, 0.43, 0.55, 0.85)
    return p
end

local function makeText(parent, x, y, w, text, font, r, g, b, justify)
    local t = parent:CreateFontString(nil, "OVERLAY", font or "GameFontHighlight")
    t:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
    if w then t:SetWidth(w) end
    t:SetJustifyH(justify or "LEFT")
    t:SetText(text or "")
    if r then t:SetTextColor(r, g, b) end
    return t
end

local function makeButton(parent, x, y, w, h, label, callback, active)
    local b = addDynamic(CreateFrame("Button", nil, parent or frame))
    b:SetPoint("TOPLEFT", parent or frame, "TOPLEFT", x, y)
    b:SetSize(w, h)
    local bg = b:CreateTexture(nil, "BACKGROUND")
    bg:SetAllPoints()
    if active then bg:SetColorTexture(0.08, 0.26, 0.34, 0.95)
    else bg:SetColorTexture(0.055, 0.065, 0.078, 0.94) end
    local line = b:CreateTexture(nil, "BORDER")
    line:SetPoint("BOTTOMLEFT", b, "BOTTOMLEFT", 0, 0)
    line:SetPoint("BOTTOMRIGHT", b, "BOTTOMRIGHT", 0, 0)
    line:SetHeight(active and 2 or 1)
    if active then line:SetColorTexture(0.22, 0.70, 0.88, 1)
    else line:SetColorTexture(0.12, 0.20, 0.24, 0.8) end
    local text = b:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    text:SetPoint("CENTER", b, "CENTER", 0, 0)
    text:SetText(label or "")
    if active then text:SetTextColor(0.78, 0.94, 1.0)
    else text:SetTextColor(0.80, 0.83, 0.86) end
    b:SetScript("OnEnter", function()
        if not active then bg:SetColorTexture(0.075, 0.10, 0.12, 0.98) end
    end)
    b:SetScript("OnLeave", function()
        if not active then bg:SetColorTexture(0.055, 0.065, 0.078, 0.94) end
    end)
    b:SetScript("OnClick", callback)
    return b
end

local function updateHeader()
    if not frame then return end
    if statusText then
        if state.online then
            statusText:SetText("●  Архив синхронизирован")
            statusText:SetTextColor(0.36, 0.88, 0.58)
        else
            statusText:SetText("●  Нет связи с архивом")
            statusText:SetTextColor(0.92, 0.40, 0.40)
        end
    end
    if zoneText then zoneText:SetText(currentZoneName()) end
    if statsText then
        statsText:SetText(string.format("Знания  %d     Существа  %d     Предметы  %d     Локации  %d",
            state.knowledgeAvailable, state.creatures, state.items, state.zones))
    end
    for i, button in ipairs(tabButtons) do
        if button._label then
            if i == current then button._label:SetTextColor(0.68, 0.91, 1.0)
            else button._label:SetTextColor(0.72, 0.74, 0.77) end
        end
        if button._line then
            if i == current then button._line:SetColorTexture(0.20, 0.67, 0.86, 1)
            else button._line:SetColorTexture(0.08, 0.10, 0.12, 0) end
        end
    end
end

local function creatureMeta(rec)
    if not rec or not rec.known then return "Неизвестное существо" end
    local typeName = CREATURE_TYPES[rec.creatureType] or "Существо"
    local className = CLASSIFICATIONS[rec.classification]
    if className then return typeName .. "  •  " .. className end
    return typeName
end

local function drawProgress(parent, x, y, w, known, total)
    local pct = total > 0 and math.floor(known * 100 / total) or 0
    local text = makeText(parent, x, y, w, string.format("Изучено %d из %d  •  %d%%", known, total, pct), "GameFontNormalSmall", 0.62, 0.78, 0.85)
    local track = parent:CreateTexture(nil, "BACKGROUND")
    track:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y - 19)
    track:SetSize(w, 6)
    track:SetColorTexture(0.075, 0.085, 0.095, 1)
    local fill = parent:CreateTexture(nil, "ARTWORK")
    fill:SetPoint("LEFT", track, "LEFT", 0, 0)
    local fillWidth = total > 0 and math.floor(w * known / total) or 0
    fill:SetSize(math.max(1, fillWidth), 6)
    fill:SetColorTexture(0.16, 0.55, 0.70, fillWidth > 0 and 1 or 0)
    return text
end

local function drawCreatures()
    local left = makePanel(frame, 24, -128, 330, 392, 0.95)
    local right = makePanel(frame, 366, -128, 490, 392, 0.95)

    makeText(left, 16, -16, 295, currentZoneName(), "GameFontHighlightLarge", 0.80, 0.93, 1.0)
    if state.catalogLoaded then
        drawProgress(left, 16, -46, 298, state.catalogKnown, state.catalogTotal)
    else
        makeText(left, 16, -48, 295, "Получаю список существ…", "GameFontNormalSmall", 0.56, 0.68, 0.74)
    end

    if state.catalogLoaded and #state.catalog == 0 then
        makeText(left, 16, -105, 295, "В этой зоне пока не найдено постоянных существ.", "GameFontNormal", 0.68, 0.73, 0.77)
        makeText(left, 16, -137, 295, "После обновления каталога сервер повторно проверит реальные координаты спавнов.", "GameFontNormalSmall", 0.48, 0.56, 0.61)
    elseif state.catalogLoaded then
        local startY = -86
        for i, rec in ipairs(state.catalog) do
            local active = i == selectedCatalog
            local row = makeButton(left, 12, startY - (i - 1) * 34, 306, 30,
                rec.known and ((rec.name ~= "" and rec.name) or "Открытая запись") or "???",
                function() selectedCatalog = i; Draw() end, active)
            local mark = row:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
            mark:SetPoint("RIGHT", row, "RIGHT", -9, 0)
            mark:SetText(rec.known and "✓" or "?")
            if rec.known then mark:SetTextColor(0.35, 0.85, 0.62)
            else mark:SetTextColor(0.42, 0.46, 0.50) end
        end
    end

    makeText(left, 105, -356, 120,
        string.format("%d / %d", state.catalogPage, state.catalogPages),
        "GameFontNormalSmall", 0.52, 0.62, 0.68, "CENTER")
    local prev = makeButton(left, 12, -346, 82, 28, "Назад", function()
        if state.catalogPage > 1 then requestCatalog(state.catalogPage - 1, false) end
    end, false)
    local nextb = makeButton(left, 236, -346, 82, 28, "Далее", function()
        if state.catalogPage < state.catalogPages then requestCatalog(state.catalogPage + 1, false) end
    end, false)
    if state.catalogPage <= 1 then prev:Disable() end
    if state.catalogPage >= state.catalogPages then nextb:Disable() end

    local rec = state.catalog[selectedCatalog]
    if not state.catalogLoaded then
        makeText(right, 28, -28, 420, "Бестиарий", "GameFontHighlightLarge", 0.82, 0.93, 1.0)
        makeText(right, 28, -72, 420, "Синхронизация с архивом…", "GameFontNormal", 0.58, 0.68, 0.74)
        return
    end

    if not rec then
        makeText(right, 28, -28, 420, "Бестиарий", "GameFontHighlightLarge", 0.82, 0.93, 1.0)
        makeText(right, 28, -72, 420, "Выберите запись слева.", "GameFontNormal", 0.58, 0.68, 0.74)
        return
    end

    if rec.known then
        makeText(right, 28, -28, 430, rec.name ~= "" and rec.name or "Открытая запись", "GameFontHighlightLarge", 0.86, 0.95, 1.0)
        makeText(right, 28, -62, 430, creatureMeta(rec), "GameFontNormal", 0.48, 0.76, 0.86)
        local seal = makePanel(right, 28, -103, 118, 118, 0.68)
        makeText(seal, 0, -35, 118, "✓", "GameFontHighlightLarge", 0.32, 0.84, 0.62, "CENTER")
        makeText(right, 174, -108, 270, "Запись открыта", "GameFontHighlight", 0.74, 0.91, 0.98)
        makeText(right, 174, -137, 270, "Встречается: " .. currentZoneName(), "GameFontNormal", 0.68, 0.72, 0.76)
        makeText(right, 174, -166, 270, "Первое открытие сохранено для всего аккаунта.", "GameFontNormalSmall", 0.50, 0.58, 0.63)
        makeText(right, 28, -252, 430, "Наблюдения", "GameFontHighlight", 0.72, 0.88, 0.96)
        makeText(right, 28, -281, 430, "Позже здесь появятся способности, сопротивления, полезный лут и заметки об особенностях существа.", "GameFontNormal", 0.62, 0.68, 0.72)
    else
        makeText(right, 28, -28, 430, "???", "GameFontHighlightLarge", 0.62, 0.66, 0.70)
        makeText(right, 28, -62, 430, "Неизвестное существо", "GameFontNormal", 0.46, 0.52, 0.56)
        local mystery = makePanel(right, 28, -103, 430, 146, 0.60)
        makeText(mystery, 0, -50, 430, "?", "GameFontHighlightLarge", 0.30, 0.42, 0.48, "CENTER")
        makeText(right, 28, -278, 430, "Победите это существо, чтобы открыть его запись.", "GameFontHighlight", 0.70, 0.76, 0.80)
        makeText(right, 28, -309, 430, "До открытия архив не раскрывает имя и сведения о нём.", "GameFontNormalSmall", 0.48, 0.56, 0.61)
    end
end

local function drawLocations()
    local left = makePanel(frame, 24, -128, 330, 392, 0.95)
    local right = makePanel(frame, 366, -128, 490, 392, 0.95)
    makeText(left, 16, -16, 295, "Изученные локации", "GameFontHighlightLarge", 0.80, 0.93, 1.0)
    makeText(left, 16, -48, 295, "Последние открытия аккаунта", "GameFontNormalSmall", 0.52, 0.63, 0.69)

    local records = state.recent[3] or {}
    if not state.recentLoaded[3] then
        makeText(left, 16, -92, 295, "Получаю список…", "GameFontNormal", 0.62, 0.68, 0.72)
    elseif #records == 0 then
        makeText(left, 16, -92, 295, "Пока нет сохранённых локаций.", "GameFontNormal", 0.62, 0.68, 0.72)
    else
        for i = 1, math.min(#records, 8) do
            local rec = records[i]
            local title = areaName(rec.entry) or ("Локация " .. tostring(rec.entry))
            makeButton(left, 12, -78 - (i - 1) * 34, 306, 30, title,
                function() selectedLocation = i; Draw() end, i == selectedLocation)
        end
    end

    local rec = records[selectedLocation]
    local title = rec and (areaName(rec.entry) or "Изученная локация") or currentZoneName()
    makeText(right, 28, -28, 430, title, "GameFontHighlightLarge", 0.86, 0.95, 1.0)
    makeText(right, 28, -62, 430, "Архив исследования мира", "GameFontNormal", 0.48, 0.76, 0.86)
    makeText(right, 28, -112, 430, "Локации открываются один раз на аккаунт.", "GameFontHighlight", 0.72, 0.84, 0.90)
    makeText(right, 28, -145, 430, "За первое посещение новой зоны энциклопедия выдаёт 3 очка знаний.", "GameFontNormal", 0.64, 0.69, 0.73)
    makeText(right, 28, -202, 430, "Текущая зона", "GameFontHighlight", 0.72, 0.88, 0.96)
    makeText(right, 28, -233, 430, currentZoneName(), "GameFontNormal", 0.78, 0.82, 0.85)
end

local function drawTalents()
    local left = makePanel(frame, 24, -128, 260, 392, 0.95)
    local right = makePanel(frame, 296, -128, 560, 392, 0.95)
    makeText(left, 16, -16, 225, "Ветви знаний", "GameFontHighlightLarge", 0.80, 0.93, 1.0)
    makeText(left, 16, -48, 225, "Доступно очков: " .. tostring(state.knowledgeAvailable), "GameFontNormal", 0.48, 0.76, 0.86)
    for i, talent in ipairs(TALENTS) do
        makeButton(left, 12, -82 - (i - 1) * 48, 236, 40, talent[1],
            function() selectedTalent = i; Draw() end, i == selectedTalent)
    end

    local talent = TALENTS[selectedTalent] or TALENTS[1]
    makeText(right, 30, -30, 490, talent[1], "GameFontHighlightLarge", 0.86, 0.95, 1.0)
    makeText(right, 30, -70, 490, talent[2], "GameFontNormal", 0.62, 0.72, 0.77)
    local node = makePanel(right, 30, -120, 110, 110, 0.65)
    makeText(node, 0, -42, 110, "◇", "GameFontHighlightLarge", 0.28, 0.62, 0.76, "CENTER")
    makeText(right, 170, -126, 340, "Ветка подготавливается", "GameFontHighlight", 0.70, 0.87, 0.95)
    makeText(right, 170, -158, 340, talent[3], "GameFontNormal", 0.62, 0.68, 0.72)
    makeText(right, 30, -268, 490, "Покупка узлов будет включена только вместе с реальными серверными эффектами.", "GameFontNormalSmall", 0.48, 0.55, 0.60)
end

local function drawAppearances()
    local left = makePanel(frame, 24, -128, 520, 392, 0.95)
    local right = makePanel(frame, 556, -128, 300, 392, 0.95)
    makeText(left, 16, -16, 485, "Коллекция обликов", "GameFontHighlightLarge", 0.80, 0.93, 1.0)
    makeText(left, 16, -48, 485, "Облик не влияет на способности спутника.", "GameFontNormalSmall", 0.52, 0.63, 0.69)

    for i, appearance in ipairs(APPEARANCES) do
        local col = (i - 1) % 3
        local row = math.floor((i - 1) / 3)
        local x = 12 + col * 168
        local y = -82 - row * 132
        local b = makeButton(left, x, y, 156, 116, "", function() selectedAppearance = i; Draw() end, i == selectedAppearance)
        local icon = b:CreateFontString(nil, "OVERLAY", "GameFontHighlightLarge")
        icon:SetPoint("TOP", b, "TOP", 0, -20)
        icon:SetText(appearance[3] and "◇" or "?")
        icon:SetTextColor(appearance[3] and 0.38 or 0.35, appearance[3] and 0.70 or 0.39, appearance[3] and 0.82 or 0.43)
        local label = b:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
        label:SetPoint("BOTTOM", b, "BOTTOM", 0, 15)
        label:SetWidth(140)
        label:SetText(appearance[1])
        label:SetTextColor(0.78, 0.82, 0.85)
    end

    local appearance = APPEARANCES[selectedAppearance] or APPEARANCES[1]
    makeText(right, 24, -28, 250, appearance[1], "GameFontHighlightLarge", 0.86, 0.95, 1.0)
    makeText(right, 24, -69, 250, appearance[2], "GameFontNormal", 0.58, 0.68, 0.73)
    local preview = makePanel(right, 24, -112, 252, 150, 0.60)
    makeText(preview, 0, -58, 252, appearance[3] and "◇" or "?", "GameFontHighlightLarge", 0.28, 0.58, 0.70, "CENTER")
    makeText(right, 24, -290, 250, appearance[3] and "Доступен" or "Пока закрыт", "GameFontHighlight", appearance[3] and 0.38 or 0.55, appearance[3] and 0.82 or 0.58, appearance[3] and 0.62 or 0.61)
end

Draw = function()
    if not frame then return end
    clearDynamic()
    updateHeader()
    if current == 1 then drawCreatures()
    elseif current == 2 then drawLocations()
    elseif current == 3 then drawTalents()
    else drawAppearances() end
end

local function refreshCurrent()
    requestStatus(true)
    if current == 1 then
        later(0.25, function() requestCatalog(state.catalogPage or 1, true) end)
    elseif current == 2 then
        later(0.25, function() requestRecent(3, true) end)
    end
end

local function switchTab(index)
    current = index
    if db then db.currentTab = current end
    Draw()
    if current == 1 then
        later(0.15, function() requestCatalog(1, true) end)
    elseif current == 2 then
        later(0.15, function() requestRecent(3, true) end)
    end
end

local function createTab(index, label, x)
    local b = CreateFrame("Button", nil, frame)
    b:SetPoint("TOPLEFT", frame, "TOPLEFT", x, -82)
    b:SetSize(190, 34)
    local bg = b:CreateTexture(nil, "BACKGROUND")
    bg:SetAllPoints()
    bg:SetColorTexture(0.025, 0.03, 0.038, 0.80)
    local text = b:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    text:SetPoint("CENTER", b, "CENTER", 0, 1)
    text:SetText(label)
    local line = b:CreateTexture(nil, "ARTWORK")
    line:SetPoint("BOTTOMLEFT", b, "BOTTOMLEFT", 8, 0)
    line:SetPoint("BOTTOMRIGHT", b, "BOTTOMRIGHT", -8, 0)
    line:SetHeight(2)
    b._label = text
    b._line = line
    b:SetScript("OnClick", function() switchTab(index) end)
    b:SetScript("OnEnter", function() bg:SetColorTexture(0.05, 0.07, 0.085, 0.95) end)
    b:SetScript("OnLeave", function() bg:SetColorTexture(0.025, 0.03, 0.038, 0.80) end)
    tabButtons[index] = b
end

local function CreateUI()
    if frame then return end
    frame = CreateFrame("Frame", "ForeverEncyclopediaFrame", UIParent, "BasicFrameTemplateWithInset")
    frame:SetSize(880, 560)
    frame:SetPoint("CENTER")
    frame:SetMovable(true)
    frame:SetClampedToScreen(true)
    frame:EnableMouse(true)
    frame:RegisterForDrag("LeftButton")
    frame:SetScript("OnDragStart", frame.StartMoving)
    frame:SetScript("OnDragStop", frame.StopMovingOrSizing)
    frame:SetScript("OnShow", refreshCurrent)
    frame:Hide()

    frame.TitleText:SetText("Живая энциклопедия")
    if frame.TitleText.SetTextColor then frame.TitleText:SetTextColor(0.72, 0.90, 0.98) end

    local header = frame:CreateTexture(nil, "BACKGROUND")
    header:SetPoint("TOPLEFT", frame, "TOPLEFT", 10, -34)
    header:SetPoint("TOPRIGHT", frame, "TOPRIGHT", -10, -34)
    header:SetHeight(42)
    header:SetColorTexture(0.022, 0.028, 0.035, 0.94)

    statusText = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    statusText:SetPoint("TOPLEFT", frame, "TOPLEFT", 24, -48)
    statusText:SetWidth(220)
    statusText:SetJustifyH("LEFT")

    statsText = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    statsText:SetPoint("TOP", frame, "TOP", 0, -48)
    statsText:SetWidth(420)
    statsText:SetJustifyH("CENTER")
    statsText:SetTextColor(0.60, 0.70, 0.76)

    zoneText = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    zoneText:SetPoint("TOPRIGHT", frame, "TOPRIGHT", -24, -47)
    zoneText:SetWidth(210)
    zoneText:SetJustifyH("RIGHT")
    zoneText:SetTextColor(0.72, 0.82, 0.88)

    createTab(1, "Существа", 42)
    createTab(2, "Локации", 238)
    createTab(3, "Таланты", 434)
    createTab(4, "Облики", 630)

    local version = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    version:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -18, 15)
    version:SetText("Forever Encyclopedia 0.5")
    version:SetTextColor(0.34, 0.39, 0.43)

    if db and db.uiVersion == 5 then
        current = tonumber(db.currentTab) or 1
    else
        current = 1
        if db then db.uiVersion = 5; db.currentTab = 1 end
    end
    if current < 1 or current > 4 then current = 1 end
    Draw()
end

local function parseResponse(text)
    text = tostring(text or "")

    if text:sub(1, 8) == "CATHEAD|" then
        local _, zone, page, pages, total, known = strsplit("|", text)
        state.catalog = {}
        state.catalogZone = tonumber(zone) or 0
        state.catalogPage = tonumber(page) or 1
        state.catalogPages = tonumber(pages) or 1
        state.catalogTotal = tonumber(total) or 0
        state.catalogKnown = tonumber(known) or 0
        state.catalogLoaded = false
        selectedCatalog = 1
        if current == 1 then Draw() end
        return
    end

    if text:sub(1, 4) == "CAT|" then
        local _, entry, known, creatureType, classification, name = strsplit("|", text)
        state.catalog[#state.catalog + 1] = {
            entry = tonumber(entry) or 0,
            known = tonumber(known) == 1,
            creatureType = tonumber(creatureType) or 0,
            classification = tonumber(classification) or 0,
            name = name or "",
        }
        return
    end

    if text == "CATEND" then
        state.catalogLoaded = true
        state.online = true
        selectedCatalog = 1
        for i, rec in ipairs(state.catalog) do
            if rec.known then selectedCatalog = i; break end
        end
        if current == 1 then Draw() end
        return
    end

    local tag, a, b, c, d = strsplit(" ", text, 5)
    if tag == "STATE" then
        state.total = tonumber(a) or 0
        state.creatures = tonumber(b) or 0
        state.items = tonumber(c) or 0
        state.zones = tonumber(d) or 0
        state.online = true
        updateHeader()
    elseif tag == "KNOW" then
        state.knowledgeTotal = tonumber(a) or 0
        state.knowledgeSpent = tonumber(b) or 0
        state.knowledgeAvailable = tonumber(c) or 0
        state.rewardedDiscoveries = tonumber(d) or 0
        updateHeader()
        if current == 3 then Draw() end
    elseif tag == "CURRENT" then
        local oldZone = state.zone
        state.map = tonumber(a) or 0
        state.zone = tonumber(b) or 0
        state.area = tonumber(c) or 0
        if oldZone ~= 0 and oldZone ~= state.zone then
            state.catalogPage = 1
            state.catalogLoaded = false
            state.catalog = {}
            selectedCatalog = 1
        end
        updateHeader()
    elseif tag == "REC" then
        local kind = tonumber(a) or 0
        if state.recent[kind] then
            state.recent[kind][#state.recent[kind] + 1] = {
                entry = tonumber(b) or 0,
                map = tonumber(c) or 0,
                zone = tonumber(d) or 0,
            }
        end
    elseif tag == "RECEND" then
        local kind = tonumber(a) or 0
        if state.recentLoaded[kind] ~= nil then state.recentLoaded[kind] = true end
        state.online = true
        if current == 2 and kind == 3 then Draw() end
    elseif tag == "ERROR" then
        state.online = false
        chat((a or "Ошибка сервера") .. (b and (" " .. tostring(b)) or ""))
        updateHeader()
    elseif tag == "END" then
        waiting = false
        retriedSelf = false
        state.online = true
        updateHeader()
    end
end

SLASH_FOREVERENCYCLOPEDIA1 = "/encyclopedia"
SLASH_FOREVERENCYCLOPEDIA2 = "/ency"
SlashCmdList["FOREVERENCYCLOPEDIA"] = function(text)
    text = (text or ""):match("^%s*(.-)%s*$")
    if text == "" then
        CreateUI()
        if frame:IsShown() then frame:Hide() else frame:Show() end
    elseif text == "status" or text == "refresh" then
        refreshCurrent()
    else
        chat("Команды: /ency, /ency refresh")
    end
end

local events = CreateFrame("Frame")
events:RegisterEvent("ADDON_LOADED")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("PLAYER_ENTERING_WORLD")
events:RegisterEvent("ZONE_CHANGED_NEW_AREA")
events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent", function(_, event, ...)
    if event == "ADDON_LOADED" then
        local name = ...
        if name ~= ADDON then return end
        ForeverEncyclopediaDB = ForeverEncyclopediaDB or {}
        db = ForeverEncyclopediaDB
        registerPrefixes()
        return
    end

    if event == "CHAT_MSG_ADDON" then
        local prefix, text = ...
        if prefix == RESPONSE then parseResponse(text) end
        return
    end

    registerPrefixes()
    if event == "ZONE_CHANGED_NEW_AREA" then
        state.catalogPage = 1
        state.catalogLoaded = false
        state.catalog = {}
        selectedCatalog = 1
    end
    later(1.0, function()
        requestStatus(true)
        if frame and frame:IsShown() then
            if current == 1 then later(0.25, function() requestCatalog(1, true) end)
            elseif current == 2 then later(0.25, function() requestRecent(3, true) end) end
        end
    end)
end)

events:SetScript("OnUpdate", function()
    if not waiting then return end
    local now = GetTime and GetTime() or 0
    if not retriedSelf and now - lastStatus >= 2.0 then
        local name = UnitName and UnitName("player")
        if name then
            retriedSelf = true
            sendRaw("status", name, true)
        end
    end
    if now - lastStatus >= 6.0 then
        waiting = false
        state.online = false
        updateHeader()
    end
end)
