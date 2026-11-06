-- 3D preview for encyclopedia companion appearances.
-- Uses verified creature entries already present in modern client data.

local APPEARANCE_MODELS = {
    ["Живая книга"] = 171120,      -- Animated Tome
    ["Архивариус"] = 205781,       -- Archivist Edress
    ["Дух знаний"] = 161896,       -- The Archivist (spectral)
    ["Малый конструкт"] = 183783,  -- Nascence Servitor
    ["Хранитель рун"] = 130946,    -- Runekeeper Construct
}

local viewer
local model
local fallback
local currentEntry
local rotation = 0.25
local zoom = 1.22
local dragging = false
local dragStartX = 0
local dragStartRotation = 0
local scanElapsed = 0

local function mainFrame()
    return _G.ForeverEncyclopediaFrame
end

local function ensureViewer()
    local parent = mainFrame()
    if not parent then return nil end
    if viewer then return viewer end

    viewer = CreateFrame("Frame", "ForeverEncyclopediaAppearanceModelViewer", parent)
    viewer:SetSize(210, 166)
    viewer:SetPoint("TOPLEFT", parent, "TOPLEFT", 630, -246)
    viewer:SetFrameStrata(parent:GetFrameStrata())
    viewer:SetFrameLevel(parent:GetFrameLevel() + 12)
    viewer:EnableMouse(true)
    viewer:EnableMouseWheel(true)
    viewer:Hide()

    local plate = viewer:CreateTexture(nil, "BACKGROUND")
    plate:SetPoint("CENTER", viewer, "CENTER", 0, -2)
    plate:SetSize(180, 138)
    plate:SetColorTexture(0.012, 0.010, 0.008, 0.98)

    local glow = viewer:CreateTexture(nil, "BACKGROUND", nil, 1)
    glow:SetPoint("CENTER", plate, "CENTER", 0, 8)
    glow:SetSize(166, 100)
    glow:SetColorTexture(0.13, 0.075, 0.024, 0.18)

    local function edge(a, b, vertical)
        local e = viewer:CreateTexture(nil, "BORDER")
        if vertical then
            e:SetPoint(a, plate, a, 0, 0)
            e:SetPoint(b, plate, b, 0, 0)
            e:SetWidth(1)
        else
            e:SetPoint(a, plate, a, 0, 0)
            e:SetPoint(b, plate, b, 0, 0)
            e:SetHeight(1)
        end
        e:SetColorTexture(0.43, 0.28, 0.10, 0.90)
    end
    edge("TOPLEFT", "TOPRIGHT", false)
    edge("BOTTOMLEFT", "BOTTOMRIGHT", false)
    edge("TOPLEFT", "BOTTOMLEFT", true)
    edge("TOPRIGHT", "BOTTOMRIGHT", true)

    model = CreateFrame("PlayerModel", nil, viewer)
    model:SetPoint("CENTER", viewer, "CENTER", 0, -2)
    model:SetSize(180, 138)
    model:SetKeepModelOnHide(true)
    model:EnableMouse(false)

    fallback = viewer:CreateTexture(nil, "ARTWORK")
    fallback:SetPoint("CENTER", viewer, "CENTER", 0, 0)
    fallback:SetSize(58, 58)
    fallback:SetTexture("Interface\\Icons\\INV_Misc_QuestionMark")
    fallback:SetAlpha(0.26)
    fallback:Hide()

    viewer:SetScript("OnMouseDown", function(self, button)
        if button ~= "LeftButton" or not currentEntry then return end
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
        if not currentEntry or not model then return end
        zoom = math.max(0.78, math.min(2.15, zoom - delta * 0.10))
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
    currentEntry = nil
    if viewer then viewer:Hide() end
end

local function showEntry(entry)
    entry = tonumber(entry)
    local v = ensureViewer()
    if not v or not entry or entry <= 0 then
        hideViewer()
        return
    end

    currentEntry = entry
    rotation = 0.25
    zoom = 1.22
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
            if currentEntry ~= entry or not viewer or not viewer:IsShown() then return end
            if model.GetDisplayInfo then
                local okDisplay, displayID = pcall(model.GetDisplayInfo, model)
                if not okDisplay or not tonumber(displayID) or tonumber(displayID) <= 0 then
                    model:Hide()
                    fallback:Show()
                end
            end
        end)
    end

    v:Show()
end

local function getLabel(button)
    local regions = { button:GetRegions() }
    for _, region in ipairs(regions) do
        if region and region.GetObjectType and region:GetObjectType() == "FontString" then
            local text = region:GetText()
            if text and APPEARANCE_MODELS[text] then return text end
        end
    end
end

local function collectAppearanceButtons(frame, out)
    if not frame or not frame.GetChildren then return end
    local children = { frame:GetChildren() }
    for _, child in ipairs(children) do
        if child and child.IsShown and child:IsShown() then
            if child.GetObjectType and child:GetObjectType() == "Button" then
                local w, h = child:GetSize()
                if w and h and w >= 160 and w <= 164 and h >= 118 and h <= 122 then
                    local label = getLabel(child)
                    if label then out[#out + 1] = { button = child, label = label } end
                end
            end
            collectAppearanceButtons(child, out)
        end
    end
end

local function scanAppearances()
    local parent = mainFrame()
    if not parent or not parent:IsShown() then
        hideViewer()
        return
    end

    local found = {}
    collectAppearanceButtons(parent, found)
    if #found == 0 then
        hideViewer()
        return
    end

    for _, info in ipairs(found) do
        local button = info.button
        button._encyAppearanceEntry = APPEARANCE_MODELS[info.label]
        if not button._encyAppearanceHooked then
            button._encyAppearanceHooked = true
            button:HookScript("OnClick", function(self)
                showEntry(self._encyAppearanceEntry)
            end)
        end
    end

    if not currentEntry then
        showEntry(APPEARANCE_MODELS["Живая книга"])
    end
end

local watcher = CreateFrame("Frame")
watcher:SetScript("OnUpdate", function(_, elapsed)
    scanElapsed = scanElapsed + elapsed
    if scanElapsed < 0.12 then return end
    scanElapsed = 0
    scanAppearances()
end)
