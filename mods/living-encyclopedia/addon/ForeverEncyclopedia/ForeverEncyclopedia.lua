local ADDON = ...
local REQUEST = "FEC1"
local RESPONSE = "FER1"
local SERVER_TARGET = "SERVER"

local frame
local bookDock
local bookManaBar
local bookManaText
local bookCooldowns = {}
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

local filterKnownIndex = 1
local filterTypeIndex = 1
local filterRankIndex = 1

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
    mana = 0,
    maxMana = 0,
    abilitiesEnabled = false,
    cooldowns = { 0, 0, 0 },
    recent = { [1] = {}, [2] = {}, [3] = {} },
    recentLoaded = { [1] = false, [2] = false, [3] = false },
    catalog = {},
    catalogLoaded = false,
    catalogZone = 0,
    catalogPage = 1,
    catalogPages = 1,
    catalogTotal = 0,
    catalogKnown = 0,
    catalogZoneTotal = 0,
    catalogZoneKnown = 0,
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
    [0] = "Обычный", [1] = "Элита", [2] = "Редкая элита", [3] = "Мировой босс", [4] = "Редкий",
}

local KNOWN_FILTERS = {
    { 0, "Все записи" },
    { 1, "Открытые" },
    { 2, "Неизвестные" },
}

local TYPE_FILTERS = {
    { 0, "Все типы" },
    { 1, "Звери" },
    { 7, "Гуманоиды" },
    { 6, "Нежить" },
    { 3, "Демоны" },
    { 4, "Элементали" },
    { 2, "Дракониды" },
    { 9, "Механизмы" },
}

