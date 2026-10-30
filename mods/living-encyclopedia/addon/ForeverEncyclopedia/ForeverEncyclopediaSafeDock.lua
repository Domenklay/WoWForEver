local RESPONSE = "FBR1"
local REQUEST = "FEB1"
local TALENT_RESPONSE = "FTR1"
local BASE_RESPONSE = "FER1"
local SERVER_TARGET = "SERVER"

local dock
local manaBar
local manaText
local feedbackText
local feedbackSerial = 0
local abilityButtons = {}
local state = {
    mana = 0,
    maxMana = 100,
    mask = 0,
    cooldowns = { 0, 0, 0 },
    barrier = 0,
    companion = false,
    casts = false,
}

local function registerPrefix(prefix)
    if C_ChatInfo and C_ChatInfo.RegisterAddonMessagePrefix then
        pcall(C_ChatInfo.RegisterAddonMessagePrefix, prefix)
    end
end

local function sendRuntime(payload)
    registerPrefix(REQUEST)
    registerPrefix(RESPONSE)
    if C_ChatInfo and C_ChatInfo.SendAddonMessage then
        pcall(C_ChatInfo.SendAddonMessage, REQUEST, payload, "WHISPER", SERVER_TARGET)
    end
end

local function sendStatus() sendRuntime("status") end
_G.ForeverEncyclopediaRuntimeRefresh = sendStatus

local function unlocked(bit)
    if bit32 then return bit32.band(state.mask, bit) ~= 0 end
    return state.mask % (bit * 2) >= bit
end

local function hideLegacyDock()
    for _, name in ipairs({"ForeverEncyclopediaV21BookDock", "ForeverEncyclopediaV2BookDock", "ForeverEncyclopediaBookDock"}) do
        local legacy = _G[name]
        if legacy then
            legacy:Hide()
            legacy:SetAlpha(0)
            legacy:EnableMouse(false)
        end
    end
end

local function addBorder(frame, r, g, b, a)
    local function edge(point1, point2, width, height)
        local t = frame:CreateTexture(nil, "BORDER")
        t:SetColorTexture(r, g, b, a or 1)
        t:SetPoint(point1)
        t:SetPoint(point2)
        if width then t:SetWidth(width) end
        if height then t:SetHeight(height) end
    end
    edge("TOPLEFT", "TOPRIGHT", nil, 1)
    edge("BOTTOMLEFT", "BOTTOMRIGHT", nil, 1)
    edge("TOPLEFT", "BOTTOMLEFT", 1, nil)
    edge("TOPRIGHT", "BOTTOMRIGHT", 1, nil)
end

local function placeDock()
    if not dock then return end
    dock:ClearAllPoints()
    if ChatFrame1 then
        dock:SetPoint("BOTTOMLEFT", ChatFrame1, "TOPLEFT", 8, 14)
    elseif ChatFrameMenuButton then
        dock:SetPoint("BOTTOMLEFT", ChatFrameMenuButton, "TOPLEFT", 0, 52)
    else
        dock:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", 28, 210)
    end
end

local abilityDefs = {
    { bit = 1, icon = "Interface\\Icons\\Spell_Holy_PowerWordShield", name = "Охранная печать" },
    { bit = 2, icon = "Interface\\Icons\\Spell_Holy_Heal", name = "Целительная пометка" },
    { bit = 4, icon = "Interface\\Icons\\Spell_Arcane_Arcane01", name = "Тактическая подсказка" },
}

local function feedback(text, r, g, b)
    if not feedbackText then return end
    feedbackSerial = feedbackSerial + 1
    local serial = feedbackSerial
    feedbackText:SetText(text or "")
    feedbackText:SetTextColor(r or 1, g or 1, b or 1)
    feedbackText:SetAlpha(1)
    C_Timer.After(2.4, function()
        if feedbackText and serial == feedbackSerial then feedbackText:SetText("") end
    end)
end

local function update()
    if not dock then return end
    hideLegacyDock()
    local maxMana = math.max(1, tonumber(state.maxMana) or 100)
    local mana = math.max(0, math.min(maxMana, tonumber(state.mana) or 0))
    manaBar:SetMinMaxValues(0, maxMana)
    manaBar:SetValue(mana)
    manaText:SetText(mana .. "/" .. maxMana)

    for i, button in ipairs(abilityButtons) do
        local def = abilityDefs[i]
        local isUnlocked = unlocked(def.bit)
        button.icon:SetAlpha(isUnlocked and 1 or 0.22)
        button.lock:SetShown(not isUnlocked)
        local seconds = tonumber(state.cooldowns[i]) or 0
        if button.cooldown and button.cooldown.SetCooldown then
            if seconds > 0 then button.cooldown:SetCooldown(GetTime(), seconds)
            elseif button.cooldown.Clear then button.cooldown:Clear() end
        end
    end
end

