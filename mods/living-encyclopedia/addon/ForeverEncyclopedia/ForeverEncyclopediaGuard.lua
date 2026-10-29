local function hideLegacyDocks()
    for _, name in ipairs({
        "ForeverEncyclopediaBookDock",
        "ForeverEncyclopediaV2BookDock",
        "ForeverEncyclopediaV21BookDock",
    }) do
        local f = _G[name]
        if f then
            f:Hide()
            f:SetAlpha(0)
            f:EnableMouse(false)
        end
    end
end

local function hideModelDescendants(frame)
    if not frame or not frame.GetChildren then return end
    local children = { frame:GetChildren() }
    for _, child in ipairs(children) do
        if child and child.GetObjectType then
            local objectType = child:GetObjectType()
            if objectType == "PlayerModel" or objectType == "Model" or objectType == "ModelScene" then
                if child.SetKeepModelOnHide then pcall(child.SetKeepModelOnHide, child, false) end
                child:Hide()
            end
        end
        hideModelDescendants(child)
    end
end

local hookedMain
local function protectMainFrame()
    local main = _G.ForeverEncyclopediaV21Frame
    if not main then return end
    if hookedMain ~= main then
        hookedMain = main
        main:HookScript("OnHide", function(self)
            hideModelDescendants(self)
        end)
    end
    if not main:IsShown() then
        hideModelDescendants(main)
    end
end

local guard = CreateFrame("Frame")
guard:RegisterEvent("PLAYER_LOGIN")
guard:RegisterEvent("PLAYER_ENTERING_WORLD")
guard:SetScript("OnEvent", function()
    hideLegacyDocks()
    C_Timer.After(0.2, hideLegacyDocks)
    C_Timer.After(0.5, protectMainFrame)
end)

local elapsed = 0
guard:SetScript("OnUpdate", function(_, dt)
    elapsed = elapsed + dt
    if elapsed < 0.5 then return end
    elapsed = 0
    hideLegacyDocks()
    protectMainFrame()
end)
