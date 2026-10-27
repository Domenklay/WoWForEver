-- Hide the legacy ForeverSubclassTalentPanel contents once PanelV2 is available.
-- The legacy panel remains as the host/container because the tab integration expects it,
-- but its original buttons, labels and scroll frame must never render or receive input.

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
    if not host or not v2 then return false end

    -- Hide all old regions created directly on the legacy panel: headline, progress,
    -- help text, notice and its original backdrop/borders. V2 paints its own surface.
    if host.GetRegions then
        for _, region in ipairs({ host:GetRegions() }) do
            if region and region.SetAlpha then pcall(region.SetAlpha, region, 0) end
        end
    end

    -- Every direct child except V2 belongs to the old implementation. Alpha/mouse
    -- suppression survives subsequent Show() calls made by the legacy refresh loop.
    if host.GetChildren then
        for _, child in ipairs({ host:GetChildren() }) do
            if child ~= v2 then neutralizeFrame(child) end
        end
    end

    -- Make V2 the only visible/interactive body.
    if v2.SetAlpha then v2:SetAlpha(1) end
    if v2.EnableMouse then v2:EnableMouse(true) end
    if v2.SetFrameStrata then v2:SetFrameStrata("FULLSCREEN_DIALOG") end
    if v2.SetFrameLevel then v2:SetFrameLevel(12000) end
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

-- Keep enforcing only while the panel exists. This is cheap (a handful of children)
-- and prevents the legacy refresh loop from restoring opacity/mouse state later.
events:SetScript("OnUpdate", function(self, elapsed)
    self._elapsed = (self._elapsed or 0) + elapsed
    if self._elapsed < 0.5 then return end
    self._elapsed = 0
    suppress()
end)