local RANK_FILTERS = {
    { -1, "Любая редкость" },
    { 0, "Обычные" },
    { 1, "Элита" },
    { 4, "Редкие" },
    { 2, "Редкая элита" },
    { 3, "Боссы" },
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

local ABILITY_SLOTS = {
    { "Защитный щит", "Interface\\Icons\\Spell_Holy_PowerWordShield" },
    { "Лечение", "Interface\\Icons\\Spell_Holy_Heal" },
    { "Поддержка", "Interface\\Icons\\Spell_Arcane_Arcane01" },
}

local function chat(msg)
    if DEFAULT_CHAT_FRAME then
        DEFAULT_CHAT_FRAME:AddMessage("|cffffd37f[Энциклопедия]|r " .. tostring(msg))
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

local function currentCatalogFilters()
    return KNOWN_FILTERS[filterKnownIndex][1], TYPE_FILTERS[filterTypeIndex][1], RANK_FILTERS[filterRankIndex][1]
end

local function requestCatalog(page, quiet)
    page = tonumber(page) or 1
    if page < 1 then page = 1 end
    local known, creatureType, rank = currentCatalogFilters()
    state.catalog = {}
    state.catalogLoaded = false
    selectedCatalog = 1
    if Draw then Draw() end
    return sendRaw(string.format("catalog %d %d %d %d", page, known, creatureType, rank), SERVER_TARGET, quiet)
end

local function requestRecent(kind, quiet)
    if kind < 1 or kind > 3 then return false end
    state.recent[kind] = {}
    state.recentLoaded[kind] = false
    return sendRaw("recent " .. tostring(kind), SERVER_TARGET, quiet)
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

local function addParchment(texture, alpha)
    texture:SetTexture("Interface\\AchievementFrame\\UI-Achievement-Parchment-Horizontal")
    texture:SetAlpha(alpha or 0.16)
end

local function makePanel(parent, x, y, w, h, alpha)
    local p = addDynamic(CreateFrame("Frame", nil, parent or frame))
    p:SetPoint("TOPLEFT", parent or frame, "TOPLEFT", x, y)
    p:SetSize(w, h)

    local base = p:CreateTexture(nil, "BACKGROUND")
    base:SetAllPoints()
    base:SetColorTexture(0.075, 0.050, 0.030, alpha or 0.94)

    local parchment = p:CreateTexture(nil, "BACKGROUND", nil, 1)
    parchment:SetAllPoints()
    addParchment(parchment, 0.14)

    local top = p:CreateTexture(nil, "BORDER")
    top:SetPoint("TOPLEFT", p, "TOPLEFT", 1, -1)
    top:SetPoint("TOPRIGHT", p, "TOPRIGHT", -1, -1)
    top:SetHeight(1)
    top:SetColorTexture(0.48, 0.32, 0.14, 0.85)

    local bottom = p:CreateTexture(nil, "BORDER")
    bottom:SetPoint("BOTTOMLEFT", p, "BOTTOMLEFT", 1, 1)
    bottom:SetPoint("BOTTOMRIGHT", p, "BOTTOMRIGHT", -1, 1)
    bottom:SetHeight(1)
    bottom:SetColorTexture(0.20, 0.13, 0.07, 0.85)
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

    local base = b:CreateTexture(nil, "BACKGROUND")
    base:SetAllPoints()
    if active then base:SetColorTexture(0.30, 0.18, 0.065, 0.96)
    else base:SetColorTexture(0.11, 0.075, 0.045, 0.94) end

    local art = b:CreateTexture(nil, "BACKGROUND", nil, 1)
    art:SetAllPoints()
    art:SetTexture("Interface\\AchievementFrame\\UI-Achievement-Category-Background")
    art:SetAlpha(active and 0.34 or 0.18)

    local line = b:CreateTexture(nil, "BORDER")
    line:SetPoint("BOTTOMLEFT", b, "BOTTOMLEFT", 2, 1)
    line:SetPoint("BOTTOMRIGHT", b, "BOTTOMRIGHT", -2, 1)
    line:SetHeight(active and 2 or 1)
    if active then line:SetColorTexture(0.76, 0.52, 0.18, 1)
    else line:SetColorTexture(0.27, 0.18, 0.09, 0.9) end

    local text = b:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    text:SetPoint("CENTER", b, "CENTER", 0, 0)
    text:SetText(label or "")
    if active then text:SetTextColor(1.0, 0.86, 0.56)
    else text:SetTextColor(0.88, 0.82, 0.72) end

    b:SetScript("OnEnter", function()
        if not active then base:SetColorTexture(0.19, 0.12, 0.055, 0.98) end
    end)
    b:SetScript("OnLeave", function()
        if active then base:SetColorTexture(0.30, 0.18, 0.065, 0.96)
        else base:SetColorTexture(0.11, 0.075, 0.045, 0.94) end
    end)
    b:SetScript("OnClick", callback)
    return b
end

local function cycleFilter(kind)
    if kind == "known" then
        filterKnownIndex = filterKnownIndex % #KNOWN_FILTERS + 1
    elseif kind == "type" then
        filterTypeIndex = filterTypeIndex % #TYPE_FILTERS + 1
    elseif kind == "rank" then
        filterRankIndex = filterRankIndex % #RANK_FILTERS + 1
    end
    state.catalogPage = 1
    requestCatalog(1, true)
end

local function resetFilters()
    filterKnownIndex = 1
    filterTypeIndex = 1
    filterRankIndex = 1
    state.catalogPage = 1
    requestCatalog(1, true)
end

local function updateBookDock()
    if not bookDock then return end
    local maxMana = tonumber(state.maxMana) or 0
    local mana = tonumber(state.mana) or 0
    if maxMana < 1 then maxMana = 1 end
    if mana < 0 then mana = 0 end
    if mana > maxMana then mana = maxMana end

    if bookManaBar then
        bookManaBar:SetMinMaxValues(0, maxMana)
        bookManaBar:SetValue(mana)
    end
    if bookManaText then
        if state.maxMana > 0 then bookManaText:SetText(string.format("%d / %d", mana, state.maxMana))
        else bookManaText:SetText("— / —") end
    end

    for i, slot in ipairs(bookCooldowns) do
        local cd = tonumber(state.cooldowns[i]) or 0
        if state.abilitiesEnabled then
            slot.icon:SetAlpha(1)
            slot.lock:SetText("")
            if slot.cooldown and slot.cooldown.SetCooldown then
                if cd > 0 then slot.cooldown:SetCooldown(GetTime(), cd)
                else slot.cooldown:Clear() end
            end
        else
            slot.icon:SetAlpha(0.28)
            slot.lock:SetText("—")
            if slot.cooldown and slot.cooldown.Clear then slot.cooldown:Clear() end
        end
    end
end

local function updateHeader()
    if not frame then
        updateBookDock()
        return
    end
    if statusText then
        if state.online then
            statusText:SetText("Архив синхронизирован")
            statusText:SetTextColor(0.42, 0.82, 0.48)
        else
            statusText:SetText("Нет связи с архивом")
            statusText:SetTextColor(0.92, 0.42, 0.36)
        end
    end
    if zoneText then zoneText:SetText(currentZoneName()) end
    if statsText then
        statsText:SetText(string.format("Знания %d     Существа %d     Предметы %d     Локации %d",
            state.knowledgeAvailable, state.creatures, state.items, state.zones))
    end
    for i, button in ipairs(tabButtons) do
        if button._label then
            if i == current then button._label:SetTextColor(1.0, 0.82, 0.42)
            else button._label:SetTextColor(0.82, 0.76, 0.66) end
        end
        if button._line then
            if i == current then button._line:SetColorTexture(0.75, 0.48, 0.14, 1)
            else button._line:SetColorTexture(0.2, 0.12, 0.05, 0) end
        end
    end
    updateBookDock()
end

local function creatureMeta(rec)
    if not rec or not rec.known then return "Неизвестное существо" end
    local typeName = CREATURE_TYPES[rec.creatureType] or "Существо"
    local className = CLASSIFICATIONS[rec.classification]
    if className and rec.classification ~= 0 then return typeName .. "  •  " .. className end
    return typeName
end

local function drawProgress(parent, x, y, w, known, total)
    local pct = total > 0 and math.floor(known * 100 / total) or 0
    makeText(parent, x, y, w, string.format("Изучено %d из %d  •  %d%%", known, total, pct), "GameFontNormalSmall", 0.84, 0.76, 0.62)
    local track = parent:CreateTexture(nil, "BACKGROUND")
    track:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y - 19)
    track:SetSize(w, 7)
    track:SetColorTexture(0.10, 0.065, 0.035, 1)
    local fill = parent:CreateTexture(nil, "ARTWORK")
    fill:SetPoint("LEFT", track, "LEFT", 0, 0)
    local fillWidth = total > 0 and math.floor(w * known / total) or 0
    fill:SetSize(math.max(1, fillWidth), 7)
    fill:SetColorTexture(0.62, 0.38, 0.10, fillWidth > 0 and 1 or 0)
