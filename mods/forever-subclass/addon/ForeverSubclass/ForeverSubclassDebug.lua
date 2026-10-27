-- Diagnostics for ForeverSubclass. No gameplay authority lives here.
-- /fsubdebug opens a copyable log. Move the mouse over a class card/button and click it;
-- the log records the frame that actually owns the mouse hit-test.

local ADDON = "ForeverSubclass"
local MAX_LINES = 500
local lines = _G.ForeverSubclassDebugLog or {}
_G.ForeverSubclassDebugLog = lines
local window, editBox
local lastFocusDesc
local transportWrapped = false
local hooks = setmetatable({}, { __mode = "k" })

local function now()
    if date then return date("%H:%M:%S") end
    return tostring(GetTime and math.floor(GetTime()) or 0)
end

local function trim()
    while #lines > MAX_LINES do table.remove(lines, 1) end
end

local function add(text)
    text = tostring(text or "")
    table.insert(lines, string.format("[%s] %s", now(), text))
    trim()
    _G.ForeverSubclassDebugLog = lines
    if editBox and editBox:IsShown() then
        editBox:SetText(table.concat(lines, "\n"))
        editBox:SetCursorPosition(#editBox:GetText())
    end
end

_G.ForeverSubclassDebugAdd = add

local function addonVersion()
    if C_AddOns and C_AddOns.GetAddOnMetadata then
        return C_AddOns.GetAddOnMetadata(ADDON, "Version") or "?"
    end
    if GetAddOnMetadata then return GetAddOnMetadata(ADDON, "Version") or "?" end
    return "?"
end

local function frameText(frame)
    if not frame then return nil end
    if frame.GetText then
        local ok, value = pcall(frame.GetText, frame)
        if ok and value and value ~= "" then return tostring(value) end
    end
    if frame.GetRegions then
        for _, region in ipairs({ frame:GetRegions() }) do
            if region and region.GetObjectType and region:GetObjectType() == "FontString" and region.GetText then
                local ok, value = pcall(region.GetText, region)
                if ok and value and value ~= "" then return tostring(value) end
            end
        end
    end
end

local function describe(frame)
    if not frame then return "<none>" end
    local name = frame.GetName and frame:GetName() or nil
    local object = frame.GetObjectType and frame:GetObjectType() or "?"
    local strata = frame.GetFrameStrata and frame:GetFrameStrata() or "?"
    local level = frame.GetFrameLevel and frame:GetFrameLevel() or -1
    local shown = frame.IsShown and frame:IsShown() and "shown" or "hidden"
    local mouse = frame.IsMouseEnabled and frame:IsMouseEnabled() and "mouse=1" or "mouse=0"
    local text = frameText(frame)
    return string.format("%s name=%s strata=%s level=%s %s %s%s",
        object, name or "<unnamed>", tostring(strata), tostring(level), shown, mouse,
        text and (" text='" .. text .. "'") or "")
end

local function currentMouseFocus()
    if GetMouseFoci then
        local list = { GetMouseFoci() }
        return list[1]
    end
    if GetMouseFocus then return GetMouseFocus() end
    return nil
end

local function hookButtons(root)
    if not root or not root.GetChildren then return end
    for _, child in ipairs({ root:GetChildren() }) do
        if child and child.GetObjectType and child:GetObjectType() == "Button" and not hooks[child] then
            hooks[child] = true
            if child.HookScript then
                child:HookScript("OnEnter", function(self) add("ENTER " .. describe(self)) end)
                child:HookScript("OnMouseDown", function(self, button) add("MOUSEDOWN " .. tostring(button) .. " " .. describe(self)) end)
                child:HookScript("OnClick", function(self, button) add("CLICK " .. tostring(button) .. " " .. describe(self)) end)
            end
        end
        hookButtons(child)
    end
end

local function wrapTransport()
    if transportWrapped or not _G.ForeverSubclassDirectSend then return end
    local original = _G.ForeverSubclassDirectSend
    _G.ForeverSubclassDirectSend = function(payload, quiet)
        add("TX FSC1 " .. tostring(payload))
        local ok, result = pcall(original, payload, quiet)
        if not ok then
            add("TX ERROR " .. tostring(result))
            return false
        end
        add("TX RESULT " .. tostring(result))
        return result
    end
    transportWrapped = true
    add("transport wrapper installed")
end

local function refreshHeader()
    local version = addonVersion()
    local build, buildNumber, buildDate, tocVersion = GetBuildInfo and GetBuildInfo() or "?", "?", "?", "?"
    if GetBuildInfo then build, buildNumber, buildDate, tocVersion = GetBuildInfo() end
    add(string.format("CLIENT addon=%s wow=%s build=%s toc=%s", version, tostring(build), tostring(buildNumber), tostring(tocVersion)))
    local root = _G.ForeverSubclassPanelV2
    local legacy = _G.ForeverSubclassTalentPanel
    local talent = _G.PlayerSpellsFrame and _G.PlayerSpellsFrame.TalentsFrame
    add("FRAME V2 " .. describe(root))
    add("FRAME LEGACY " .. describe(legacy))
    add("FRAME TALENTS " .. describe(talent))
    if root then hookButtons(root) end
end

local function createWindow()
    if window then return end
    local template = BackdropTemplateMixin and "BackdropTemplate" or nil
    window = CreateFrame("Frame", "ForeverSubclassDebugWindow", UIParent, template)
    window:SetSize(860, 560)
    window:SetPoint("CENTER")
    window:SetFrameStrata("TOOLTIP")
    window:SetFrameLevel(20000)
    window:EnableMouse(true)
    window:SetMovable(true)
    window:RegisterForDrag("LeftButton")
    window:SetScript("OnDragStart", window.StartMoving)
    window:SetScript("OnDragStop", window.StopMovingOrSizing)
    if window.SetBackdrop then
        window:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background", edgeFile="Interface\\Tooltips\\UI-Tooltip-Border", tile=true, tileSize=16, edgeSize=12, insets={left=3,right=3,top=3,bottom=3}})
        window:SetBackdropColor(0.02,0.02,0.02,0.98)
    end

    local title = window:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
    title:SetPoint("TOPLEFT", 14, -12)
    title:SetText("ForeverSubclass - диагностика")
    local hint = window:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    hint:SetPoint("TOPLEFT", title, "BOTTOMLEFT", 0, -5)
    hint:SetText("Наведи мышь на класс/кнопку, попробуй нажать, затем Ctrl+A / Ctrl+C из поля ниже.")

    local close = CreateFrame("Button", nil, window, "UIPanelCloseButton")
    close:SetPoint("TOPRIGHT", -4, -4)

    local scroll = CreateFrame("ScrollFrame", nil, window, "UIPanelScrollFrameTemplate")
    scroll:SetPoint("TOPLEFT", 14, -58)
    scroll:SetPoint("BOTTOMRIGHT", -32, 46)
    editBox = CreateFrame("EditBox", nil, scroll)
    editBox:SetMultiLine(true)
    editBox:SetAutoFocus(false)
    editBox:SetFontObject(ChatFontNormal)
    editBox:SetWidth(800)
    editBox:SetTextInsets(4,4,4,4)
    editBox:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    scroll:SetScrollChild(editBox)

    local refresh = CreateFrame("Button", nil, window, "UIPanelButtonTemplate")
    refresh:SetSize(110, 24)
    refresh:SetPoint("BOTTOMLEFT", 14, 12)
    refresh:SetText("Снимок")
    refresh:SetScript("OnClick", function()
        refreshHeader()
        editBox:SetText(table.concat(lines, "\n"))
    end)

    local clear = CreateFrame("Button", nil, window, "UIPanelButtonTemplate")
    clear:SetSize(110, 24)
    clear:SetPoint("LEFT", refresh, "RIGHT", 8, 0)
    clear:SetText("Очистить")
    clear:SetScript("OnClick", function()
        wipe(lines)
        _G.ForeverSubclassDebugLog = lines
        add("log cleared")
    end)

    window:Hide()
end

SLASH_FOREVERSUBCLASSDEBUG1 = "/fsubdebug"
SlashCmdList["FOREVERSUBCLASSDEBUG"] = function(msg)
    createWindow()
    msg = (msg or ""):lower()
    if msg == "clear" then wipe(lines); add("log cleared") end
    refreshHeader()
    editBox:SetText(table.concat(lines, "\n"))
    editBox:SetHeight(math.max(520, select(2, editBox:GetFont()) and (#lines * 14) or (#lines * 14)))
    window:Show()
    editBox:HighlightText(0,0)
end

local events = CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("ADDON_LOADED")
events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent", function(_, event, ...)
    if event == "CHAT_MSG_ADDON" then
        local prefix, text, channel, sender = ...
        if prefix == "FSR1" or prefix == "FSC1" then
            add(string.format("RX %s channel=%s sender=%s %s", tostring(prefix), tostring(channel), tostring(sender), tostring(text)))
        end
        return
    end
    if event == "PLAYER_LOGIN" then
        add("PLAYER_LOGIN")
        refreshHeader()
    end
end)

events:SetScript("OnUpdate", function(self, elapsed)
    self._elapsed = (self._elapsed or 0) + elapsed
    if self._elapsed < 0.20 then return end
    self._elapsed = 0
    wrapTransport()
    local root = _G.ForeverSubclassPanelV2
    if root and root:IsShown() then
        hookButtons(root)
        local focus = currentMouseFocus()
        local desc = describe(focus)
        if desc ~= lastFocusDesc then
            lastFocusDesc = desc
            add("MOUSEFOCUS " .. desc)
        end
    end
end)
