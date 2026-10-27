-- Mouse hit-test fix for the V2 subclass panel on WoW Forever 1.60.x.
-- Do not elevate whole panels above PlayerSpellsFrame. Only actual interactive controls
-- receive mouse input and a level above the local talent content.

local fixed = false

local function setLevel(frame, level)
    if not frame then return end
    if frame.SetFrameStrata then pcall(frame.SetFrameStrata, frame, "MEDIUM") end
    if frame.SetFrameLevel then pcall(frame.SetFrameLevel, frame, level) end
end

local function walk(frame, depth, base)
    if not frame or depth > 12 then return end
    local level = base + depth * 3
    if frame.GetObjectType and frame:GetObjectType() == "Button" then
        setLevel(frame, level + 2)
        if frame.EnableMouse then frame:EnableMouse(true) end
        if frame.RegisterForClicks then pcall(frame.RegisterForClicks, frame, "LeftButtonUp") end
    else
        if frame ~= _G.ForeverSubclassPanelV2 then
            setLevel(frame, level)
            if frame.EnableMouse then frame:EnableMouse(false) end
            if frame.EnableMouseWheel then frame:EnableMouseWheel(false) end
        end
    end

    if not frame.GetChildren then return end
    for _, child in ipairs({ frame:GetChildren() }) do
        walk(child, depth + 1, base)
    end
end

local function apply()
    local root = _G.ForeverSubclassPanelV2
    local talentHost = _G.PlayerSpellsFrame and _G.PlayerSpellsFrame.TalentsFrame
    if not root or not talentHost then return false end

    local base = (talentHost:GetFrameLevel() or 100) + 2100
    setLevel(root, base)
    root:EnableMouse(false)
    if root.EnableMouseWheel then root:EnableMouseWheel(false) end
    walk(root, 0, base)

    if not fixed and root.HookScript then
        fixed = true
        root:HookScript("OnShow", function()
            local b = (talentHost:GetFrameLevel() or 100) + 2100
            setLevel(root, b)
            root:EnableMouse(false)
            walk(root, 0, b)
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