end

local function addCatalogScrollbar(parent)
    local slider = addDynamic(CreateFrame("Slider", nil, parent, "UIPanelScrollBarTemplate"))
    slider:SetPoint("TOPRIGHT", parent, "TOPRIGHT", -4, -146)
    slider:SetPoint("BOTTOMRIGHT", parent, "BOTTOMRIGHT", -4, 46)
    slider:SetMinMaxValues(1, math.max(1, state.catalogPages))
    slider:SetValueStep(1)
    slider._sync = true
    slider:SetValue(math.max(1, state.catalogPage))
    slider._sync = false
    slider:SetScript("OnValueChanged", function(self, value)
        if self._sync then return end
        local page = math.floor((tonumber(value) or 1) + 0.5)
        if page ~= state.catalogPage then requestCatalog(page, true) end
    end)
    return slider
end

local function drawCreatures()
    local left = makePanel(frame, 24, -134, 362, 414, 0.96)
    local right = makePanel(frame, 398, -134, 498, 414, 0.96)

    makeText(left, 16, -14, 320, currentZoneName(), "GameFontHighlightLarge", 1.0, 0.88, 0.64)
    if state.catalogLoaded then
        drawProgress(left, 16, -43, 324, state.catalogZoneKnown, state.catalogZoneTotal)
    else
        makeText(left, 16, -46, 320, "Получаю список существ…", "GameFontNormalSmall", 0.72, 0.66, 0.58)
    end

    local knownLabel = KNOWN_FILTERS[filterKnownIndex][2]
    local typeLabel = TYPE_FILTERS[filterTypeIndex][2]
    local rankLabel = RANK_FILTERS[filterRankIndex][2]
    makeButton(left, 12, -73, 104, 26, knownLabel, function() cycleFilter("known") end, filterKnownIndex ~= 1)
    makeButton(left, 120, -73, 104, 26, typeLabel, function() cycleFilter("type") end, filterTypeIndex ~= 1)
    makeButton(left, 228, -73, 104, 26, rankLabel, function() cycleFilter("rank") end, filterRankIndex ~= 1)

    local shown = state.catalogLoaded and state.catalogTotal or 0
    makeText(left, 16, -106, 230, "Показано записей: " .. tostring(shown), "GameFontNormalSmall", 0.72, 0.65, 0.55)
    if filterKnownIndex ~= 1 or filterTypeIndex ~= 1 or filterRankIndex ~= 1 then
        local reset = makeButton(left, 247, -103, 85, 23, "Сбросить", resetFilters, false)
        reset:SetAlpha(0.88)
    end

    local rowStart = -132
    if state.catalogLoaded and #state.catalog == 0 then
        makeText(left, 16, rowStart - 8, 310, "По выбранным фильтрам записей нет.", "GameFontNormal", 0.82, 0.76, 0.68)
    elseif state.catalogLoaded then
        for i, rec in ipairs(state.catalog) do
            local active = i == selectedCatalog
            local row = makeButton(left, 12, rowStart - (i - 1) * 31, 320, 28,
                rec.known and ((rec.name ~= "" and rec.name) or "Открытая запись") or "???",
                function() selectedCatalog = i; Draw() end, active)
            local status = row:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
            status:SetPoint("RIGHT", row, "RIGHT", -8, 0)
            status:SetText(rec.known and "Открыто" or "?")
            if rec.known then status:SetTextColor(0.50, 0.82, 0.48)
            else status:SetTextColor(0.54, 0.49, 0.42) end
        end
    end

    makeText(left, 116, -387, 115, string.format("Страница %d / %d", state.catalogPage, state.catalogPages), "GameFontNormalSmall", 0.72, 0.65, 0.55, "CENTER")
    local prev = makeButton(left, 12, -378, 88, 26, "Назад", function()
        if state.catalogPage > 1 then requestCatalog(state.catalogPage - 1, false) end
    end, false)
    local nextb = makeButton(left, 244, -378, 88, 26, "Далее", function()
        if state.catalogPage < state.catalogPages then requestCatalog(state.catalogPage + 1, false) end
    end, false)
    if state.catalogPage <= 1 then prev:Disable() end
    if state.catalogPage >= state.catalogPages then nextb:Disable() end

    addCatalogScrollbar(left)
    left:EnableMouseWheel(true)
    left:SetScript("OnMouseWheel", function(_, delta)
        if delta < 0 and state.catalogPage < state.catalogPages then
            requestCatalog(state.catalogPage + 1, true)
        elseif delta > 0 and state.catalogPage > 1 then
            requestCatalog(state.catalogPage - 1, true)
        end
    end)

    local rec = state.catalog[selectedCatalog]
    if not state.catalogLoaded then
        makeText(right, 28, -28, 430, "Бестиарий", "GameFontHighlightLarge", 1.0, 0.88, 0.64)
        makeText(right, 28, -72, 430, "Синхронизация с архивом…", "GameFontNormal", 0.72, 0.66, 0.58)
        return
    end

    if not rec then
        makeText(right, 28, -28, 430, "Бестиарий", "GameFontHighlightLarge", 1.0, 0.88, 0.64)
        makeText(right, 28, -72, 430, "Выберите запись слева.", "GameFontNormal", 0.72, 0.66, 0.58)
        return
    end

    if rec.known then
        makeText(right, 28, -28, 438, rec.name ~= "" and rec.name or "Открытая запись", "GameFontHighlightLarge", 1.0, 0.90, 0.68)
        makeText(right, 28, -61, 438, creatureMeta(rec), "GameFontNormal", 0.83, 0.68, 0.42)

        local seal = makePanel(right, 28, -102, 126, 126, 0.78)
        local sealIcon = seal:CreateTexture(nil, "ARTWORK")
        sealIcon:SetPoint("CENTER", seal, "CENTER", 0, 5)
        sealIcon:SetSize(72, 72)
        sealIcon:SetTexture("Interface\\Icons\\INV_Misc_Book_09")
        local sealText = makeText(seal, 0, -96, 126, "Открыто", "GameFontNormalSmall", 0.54, 0.82, 0.48, "CENTER")

        makeText(right, 184, -109, 275, "Запись открыта", "GameFontHighlight", 0.96, 0.82, 0.54)
        makeText(right, 184, -140, 275, "Встречается: " .. currentZoneName(), "GameFontNormal", 0.82, 0.78, 0.70)
        makeText(right, 184, -172, 275, "Первое открытие сохранено для всего аккаунта.", "GameFontNormalSmall", 0.64, 0.59, 0.52)

        makeText(right, 28, -258, 438, "Наблюдения", "GameFontHighlight", 0.96, 0.82, 0.54)
        makeText(right, 28, -290, 438, "Здесь будут способности, сопротивления, полезный лут и особенности существа.", "GameFontNormal", 0.76, 0.71, 0.64)
    else
        makeText(right, 28, -28, 438, "???", "GameFontHighlightLarge", 0.72, 0.67, 0.60)
        makeText(right, 28, -61, 438, "Неизвестное существо", "GameFontNormal", 0.66, 0.61, 0.54)
        local mystery = makePanel(right, 28, -103, 438, 154, 0.72)
        makeText(mystery, 0, -49, 438, "?", "GameFontHighlightLarge", 0.55, 0.43, 0.28, "CENTER")
        makeText(right, 28, -287, 438, "Победите это существо, чтобы открыть его запись.", "GameFontHighlight", 0.92, 0.80, 0.58)
        makeText(right, 28, -319, 438, "До открытия архив не раскрывает имя и сведения о нём.", "GameFontNormalSmall", 0.64, 0.59, 0.52)
    end
