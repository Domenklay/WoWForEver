-- Friendlier presentation and connection diagnostics for the Forever subclass tab.
-- Does not own gameplay state: the server and ForeverSubclassTalentTab remain authoritative.

local RESPONSE = "FSR1"
local serverSeen = false
local panelSeenAt = nil
local decorated = false
local statusText, statusDot, retryButton, helpText
local actionButtons = {}
local lastStatusRequest = 0

local function addMessage(text)
    if DEFAULT_CHAT_FRAME and text then
        DEFAULT_CHAT_FRAME:AddMessage("|cff67d9ff[Подклассы]|r " .. text)
    end
end

local function requestStatus()
    lastStatusRequest = GetTime and GetTime() or 0
    if SlashCmdList and SlashCmdList["FOREVERSUBCLASS"] then
        SlashCmdList["FOREVERSUBCLASS"]("status")
    end
end

local function walkButtons(root, out, depth)
    if not root or depth > 7 or not root.GetChildren then return end
    local children = { root:GetChildren() }
    for _, child in ipairs(children) do
        if child and child.GetObjectType and child:GetObjectType() == "Button" then
            table.insert(out, child)
        end
        walkButtons(child, out, depth + 1)
    end
end

local actionNames = {
    ["Изучить"] = true,
    ["Активировать"] = true,
    ["XP сюда"] = true,
    ["Отключить"] = true,
}

local function discoverActionButtons(panel)
    actionButtons = {}
    local buttons = {}
    walkButtons(panel, buttons, 0)
    for _, button in ipairs(buttons) do
        local text
        if button.GetText then
            local ok, value = pcall(button.GetText, button)
            if ok then text = value end
        end
        if text and actionNames[text] then
            table.insert(actionButtons, button)
        end
        -- The default Forever skin makes these labels hard to read. Keep the native
        -- button artwork, but use a neutral readable font where supported.
        if button.SetNormalFontObject and _G.GameFontHighlightSmall then
            pcall(button.SetNormalFontObject, button, _G.GameFontHighlightSmall)
        end
    end
end

local function setWaiting()
    if statusText then statusText:SetText("Соединение с сервером…") end
    if statusDot and statusDot.SetColorTexture then statusDot:SetColorTexture(0.85, 0.62, 0.10, 1) end
    if retryButton then retryButton:Hide() end
    for _, button in ipairs(actionButtons) do button:SetEnabled(false) end
end

local function setOffline()
    if statusText then statusText:SetText("Сервер подклассов не отвечает") end
    if statusDot and statusDot.SetColorTexture then statusDot:SetColorTexture(0.80, 0.16, 0.12, 1) end
    if retryButton then retryButton:Show() end
    if helpText then
        helpText:SetText("Аддон работает, но сервер не прислал состояние. Персонажа пересоздавать не нужно — проверьте серверный модуль ForeverSubclass.")
    end
    for _, button in ipairs(actionButtons) do button:SetEnabled(false) end
end

local function setOnline()
    if statusText then statusText:SetText("Сервер подключен") end
    if statusDot and statusDot.SetColorTexture then statusDot:SetColorTexture(0.16, 0.72, 0.30, 1) end
    if retryButton then retryButton:Hide() end
    if helpText then
        helpText:SetText("Подкласс доступен с 10-го уровня. Выберите класс, изучите его, активируйте и при необходимости направьте в него опыт.")
    end
    -- Do not force-enable action buttons here. The main tab code decides which
    -- operations are legal for the current selection and refreshes their state.
end

local function decorate()
    local panel = _G.ForeverSubclassTalentPanel
    if not panel or decorated then return false end
    decorated = true

    -- Soft panels separate class management from the ability loadout without
    -- replacing Blizzard/Forever artwork.
    local left = panel:CreateTexture(nil, "BACKGROUND")
    left:SetColorTexture(0.02, 0.02, 0.02, 0.42)
    left:SetPoint("TOPLEFT", 10, -64)
    left:SetPoint("BOTTOMLEFT", 10, 48)
    left:SetWidth(450)

    local right = panel:CreateTexture(nil, "BACKGROUND")
    right:SetColorTexture(0.02, 0.02, 0.02, 0.32)
    right:SetPoint("TOPLEFT", 470, -64)
    right:SetPoint("BOTTOMRIGHT", -10, 48)

    local divider = panel:CreateTexture(nil, "BORDER")
    divider:SetColorTexture(0.45, 0.35, 0.18, 0.65)
    divider:SetPoint("TOPLEFT", 463, -72)
    divider:SetPoint("BOTTOMLEFT", 463, 56)
    divider:SetWidth(1)

    statusDot = panel:CreateTexture(nil, "OVERLAY")
    statusDot:SetSize(9, 9)
    statusDot:SetPoint("TOPRIGHT", panel, "TOPRIGHT", -248, -20)
    statusDot:SetColorTexture(0.85, 0.62, 0.10, 1)

    statusText = panel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    statusText:SetPoint("LEFT", statusDot, "RIGHT", 7, 0)
    statusText:SetWidth(185)
    statusText:SetJustifyH("LEFT")
    statusText:SetText("Соединение с сервером…")

    retryButton = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
    retryButton:SetSize(82, 22)
    retryButton:SetPoint("TOPRIGHT", panel, "TOPRIGHT", -12, -12)
    retryButton:SetText("Повторить")
    retryButton:SetScript("OnClick", function()
        panelSeenAt = GetTime and GetTime() or 0
        setWaiting()
        requestStatus()
    end)
    retryButton:Hide()

    helpText = panel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    helpText:SetPoint("BOTTOMLEFT", panel, "BOTTOMLEFT", 20, 27)
    helpText:SetPoint("BOTTOMRIGHT", panel, "BOTTOMRIGHT", -20, 27)
    helpText:SetJustifyH("LEFT")
    helpText:SetText("Подкласс доступен с 10-го уровня. Персонажа пересоздавать не требуется.")

    discoverActionButtons(panel)

    if panel.HookScript then
        panel:HookScript("OnShow", function()
            panelSeenAt = GetTime and GetTime() or 0
            discoverActionButtons(panel)
            if serverSeen then setOnline() else setWaiting(); requestStatus() end
        end)
    end

    if panel:IsShown() then
        panelSeenAt = GetTime and GetTime() or 0
        discoverActionButtons(panel)
        if serverSeen then setOnline() else setWaiting(); requestStatus() end
    end
    return true
end

local events = CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("ADDON_LOADED")
events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent", function(_, event, ...)
    if event == "CHAT_MSG_ADDON" then
        local prefix = ...
        if prefix == RESPONSE then
            serverSeen = true
            setOnline()
        end
        return
    end
    if C_Timer and C_Timer.After then
        C_Timer.After(0, decorate)
        C_Timer.After(0.25, decorate)
    else
        decorate()
    end
end)

events:SetScript("OnUpdate", function(self, elapsed)
    self._elapsed = (self._elapsed or 0) + elapsed
    if self._elapsed < 0.25 then return end
    self._elapsed = 0
    decorate()

    local panel = _G.ForeverSubclassTalentPanel
    if not panel or not panel:IsShown() or serverSeen or not panelSeenAt then return end
    local now = GetTime and GetTime() or 0
    if now - panelSeenAt >= 3.0 then
        setOffline()
    end
end)