local function createDock()
    if dock then placeDock(); hideLegacyDock(); update(); return end

    hideLegacyDock()
    dock = CreateFrame("Frame", "ForeverEncyclopediaSafeDock", UIParent)
    dock:SetSize(164, 46)
    dock:SetFrameStrata("MEDIUM")
    dock:SetClampedToScreen(true)
    dock:EnableMouse(false)
    placeDock()

    feedbackText = dock:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    feedbackText:SetPoint("BOTTOMLEFT", dock, "TOPLEFT", 0, 3)
    feedbackText:SetJustifyH("LEFT")
    feedbackText:SetText("")

    local book = CreateFrame("Button", nil, dock)
    book:RegisterForClicks("LeftButtonUp", "RightButtonUp")
    book:SetSize(42, 42)
    book:SetPoint("LEFT", dock, "LEFT", 0, 0)
    local bookBg = book:CreateTexture(nil, "BACKGROUND")
    bookBg:SetAllPoints()
    bookBg:SetColorTexture(0.035, 0.020, 0.010, 0.94)
    addBorder(book, 0.52, 0.34, 0.10, 1)
    local icon = book:CreateTexture(nil, "ARTWORK")
    icon:SetPoint("TOPLEFT", book, "TOPLEFT", 4, -4)
    icon:SetPoint("BOTTOMRIGHT", book, "BOTTOMRIGHT", -4, 4)
    icon:SetTexture("Interface\\Icons\\INV_Misc_Book_09")
    book:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_TOP")
        GameTooltip:AddLine("Живая энциклопедия", 1, 0.82, 0.42)
        GameTooltip:AddLine("ЛКМ: открыть архив знаний", 0.78, 0.78, 0.78)
        GameTooltip:AddLine("ПКМ: показать/скрыть спутника", 0.78, 0.78, 0.78)
        GameTooltip:AddLine("Спутник: " .. (state.companion and "в мире" or "скрыт"), state.companion and 0.45 or 0.65, state.companion and 1.0 or 0.65, 0.45)
        GameTooltip:AddLine("Боевые касты: " .. (state.casts and "включены" or "выключены"), state.casts and 1.0 or 0.65, state.casts and 0.7 or 0.65, 0.35)
        GameTooltip:Show()
    end)
    book:SetScript("OnLeave", function() GameTooltip:Hide() end)
    book:SetScript("OnClick", function(_, button)
        if button == "RightButton" then
            sendRuntime("companion toggle")
            return
        end
        local handler = SlashCmdList and SlashCmdList["FOREVERENCYCLOPEDIAV21"]
        if handler then handler() end
    end)

    manaBar = CreateFrame("StatusBar", nil, dock)
    manaBar:SetPoint("TOPLEFT", dock, "TOPLEFT", 48, -2)
    manaBar:SetSize(112, 9)
    manaBar:SetStatusBarTexture("Interface\\TargetingFrame\\UI-StatusBar")
    manaBar:SetStatusBarColor(0.18, 0.36, 0.72)
    local manaBg = manaBar:CreateTexture(nil, "BACKGROUND")
    manaBg:SetAllPoints()
    manaBg:SetColorTexture(0.015, 0.015, 0.022, 0.92)
    addBorder(manaBar, 0.30, 0.22, 0.10, 0.95)
    manaText = manaBar:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    manaText:SetPoint("CENTER", manaBar, "CENTER", 0, 0)

    for i, def in ipairs(abilityDefs) do
        local button = CreateFrame("Button", nil, dock)
        button:SetSize(30, 30)
        button:SetPoint("TOPLEFT", dock, "TOPLEFT", 48 + (i - 1) * 37, -14)
        local bg = button:CreateTexture(nil, "BACKGROUND")
        bg:SetAllPoints()
        bg:SetColorTexture(0.035, 0.022, 0.012, 0.96)
        addBorder(button, 0.38, 0.25, 0.08, 1)
        button.icon = button:CreateTexture(nil, "ARTWORK")
        button.icon:SetPoint("TOPLEFT", button, "TOPLEFT", 3, -3)
        button.icon:SetPoint("BOTTOMRIGHT", button, "BOTTOMRIGHT", -3, 3)
        button.icon:SetTexture(def.icon)
        button.lock = button:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
        button.lock:SetPoint("CENTER")
        button.lock:SetText("×")
        button.lock:SetTextColor(0.72, 0.58, 0.46)
        button.cooldown = CreateFrame("Cooldown", nil, button, "CooldownFrameTemplate")
        button.cooldown:SetAllPoints(button.icon)
        button.cooldown:SetFrameLevel(button:GetFrameLevel() + 5)
        button:SetScript("OnEnter", function(self)
            GameTooltip:SetOwner(self, "ANCHOR_TOP")
            GameTooltip:AddLine(def.name, 1, 0.82, 0.42)
            if unlocked(def.bit) then
                local cd = tonumber(state.cooldowns[i]) or 0
                GameTooltip:AddLine(cd > 0 and ("Перезарядка: " .. cd .. " сек.") or "Готово", 0.72, 0.82, 0.68)
                if not state.casts then GameTooltip:AddLine("Диагностика: касты временно выключены.", 0.85, 0.55, 0.25) end
            else
                GameTooltip:AddLine(i == 3 and "Нативная версия ещё не подключена." or "Не изучено в дереве талантов.", 0.62, 0.62, 0.62)
            end
            GameTooltip:Show()
        end)
        button:SetScript("OnLeave", function() GameTooltip:Hide() end)
        abilityButtons[i] = button
    end
    update()
