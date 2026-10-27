-- Reliable command transport for WoW Forever 1.60.1.70532.
-- Self-whisper AddOn messages are unreliable on this client build, so user actions
-- use a normal TrinityCore .fsub command. The server still executes the same
-- server-authoritative Request() path and answers with the existing FSR1 snapshot.

local classIds = {
    ["Воин"] = 1,
    ["Паладин"] = 2,
    ["Охотник"] = 3,
    ["Разбойник"] = 4,
    ["Жрец"] = 5,
    ["Шаман"] = 7,
    ["Маг"] = 8,
    ["Чернокнижник"] = 9,
    ["Друид"] = 11,
}

local selectedClass = 5
local hooked = setmetatable({}, { __mode = "k" })
local ready = false

local function chatError(text)
    if DEFAULT_CHAT_FRAME then
        DEFAULT_CHAT_FRAME:AddMessage("|cffff5555[Подклассы]|r " .. text)
    end
end

local function sendCommand(payload)
    if not payload or payload == "" then payload = "status" end
    local message = ".fsub " .. payload

    -- Forever exposes the normal chat sender; a leading dot is consumed by
    -- TrinityCore's command parser and is never broadcast to nearby players.
    if C_ChatInfo and C_ChatInfo.SendChatMessage then
        local ok = pcall(C_ChatInfo.SendChatMessage, message, "SAY")
        if ok then return true end
    end
    if SendChatMessage then
        local ok = pcall(SendChatMessage, message, "SAY")
        if ok then return true end
    end

    chatError("Клиент не позволил отправить серверную команду .fsub.")
    return false
end

_G.ForeverSubclassCommandSend = sendCommand

local function getText(button)
    if not button or not button.GetText then return nil end
    local ok, text = pcall(button.GetText, button)
    if ok then return text end
end

local function classIdFromText(text)
    if not text then return nil end
    text = text:gsub("^>%s*", "")
    for name, id in pairs(classIds) do
        if text:sub(1, #name) == name then return id end
    end
end

local function walk(root, out, depth)
    if not root or depth > 8 or not root.GetChildren then return end
    for _, child in ipairs({ root:GetChildren() }) do
        if child and child.GetObjectType and child:GetObjectType() == "Button" then
            table.insert(out, child)
        end
        walk(child, out, depth + 1)
    end
end

local function wireButton(button)
    if not button or hooked[button] then return end
    local text = getText(button)
    local id = classIdFromText(text)

    if id then
        hooked[button] = true
        button:HookScript("OnClick", function()
            local current = classIdFromText(getText(button))
            if current then selectedClass = current end
        end)
        return
    end

    -- Replace the earlier self-whisper handlers for gameplay actions. This avoids
    -- duplicate requests if a future client build fixes self-whispers.
    if text == "Изучить" then
        hooked[button] = true
        button:SetScript("OnClick", function() sendCommand("learn " .. selectedClass) end)
    elseif text == "Активировать" then
        hooked[button] = true
        button:SetScript("OnClick", function() sendCommand("active " .. selectedClass) end)
    elseif text == "XP сюда" then
        hooked[button] = true
        button:SetScript("OnClick", function() sendCommand("xp " .. selectedClass) end)
    elseif text == "Отключить" then
        hooked[button] = true
        button:SetScript("OnClick", function() sendCommand("clear") end)
    elseif text == "Повторить" then
        hooked[button] = true
        button:SetScript("OnClick", function() sendCommand("status") end)
    end
end

local function wirePanel()
    local panel = _G.ForeverSubclassTalentPanel
    if not panel then return false end
    local buttons = {}
    walk(panel, buttons, 0)
    for _, button in ipairs(buttons) do wireButton(button) end
    return true
end

local function wireEntryPoints()
    local tab = _G.ForeverSubclassTalentTab
    if tab and not hooked[tab] then
        hooked[tab] = true
        tab:HookScript("OnClick", function() sendCommand("status") end)
    end

    local proxy = _G.ForeverSubclassTalentClickProxy
    if proxy and not hooked[proxy] then
        hooked[proxy] = true
        proxy:HookScript("OnClick", function() sendCommand("status") end)
    end

    wirePanel()
end

-- Keep /fsub useful for manual diagnostics too. Commands typed by the player now
-- use the same reliable server path as the buttons.
local previousSlash = SlashCmdList and SlashCmdList["FOREVERSUBCLASS"]
if SlashCmdList then
    SlashCmdList["FOREVERSUBCLASS"] = function(text)
        text = text or ""
        if text == "" then
            if _G.ForeverSubclassOpenTalentTab then pcall(_G.ForeverSubclassOpenTalentTab) end
            sendCommand("status")
            return
        end
        if text == "status" or text == "clear"
            or text:match("^learn%s+%d+$") or text:match("^active%s+%d+$") or text:match("^xp%s+%d+$")
            or text:match("^select%s+%d+$") or text:match("^remove%s+%d+$") or text:match("^cast%s+%d+$")
            or text:match("^debuglevel%s+%d+%s+%d+$") then
            sendCommand(text)
            return
        end
        if previousSlash then previousSlash(text) end
    end
end

local events = CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("ADDON_LOADED")
events:SetScript("OnEvent", function()
    if C_Timer and C_Timer.After then
        C_Timer.After(0, wireEntryPoints)
        C_Timer.After(0.25, wireEntryPoints)
        C_Timer.After(1.0, wireEntryPoints)
    else
        wireEntryPoints()
    end
end)

events:SetScript("OnUpdate", function(self, elapsed)
    self._elapsed = (self._elapsed or 0) + elapsed
    if self._elapsed < 0.5 then return end
    self._elapsed = 0
    wireEntryPoints()
    if _G.ForeverSubclassTalentPanel and _G.ForeverSubclassTalentTab then ready = true end
    if ready then self:SetScript("OnUpdate", nil) end
end)
