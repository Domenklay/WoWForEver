local RESPONSE = "FER1"

local pageRecords = {}
local viewer
local model
local fallback
local selectedEntry
local rotation = 0.35
local zoom = 1.28
local dragging = false
local dragStartX = 0
local dragStartRotation = 0
local scanElapsed = 0

local function getMainFrame()
    return _G.ForeverEncyclopediaFrame
end

local function ensureViewer()
    local parent = getMainFrame()
    if not parent then return nil end
    if viewer then return viewer end

    viewer = CreateFrame("Frame", "ForeverEncyclopediaCreatureModelViewer", parent)
    viewer:SetSize(164, 146)
    viewer:SetPoint("TOPLEFT", parent, "TOPLEFT", 412, -222)
    viewer:SetFrameStrata(parent:GetFrameStrata())
    viewer:SetFrameLevel(parent:GetFrameLevel() + 12)
    viewer:EnableMouse(true)
    viewer:EnableMouseWheel(true)
    viewer:Hide()

    -- Compact opaque stage. The model viewport uses exactly the same bounds,
    -- so no creature geometry can spill outside the dark background.
    local plate = viewer:CreateTexture(nil, "BACKGROUND")
    plate:SetPoint("CENTER", viewer, "CENTER", 0, -2)
    plate:SetSize(154, 128)
    plate:SetColorTexture(0.012, 0.010, 0.008, 0.98)

    local glow = viewer:CreateTexture(nil, "BACKGROUND", nil, 1)
    glow:SetPoint("CENTER", plate, "CENTER", 0, 6)
    glow:SetSize(142, 92)
    glow:SetColorTexture(0.10, 0.055, 0.020, 0.18)

    local top = viewer:CreateTexture(nil, "BORDER")
    top:SetPoint("TOPLEFT", plate, "TOPLEFT", 0, 0)
    top:SetPoint("TOPRIGHT", plate, "TOPRIGHT", 0, 0)
    top:SetHeight(1)
    top:SetColorTexture(0.49, 0.31, 0.11, 0.94)

    local bottom = viewer:CreateTexture(nil, "BORDER")
    bottom:SetPoint("BOTTOMLEFT", plate, "BOTTOMLEFT", 0, 0)
    bottom:SetPoint("BOTTOMRIGHT", plate, "BOTTOMRIGHT", 0, 0)
    bottom:SetHeight(1)
    bottom:SetColorTexture(0.16, 0.095, 0.035, 0.92)

    local left = viewer:CreateTexture(nil, "BORDER")
    left:SetPoint("TOPLEFT", plate, "TOPLEFT", 0, 0)
    left:SetPoint("BOTTOMLEFT", plate, "BOTTOMLEFT", 0, 0)
    left:SetWidth(1)
    left:SetColorTexture(0.29, 0.18, 0.07, 0.90)

    local right = viewer:CreateTexture(nil, "BORDER")
    right:SetPoint("TOPRIGHT", plate, "TOPRIGHT", 0, 0)
    right:SetPoint("BOTTOMRIGHT", plate, "BOTTOMRIGHT", 0, 0)
    right:SetWidth(1)
    right:SetColorTexture(0.29, 0.18, 0.07, 0.90)

    model = CreateFrame("PlayerModel", nil, viewer)
    model:SetPoint("CENTER", viewer, "CENTER", 0, -2)
    model:SetSize(154, 128)
    model:SetKeepModelOnHide(true)
    model:EnableMouse(false)

    fallback = viewer:CreateTexture(nil, "ARTWORK")
    fallback:SetPoint("CENTER", viewer, "CENTER", 0, -2)
    fallback:SetSize(50, 50)
    fallback:SetTexture("Interface\\Icons\\INV_Misc_QuestionMark")
    fallback:SetAlpha(0.22)
    fallback:Hide()

    viewer:SetScript("OnMouseDown", function(self, button)
        if button ~= "LeftButton" or not selectedEntry then return end
        dragging = true
        dragStartX = GetCursorPosition()
        dragStartRotation = rotation
        self:SetScript("OnUpdate", function()
            if not dragging or not model then return end
            local x = GetCursorPosition()
            rotation = dragStartRotation + (x - dragStartX) * 0.012
            model:SetRotation(rotation, false)
        end)
    end)

    viewer:SetScript("OnMouseUp", function(self)
        dragging = false
        self:SetScript("OnUpdate", nil)
    end)

    viewer:SetScript("OnMouseWheel", function(_, delta)
        if not selectedEntry or not model then return end
        zoom = math.max(0.78, math.min(2.20, zoom - delta * 0.10))
        model:SetCamDistanceScale(zoom)
        model:RefreshCamera()
    end)

    viewer:SetScript("OnHide", function(self)
        dragging = false
        self:SetScript("OnUpdate", nil)
    end)

    return viewer
end

local function hideViewer()
    selectedEntry = nil
    if viewer then viewer:Hide() end
end

