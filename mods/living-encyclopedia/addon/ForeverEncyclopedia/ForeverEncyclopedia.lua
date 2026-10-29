local ADDON = ...
local REQUEST = "FEC1"
local RESPONSE = "FER1"
local SERVER_TARGET = "SERVER"
local frame
local current = 1
local lines = {}
local state = { total = 0, creatures = 0, items = 0, zones = 0, map = 0, zone = 0, area = 0, online = false }
local lastStatus = 0
local waiting = false
local retriedSelf = false

local function chat(msg)
    if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cff66ccff[Энциклопедия]|r " .. tostring(msg)) end
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

local function Text(parent, x, y, value)
    local t = parent:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    t:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
    t:SetWidth(485)
    t:SetJustifyH("LEFT")
    t:SetText(value)
    return t
end

local function clearLines()
    for _, line in ipairs(lines) do line:Hide() end
    wipe(lines)
end

local function Draw()
    if not frame then return end
    clearLines()
    local function add(y, text)
        lines[#lines + 1] = Text(frame, 24, y, text)
    end
    local status = state.online and "|cff55ff55связь с сервером есть|r" or "|cffff5555нет ответа сервера|r"
    add(-88, "Состояние: " .. status)
    add(-112, string.format("Открытий: %d   Существа: %d   Предметы: %d   Локации: %d", state.total, state.creatures, state.items, state.zones))

    if current == 1 then
        add(-152, "Таланты спутника ещё не подключены к игровой логике.")
        add(-178, "Подготовленные лимиты: лечение 25–40% HP, щит до 30% HP.")
        add(-204, "Регенерация: 1 мана/5 с в бою, 5 маны/5 с вне боя.")
    elseif current == 2 then
        add(-152, "Бестиарий уже записывает уникальные убийства существ на аккаунт.")
        add(-178, "Найдено уникальных существ: " .. tostring(state.creatures))
        add(-204, "Полный список по зонам и неизвестные существа — следующий этап.")
    elseif current == 3 then
        add(-152, string.format("Текущие ID: карта %d, зона %d, область %d", state.map, state.zone, state.area))
        add(-178, "Посещение новой зоны записывается один раз на аккаунт.")
        add(-204, "Изучено уникальных зон: " .. tostring(state.zones))
    else
        add(-152, "Облики: книги, библиотекари, духи и конструкты.")
        add(-178, "Разблокировка достижениями/торговцами предусмотрена архитектурой.")
        add(-204, "DisplayID будут добавляться только после проверки моделей клиента.")
    end
end

local function CreateUI()
    if frame then return end
    frame = CreateFrame("Frame", "ForeverEncyclopediaFrame", UIParent, "BasicFrameTemplateWithInset")
    frame:SetSize(540, 340)
    frame:SetPoint("CENTER")
    frame:SetMovable(true)
    frame:EnableMouse(true)
    frame:RegisterForDrag("LeftButton")
    frame:SetScript("OnDragStart", frame.StartMoving)
    frame:SetScript("OnDragStop", frame.StopMovingOrSizing)
    frame:SetScript("OnShow", function() requestStatus(true) end)
    frame:Hide()
    frame.TitleText:SetText("Живая энциклопедия")
    local tabs = {"Таланты", "Существа", "Локации", "Облики"}
    for i, name in ipairs(tabs) do
        local b = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
        b:SetSize(118, 25)
        b:SetPoint("TOPLEFT", 22 + (i - 1) * 126, -49)
        b:SetText(name)
        b:SetScript("OnClick", function() current = i; Draw() end)
    end
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
    elseif tag == "CURRENT" then
        state.map = tonumber(a) or 0
        state.zone = tonumber(b) or 0
        state.area = tonumber(c) or 0
        Draw()
    elseif tag == "ERROR" then
        state.online = false
        if b then a = tostring(a or "") .. " " .. tostring(b) end
        chat(a or "Ошибка сервера")
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
    if C_Timer and C_Timer.After then C_Timer.After(1.0, function() requestStatus(true) end)
    else requestStatus(true) end
end)

events:SetScript("OnUpdate", function(_, dt)
    if not waiting then return end
    local now = GetTime and GetTime() or 0
    if not retriedSelf and now - lastStatus >= 2.0 then
        local name = UnitName and UnitName("player")
        if name then retriedSelf = true; sendRaw("status", name, true) end
    end
    if now - lastStatus >= 6.0 then
        waiting = false
        state.online = false
        Draw()
    end
end)
