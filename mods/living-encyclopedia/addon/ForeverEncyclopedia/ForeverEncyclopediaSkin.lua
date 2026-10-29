-- UI repair layer for Forever Encyclopedia.
-- Blizzard achievement category textures have baked-in empty areas and do not
-- stretch cleanly on the custom button sizes used by this addon. This module
-- replaces only those visual surfaces with deterministic full-rect borders.

local scanElapsed = 0
local replacements = {
    ["Победите это существо, чтобы открыть его запись."] = "Существо ещё не встречено. Его модель доступна сразу.",
    ["До открытия архив не раскрывает имя и сведения о нём."] = "Сведения открываются развитием Живой энциклопедии и не зависят от встречи с существом.",
}

local function setBorderColor(button, r, g, b, a)
    if not button._encySkin then return end
    for _, edge in ipairs(button._encySkin.edges) do
        edge:SetColorTexture(r, g, b, a)
    end
end

local function skinButton(button)
    if not button or button._encyFullButtonSkin then return end
    local w, h = button:GetSize()
    if not w or not h or w < 80 or h < 22 then return end

    button._encyFullButtonSkin = true

    -- Draw above the stretched achievement background, but below text/icons.
    local fill = button:CreateTexture(nil, "BACKGROUND", nil, 7)
    fill:SetAllPoints(button)
    fill:SetColorTexture(0.105, 0.067, 0.035, 0.97)

    local inner = button:CreateTexture(nil, "BACKGROUND", nil, 8)
    inner:SetPoint("TOPLEFT", button, "TOPLEFT", 2, -2)
    inner:SetPoint("BOTTOMRIGHT", button, "BOTTOMRIGHT", -2, 2)
    inner:SetColorTexture(0.045, 0.028, 0.016, 0.30)

    local top = button:CreateTexture(nil, "BORDER", nil, 7)
    top:SetPoint("TOPLEFT", button, "TOPLEFT", 0, 0)
    top:SetPoint("TOPRIGHT", button, "TOPRIGHT", 0, 0)
    top:SetHeight(1)

    local bottom = button:CreateTexture(nil, "BORDER", nil, 7)
    bottom:SetPoint("BOTTOMLEFT", button, "BOTTOMLEFT", 0, 0)
    bottom:SetPoint("BOTTOMRIGHT", button, "BOTTOMRIGHT", 0, 0)
    bottom:SetHeight(1)

    local left = button:CreateTexture(nil, "BORDER", nil, 7)
    left:SetPoint("TOPLEFT", button, "TOPLEFT", 0, 0)
    left:SetPoint("BOTTOMLEFT", button, "BOTTOMLEFT", 0, 0)
    left:SetWidth(1)

    local right = button:CreateTexture(nil, "BORDER", nil, 7)
    right:SetPoint("TOPRIGHT", button, "TOPRIGHT", 0, 0)
    right:SetPoint("BOTTOMRIGHT", button, "BOTTOMRIGHT", 0, 0)
    right:SetWidth(1)

    button._encySkin = { fill = fill, inner = inner, edges = { top, bottom, left, right } }
    setBorderColor(button, 0.43, 0.27, 0.10, 0.95)

    local highlight = button:CreateTexture(nil, "HIGHLIGHT")
    highlight:SetPoint("TOPLEFT", button, "TOPLEFT", 1, -1)
    highlight:SetPoint("BOTTOMRIGHT", button, "BOTTOMRIGHT", -1, 1)
    highlight:SetColorTexture(0.55, 0.32, 0.08, 0.16)

    button:HookScript("OnEnter", function(self)
        if self._encySkin then
            self._encySkin.fill:SetColorTexture(0.16, 0.095, 0.040, 0.98)
            setBorderColor(self, 0.72, 0.48, 0.15, 1.0)
        end
    end)
    button:HookScript("OnLeave", function(self)
        if self._encySkin then
            self._encySkin.fill:SetColorTexture(0.105, 0.067, 0.035, 0.97)
            setBorderColor(self, 0.43, 0.27, 0.10, 0.95)
        end
    end)
    button:HookScript("OnDisable", function(self)
        if self._encySkin then
            self._encySkin.fill:SetAlpha(0.52)
            self._encySkin.inner:SetAlpha(0.52)
            for _, edge in ipairs(self._encySkin.edges) do edge:SetAlpha(0.52) end
        end
    end)
    button:HookScript("OnEnable", function(self)
        if self._encySkin then
            self._encySkin.fill:SetAlpha(1)
            self._encySkin.inner:SetAlpha(1)
            for _, edge in ipairs(self._encySkin.edges) do edge:SetAlpha(1) end
        end
    end)

    if button.IsEnabled and not button:IsEnabled() then
        button._encySkin.fill:SetAlpha(0.52)
        button._encySkin.inner:SetAlpha(0.52)
        for _, edge in ipairs(button._encySkin.edges) do edge:SetAlpha(0.52) end
    end
end

local function repairRegions(frame)
    if not frame or not frame.GetRegions then return end
    local regions = { frame:GetRegions() }
    for _, region in ipairs(regions) do
        if region and region.GetObjectType and region:GetObjectType() == "FontString" then
            local text = region:GetText()
            local replacement = text and replacements[text]
            if replacement then region:SetText(replacement) end
        end
    end
end

local function scan(frame)
    if not frame or not frame.IsShown or not frame:IsShown() then return end
    repairRegions(frame)

    if frame.GetObjectType and frame:GetObjectType() == "Button" then
        skinButton(frame)
    end

    if not frame.GetChildren then return end
    local children = { frame:GetChildren() }
    for _, child in ipairs(children) do
        scan(child)
    end
end

local watcher = CreateFrame("Frame")
watcher:SetScript("OnUpdate", function(_, elapsed)
    scanElapsed = scanElapsed + elapsed
    if scanElapsed < 0.20 then return end
    scanElapsed = 0
    local main = _G.ForeverEncyclopediaFrame
    if main and main:IsShown() then scan(main) end
end)