local function showCreature(entry)
    entry = tonumber(entry)
    local v = ensureViewer()
    if not v or not entry or entry <= 0 then
        hideViewer()
        return
    end

    selectedEntry = entry
    rotation = 0.35
    zoom = 1.28
    fallback:Hide()
    model:Show()
    model:ClearModel()

    local ok = pcall(function()
        model:SetCreature(entry)
        model:SetPortraitZoom(0)
        model:SetCamDistanceScale(zoom)
        model:SetRotation(rotation, false)
        model:RefreshCamera()
    end)

    if not ok then
        model:Hide()
        fallback:Show()
    else
        C_Timer.After(0.20, function()
            if selectedEntry ~= entry or not viewer or not viewer:IsShown() then return end
            local good = true
            if model.GetDisplayInfo then
                local okDisplay, displayID = pcall(model.GetDisplayInfo, model)
                good = okDisplay and tonumber(displayID) and tonumber(displayID) > 0
            end
            if not good then
                model:Hide()
                fallback:Show()
            end
        end)
    end

    v:Show()
end

local function regionText(button)
    local regions = { button:GetRegions() }
    for _, region in ipairs(regions) do
        if region and region.GetObjectType and region:GetObjectType() == "FontString" then
            local text = region:GetText()
            if text and text ~= "" then return text end
        end
    end
end

local function hasLegacyBookIcon(frame)
    if not frame or not frame.GetRegions then return false end
    local regions = { frame:GetRegions() }
    for _, region in ipairs(regions) do
        if region and region.GetObjectType and region:GetObjectType() == "Texture" and region.GetTexture then
            local tex = region:GetTexture()
            if type(tex) == "string" and tex:find("INV_Misc_Book_09", 1, true) then return true end
        end
    end
    return false
end

local function hideLegacyCreatureSeal(frame)
    if not frame or not frame.GetChildren then return end
    local children = { frame:GetChildren() }
    for _, child in ipairs(children) do
        if child and child.IsShown and child:IsShown() then
            local w, h = child:GetSize()
            if w and h and w >= 124 and w <= 128 and h >= 124 and h <= 128 and hasLegacyBookIcon(child) then
                child:Hide()
            else
                hideLegacyCreatureSeal(child)
            end
        end
    end
end

local function collectCreatureRows(frame, out)
    if not frame or not frame.GetChildren then return end
    local children = { frame:GetChildren() }
    for _, child in ipairs(children) do
        if child and child.IsShown and child:IsShown() then
            if child.GetObjectType and child:GetObjectType() == "Button" then
                local w, h = child:GetSize()
                if w and h and w >= 318 and w <= 322 and h >= 27 and h <= 29 and regionText(child) then
                    out[#out + 1] = child
                end
            end
            collectCreatureRows(child, out)
        end
    end
end

local function hookVisibleRows()
    local parent = getMainFrame()
    if not parent or not parent:IsShown() or #pageRecords == 0 then
        hideViewer()
        return
    end

    local buttons = {}
    collectCreatureRows(parent, buttons)
    if #buttons == 0 then
        hideViewer()
        return
    end

    -- Remove the old 2D book preview from the creature card. It is recreated
    -- by the legacy layout on every Draw(), so this is intentionally repeated.
    hideLegacyCreatureSeal(parent)

    table.sort(buttons, function(a, b)
        local at = a:GetTop() or 0
        local bt = b:GetTop() or 0
        return at > bt
    end)

    while #buttons > #pageRecords do table.remove(buttons) end

    for i, button in ipairs(buttons) do
        local rec = pageRecords[i]
        button._encyModelEntry = rec and rec.entry or nil
        if not button._encyModelHooked then
            button._encyModelHooked = true
            button:HookScript("OnClick", function(self)
                if self._encyModelEntry then showCreature(self._encyModelEntry)
                else hideViewer() end
            end)
        end
    end

    local entryStillVisible = false
    if selectedEntry then
        for _, rec in ipairs(pageRecords) do
            if rec.entry == selectedEntry then entryStillVisible = true; break end
        end
    end
    if not entryStillVisible and pageRecords[1] then showCreature(pageRecords[1].entry) end
end

local events = CreateFrame("Frame")
events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent", function(_, _, prefix, text)
    if prefix ~= RESPONSE then return end
    text = tostring(text or "")

    if text:sub(1, 8) == "CATHEAD|" then
        wipe(pageRecords)
        hideViewer()
        return
    end

    if text:sub(1, 4) == "CAT|" then
        local _, entry = strsplit("|", text)
        pageRecords[#pageRecords + 1] = { entry = tonumber(entry) or 0 }
        return
    end

    if text == "CATEND" then
        C_Timer.After(0.03, hookVisibleRows)
    end
end)

events:SetScript("OnUpdate", function(_, elapsed)
    scanElapsed = scanElapsed + elapsed
    if scanElapsed < 0.12 then return end
    scanElapsed = 0
    local parent = getMainFrame()
    if parent and parent:IsShown() and #pageRecords > 0 then
        hookVisibleRows()
    else
        hideViewer()
    end
end)
