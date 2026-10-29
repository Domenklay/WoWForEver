local RESPONSE = "FER1"

local pageRecords = {}
local viewer
local model
local fallback
local selectedEntry
local rotation = 0.35
local zoom = 1.0
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

    -- Transparent model-only layer. The main encyclopedia panel supplies the
    -- visual container; the model viewer itself must not draw a square/card.
    viewer = CreateFrame("Frame", "ForeverEncyclopediaCreatureModelViewer", parent)
    viewer:SetSize(176, 168)
    viewer:SetPoint("TOPLEFT", parent, "TOPLEFT", 408, -218)
    viewer:SetFrameStrata(parent:GetFrameStrata())
    viewer:SetFrameLevel(parent:GetFrameLevel() + 8)
    viewer:EnableMouse(true)
    viewer:EnableMouseWheel(true)
    viewer:Hide()

    model = CreateFrame("PlayerModel", nil, viewer)
    model:SetAllPoints(viewer)
    model:SetKeepModelOnHide(true)
    model:EnableMouse(false)

    fallback = viewer:CreateTexture(nil, "ARTWORK")
    fallback:SetPoint("CENTER", viewer, "CENTER", 0, 0)
    fallback:SetSize(54, 54)
    fallback:SetTexture("Interface\\Icons\\INV_Misc_QuestionMark")
    fallback:SetAlpha(0.24)
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
        zoom = math.max(0.55, math.min(1.85, zoom - delta * 0.10))
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
    zoom = 1.0
    fallback:Hide()
    model:Show()
    model:ClearModel()

    local ok = pcall(function()
        -- WoW Forever exposes PlayerModel:SetCreature(creatureID), so entry is
        -- enough; no separate display-id database is required client-side.
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

-- Only creature-list rows are 320x28. Narrow matching is intentional: the
-- previous broad scan also matched location rows and kept a creature model
-- alive on other tabs.
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
        -- We are no longer on the creature tab (or the list is not drawn).
        hideViewer()
        return
    end

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

    -- Model visibility is independent from discovery state. Discovery controls
    -- records/progress, while the physical creature can always be inspected.
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
    if scanElapsed < 0.15 then return end
    scanElapsed = 0
    local parent = getMainFrame()
    if parent and parent:IsShown() and #pageRecords > 0 then
        hookVisibleRows()
    else
        hideViewer()
    end
end)
