-- UI prototype. No addon messages or server mutations until server adapter exists.
local ADDON = ...
local db
local frame
local tabs = {"Таланты", "Существа", "Локации", "Облики"}
local current = 1
local lines = {}
local function Text(parent, size, x, y, value)
    local t = parent:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    t:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
    t:SetWidth(485)
    t:SetJustifyH("LEFT")
    t:SetText(value)
    return t
end
local function Draw()
    if not frame then return end
    for _, line in ipairs(lines) do line:Hide() end
    wipe(lines)
    local function add(y, s)
        lines[#lines+1] = Text(frame, 12, 24, y, s)
    end
    if current == 1 then
        add(-95, "Защита | Исцеление | Усиление | Мудрость | Познание")
        add(-125, "Щит: не более 30% максимального HP")
        add(-150, "Исцеление: 25% HP, до 40% после прокачки")
        add(-175, "Регенерация: 1 мана/5 с в бою; 5 маны/5 с вне боя")
        add(-210, "Очки и таланты появятся после подключения сервера.")
    elseif current == 2 then
        add(-95, "Бестиарий: впервые обнаруженные и ещё неизвестные существа")
        add(-125, "Данные поступят из серверного индекса существ.")
    elseif current == 3 then
        add(-95, "Выбор континента, зоны и подземелья")
        add(-125, "Фильтры: все / изученные / неизвестные / редкие / боссы")
        add(-155, "Каталог станет доступен после синхронизации с worldserver.")
    else
        add(-95, "Облики: книги, библиотекари, духи, конструкты")
        add(-125, "Разблокировка: достижения, торговцы, события")
        add(-155, "Облики и DisplayID появятся после проверки клиентских моделей.")
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
    frame:Hide()
    frame.TitleText:SetText("Живая энциклопедия — прототип")
    for i, name in ipairs(tabs) do
        local b = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
        b:SetSize(118, 25)
        b:SetPoint("TOPLEFT", 22 + (i-1)*126, -49)
        b:SetText(name)
        b:SetScript("OnClick", function() current = i; Draw() end)
    end
    Draw()
end
SLASH_FOREVERENCYCLOPEDIA1 = "/encyclopedia"
SLASH_FOREVERENCYCLOPEDIA2 = "/ency"
SlashCmdList.FOREVERENCYCLOPEDIA = function()
    CreateUI()
    if frame:IsShown() then frame:Hide() else frame:Show() end
end
local events = CreateFrame("Frame")
events:RegisterEvent("ADDON_LOADED")
events:SetScript("OnEvent", function(_, _, name)
    if name ~= ADDON then return end
    ForeverEncyclopediaDB = ForeverEncyclopediaDB or {}
    db = ForeverEncyclopediaDB
end)
