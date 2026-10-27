-- Direct user-action transport for WoW Forever 1.60.x.
-- The 70532 client can restrict addon-message sends that are deferred to OnUpdate.
-- FSC1 is now a server-bound addon protocol: the client sends a WHISPER packet to
-- the synthetic target SERVER and our TrinityCore compatibility patch consumes it
-- before normal player-name resolution. The server remains authoritative.

local REQUEST = "FSC1"
local SERVER_TARGET = "SERVER"
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
local decorated = false

local function directSend(payload, quiet)
    if not C_ChatInfo or not C_ChatInfo.SendAddonMessage then
        if not quiet and DEFAULT_CHAT_FRAME then
            DEFAULT_CHAT_FRAME:AddMessage("|cffff5555[Подклассы]|r Клиент не поддерживает C_ChatInfo.SendAddonMessage.")
        end
        return false
    end

    if C_ChatInfo.RegisterAddonMessagePrefix then
        pcall(C_ChatInfo.RegisterAddonMessagePrefix, REQUEST)
        pcall(C_ChatInfo.RegisterAddonMessagePrefix, "FSR1")
    end

    local ok, result = pcall(C_ChatInfo.SendAddonMessage, REQUEST, payload, "WHISPER", SERVER_TARGET)
    if not ok then
        if not quiet and DEFAULT_CHAT_FRAME then
            DEFAULT_CHAT_FRAME:AddMessage("|cffff5555[Подклассы]|r Не удалось отправить запрос серверу: " .. tostring(result))
        end
        return false
    end
    return result ~= false
end

_G.ForeverSubclassDirectSend = directSend

local function getText(button)
    if not button or not button.GetText then return nil end
    local ok, text = pcall(button.GetText, button)
    if ok then return text end
end

local function findClassId(text)
    if not text then return nil end
    text = text:gsub("^>%s*", "")
    for name, id in pairs(classIds) do
        if text:sub(1, #name) == name then return id end
    end
end

local function walk(root, out, depth)
    if not root or depth > 8 or not root.GetChildren then return end
    local children = { root:GetChildren() }
    for _, child in ipairs(children) do
        if child and child.GetObjectType and child:GetObjectType() == "Button" then
            table.insert(out, child)
        end
        walk(child, out, depth + 1)
    end
end

local function wireButton(button)
    if not button or hooked[button] then return end
    local text = getText(button)
    local classId = findClassId(text)

    if classId then
        hooked[button] = true
        button:HookScript("OnClick", function()
            local current = findClassId(getText(button))
            if current then selectedClass = current end
        end)
        return
    end

    if text == "Изучить" then
        hooked[button] = true
        button:SetScript("OnClick", function() directSend("learn " .. selectedClass) end)
    elseif text == "Активировать" then
        hooked[button] = true
        button:SetScript("OnClick", function() directSend("active " .. selectedClass) end)
    elseif text == "XP сюда" then
        hooked[button] = true
        button:SetScript("OnClick", function() directSend("xp " .. selectedClass) end)
    elseif text == "Отключить" then
        hooked[button] = true
        button:SetScript("OnClick", function() directSend("clear") end)
    elseif text == "Повторить" then
        hooked[button] = true
        button:SetScript("OnClick", function() directSend("status") end)
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
        tab:HookScript("OnClick", function() directSend("status", true) end)
    end

    local proxy = _G.ForeverSubclassTalentClickProxy
    if proxy and not hooked[proxy] then
        hooked[proxy] = true
        proxy:HookScript("OnClick", function() directSend("status", true) end)
    end

    local panel = _G.ForeverSubclassTalentPanel
    if panel and not hooked[panel] then
        hooked[panel] = true
        panel:HookScript("OnShow", function()
            wirePanel()
            directSend("status", true)
        end)
    end

    wirePanel()
end

local legacySlash = SlashCmdList and SlashCmdList["FOREVERSUBCLASS"]
if SlashCmdList and legacySlash then
    SlashCmdList["FOREVERSUBCLASS"] = function(text)
        text = text or ""
        if text == "status" then
            directSend("status")
            return
        end
        if text:match("^learn%s+%d+$") or text:match("^active%s+%d+$") or text:match("^xp%s+%d+$")
            or text:match("^select%s+%d+$") or text:match("^remove%s+%d+$") or text:match("^cast%s+%d+$")
            or text == "clear" or text:match("^debuglevel%s+%d+%s+%d+$") then
            directSend(text)
            return
        end
        legacySlash(text)
        if not text:match("%S") then directSend("status", true) end
    end
end

local events = CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("ADDON_LOADED")
events:SetScript("OnEvent", function(_, event)
    if C_ChatInfo and C_ChatInfo.RegisterAddonMessagePrefix then
        pcall(C_ChatInfo.RegisterAddonMessagePrefix, REQUEST)
        pcall(C_ChatInfo.RegisterAddonMessagePrefix, "FSR1")
    end
    if C_Timer and C_Timer.After then
        C_Timer.After(0, wireEntryPoints)
        C_Timer.After(0.25, wireEntryPoints)
        C_Timer.After(1.0, wireEntryPoints)
        if event == "PLAYER_LOGIN" then C_Timer.After(1.25, function() directSend("status", true) end) end
    else
        wireEntryPoints()
    end
end)

events:SetScript("OnUpdate", function(self, elapsed)
    self._elapsed = (self._elapsed or 0) + elapsed
    if self._elapsed < 0.5 then return end
    self._elapsed = 0
    wireEntryPoints()
    if _G.ForeverSubclassTalentPanel and _G.ForeverSubclassTalentTab then
        decorated = true
    end
    if decorated then self:SetScript("OnUpdate", nil) end
end)