end

local function drawLocations()
    local left = makePanel(frame, 24, -134, 340, 414, 0.96)
    local right = makePanel(frame, 376, -134, 520, 414, 0.96)
    makeText(left, 16, -16, 300, "Изученные локации", "GameFontHighlightLarge", 1.0, 0.88, 0.64)
    makeText(left, 16, -48, 300, "Последние открытия аккаунта", "GameFontNormalSmall", 0.72, 0.65, 0.55)

    local records = state.recent[3] or {}
    if not state.recentLoaded[3] then
        makeText(left, 16, -92, 300, "Получаю список…", "GameFontNormal", 0.72, 0.66, 0.58)
    elseif #records == 0 then
        makeText(left, 16, -92, 300, "Пока нет сохранённых локаций.", "GameFontNormal", 0.72, 0.66, 0.58)
    else
        for i = 1, math.min(#records, 9) do
            local rec = records[i]
            local title = areaName(rec.entry) or ("Локация " .. tostring(rec.entry))
            makeButton(left, 12, -78 - (i - 1) * 34, 316, 30, title,
                function() selectedLocation = i; Draw() end, i == selectedLocation)
        end
    end

    left:EnableMouseWheel(true)
    left:SetScript("OnMouseWheel", function(_, delta)
        if #records < 2 then return end
        selectedLocation = selectedLocation - delta
        if selectedLocation < 1 then selectedLocation = 1 end
        if selectedLocation > #records then selectedLocation = #records end
        Draw()
    end)

    local rec = records[selectedLocation]
    local title = rec and (areaName(rec.entry) or "Изученная локация") or currentZoneName()
    makeText(right, 28, -28, 460, title, "GameFontHighlightLarge", 1.0, 0.90, 0.68)
    makeText(right, 28, -62, 460, "Архив исследования мира", "GameFontNormal", 0.83, 0.68, 0.42)
    makeText(right, 28, -112, 460, "Локации открываются один раз на аккаунт.", "GameFontHighlight", 0.94, 0.80, 0.56)
    makeText(right, 28, -145, 460, "За первое посещение новой зоны энциклопедия выдаёт 3 очка знаний.", "GameFontNormal", 0.76, 0.71, 0.64)
    makeText(right, 28, -202, 460, "Текущая зона", "GameFontHighlight", 0.94, 0.80, 0.56)
    makeText(right, 28, -233, 460, currentZoneName(), "GameFontNormal", 0.86, 0.81, 0.72)
end

local function drawTalents()
    local left = makePanel(frame, 24, -134, 280, 414, 0.96)
    local right = makePanel(frame, 316, -134, 580, 414, 0.96)
    makeText(left, 16, -16, 245, "Ветви знаний", "GameFontHighlightLarge", 1.0, 0.88, 0.64)
    makeText(left, 16, -48, 245, "Доступно очков: " .. tostring(state.knowledgeAvailable), "GameFontNormal", 0.83, 0.68, 0.42)
    for i, talent in ipairs(TALENTS) do
        makeButton(left, 12, -82 - (i - 1) * 50, 256, 42, talent[1],
            function() selectedTalent = i; Draw() end, i == selectedTalent)
    end

    local talent = TALENTS[selectedTalent] or TALENTS[1]
    makeText(right, 30, -30, 510, talent[1], "GameFontHighlightLarge", 1.0, 0.90, 0.68)
    makeText(right, 30, -70, 510, talent[2], "GameFontNormal", 0.78, 0.72, 0.64)
    local node = makePanel(right, 30, -120, 118, 118, 0.76)
    local icon = node:CreateTexture(nil, "ARTWORK")
    icon:SetPoint("CENTER")
    icon:SetSize(72, 72)
    icon:SetTexture("Interface\\Icons\\INV_Misc_Book_11")
    icon:SetDesaturated(true)
    icon:SetAlpha(0.55)
    makeText(right, 178, -126, 350, "Ветка подготавливается", "GameFontHighlight", 0.94, 0.80, 0.56)
    makeText(right, 178, -158, 350, talent[3], "GameFontNormal", 0.74, 0.69, 0.62)
    makeText(right, 30, -278, 510, "Покупка узлов включится только вместе с реальными серверными эффектами.", "GameFontNormalSmall", 0.62, 0.57, 0.50)
end

local function drawAppearances()
    local left = makePanel(frame, 24, -134, 540, 414, 0.96)
    local right = makePanel(frame, 576, -134, 320, 414, 0.96)
    makeText(left, 16, -16, 500, "Коллекция обликов", "GameFontHighlightLarge", 1.0, 0.88, 0.64)
    makeText(left, 16, -48, 500, "Облик не влияет на способности спутника.", "GameFontNormalSmall", 0.72, 0.65, 0.55)

    for i, appearance in ipairs(APPEARANCES) do
        local col = (i - 1) % 3
        local row = math.floor((i - 1) / 3)
        local x = 12 + col * 174
        local y = -82 - row * 136
        local b = makeButton(left, x, y, 162, 120, "", function() selectedAppearance = i; Draw() end, i == selectedAppearance)
        local icon = b:CreateTexture(nil, "ARTWORK")
        icon:SetPoint("TOP", b, "TOP", 0, -14)
        icon:SetSize(50, 50)
        icon:SetTexture("Interface\\Icons\\INV_Misc_Book_09")
        icon:SetDesaturated(not appearance[3])
        icon:SetAlpha(appearance[3] and 1 or 0.35)
        local label = b:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
        label:SetPoint("BOTTOM", b, "BOTTOM", 0, 17)
        label:SetWidth(145)
        label:SetText(appearance[1])
        label:SetTextColor(0.90, 0.84, 0.74)
    end

    local appearance = APPEARANCES[selectedAppearance] or APPEARANCES[1]
    makeText(right, 24, -28, 270, appearance[1], "GameFontHighlightLarge", 1.0, 0.90, 0.68)
    makeText(right, 24, -69, 270, appearance[2], "GameFontNormal", 0.76, 0.70, 0.62)
    local preview = makePanel(right, 24, -112, 272, 166, 0.72)
    local previewIcon = preview:CreateTexture(nil, "ARTWORK")
    previewIcon:SetPoint("CENTER")
    previewIcon:SetSize(96, 96)
    previewIcon:SetTexture("Interface\\Icons\\INV_Misc_Book_09")
    previewIcon:SetDesaturated(not appearance[3])
    previewIcon:SetAlpha(appearance[3] and 1 or 0.30)
    makeText(right, 24, -307, 270, appearance[3] and "Доступен" or "Пока закрыт", "GameFontHighlight", appearance[3] and 0.50 or 0.72, appearance[3] and 0.82 or 0.58, appearance[3] and 0.48 or 0.42)
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
    b:SetPoint("TOPLEFT", frame, "TOPLEFT", x, -88)
    b:SetSize(198, 34)

    local base = b:CreateTexture(nil, "BACKGROUND")
    base:SetAllPoints()
    base:SetColorTexture(0.095, 0.062, 0.035, 0.92)

    local art = b:CreateTexture(nil, "BACKGROUND", nil, 1)
    art:SetAllPoints()
    art:SetTexture("Interface\\AchievementFrame\\UI-Achievement-Category-Background")
    art:SetAlpha(0.20)

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
    b:SetScript("OnEnter", function() base:SetColorTexture(0.18, 0.11, 0.045, 0.98) end)
    b:SetScript("OnLeave", function() base:SetColorTexture(0.095, 0.062, 0.035, 0.92) end)
    tabButtons[index] = b
end

local function CreateUI()
    if frame then return end

    frame = CreateFrame("Frame", "ForeverEncyclopediaFrame", UIParent, "BasicFrameTemplateWithInset")
    frame:SetSize(920, 590)
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
    if frame.TitleText.SetTextColor then frame.TitleText:SetTextColor(1.0, 0.82, 0.42) end

    local background = frame:CreateTexture(nil, "BACKGROUND")
    background:SetPoint("TOPLEFT", frame, "TOPLEFT", 10, -34)
    background:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -10, 10)
    background:SetColorTexture(0.055, 0.035, 0.022, 0.97)

    local parchment = frame:CreateTexture(nil, "BACKGROUND", nil, 1)
    parchment:SetPoint("TOPLEFT", frame, "TOPLEFT", 10, -34)
    parchment:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -10, 10)
    addParchment(parchment, 0.18)

    local header = frame:CreateTexture(nil, "BACKGROUND", nil, 2)
    header:SetPoint("TOPLEFT", frame, "TOPLEFT", 10, -34)
    header:SetPoint("TOPRIGHT", frame, "TOPRIGHT", -10, -34)
    header:SetHeight(46)
    header:SetColorTexture(0.095, 0.058, 0.028, 0.96)

    statusText = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    statusText:SetPoint("TOPLEFT", frame, "TOPLEFT", 26, -50)
    statusText:SetWidth(220)
    statusText:SetJustifyH("LEFT")

    statsText = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    statsText:SetPoint("TOP", frame, "TOP", 0, -50)
    statsText:SetWidth(430)
    statsText:SetJustifyH("CENTER")
    statsText:SetTextColor(0.82, 0.75, 0.63)

    zoneText = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    zoneText:SetPoint("TOPRIGHT", frame, "TOPRIGHT", -26, -49)
    zoneText:SetWidth(220)
    zoneText:SetJustifyH("RIGHT")
    zoneText:SetTextColor(0.93, 0.85, 0.70)

    createTab(1, "Существа", 42)
    createTab(2, "Локации", 251)
    createTab(3, "Таланты", 460)
    createTab(4, "Облики", 669)

    local version = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    version:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -18, 15)
    version:SetText("Forever Encyclopedia 0.6")
    version:SetTextColor(0.46, 0.40, 0.33)

    if db and db.uiVersion == 6 then
        current = tonumber(db.currentTab) or 1
        filterKnownIndex = tonumber(db.filterKnownIndex) or 1
        filterTypeIndex = tonumber(db.filterTypeIndex) or 1
        filterRankIndex = tonumber(db.filterRankIndex) or 1
    else
        current = 1
        filterKnownIndex = 1
        filterTypeIndex = 1
        filterRankIndex = 1
        if db then db.uiVersion = 6; db.currentTab = 1 end
    end

    if current < 1 or current > 4 then current = 1 end
    if filterKnownIndex < 1 or filterKnownIndex > #KNOWN_FILTERS then filterKnownIndex = 1 end
    if filterTypeIndex < 1 or filterTypeIndex > #TYPE_FILTERS then filterTypeIndex = 1 end
    if filterRankIndex < 1 or filterRankIndex > #RANK_FILTERS then filterRankIndex = 1 end
    Draw()
