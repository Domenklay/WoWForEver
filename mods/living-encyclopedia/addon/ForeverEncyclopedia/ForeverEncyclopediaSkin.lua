-- Stable UI skin for Forever Encyclopedia.
-- Replaces stretched achievement-category button art with deterministic
-- full-rect layered buttons. Applied immediately to newly created buttons
-- while the encyclopedia is visible, so there is no delayed "flattening" pop.

local replacements = {
    ["Победите это существо, чтобы открыть его запись."] = "Существо ещё не встречено. Его модель доступна сразу.",
    ["До открытия архив не раскрывает имя и сведения о нём."] = "Сведения открываются развитием Живой энциклопедии и не зависят от встречи с существом.",
}

local function hideBrokenAchievementArt(button)
    if not button or not button.GetRegions then return end
    local regions = { button:GetRegions() }
    for _, region in ipairs(regions) do
        if region and region.GetObjectType and region:GetObjectType() == "Texture" and region.GetTexture then
            local tex = region:GetTexture()
            if type(tex) == "string" and tex:find("UI%-Achievement%-Category%-Background") then
                region:SetAlpha(0)
            end
        end
    end
end

local function setBorderColor(button, r, g, b, a)
    local skin = button and button._encySkin
    if not skin then return end
    for _, edge in ipairs(skin.edges) do edge:SetColorTexture(r, g, b, a) end
end

local function applyState(button, hover)
    local skin = button and button._encySkin
    if not skin then return end
    local enabled = not button.IsEnabled or button:IsEnabled()
    if not enabled then
        skin.base:SetColorTexture(0.070, 0.045, 0.026, 0.76)
        skin.top:SetColorTexture(0.105, 0.066, 0.030, 0.44)
        skin.bottom:SetColorTexture(0.025, 0.016, 0.010, 0.58)
        setBorderColor(button, 0.23, 0.15, 0.075, 0.65)
        return
    end

    if hover then
        skin.base:SetColorTexture(0.185, 0.112, 0.046, 0.98)
        skin.top:SetColorTexture(0.30, 0.175, 0.060, 0.64)
        skin.bottom:SetColorTexture(0.070, 0.038, 0.018, 0.72)
        setBorderColor(button, 0.78, 0.52, 0.17, 1.0)
    else
        skin.base:SetColorTexture(0.120, 0.075, 0.035, 0.98)
        skin.top:SetColorTexture(0.205, 0.122, 0.046, 0.52)
        skin.bottom:SetColorTexture(0.045, 0.026, 0.014, 0.68)
        setBorderColor(button, 0.49, 0.31, 0.105, 0.98)
    end
end

local function skinButton(button)
    if not button then return end
    hideBrokenAchievementArt(button)
    if button._encyFullButtonSkin then return end

    local w, h = button:GetSize()
    if not w or not h or w < 80 or h < 22 then return end
    button._encyFullButtonSkin = true

    local base = button:CreateTexture(nil, "BACKGROUND", nil, 5)
    base:SetAllPoints(button)

    -- Raised top half.
    local top = button:CreateTexture(nil, "BACKGROUND", nil, 6)
    top:SetPoint("TOPLEFT", button, "TOPLEFT", 2, -2)
    top:SetPoint("TOPRIGHT", button, "TOPRIGHT", -2, -2)
    top:SetHeight(math.max(7, math.floor(h * 0.43)))

    -- Recessed lower half creates the native WoW-button depth without stretching art.
    local bottom = button:CreateTexture(nil, "BACKGROUND", nil, 6)
    bottom:SetPoint("BOTTOMLEFT", button, "BOTTOMLEFT", 2, 2)
    bottom:SetPoint("BOTTOMRIGHT", button, "BOTTOMRIGHT", -2, 2)
    bottom:SetHeight(math.max(7, math.floor(h * 0.42)))

    local shine = button:CreateTexture(nil, "BORDER", nil, 5)
    shine:SetPoint("TOPLEFT", button, "TOPLEFT", 3, -3)
    shine:SetPoint("TOPRIGHT", button, "TOPRIGHT", -3, -3)
    shine:SetHeight(1)
    shine:SetColorTexture(0.94, 0.67, 0.27, 0.24)

    local shadow = button:CreateTexture(nil, "BORDER", nil, 5)
    shadow:SetPoint("BOTTOMLEFT", button, "BOTTOMLEFT", 3, 3)
    shadow:SetPoint("BOTTOMRIGHT", button, "BOTTOMRIGHT", -3, 3)
    shadow:SetHeight(2)
    shadow:SetColorTexture(0.015, 0.010, 0.007, 0.72)

    local edges = {}
    local edgeTop = button:CreateTexture(nil, "BORDER", nil, 7)
    edgeTop:SetPoint("TOPLEFT", button, "TOPLEFT", 0, 0)
    edgeTop:SetPoint("TOPRIGHT", button, "TOPRIGHT", 0, 0)
    edgeTop:SetHeight(1)
    edges[#edges + 1] = edgeTop

    local edgeBottom = button:CreateTexture(nil, "BORDER", nil, 7)
    edgeBottom:SetPoint("BOTTOMLEFT", button, "BOTTOMLEFT", 0, 0)
    edgeBottom:SetPoint("BOTTOMRIGHT", button, "BOTTOMRIGHT", 0, 0)
    edgeBottom:SetHeight(1)
    edges[#edges + 1] = edgeBottom

    local edgeLeft = button:CreateTexture(nil, "BORDER", nil, 7)
    edgeLeft:SetPoint("TOPLEFT", button, "TOPLEFT", 0, 0)
    edgeLeft:SetPoint("BOTTOMLEFT", button, "BOTTOMLEFT", 0, 0)
    edgeLeft:SetWidth(1)
    edges[#edges + 1] = edgeLeft

    local edgeRight = button:CreateTexture(nil, "BORDER", nil, 7)
    edgeRight:SetPoint("TOPRIGHT", button, "TOPRIGHT", 0, 0)
    edgeRight:SetPoint("BOTTOMRIGHT", button, "BOTTOMRIGHT", 0, 0)
    edgeRight:SetWidth(1)
    edges[#edges + 1] = edgeRight

    button._encySkin = {
        base = base,
        top = top,
        bottom = bottom,
        shine = shine,
        shadow = shadow,
        edges = edges,
    }

    local highlight = button:CreateTexture(nil, "HIGHLIGHT")
    highlight:SetPoint("TOPLEFT", button, "TOPLEFT", 1, -1)
    highlight:SetPoint("BOTTOMRIGHT", button, "BOTTOMRIGHT", -1, 1)
    highlight:SetColorTexture(0.82, 0.48, 0.12, 0.10)

    button:HookScript("OnEnter", function(self) applyState(self, true) end)
    button:HookScript("OnLeave", function(self) applyState(self, false) end)
    button:HookScript("OnDisable", function(self) applyState(self, false) end)
    button:HookScript("OnEnable", function(self) applyState(self, false) end)

    applyState(button, false)
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
    if frame.GetObjectType and frame:GetObjectType() == "Button" then skinButton(frame) end
    if not frame.GetChildren then return end
    local children = { frame:GetChildren() }
    for _, child in ipairs(children) do scan(child) end
end

local watcher = CreateFrame("Frame")
watcher:SetScript("OnUpdate", function()
    local main = _G.ForeverEncyclopediaFrame
    if main and main:IsShown() then scan(main) end
end)
