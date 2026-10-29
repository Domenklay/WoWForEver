local ADDON = ...
local REQUEST = "FEC1"
local RESPONSE = "FER1"
local SERVER_TARGET = "SERVER"

local frame
local current = 1
local dynamic = {}
local navButtons = {}
local statValues = {}
local statusText
local locationText

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
    local ok, result = pcall(C_ChatInfo.SendAddonMessage, REQUEST, payload, "WHISPER", target)
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

local function later(delay, fn)
    if C_Timer and C_Timer.After then C_Timer.After(delay, fn) else fn() end
end

local function addDynamic(object)
    dynamic[#dynamic + 1] = object
    return object
end

local function clearDynamic()
    for _, object in ipairs(dynamic) do object:Hide() end
    wipe(dynamic)
end

local function makeText(parent, anchor, relative, relPoint, x, y, width, text, font)
    local t = parent:CreateFontString(nil, "OVERLAY", font or "GameFontHighlight")
    t:SetPoint(anchor, relative, relPoint, x, y)
    if width then t:SetWidth(width) end
    t:SetJustifyH("LEFT")
    t:SetText(text or "")
    return t
end

local function addText(x, y, width, text, font, r, g, b)
    local t = addDynamic(makeText(frame, "TOPLEFT", frame, "TOPLEFT", x, y, width, text, font))
    if r then t:SetTextColor(r, g, b) end
    return t
end

local function addPanel(x, y, width, height, alpha)
    local p = addDynamic(CreateFrame("Frame", nil, frame))
    p:SetPoint("TOPLEFT", frame, "TOPLEFT", x, y)
    p:SetSize(width, height)
    local bg = p:CreateTexture(nil, "BACKGROUND")
    bg:SetAllPoints()
    bg:SetColorTexture(0.055, 0.07, 0.085, alpha or 0.82)
    local top = p:CreateTexture(nil, "BORDER")
    top:SetPoint("TOPLEFT", p, "TOPLEFT", 0, 0)
    top:SetPoint("TOPRIGHT", p, "TOPRIGHT", 0, 0)
    top:SetHeight(1)
    top:SetColorTexture(0.22, 0.42, 0.52, 0.8)
    return p
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

local function itemName(id)
    if GetItemInfo then
        local ok, name = pcall(GetItemInfo, id)
        if ok and name and name ~= "" then return name end
    end
    return nil
end

local function updateHeader()
    if not frame then return end

    if statusText then
        if state.online then
            statusText:SetText("●  Синхронизация активна   •   открытий: " .. tostring(state.total))
            statusText:SetTextColor(0.35, 0.9, 0.55)
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
            else fs:SetTextColor(0.85, 0.85, 0.85) end
        end
    end
end

local function listRow(y, iconText, title, details)
    local row = addPanel(214, y, 520, 34, 0.65)
    local badge = row:CreateTexture(nil, "ARTWORK")
    badge:SetPoint("LEFT", row, "LEFT", 8, 0)
    badge:SetSize(22, 22)
    badge:SetColorTexture(0.12, 0.28, 0.36, 0.95)

    local glyph = row:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    glyph:SetPoint("CENTER", badge, "CENTER", 0, 0)
    glyph:SetText(iconText or "•")
    glyph:SetTextColor(0.7, 0.92, 1.0)

    local titleText = row:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    titleText:SetPoint("TOPLEFT", row, "TOPLEFT", 40, -5)
    titleText:SetWidth(325)
    titleText:SetJustifyH("LEFT")
    titleText:SetText(title or "")
    titleText:SetTextColor(0.95, 0.95, 0.95)

    local detailText = row:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    detailText:SetPoint("TOPLEFT", row, "TOPLEFT", 40, -19)
    detailText:SetWidth(465)
    detailText:SetJustifyH("LEFT")
    detailText:SetText(details or "")
    detailText:SetTextColor(0.58, 0.68, 0.75)
end

local function drawRecent(kind, title, subtitle)
    addText(214, -176, 520, title, "GameFontHighlightLarge", 0.88, 0.95, 1.0)
    addText(214, -201, 520, subtitle, "GameFontNormalSmall", 0.6, 0.7, 0.77)

    local records = state.recent[kind] or {}
    if not state.recentLoaded[kind] then
        addText(214, -246, 500, "Получаю список с сервера…", "GameFontNormal", 0.7, 0.8, 0.85)
        return
    end
    if #records == 0 then
        addText(214, -246, 500, "Пока нет открытий этого типа.", "GameFontNormal", 0.7, 0.8, 0.85)
        return
    end

    local y = -232
    for i = 1, math.min(#records, 8) do
        local rec = records[i]
        local name
        local icon = "?"
        if kind == 1 then
            name = "Существо #" .. tostring(rec.entry)
            icon = "С"
        elseif kind == 2 then
            name = itemName(rec.entry) or ("Предмет #" .. tostring(rec.entry))
            icon = "П"
        else
            name = areaName(rec.entry) or ("Локация #" .. tostring(rec.entry))
            icon = "Л"
        end
        listRow(y, icon, name, string.format("Карта %d  •  зона %d", rec.map or 0, rec.zone or 0))
        y = y - 38
    end
end

local function drawTalents()
    addText(214, -176, 520, "Таланты спутника", "GameFontHighlightLarge", 0.88, 0.95, 1.0)
    addText(214, -201, 520, "Очки знаний уже начисляются сервером за первые уникальные открытия. Покупка талантов пока заблокирована.", "GameFontNormalSmall", 0.6, 0.7, 0.77)

    local progress = addPanel(214, -232, 520, 54, 0.8)
    local p1 = progress:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    p1:SetPoint("TOPLEFT", progress, "TOPLEFT", 12, -9)
    p1:SetText("Доступно очков знаний: " .. tostring(state.knowledgeAvailable))
    p1:SetTextColor(0.72, 0.92, 1.0)
    local p2 = progress:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    p2:SetPoint("TOPLEFT", progress, "TOPLEFT", 12, -31)
    p2:SetText(string.format("Всего получено: %d   •   потрачено: %d   •   награждённых открытий: %d",
        state.knowledgeTotal, state.knowledgeSpent, state.rewardedDiscoveries))
    p2:SetTextColor(0.58, 0.68, 0.75)

    local branches = {
        { "Защита", "Щиты и снижение входящего урона", "до 30% HP" },
        { "Исцеление", "Помощь владельцу и группе", "25% → 40% HP" },
        { "Усиление", "Короткие полезные эффекты", "подготовка" },
        { "Мудрость", "Эффективность маны спутника", "1/5 и 5/5 сек" },
        { "Познание", "Бонусы за заполнение энциклопедии", "подготовка" },
    }
    local positions = {{214,-300},{480,-300},{214,-382},{480,-382},{347,-464}}

    for i, branch in ipairs(branches) do
        local p = addPanel(positions[i][1], positions[i][2], 250, 66, 0.72)
        local name = p:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
        name:SetPoint("TOPLEFT", p, "TOPLEFT", 12, -9)
        name:SetText(branch[1])
        name:SetTextColor(0.75, 0.9, 1.0)
        local desc = p:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
        desc:SetPoint("TOPLEFT", p, "TOPLEFT", 12, -27)
        desc:SetWidth(220)
        desc:SetJustifyH("LEFT")
        desc:SetText(branch[2])
        desc:SetTextColor(0.7, 0.74, 0.78)
        local lock = p:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
        lock:SetPoint("BOTTOMLEFT", p, "BOTTOMLEFT", 12, 7)
        lock:SetText("Заблокировано  •  " .. branch[3])
        lock:SetTextColor(0.5, 0.55, 0.6)
    end
end

local function drawLocations()
    addText(214, -176, 520, "Изучение мира", "GameFontHighlightLarge", 0.88, 0.95, 1.0)
    addText(214, -201, 520, "Текущая область записывается на аккаунт один раз. Ниже — последние открытые зоны.", "GameFontNormalSmall", 0.6, 0.7, 0.77)

    local currentPanel = addPanel(214, -232, 520, 58, 0.8)
    local name = currentPanel:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    name:SetPoint("TOPLEFT", currentPanel, "TOPLEFT", 12, -9)
    name:SetText(currentZoneName())
    name:SetTextColor(0.8, 0.93, 1.0)
    local ids = currentPanel:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    ids:SetPoint("TOPLEFT", currentPanel, "TOPLEFT", 12, -31)
    ids:SetText(string.format("map %d   zone %d   area %d", state.map, state.zone, state.area))
    ids:SetTextColor(0.55, 0.65, 0.72)

    local records = state.recent[3] or {}
    local y = -301
    if not state.recentLoaded[3] then
        addText(214, y, 500, "Получаю список с сервера…", "GameFontNormal", 0.7, 0.8, 0.85)
    elseif #records == 0 then
        addText(214, y, 500, "Пока нет сохранённых зон.", "GameFontNormal", 0.7, 0.8, 0.85)
    else
        for i = 1, math.min(#records, 5) do
            local rec = records[i]
            local title = areaName(rec.entry) or ("Локация #" .. tostring(rec.entry))
            listRow(y, "Л", title, string.format("Карта %d  •  зона %d", rec.map or 0, rec.zone or 0))
            y = y - 38
        end
    end
end

local function drawAppearances()
    addText(214, -176, 520, "Облики спутника", "GameFontHighlightLarge", 0.88, 0.95, 1.0)
    addText(214, -201, 520, "Внешность не влияет на способности. Модели будут открываться отдельно от талантов.", "GameFontNormalSmall", 0.6, 0.7, 0.77)

    local cards = {
        {"Живая книга", "Базовый облик", "Стандарт"},
        {"Хранитель знаний", "Разблокировка достижением", "Закрыто"},
        {"Дух архива", "Редкая награда события", "Закрыто"},
        {"Малый конструкт", "Торговец / коллекция", "Закрыто"},
    }
    local positions = {{214,-236},{480,-236},{214,-337},{480,-337}}

    for i, data in ipairs(cards) do
        local p = addPanel(positions[i][1], positions[i][2], 250, 86, 0.72)
        local preview = p:CreateTexture(nil, "ARTWORK")
        preview:SetPoint("LEFT", p, "LEFT", 10, 0)
        preview:SetSize(52, 52)
        preview:SetColorTexture(0.1, 0.2, 0.25, 1)
        local mark = p:CreateFontString(nil, "OVERLAY", "GameFontHighlightLarge")
        mark:SetPoint("CENTER", preview, "CENTER", 0, 0)
        mark:SetText(i == 1 and "К" or "?")
        mark:SetTextColor(0.65, 0.88, 1)
        local title = p:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
        title:SetPoint("TOPLEFT", p, "TOPLEFT", 72, -13)
        title:SetText(data[1])
        local desc = p:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
        desc:SetPoint("TOPLEFT", p, "TOPLEFT", 72, -34)
        desc:SetWidth(165)
        desc:SetJustifyH("LEFT")
        desc:SetText(data[2])
        desc:SetTextColor(0.65, 0.7, 0.75)
        local status = p:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
        status:SetPoint("BOTTOMLEFT", p, "BOTTOMLEFT", 72, 10)
        status:SetText(data[3])
        if i == 1 then status:SetTextColor(0.35, 0.9, 0.55) else status:SetTextColor(0.55, 0.58, 0.62) end
    end
end

local function Draw()
    if not frame then return end
    clearDynamic()
    updateHeader()

    if current == 1 then drawTalents()
    elseif current == 2 then drawRecent(1, "Бестиарий", "Уникальные существа сохраняются на весь аккаунт. Показаны последние открытия.")
    elseif current == 3 then drawLocations()
    else drawAppearances() end
end

local function requestCurrentTab()
    if current == 2 then requestRecent(1, true)
    elseif current == 3 then requestRecent(3, true) end
end

local function CreateUI()
    if frame then return end

    frame = CreateFrame("Frame", "ForeverEncyclopediaFrame", UIParent, "BasicFrameTemplateWithInset")
    frame:SetSize(760, 540)
    frame:SetPoint("CENTER")
    frame:SetMovable(true)
    frame:EnableMouse(true)
    frame:RegisterForDrag("LeftButton")
    frame:SetScript("OnDragStart", frame.StartMoving)
    frame:SetScript("OnDragStop", frame.StopMovingOrSizing)
    frame:SetScript("OnShow", function()
        requestStatus(true)
        later(0.30, requestCurrentTab)
    end)
    frame:Hide()
    frame.TitleText:SetText("Живая энциклопедия")

    statusText = makeText(frame, "TOPLEFT", frame, "TOPLEFT", 22, -38, 300, "●  Проверка связи…", "GameFontNormalSmall")
    statusText:SetTextColor(0.65, 0.7, 0.75)
    locationText = makeText(frame, "TOPRIGHT", frame, "TOPRIGHT", -48, -38, 360, "", "GameFontNormalSmall")
    locationText:SetJustifyH("RIGHT")
    locationText:SetTextColor(0.65, 0.72, 0.78)

    local refresh = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
    refresh:SetSize(90, 22)
    refresh:SetPoint("TOPRIGHT", frame, "TOPRIGHT", -18, -57)
    refresh:SetText("Обновить")
    refresh:SetScript("OnClick", function()
        requestStatus(false)
        later(0.30, requestCurrentTab)
    end)

    local tabs = {"Таланты", "Существа", "Локации", "Облики"}
    for i, name in ipairs(tabs) do
        local b = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
        b:SetSize(170, 28)
        b:SetPoint("TOPLEFT", frame, "TOPLEFT", 22, -87 - (i - 1) * 36)
        b:SetText(name)
        b:SetScript("OnClick", function()
            current = i
            Draw()
            later(0.05, requestCurrentTab)
        end)
        navButtons[i] = b
    end

    local statNames = {"Очки знаний", "Существа", "Предметы", "Локации"}
    for i, name in ipairs(statNames) do
        local p = CreateFrame("Frame", nil, frame)
        p:SetSize(122, 58)
        p:SetPoint("TOPLEFT", frame, "TOPLEFT", 214 + (i - 1) * 130, -90)
        local bg = p:CreateTexture(nil, "BACKGROUND")
        bg:SetAllPoints()
        bg:SetColorTexture(0.055, 0.07, 0.085, 0.82)
        local top = p:CreateTexture(nil, "BORDER")
        top:SetPoint("TOPLEFT", p, "TOPLEFT", 0, 0)
        top:SetPoint("TOPRIGHT", p, "TOPRIGHT", 0, 0)
        top:SetHeight(2)
        top:SetColorTexture(0.15, 0.45, 0.58, 0.9)
        local label = p:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
        label:SetPoint("TOPLEFT", p, "TOPLEFT", 9, -8)
        label:SetText(name)
        label:SetTextColor(0.58, 0.68, 0.75)
        local value = p:CreateFontString(nil, "OVERLAY", "GameFontHighlightLarge")
        value:SetPoint("BOTTOMLEFT", p, "BOTTOMLEFT", 9, 7)
        value:SetText("0")
        value:SetTextColor(0.82, 0.94, 1.0)
        statValues[i] = value
    end

    local divider = frame:CreateTexture(nil, "ARTWORK")
    divider:SetPoint("TOPLEFT", frame, "TOPLEFT", 202, -82)
    divider:SetPoint("BOTTOMLEFT", frame, "BOTTOMLEFT", 202, 18)
    divider:SetWidth(1)
    divider:SetColorTexture(0.16, 0.22, 0.26, 0.9)

    Draw()
end

local function parseResponse(text)
    local tag, a, b, c, d = strsplit(" ", tostring(text or ""), 5)
    if tag == "STATE" then
        state.total = tonumber(a) or 0
        state.creatures = tonumber(b) or 0
        state.items = tonumber(c) or 0
        state.zones = tonumber(d) or 0
        state.online = true
        Draw()
    elseif tag == "KNOW" then
        state.knowledgeTotal = tonumber(a) or 0
        state.knowledgeSpent = tonumber(b) or 0
        state.knowledgeAvailable = tonumber(c) or 0
        state.rewardedDiscoveries = tonumber(d) or 0
        Draw()
    elseif tag == "CURRENT" then
        state.map = tonumber(a) or 0
        state.zone = tonumber(b) or 0
        state.area = tonumber(c) or 0
        Draw()
    elseif tag == "REC" then
        local kind = tonumber(a)
        if kind and state.recent[kind] then
            state.recent[kind][#state.recent[kind] + 1] = {
                entry = tonumber(b) or 0,
                map = tonumber(c) or 0,
                zone = tonumber(d) or 0,
            }
        end
    elseif tag == "RECEND" then
        local kind = tonumber(a)
        if kind and state.recentLoaded[kind] ~= nil then
            state.recentLoaded[kind] = true
            Draw()
        end
    elseif tag == "ERROR" then
        state.online = false
        local message = tostring(a or "Ошибка сервера")
        if b then message = message .. " " .. tostring(b) end
        chat(message)
        Draw()
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
    elseif text == "status" then
        requestStatus(false)
    else
        chat("Команды: /ency, /ency status")
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
        registerPrefixes()
        return
    end

    if event == "CHAT_MSG_ADDON" then
        local prefix, text = ...
        if prefix == RESPONSE then parseResponse(text) end
        return
    end

    registerPrefixes()
    later(1.0, function()
        requestStatus(true)
        if frame and frame:IsShown() then later(0.30, requestCurrentTab) end
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
        Draw()
    end
end)
