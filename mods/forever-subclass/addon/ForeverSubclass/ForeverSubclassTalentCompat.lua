-- Forever 1.60.x compatibility shim for the subclass talent tab.
-- The Forever client uses PlayerSpellsFrame.TalentsFrame for the actual talent page.
-- Earlier builds of our addon attached to PlayerSpellsFrame itself, which can leave
-- the custom tab outside/under the visible talent page. This file reparents the
-- already-created UI to the real Forever talent frame once Blizzard_PlayerSpells loads.

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
    local children = { root:GetChildren() }
    for _, child in ipairs(children) do
        if child and child ~= _G.ForeverSubclassTalentTab then
            if child.GetObjectType and child:GetObjectType() == "Button" then
                table.insert(out, child)
            end
            collectButtons(child, out, depth + 1)
        end
    end
end

local function hideSubclassPanel()
    local panel = _G.ForeverSubclassTalentPanel
    if panel then panel:Hide() end
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

    local anchor
    local anchorLeft = -math.huge
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
            if left and left > anchorLeft then
                anchor = button
                anchorLeft = left
            elseif not anchor then
                anchor = button
            end
        end
    end

    tab:ClearAllPoints()
    if anchor then
        tab:SetPoint("LEFT", anchor, "RIGHT", 7, 0)
    else
        -- Stable fallback for the Forever talent layout: same top row as spec tabs.
        tab:SetPoint("TOPLEFT", talentHost, "TOPLEFT", 365, -8)
    end
    tab:SetFrameStrata(talentHost:GetFrameStrata())
    tab:SetFrameLevel((talentHost:GetFrameLevel() or 1) + 100)
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
    -- Leave Blizzard's title/spec-tab header visible and replace only the tree body.
    panel:SetPoint("TOPLEFT", talentHost, "TOPLEFT", 0, -44)
    panel:SetPoint("BOTTOMRIGHT", talentHost, "BOTTOMRIGHT", 0, 0)
    panel:SetFrameStrata(talentHost:GetFrameStrata())
    panel:SetFrameLevel((talentHost:GetFrameLevel() or 1) + 90)

    positionTab(talentHost)

    if not hooked[talentHost] and talentHost.HookScript then
        hooked[talentHost] = true
        talentHost:HookScript("OnShow", function()
            positionTab(talentHost)
        end)
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
    else
        fixTalentTab()
    end
end)

-- Keep retrying only until the load-on-demand talent UI and our tab both exist.
events:SetScript("OnUpdate", function(self, elapsed)
    self._elapsed = (self._elapsed or 0) + elapsed
    if self._elapsed < 0.5 then return end
    self._elapsed = 0
    if fixTalentTab() then
        -- We keep the frame alive for ADDON_LOADED/OnShow, but no longer poll every frame.
        self:SetScript("OnUpdate", nil)
    end
end)
