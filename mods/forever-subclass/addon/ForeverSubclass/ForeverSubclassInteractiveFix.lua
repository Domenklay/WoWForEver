-- Mouse hit-test fix for the V2 subclass panel on WoW Forever 1.60.x.
-- Blizzard's PlayerSpells/Talents frames use unusually high strata/levels.
-- Keep the V2 presentation on the same high strata and explicitly lift every
-- interactive button above the talent-tree content without replacing handlers.

local fixed = false

local function lift(frame, level)
    if not frame then return end
    if frame.SetFrameStrata then pcall(frame.SetFrameStrata, frame, "FULLSCREEN_DIALOG") end
    if frame.SetFrameLevel then pcall(frame.SetFrameLevel, frame, level) end
end

local function walk(frame, depth)
    if not frame or depth > 12 then return end
    local base = 12020 + depth * 4
    if frame.GetObjectType and frame:GetObjectType() == "Button" then
        lift(frame, base + 2)
        if frame.EnableMouse then frame:EnableMouse(true) end
        if frame.RegisterForClicks then pcall(frame.RegisterForClicks, frame, "LeftButtonUp", "LeftButtonDown") end
    elseif frame ~= _G.ForeverSubclassPanelV2 then
        lift(frame, base)
    end

    if not frame.GetChildren then return end
    for _, child in ipairs({ frame:GetChildren() }) do
        walk(child, depth + 1)
    end
end

local function apply()
    local root = _G.ForeverSubclassPanelV2
    local legacy = _G.ForeverSubclassTalentPanel
    if not root or not legacy then return false end

    -- The old panel is only a host now. It must stay visible, but V2 owns all
    -- mouse interaction in the body.
    lift(legacy, 11900)
    lift(root, 12000)
    root:EnableMouse(true)
    walk(root, 0)

    -- Keep the V2 root on top whenever Blizzard rebuilds the talent frame.
    if not fixed and root.HookScript then
        fixed = true
        root:HookScript("OnShow", function()
            lift(root, 12000)
            walk(root, 0)
        end)
    end
    return true
end

local events = CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("ADDON_LOADED")
events:SetScript("OnEvent", function()
    if C_Timer and C_Timer.After then
        C_Timer.After(0, apply)
        C_Timer.After(0.25, apply)
        C_Timer.After(1.0, apply)
    else
        apply()
    end
end)

events:SetScript("OnUpdate", function(self, elapsed)
    self._elapsed = (self._elapsed or 0) + elapsed
    if self._elapsed < 0.5 then return end
    self._elapsed = 0
    if apply() then self:SetScript("OnUpdate", nil) end
end)
