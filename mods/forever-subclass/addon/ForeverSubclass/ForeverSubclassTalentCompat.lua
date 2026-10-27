-- Forever 1.60.x compatibility shim for the subclass talent tab.
-- Keep the custom tab on Blizzard's normal talent-frame layer. Do not use any
-- UIParent proxy: in Forever 70532 that proxy overlaps and blocks native tabs.

local fixed = false
local hooked = {}

local nativeTabText = {
    ["Основное"] = true,
    ["Дополнительное"] = true,
    ["Основной"] = true,
    ["Primary"] = true,
    ["Secondary"] = true,
    ["Main"] = true,
}

local function getTalentHost()
    return _G.PlayerSpellsFrame and _G.PlayerSpellsFrame.TalentsFrame
end

local function collectButtons(root, out, depth)
    if not root or depth > 6 or not root.GetChildren then return end
    for _, child in ipairs({ root:GetChildren() }) do
        if child and child ~= _G.ForeverSubclassTalentTab then
            if child.GetObjectType and child:GetObjectType() == "Button" then table.insert(out, child) end
            collectButtons(child, out, depth + 1)
        end
    end
end

local function hideSubclassPanel()
    local panel = _G.ForeverSubclassTalentPanel
    local v2 = _G.ForeverSubclassPanelV2
    if panel then panel:Hide() end
    if v2 then v2:Hide() end
    local tab = _G.ForeverSubclassTalentTab
    if tab then
        tab:SetEnabled(true)
        if PanelTemplates_DeselectTab then pcall(PanelTemplates_DeselectTab, tab) end
    end
end

local function positionTab(talentHost)
    local tab = _G.ForeverSubclassTalentTab
    if not tab then return end

    local buttons = {}
    collectButtons(talentHost, buttons, 0)
    if _G.PlayerSpellsFrame and _G.PlayerSpellsFrame ~= talentHost then
        collectButtons(_G.PlayerSpellsFrame, buttons, 0)
    end

    local anchor, anchorLeft
    anchorLeft = -math.huge
    for _, button in ipairs(buttons) do
        local text
        if button.GetText then
            local ok, value = pcall(button.GetText, button)
            if ok then text = value end
        end
        if text and nativeTabText[text] then
            if not hooked[button] and button.HookScript then
                hooked[button] = true
                button:HookScript("OnClick", hideSubclassPanel)
            end
            local left = button.GetLeft and button:GetLeft()
            if left and left > anchorLeft then anchor, anchorLeft = button, left
            elseif not anchor then anchor = button end
        end
    end

    tab:ClearAllPoints()
    if anchor then tab:SetPoint("LEFT", anchor, "RIGHT", 7, 0)
    else tab:SetPoint("TOPLEFT", talentHost, "TOPLEFT", 365, -8) end
    tab:SetParent(talentHost)
    tab:SetFrameStrata(talentHost:GetFrameStrata())
    tab:SetFrameLevel((anchor and anchor.GetFrameLevel and anchor:GetFrameLevel() or talentHost:GetFrameLevel()) + 1)
    tab:EnableMouse(true)
    if tab.RegisterForClicks then tab:RegisterForClicks("LeftButtonUp") end
    tab:SetEnabled(true)
    tab:Show()
end

local function fixTalentTab()
    local talentHost = getTalentHost()
    local tab = _G.ForeverSubclassTalentTab
    local panel = _G.ForeverSubclassTalentPanel
    if not talentHost or not tab or not panel then return false end

    if tab:GetParent() ~= talentHost then tab:SetParent(talentHost) end
    if panel:GetParent() ~= talentHost then panel:SetParent(talentHost) end

    panel:ClearAllPoints()
    panel:SetPoint("TOPLEFT", talentHost, "TOPLEFT", 0, -44)
    panel:SetPoint("BOTTOMRIGHT", talentHost, "BOTTOMRIGHT", 0, 0)
    panel:SetFrameStrata(talentHost:GetFrameStrata())
    panel:SetFrameLevel(talentHost:GetFrameLevel() + 2)

    positionTab(talentHost)

    if not hooked[talentHost] and talentHost.HookScript then
        hooked[talentHost] = true
        talentHost:HookScript("OnShow", function() positionTab(talentHost) end)
        talentHost:HookScript("OnHide", hideSubclassPanel)
    end

    fixed = true
    return true
end

local events = CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("ADDON_LOADED")
events:SetScript("OnEvent", function(_, event, addonName)
    if event == "ADDON_LOADED" and addonName ~= "Blizzard_PlayerSpells" and fixed then return end
    if C_Timer and C_Timer.After then
        C_Timer.After(0, fixTalentTab)
        C_Timer.After(0.2, fixTalentTab)
    else fixTalentTab() end
end)

events:SetScript("OnUpdate", function(self, elapsed)
    self._elapsed = (self._elapsed or 0) + elapsed
    if self._elapsed < 0.5 then return end
    self._elapsed = 0
    if fixTalentTab() then self:SetScript("OnUpdate", nil) end
end)
