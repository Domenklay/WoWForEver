local elapsed = 0

local function scrubInternalCreatureClass()
    local root = _G.ForeverEncyclopediaV21Frame
    if not root or not root:IsShown() then return end

    local function scan(frame)
        if not frame then return end
        local regions = { frame:GetRegions() }
        for _, region in ipairs(regions) do
            if region and region.GetObjectType and region:GetObjectType() == "FontString" and region.GetText then
                local text = region:GetText()
                if type(text) == "string" and text:find("^Класс:") then
                    region:SetText("")
                end
            end
        end
        local children = { frame:GetChildren() }
        for _, child in ipairs(children) do
            scan(child)
        end
    end

    scan(root)
end

local watcher = CreateFrame("Frame")
watcher:SetScript("OnUpdate", function(_, dt)
    elapsed = elapsed + dt
    if elapsed < 0.25 then return end
    elapsed = 0
    scrubInternalCreatureClass()
end)
