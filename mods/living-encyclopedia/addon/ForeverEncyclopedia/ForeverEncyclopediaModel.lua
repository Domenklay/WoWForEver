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

    viewer = CreateFrame("Frame", "ForeverEncyclopediaCreatureModelViewer", parent)
    viewer:SetSize(158, 158)
    viewer:SetPoint("TOPLEFT", parent, "TOPLEFT", 402, -194)
    viewer:SetFrameStrata(parent:GetFrameStrata())
    viewer:SetFrameLevel(parent:GetFrameLevel() + 8)
    viewer:EnableMouse(true)
    viewer:EnableMouseWheel(true)
    viewer:Hide()

    local bg = viewer:CreateTexture(nil, "BACKGROUND")
    bg:SetAllPoints()
    bg:SetColorTexture(0.045, 0.026, 0.012, 0.96)

    local borderTop = viewer:CreateTexture(nil, "BORDER")
    borderTop:SetPoint("TOPLEFT", viewer, "TOPLEFT", 0, 0)
    borderTop:SetPoint("TOPRIGHT", viewer, "TOPRIGHT", 0, 0)
    borderTop:SetHeight(1)
    borderTop:SetColorTexture(0.72, 0.48, 0.16, 0.95)

    local borderBottom = viewer:CreateTexture(nil, "BORDER")
    borderBottom:SetPoint("BOTTOMLEFT", viewer, "BOTTOMLEFT", 0, 0)
    borderBottom:SetPoint("BOTTOMRIGHT", viewer, "BOTTOMRIGHT", 0, 0)
    borderBottom:SetHeight(1)
    borderBottom:SetColorTexture(0.28, 0.17, 0.06, 0.95)

    model = CreateFrame("PlayerModel", nil, viewer)
    model:SetPoint("TOPLEFT", viewer, "TOPLEFT", 4, -4)
    model:SetPoint("BOTTOMRIGHT", viewer, "BOTTOMRIGHT", -4, 4)
    model:SetKeepModelOnHide(true)
    model:EnableMouse(false)

    fallback = viewer:CreateTexture(nil, "ARTWORK")
    fallback:SetPoint("CENTER", viewer, "CENTER", 0, 4)
    fallback:SetSize(64, 64)
    fallback:SetTexture("Interface\\Icons\\INV_Misc_QuestionMark")
    fallback:SetAlpha(0.32)
    fallback:Hide()

    local hint = viewer:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    hint:SetPoint("BOTTOM", viewer, "BOTTOM", 0, 6)
    hint:SetText("ЛКМ: вращать   •   колесо: масштаб")
    hint:SetTextColor(0.62, 0.52, 0.38)

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

local function showCreature(entry)
    entry = tonumber(entry)
    local v = ensureViewer()
    if not v or not entry or entry <= 0 then
        if viewer then viewer:Hide() end
        selectedEntry = nil
        return
    end

    selectedEntry = entry
    rotation = 0.35
    zoom = 1.0
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

local function collectRowButtons(frame, out)
    if not frame or not frame.GetChildren then return end
    local children = { frame:GetChildren() }
    for _, child in ipairs(children) do
        if child and child.IsShown and child:IsShown() then
            if child.GetObjectType and child:GetObjectType() == "Button" then
                local w, h = child:GetSize()
                if w and h and w >= 250 and w <= 330 and h >= 24 and h <= 34 and regionText(child) then
                    out[#out + 1] = child
                end
            end
            collectRowButtons(child, out)
        end
    end
end

local function hookVisibleRows()
    local parent = getMainFrame()
    if not parent or not parent:IsShown() or #pageRecords == 0 then
        if viewer then viewer:Hide() end
        return
    end

    local buttons = {}
    collectRowButtons(parent, buttons)
    if #buttons == 0 then
        if viewer then viewer:Hide() end
        return
    end

    table.sort(buttons, function(a, b)
        local at = a:GetTop() or 0
        local bt = b:GetTop() or 0
        return at > bt
    end)

    while #buttons > #pageRecords do
        table.remove(buttons)
    end

    for i, button in ipairs(buttons) do
        local rec = pageRecords[i]
        button._encyModelEntry = rec and rec.entry or nil
        button._encyModelKnown = rec and rec.known or false
        if not button._encyModelHooked then
            button._encyModelHooked = true
            button:HookScript("OnClick", function(self)
                if self._encyModelKnown and self._encyModelEntry then
                    showCreature(self._encyModelEntry)
                else
                    showCreature(nil)
                end
            end)
        end
    end

    if not selectedEntry then
        for _, rec in ipairs(pageRecords) do
            if rec.known then
                showCreature(rec.entry)
                break
            end
        end
    end
end

local events = CreateFrame("Frame")
events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent", function(_, _, prefix, text)
    if prefix ~= RESPONSE then return end
    text = tostring(text or "")

    if text:sub(1, 8) == "CATHEAD|" then
        wipe(pageRecords)
        selectedEntry = nil
        if viewer then viewer:Hide() end
        return
    end

    if text:sub(1, 4) == "CAT|" then
        local _, entry, known = strsplit("|", text)
        pageRecords[#pageRecords + 1] = {
            entry = tonumber(entry) or 0,
            known = tonumber(known) == 1,
        }
        return
    end

    if text == "CATEND" then
        C_Timer.After(0.08, hookVisibleRows)
    end
end)

events:SetScript("OnUpdate", function(_, elapsed)
    scanElapsed = scanElapsed + elapsed
    if scanElapsed < 0.45 then return end
    scanElapsed = 0
    local parent = getMainFrame()
    if parent and parent:IsShown() and #pageRecords > 0 then
        hookVisibleRows()
    elseif viewer then
        viewer:Hide()
    end
end)
