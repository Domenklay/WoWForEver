-- Hide the legacy ForeverSubclassTalentPanel contents once PanelV2 is available.
-- The legacy panel remains only as a geometry anchor. V2 is reparented directly to the
-- real talents frame. Neither host nor V2 root participates in mouse hit testing;
-- only actual cards/buttons/spell nodes do.

local applied = false

local function neutralizeFrame(frame)
    if not frame or frame == _G.ForeverSubclassPanelV2 then return end
    if frame.SetAlpha then pcall(frame.SetAlpha, frame, 0) end
    if frame.EnableMouse then pcall(frame.EnableMouse, frame, false) end
    if frame.EnableMouseWheel then pcall(frame.EnableMouseWheel, frame, false) end
end

local function suppress()
    local host = _G.ForeverSubclassTalentPanel
    local v2 = _G.ForeverSubclassPanelV2
    local talentHost = _G.PlayerSpellsFrame and _G.PlayerSpellsFrame.TalentsFrame
    if not host or not v2 or not talentHost then return false end

    -- The old host is geometry only. It must never catch the mouse.
    if host.EnableMouse then pcall(host.EnableMouse, host, false) end
    if host.EnableMouseWheel then pcall(host.EnableMouseWheel, host, false) end
    if host.SetFrameStrata then pcall(host.SetFrameStrata, host, "MEDIUM") end
    if host.SetFrameLevel then pcall(host.SetFrameLevel, host, (talentHost:GetFrameLevel() or 100) + 2) end

    if host.GetRegions then
        for _, region in ipairs({ host:GetRegions() }) do
            if region and region.SetAlpha then pcall(region.SetAlpha, region, 0) end
        end
    end
    if host.GetChildren then
        for _, child in ipairs({ host:GetChildren() }) do
            if child ~= v2 then neutralizeFrame(child) end
        end
    end

    -- V2 is a sibling inside the real talent page. The root paints the body but does
    -- not accept input, so it cannot mask its own child buttons or Blizzard controls.
    if v2:GetParent() ~= talentHost then v2:SetParent(talentHost) end
    v2:ClearAllPoints()
    v2:SetPoint("TOPLEFT", host, "TOPLEFT", 0, 0)
    v2:SetPoint("BOTTOMRIGHT", host, "BOTTOMRIGHT", 0, 0)
    if v2.SetAlpha then v2:SetAlpha(1) end
    if v2.EnableMouse then v2:EnableMouse(false) end
    if v2.EnableMouseWheel then v2:EnableMouseWheel(false) end
    if v2.SetFrameStrata then v2:SetFrameStrata("MEDIUM") end
    if v2.SetFrameLevel then v2:SetFrameLevel((talentHost:GetFrameLevel() or 100) + 2000) end
    v2:Show()

    if not applied and host.HookScript then
        applied = true
        host:HookScript("OnShow", function()
            if C_Timer and C_Timer.After then C_Timer.After(0, suppress) else suppress() end
        end)
    end
    return true
end

local events = CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("ADDON_LOADED")
events:SetScript("OnEvent", function()
    if C_Timer and C_Timer.After then
        C_Timer.After(0, suppress)
        C_Timer.After(0.2, suppress)
        C_Timer.After(1.0, suppress)
    else
        suppress()
    end
end)

events:SetScript("OnUpdate", function(self, elapsed)
    self._elapsed = (self._elapsed or 0) + elapsed
    if self._elapsed < 0.5 then return end
    self._elapsed = 0
    suppress()
end)
