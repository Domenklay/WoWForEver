local ADDON = ...
local REQUEST = "FEC1"
local RESPONSE = "FER1"
local SERVER_TARGET = "SERVER"

local frame
local current = 1
local db
local dynamic = {}
local navButtons = {}
local statValues = {}
local statusText
local locationText
local Draw

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

local function chat(msg)
    if DEFAULT_CHAT_FRAME then
        DEFAULT_CHAT_FRAME:AddMessage("|cff66ccff[Энциклопедия]|r " .. tostring(msg))
    end
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

local function later(delay, fn)
    if C_Timer and C_Timer.After then C_Timer.After(delay, fn) else fn() end
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
    if Draw then Draw() end
    return sendRaw("catalog " .. tostring(page), SERVER_TARGET, quiet)
end

local function addDynamic(object)
    dynamic[#dynamic + 1] = object
    return object
end

local function clearDynamic()
    for _, object in ipairs(dynamic) do object:Hide() end
    wipe(dynamic)
end

local function addText(x, y, width, text, font, r, g, b)
    local t = addDynamic(frame:CreateFontString(nil, "OVERLAY", font or "GameFontHighlight"))
    t:SetPoint("TOPLEFT", frame, "TOPLEFT", x, y)
    if width then t:SetWidth(width) end
    t:SetJustifyH("LEFT")
    t:SetText(text or "")
    if r then t:SetTextColor(r, g, b) end
    return t
end

local function addPanel(x, y, width, height, alpha)
    local p = addDynamic(CreateFrame("Frame", nil, frame))
    p:SetPoint("TOPLEFT", frame, "TOPLEFT", x, y)
    p:SetSize(width, height)

    local bg = p:CreateTexture(nil, "BACKGROUND")
    bg:SetAllPoints()
    bg:SetColorTexture(0.045, 0.055, 0.07, alpha or 0.84)

    local top = p:CreateTexture(nil, "BORDER")
    top:SetPoint("TOPLEFT", p, "TOPLEFT", 0, 0)
    top:SetPoint("TOPRIGHT", p, "TOPRIGHT", 0, 0)
    top:SetHeight(1)
    top:SetColorTexture(0.20, 0.48, 0.62, 0.75)
    return p
end

local function addButton(x, y, width, height, label, callback)
    local b = addDynamic(CreateFrame("Button", nil, frame, "UIPanelButtonTemplate"))
    b:SetPoint("TOPLEFT", frame, "TOPLEFT", x, y)
    b:SetSize(width, height)
    b:SetText(label)
    b:SetScript("OnClick", callback)
    return b
end

local function currentZoneName()
    local zone = GetRealZoneText and GetRealZoneText() or ""
    local sub = GetSubZoneText and GetSubZoneText() or ""
    if sub and sub ~= "" and sub ~= zone then return zone .. " — " .. sub end
    if zone and zone ~= "" then return zone end
    return "Зона " .. tostring(state.zone)
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

local function updateHeader()
    if not frame then return end

    if statusText then
        if state.online then
            statusText:SetText("●  Синхронизация активна  •  открытий: " .. tostring(state.total))
            statusText:SetTextColor(0.35, 0.90, 0.55)
        else
            statusText:SetText("●  Нет ответа сервера")
            statusText:SetTextColor(0.95, 0.35, 0.35)
        end
    end

    if locationText then locationText:SetText(currentZoneName()) end

    local values = { state.knowledgeAvailable, state.creatures, state.items, state.zones }
    for i = 1, 4 do
        if statValues[i] then statValues[i]:SetText(tostring(values[i] or 0)) end
    end

    for i, button in ipairs(navButtons) do
        local fs = button:GetFontString()
        if fs then
            if i == current then fs:SetTextColor(0.45, 0.85, 1.0)
            else fs:SetTextColor(0.82, 0.84, 0.86) end
        end
    end
end

local function listRow(y, marker, title, details, opened)
    local row = addPanel(210, y, 665, 28, opened and 0.72 or 0.45)
    local badge = row:CreateTexture(nil, "ARTWORK")
    badge:SetPoint("LEFT", row, "LEFT", 7, 0)
    badge:SetSize(18, 18)
    if opened then badge:SetColorTexture(0.10, 0.38, 0.48, 0.95)
    else badge:SetColorTexture(0.14, 0.15, 0.17, 0.95) end

    local glyph = row:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    glyph:SetPoint("CENTER", badge, "CENTER", 0, 0)
    glyph:SetText(marker or "?")
    if opened then glyph:SetTextColor(0.72, 0.93, 1.0)
    else glyph:SetTextColor(0.48, 0.52, 0.56) end

    local name = row:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    name:SetPoint("LEFT", row, "LEFT", 34, 0)
    name:SetWidth(330)
    name:SetJustifyH("LEFT")
    name:SetText(title or "")
    if opened then name:SetTextColor(0.92, 0.95, 0.97)
    else name:SetTextColor(0.55, 0.58, 0.62) end

    local info = row:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    info:SetPoint("RIGHT", row, "RIGHT", -10, 0)
    info:SetWidth(280)
    info:SetJustifyH("RIGHT")
    info:SetText(details or "")
    info:SetTextColor(0.55, 0.66, 0.72)
end

local function drawTalents()
    addText(210, -176, 665, "Таланты спутника", "GameFontHighlightLarge", 0.82, 0.93, 1.0)
    addText(210, -201, 665,
        "Очки знаний начисляются за первые уникальные открытия. Покупка талантов включится вместе с серверными эффектами.",
        "GameFontNormalSmall", 0.60, 0.70, 0.76)

    local progress = addPanel(210, -230, 665, 54, 0.80)
    local p1 = progress:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    p1:SetPoint("TOPLEFT", progress, "TOPLEFT", 12, -9)
    p1:SetText("Доступно очков знаний: " .. tostring(state.knowledgeAvailable))
    p1:SetTextColor(0.68, 0.90, 1.0)
    local p2 = progress:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    p2:SetPoint("TOPLEFT", progress, "TOPLEFT", 12, -31)
    p2:SetText(string.format("Получено: %d   •   потрачено: %d   •   награждённых открытий: %d",
        state.knowledgeTotal, state.knowledgeSpent, state.rewardedDiscoveries))
    p2:SetTextColor(0.58, 0.68, 0.74)

    local branches = {
        { "Защита", "Щиты и выживаемость", "щит ≤ 30% HP" },
        { "Исцеление", "Автоматическая помощь", "25% → 40% HP" },
        { "Усиление", "Короткие PvE-эффекты", "подготовка" },
        { "Мудрость", "Запас и регенерация маны", "1/5 и 5/5 сек" },
        { "Познание", "Бонусы за исследования", "подготовка" },
    }
    local positions = {{210,-300},{440,-300},{670,-300},{325,-390},{555,-390}}

    for i, data in ipairs(branches) do
        local p = addPanel(positions[i][1], positions[i][2], 205, 72, 0.70)
        local n = p:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
        n:SetPoint("TOPLEFT", p, "TOPLEFT", 11, -9)
        n:SetText(data[1])
        n:SetTextColor(0.70, 0.90, 1.0)
        local d = p:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
        d:SetPoint("TOPLEFT", p, "TOPLEFT", 11, -29)
        d:SetWidth(182)
        d:SetJustifyH("LEFT")
        d:SetText(data[2])
        d:SetTextColor(0.66, 0.70, 0.74)
        local l = p:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
        l:SetPoint("BOTTOMLEFT", p, "BOTTOMLEFT", 11, 8)
        l:SetText("Заблокировано  •  " .. data[3])
        l:SetTextColor(0.46, 0.50, 0.54)
    end
end

local function drawCatalog()
    addText(210, -176, 665, "Бестиарий текущей зоны", "GameFontHighlightLarge", 0.82, 0.93, 1.0)
    addText(210, -201, 665,
        currentZoneName() .. "  •  неизвестные существа не раскрывают имя до первого открытия",
        "GameFontNormalSmall", 0.60, 0.70, 0.76)

    local progress = addPanel(210, -228, 665, 54, 0.80)
    local pct = state.catalogTotal > 0 and math.floor(state.catalogKnown * 100 / state.catalogTotal) or 0
    local label = progress:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    label:SetPoint("TOPLEFT", progress, "TOPLEFT", 11, -8)
    if state.catalogLoaded then
        label:SetText(string.format("Изучено %d из %d существ  •  %d%%", state.catalogKnown, state.catalogTotal, pct))
    else
        label:SetText("Получаю каталог зоны с сервера…")
    end
    label:SetTextColor(0.70, 0.90, 1.0)

    local track = progress:CreateTexture(nil, "BACKGROUND")
    track:SetPoint("BOTTOMLEFT", progress, "BOTTOMLEFT", 11, 10)
    track:SetSize(643, 8)
    track:SetColorTexture(0.10, 0.12, 0.14, 1)
    local fill = progress:CreateTexture(nil, "ARTWORK")
    fill:SetPoint("LEFT", track, "LEFT", 0, 0)
    local fillWidth = state.catalogTotal > 0 and math.floor(643 * state.catalogKnown / state.catalogTotal) or 0
    fill:SetSize(math.max(1, fillWidth), 8)
    fill:SetColorTexture(0.18, 0.58, 0.72, fillWidth > 0 and 0.95 or 0)

    if state.catalogLoaded then
        local y = -291
        if #state.catalog == 0 then
            addText(210, y, 650, "В этой зоне сервер не нашёл постоянных спавнов существ.", "GameFontNormal", 0.68, 0.74, 0.78)
        else
            for i, rec in ipairs(state.catalog) do
                local opened = rec.known == true
                local title = opened and ((rec.name and rec.name ~= "") and rec.name or ("Существо #" .. tostring(rec.entry))) or "???"
                local details = opened and ("Открыто  •  ID " .. tostring(rec.entry)) or "Не открыто"
                listRow(y, opened and "✓" or "?", title, details, opened)
                y = y - 31
            end
        end

        local pageText = string.format("Страница %d / %d", state.catalogPage, state.catalogPages)
        addText(480, -581, 150, pageText, "GameFontNormalSmall", 0.62, 0.70, 0.75)
        local prev = addButton(210, -570, 110, 26, "Назад", function()
            if state.catalogPage > 1 then requestCatalog(state.catalogPage - 1, false) end
        end)
        local nextb = addButton(765, -570, 110, 26, "Вперёд", function()
            if state.catalogPage < state.catalogPages then requestCatalog(state.catalogPage + 1, false) end
        end)
        if state.catalogPage <= 1 then prev:Disable() end
        if state.catalogPage >= state.catalogPages then nextb:Disable() end
    end
end

local function drawLocations()
    addText(210, -176, 665, "Изучение мира", "GameFontHighlightLarge", 0.82, 0.93, 1.0)
    addText(210, -201, 665, "Новая зона фиксируется один раз на аккаунт и даёт очки знаний.", "GameFontNormalSmall", 0.60, 0.70, 0.76)

    local p = addPanel(210, -230, 665, 58, 0.80)
    local n = p:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    n:SetPoint("TOPLEFT", p, "TOPLEFT", 12, -9)
    n:SetText(currentZoneName())
    n:SetTextColor(0.72, 0.91, 1.0)
    local ids = p:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    ids:SetPoint("TOPLEFT", p, "TOPLEFT", 12, -31)
    ids:SetText(string.format("map %d   •   zone %d   •   area %d", state.map, state.zone, state.area))
    ids:SetTextColor(0.55, 0.65, 0.72)

    addText(210, -304, 665, "Последние открытые зоны", "GameFontHighlight", 0.78, 0.88, 0.94)
    local records = state.recent[3] or {}
    local y = -332
    if not state.recentLoaded[3] then
        addText(210, y, 650, "Получаю историю с сервера…", "GameFontNormal", 0.68, 0.74, 0.78)
    elseif #records == 0 then
        addText(210, y, 650, "Пока нет сохранённых зон.", "GameFontNormal", 0.68, 0.74, 0.78)
    else
        for i = 1, math.min(#records, 7) do
            local rec = records[i]
            local title = areaName(rec.entry) or ("Локация #" .. tostring(rec.entry))
            listRow(y, "Л", title, string.format("Карта %d  •  зона %d", rec.map or 0, rec.zone or 0), true)
            y = y - 31
        end
    end
end

local function drawAppearances()
    addText(210, -176, 665, "Облики спутника", "GameFontHighlightLarge", 0.82, 0.93, 1.0)
    addText(210, -201, 665, "Внешность не влияет на способности и будет открываться отдельно от талантов.", "GameFontNormalSmall", 0.60, 0.70, 0.76)

    local cards = {
        {"Живая книга", "Базовый облик", "Подготовка модели"},
        {"Хранитель знаний", "Награда достижения", "Закрыто"},
        {"Дух архива", "Редкое событие", "Закрыто"},
        {"Малый конструкт", "Торговец / коллекция", "Закрыто"},
    }
    local positions = {{210,-245},{550,-245},{210,-355},{550,-355}}
    for i, data in ipairs(cards) do
        local p = addPanel(positions[i][1], positions[i][2], 325, 92, 0.72)
        local preview = p:CreateTexture(nil, "ARTWORK")
        preview:SetPoint("LEFT", p, "LEFT", 12, 0)
        preview:SetSize(58, 58)
        preview:SetColorTexture(0.08, 0.18, 0.23, 1)
        local mark = p:CreateFontString(nil, "OVERLAY", "GameFontHighlightLarge")
        mark:SetPoint("CENTER", preview, "CENTER", 0, 0)
        mark:SetText("?")
        mark:SetTextColor(0.48, 0.72, 0.82)
        local name = p:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
        name:SetPoint("TOPLEFT", p, "TOPLEFT", 82, -14)
        name:SetText(data[1])
        name:SetTextColor(0.76, 0.91, 1.0)
        local desc = p:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
        desc:SetPoint("TOPLEFT", p, "TOPLEFT", 82, -37)
        desc:SetText(data[2])
        desc:SetTextColor(0.65, 0.69, 0.73)
        local st = p:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
        st:SetPoint("TOPLEFT", p, "TOPLEFT", 82, -59)
        st:SetText(data[3])
        st:SetTextColor(0.46, 0.52, 0.56)
    end
end

Draw = function()
    if not frame then return end
    clearDynamic()
    updateHeader()
    if current == 1 then drawTalents()
    elseif current == 2 then drawCatalog()
    elseif current == 3 then drawLocations()
    else drawAppearances() end
end

local function refreshCurrent()
    requestStatus(true)
    if current == 2 then
        later(0.25, function() requestCatalog(state.catalogPage or 1, true) end)
    elseif current == 3 then
        later(0.25, function() requestRecent(3, true) end)
    end
end

local function switchTab(index)
    current = index
    if db then db.currentTab = current end
    Draw()
    if current == 2 then
        later(0.20, function() requestCatalog(1, true) end)
    elseif current == 3 then
        later(0.20, function() requestRecent(3, true) end)
    end
end

local function CreateUI()
    if frame then return end

    frame = CreateFrame("Frame", "ForeverEncyclopediaFrame", UIParent, "BasicFrameTemplateWithInset")
    frame:SetSize(900, 620)
    frame:SetPoint("CENTER")
    frame:SetMovable(true)
    frame:EnableMouse(true)
    frame:RegisterForDrag("LeftButton")
    frame:SetScript("OnDragStart", frame.StartMoving)
    frame:SetScript("OnDragStop", frame.StopMovingOrSizing)
    frame:SetScript("OnShow", function() refreshCurrent() end)
    frame:Hide()

    frame.TitleText:SetText("Живая энциклопедия")
    if frame.TitleText.SetTextColor then frame.TitleText:SetTextColor(0.72, 0.91, 1.0) end

    local sidebar = frame:CreateTexture(nil, "BACKGROUND")
    sidebar:SetPoint("TOPLEFT", frame, "TOPLEFT", 10, -34)
    sidebar:SetPoint("BOTTOMLEFT", frame, "BOTTOMLEFT", 10, 10)
    sidebar:SetWidth(182)
    sidebar:SetColorTexture(0.025, 0.032, 0.042, 0.92)

    local brand = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightLarge")
    brand:SetPoint("TOPLEFT", frame, "TOPLEFT", 28, -58)
    brand:SetText("Архив знаний")
    brand:SetTextColor(0.66, 0.88, 0.98)

    local tabs = {
        {"Таланты", "Развитие спутника"},
        {"Существа", "Бестиарий зоны"},
        {"Локации", "Исследование мира"},
        {"Облики", "Внешность спутника"},
    }
    for i, data in ipairs(tabs) do
        local b = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
        b:SetSize(148, 38)
        b:SetPoint("TOPLEFT", frame, "TOPLEFT", 26, -98 - (i - 1) * 52)
        b:SetText(data[1])
        b:SetScript("OnClick", function() switchTab(i) end)
        navButtons[i] = b

        local hint = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
        hint:SetPoint("TOPLEFT", b, "BOTTOMLEFT", 6, -1)
        hint:SetText(data[2])
        hint:SetTextColor(0.42, 0.48, 0.53)
    end

    local refresh = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
    refresh:SetSize(148, 28)
    refresh:SetPoint("BOTTOMLEFT", frame, "BOTTOMLEFT", 26, 38)
    refresh:SetText("Обновить")
    refresh:SetScript("OnClick", refreshCurrent)

    local version = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    version:SetPoint("BOTTOMLEFT", frame, "BOTTOMLEFT", 28, 18)
    version:SetText("v0.4.0 • серверный каталог")
    version:SetTextColor(0.38, 0.43, 0.47)

    statusText = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    statusText:SetPoint("TOPLEFT", frame, "TOPLEFT", 210, -52)
    statusText:SetWidth(430)
    statusText:SetJustifyH("LEFT")

    locationText = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    locationText:SetPoint("TOPRIGHT", frame, "TOPRIGHT", -28, -52)
    locationText:SetWidth(250)
    locationText:SetJustifyH("RIGHT")
    locationText:SetTextColor(0.70, 0.80, 0.86)

    local labels = {"Очки знаний", "Существа", "Предметы", "Локации"}
    for i = 1, 4 do
        local x = 210 + (i - 1) * 168
        local p = CreateFrame("Frame", nil, frame)
        p:SetPoint("TOPLEFT", frame, "TOPLEFT", x, -86)
        p:SetSize(153, 66)
        local bg = p:CreateTexture(nil, "BACKGROUND")
        bg:SetAllPoints()
        bg:SetColorTexture(0.045, 0.06, 0.075, 0.92)
        local line = p:CreateTexture(nil, "BORDER")
        line:SetPoint("TOPLEFT", p, "TOPLEFT", 0, 0)
        line:SetPoint("TOPRIGHT", p, "TOPRIGHT", 0, 0)
        line:SetHeight(2)
        line:SetColorTexture(0.17, 0.48, 0.63, 0.90)

        local value = p:CreateFontString(nil, "OVERLAY", "GameFontHighlightLarge")
        value:SetPoint("TOPLEFT", p, "TOPLEFT", 12, -11)
        value:SetText("0")
        value:SetTextColor(0.75, 0.92, 1.0)
        statValues[i] = value

        local label = p:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
        label:SetPoint("BOTTOMLEFT", p, "BOTTOMLEFT", 12, 9)
        label:SetText(labels[i])
        label:SetTextColor(0.52, 0.61, 0.67)
    end

    current = (db and tonumber(db.currentTab)) or 1
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
        if current == 2 then Draw() end
        return
    end

    if text:sub(1, 4) == "CAT|" then
        local _, entry, known, name = strsplit("|", text)
        state.catalog[#state.catalog + 1] = {
            entry = tonumber(entry) or 0,
            known = tonumber(known) == 1,
            name = name or "",
        }
        return
    end

    if text == "CATEND" then
        state.catalogLoaded = true
        state.online = true
        if current == 2 then Draw() end
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
        if current == 1 then Draw() else updateHeader() end
    elseif tag == "CURRENT" then
        local oldZone = state.zone
        state.map = tonumber(a) or 0
        state.zone = tonumber(b) or 0
        state.area = tonumber(c) or 0
        if oldZone ~= 0 and oldZone ~= state.zone then
            state.catalogPage = 1
            state.catalogLoaded = false
            state.catalog = {}
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
        if current == 3 and kind == 3 then Draw() end
    elseif tag == "ERROR" then
        state.online = false
        chat((a or "Ошибка сервера") .. (b and (" " .. tostring(b)) or ""))
        updateHeader()
    elseif tag == "END" then
        waiting = false
        retriedSelf = false
        state.online = true
        Draw()
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
    end
    later(1.0, function()
        requestStatus(true)
        if frame and frame:IsShown() then
            if current == 2 then later(0.25, function() requestCatalog(1, true) end)
            elseif current == 3 then later(0.25, function() requestRecent(3, true) end) end
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