end

local function parseBook(message)
    local _, mask, mana, maxMana, shieldCd, healCd, supportCd, barrier, companion, casts = strsplit("|", tostring(message or ""))
    state.mask = tonumber(mask) or 0
    state.mana = tonumber(mana) or 0
    state.maxMana = tonumber(maxMana) or 100
    state.cooldowns[1] = tonumber(shieldCd) or 0
    state.cooldowns[2] = tonumber(healCd) or 0
    state.cooldowns[3] = tonumber(supportCd) or 0
    state.barrier = tonumber(barrier) or 0
    state.companion = tonumber(companion) == 1
    state.casts = tonumber(casts) == 1
    update()
end

local function parseEvent(message)
    local _, kind, amount, extra = strsplit("|", tostring(message or ""))
    amount = tonumber(amount) or 0
    extra = tonumber(extra) or 0
    if kind == "COMPANION_ON" then
        state.companion = true
        feedback("Диагностический спутник появился", 0.45, 1.0, 0.45)
    elseif kind == "COMPANION_OFF" then
        state.companion = false; state.casts = false
        feedback("Спутник скрыт", 0.8, 0.7, 0.55)
    elseif kind == "COMPANION_FAILED" then
        feedback("Не удалось создать безопасного спутника", 1.0, 0.35, 0.25)
    elseif kind == "CASTS_ON" then
        state.casts = true
        feedback("Боевые касты включены", 1.0, 0.72, 0.30)
    elseif kind == "CASTS_OFF" then
        state.casts = false
        feedback("Боевые касты выключены", 0.8, 0.7, 0.55)
    elseif kind == "CAST_SHIELD" then
        feedback("Спутник кастует щит", 0.45, 0.75, 1.0)
    elseif kind == "CAST_HEAL" then
        feedback("Спутник кастует лечение", 0.35, 1.0, 0.42)
    end
    update()
end

SLASH_FOREVERENCYCOMPANION1 = "/encycompanion"
SlashCmdList["FOREVERENCYCOMPANION"] = function(msg)
    msg = tostring(msg or ""):lower()
    if msg ~= "on" and msg ~= "off" then msg = "toggle" end
    sendRuntime("companion " .. msg)
end

SLASH_FOREVERENCYCASTS1 = "/encycasts"
SlashCmdList["FOREVERENCYCASTS"] = function(msg)
    msg = tostring(msg or ""):lower()
    if msg ~= "on" and msg ~= "off" then msg = "toggle" end
    sendRuntime("casts " .. msg)
end

local events = CreateFrame("Frame")
events:RegisterEvent("ADDON_LOADED")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("PLAYER_ENTERING_WORLD")
events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent", function(_, event, ...)
    if event == "ADDON_LOADED" then
        local name = ...
        if name ~= "ForeverEncyclopedia" then return end
        for _, p in ipairs({REQUEST, RESPONSE, TALENT_RESPONSE, BASE_RESPONSE}) do registerPrefix(p) end
        return
    end
    if event == "CHAT_MSG_ADDON" then
        local prefix, message = ...
        message = tostring(message or "")
        if prefix == RESPONSE and message:sub(1, 5) == "BOOK|" then parseBook(message)
        elseif prefix == RESPONSE and message:sub(1, 6) == "EVENT|" then parseEvent(message)
        elseif prefix == TALENT_RESPONSE and (message:sub(1, 7) == "BOUGHT|" or message == "END" or message:sub(1, 9) == "SELECTED|") then C_Timer.After(0.1, sendStatus)
        elseif prefix == BASE_RESPONSE and message == "END" then C_Timer.After(0.1, sendStatus) end
        return
    end
    if event == "PLAYER_LOGIN" then C_Timer.After(0, hideLegacyDock); return end
    if event == "PLAYER_ENTERING_WORLD" then
        C_Timer.After(0.8, function() hideLegacyDock(); createDock(); sendStatus() end)
    end
end)

local watchdog = CreateFrame("Frame")
local elapsed = 0
watchdog:SetScript("OnUpdate", function(_, dt)
    elapsed = elapsed + dt
    if elapsed < 0.5 then return end
    elapsed = 0
    hideLegacyDock()
    if dock and dock:IsShown() then placeDock() end
end)