end

local function toggleUI()
    CreateUI()
    if frame:IsShown() then frame:Hide() else frame:Show() end
end

local function CreateBookDock()
    if bookDock then return end

    bookDock = CreateFrame("Frame", "ForeverEncyclopediaBookDock", UIParent)
    bookDock:SetSize(176, 58)
    bookDock:SetFrameStrata("MEDIUM")
    bookDock:SetClampedToScreen(true)

    if QuickJoinToastButton then
        bookDock:SetPoint("RIGHT", QuickJoinToastButton, "LEFT", -7, 0)
    elseif FriendsMicroButton then
        bookDock:SetPoint("RIGHT", FriendsMicroButton, "LEFT", -7, 0)
    elseif ChatFrameMenuButton then
        bookDock:SetPoint("LEFT", ChatFrameMenuButton, "RIGHT", 7, 0)
    else
        bookDock:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", 24, 180)
    end

    local base = bookDock:CreateTexture(nil, "BACKGROUND")
    base:SetAllPoints()
    base:SetColorTexture(0.075, 0.045, 0.024, 0.90)
    local art = bookDock:CreateTexture(nil, "BACKGROUND", nil, 1)
    art:SetAllPoints()
    addParchment(art, 0.16)

    local book = CreateFrame("Button", nil, bookDock)
    book:SetPoint("LEFT", bookDock, "LEFT", 5, 0)
    book:SetSize(46, 46)
    local bookBorder = book:CreateTexture(nil, "BACKGROUND")
    bookBorder:SetAllPoints()
    bookBorder:SetTexture("Interface\\Buttons\\UI-Quickslot2")
    local bookIcon = book:CreateTexture(nil, "ARTWORK")
    bookIcon:SetPoint("TOPLEFT", book, "TOPLEFT", 5, -5)
    bookIcon:SetPoint("BOTTOMRIGHT", book, "BOTTOMRIGHT", -5, 5)
    bookIcon:SetTexture("Interface\\Icons\\INV_Misc_Book_09")
    book:SetScript("OnClick", toggleUI)
    book:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_TOPLEFT")
        GameTooltip:AddLine("Живая энциклопедия", 1, 0.82, 0.42)
        if state.maxMana > 0 then GameTooltip:AddLine(string.format("Мана: %d / %d", state.mana, state.maxMana), 0.55, 0.70, 1)
        else GameTooltip:AddLine("Мана: нет данных", 0.7, 0.7, 0.7) end
        GameTooltip:AddLine("Нажмите, чтобы открыть архив.", 0.8, 0.8, 0.8)
        GameTooltip:Show()
    end)
    book:SetScript("OnLeave", function() GameTooltip:Hide() end)

    local manaLabel = bookDock:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    manaLabel:SetPoint("TOPLEFT", bookDock, "TOPLEFT", 58, -5)
    manaLabel:SetText("Мана книги")
    manaLabel:SetTextColor(0.90, 0.81, 0.64)

    bookManaBar = CreateFrame("StatusBar", nil, bookDock)
    bookManaBar:SetPoint("TOPLEFT", bookDock, "TOPLEFT", 58, -19)
    bookManaBar:SetSize(110, 10)
    bookManaBar:SetStatusBarTexture("Interface\\TargetingFrame\\UI-StatusBar")
    bookManaBar:SetStatusBarColor(0.12, 0.35, 0.80)
    local manaBg = bookManaBar:CreateTexture(nil, "BACKGROUND")
    manaBg:SetAllPoints()
    manaBg:SetColorTexture(0.04, 0.04, 0.06, 0.95)
    bookManaText = bookManaBar:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    bookManaText:SetPoint("CENTER", bookManaBar, "CENTER", 0, 0)
    bookManaText:SetText("— / —")

    for i, data in ipairs(ABILITY_SLOTS) do
        local slot = CreateFrame("Button", nil, bookDock)
        slot:SetSize(25, 25)
        slot:SetPoint("TOPLEFT", bookDock, "TOPLEFT", 58 + (i - 1) * 31, -31)
        local border = slot:CreateTexture(nil, "BACKGROUND")
        border:SetAllPoints()
        border:SetTexture("Interface\\Buttons\\UI-Quickslot2")
        local icon = slot:CreateTexture(nil, "ARTWORK")
        icon:SetPoint("TOPLEFT", slot, "TOPLEFT", 3, -3)
        icon:SetPoint("BOTTOMRIGHT", slot, "BOTTOMRIGHT", -3, 3)
        icon:SetTexture(data[2])
        icon:SetAlpha(0.28)
        local cooldown = CreateFrame("Cooldown", nil, slot, "CooldownFrameTemplate")
        cooldown:SetAllPoints(icon)
        local lock = slot:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
        lock:SetPoint("CENTER", slot, "CENTER", 0, 0)
        lock:SetText("—")
        lock:SetTextColor(0.85, 0.78, 0.66)
        slot:SetScript("OnEnter", function(self)
            GameTooltip:SetOwner(self, "ANCHOR_TOP")
            GameTooltip:AddLine(data[1], 1, 0.82, 0.42)
            if state.abilitiesEnabled then
                GameTooltip:AddLine("Способность активна.", 0.65, 0.85, 0.65)
            else
                GameTooltip:AddLine("Ещё не изучено.", 0.72, 0.72, 0.72)
            end
            GameTooltip:Show()
        end)
        slot:SetScript("OnLeave", function() GameTooltip:Hide() end)
        bookCooldowns[i] = { button = slot, icon = icon, cooldown = cooldown, lock = lock }
    end

    updateBookDock()
end

local function parseResponse(text)
    text = tostring(text or "")

    if text:sub(1, 8) == "CATHEAD|" then
        local _, zone, page, pages, total, known, zoneTotal, zoneKnown = strsplit("|", text)
        state.catalog = {}
        state.catalogZone = tonumber(zone) or 0
        state.catalogPage = tonumber(page) or 1
        state.catalogPages = tonumber(pages) or 1
        state.catalogTotal = tonumber(total) or 0
        state.catalogKnown = tonumber(known) or 0
        state.catalogZoneTotal = tonumber(zoneTotal) or state.catalogTotal
        state.catalogZoneKnown = tonumber(zoneKnown) or state.catalogKnown
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

    local tag, a, b, c, d, e, f = strsplit(" ", text)
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
    elseif tag == "BOOK" then
        state.mana = tonumber(a) or 0
        state.maxMana = tonumber(b) or 0
        state.abilitiesEnabled = tonumber(c) == 1
        state.cooldowns[1] = tonumber(d) or 0
        state.cooldowns[2] = tonumber(e) or 0
        state.cooldowns[3] = tonumber(f) or 0
        updateBookDock()
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
        toggleUI()
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
    if event == "PLAYER_LOGIN" then
        CreateBookDock()
    end
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
