local TAL_RES = "FTR1"
local RUNTIME_REQ, RUNTIME_RES = "FEB1", "FBR1"
local SERVER_TARGET = "SERVER"

local creatures = {}
local nameToEntry = {}
local currentTalentEntry
local selectedEntry
local infoButton
local elapsed = 0

local function registerPrefixes()
    if C_ChatInfo and C_ChatInfo.RegisterAddonMessagePrefix then
        for _, prefix in ipairs({ TAL_RES, RUNTIME_REQ, RUNTIME_RES }) do
            pcall(C_ChatInfo.RegisterAddonMessagePrefix, prefix)
        end
    end
end

local function sendInspect(entry)
    if not entry or entry <= 0 or not C_ChatInfo or not C_ChatInfo.SendAddonMessage then return end
    registerPrefixes()
    pcall(C_ChatInfo.SendAddonMessage, RUNTIME_REQ, "inspect " .. tostring(entry), "WHISPER", SERVER_TARGET)
end

local function hasBit(mask, bit)
    mask = tonumber(mask) or 0
    if bit32 then return bit32.band(mask, bit) ~= 0 end
    return mask % (bit * 2) >= bit
end

local SCHOOL_BITS = {
    { 1, "Физический" }, { 2, "Свет" }, { 4, "Огонь" }, { 8, "Природа" },
    { 16, "Лёд" }, { 32, "Тьма" }, { 64, "Тайная магия" },
}

local function schoolName(mask)
    local names = {}
    for _, row in ipairs(SCHOOL_BITS) do
        if hasBit(mask, row[1]) then names[#names + 1] = row[2] end
    end
    return #names > 0 and table.concat(names, "/") or "Неизвестная школа"
end

local function clientSpellInfo(id)
    id = tonumber(id)
    if not id then return nil, nil, 0 end

    if GetSpellInfo then
        local ok, name, _, icon, castTime = pcall(GetSpellInfo, id)
        if ok and name then return name, icon, tonumber(castTime) or 0 end
    end

    if C_Spell and C_Spell.GetSpellInfo then
        local ok, data = pcall(C_Spell.GetSpellInfo, id)
        if ok and data then
            return data.name, data.iconID or data.iconFileID, tonumber(data.castTime) or 0
        end
    end

    return "Заклинание #" .. tostring(id), nil, 0
end

local function findSelectedEntry(frame)
    if not frame or not frame.GetChildren then return nil end

    local children = { frame:GetChildren() }
    for _, child in ipairs(children) do
        if child and child._selected and child.GetRegions then
            local regions = { child:GetRegions() }
            for _, region in ipairs(regions) do
                if region and region.GetObjectType and region:GetObjectType() == "FontString" and region.GetText then
                    local text = region:GetText()
                    local entry = text and nameToEntry[text]
                    if entry then return entry end
                end
            end
        end
        local nested = findSelectedEntry(child)
        if nested then return nested end
    end
    return nil
end

local function scrubInternalClass(frame)
    if not frame or not frame.GetRegions then return end

    local regions = { frame:GetRegions() }
    for _, region in ipairs(regions) do
        if region and region.GetObjectType and region:GetObjectType() == "FontString" and region.GetText then
            local text = region:GetText()
            if type(text) == "string" and text:find("^Класс:") then
                region:SetText("")
            end
        end
    end

    if frame.GetChildren then
        local children = { frame:GetChildren() }
        for _, child in ipairs(children) do scrubInternalClass(child) end
    end
end

local function ensureButton()
    local main = _G.ForeverEncyclopediaV21Frame
    if not main then return nil end
    if infoButton and infoButton:GetParent() == main then return infoButton end

    infoButton = CreateFrame("Button", "ForeverEncyclopediaCreatureAbilities", main)
    infoButton:SetPoint("TOPLEFT", main, "TOPLEFT", 636, -392)
    infoButton:SetSize(290, 18)
    infoButton:SetFrameStrata("HIGH")

    infoButton.text = infoButton:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    infoButton.text:SetPoint("LEFT")
    infoButton.text:SetJustifyH("LEFT")
    infoButton.text:SetTextColor(0.86, 0.76, 0.58)

    infoButton:SetScript("OnEnter", function(self)
        local entry = self.entry
        local record = entry and creatures[entry]
        if not record or (record.level or 0) < 4 then return end

        GameTooltip:SetOwner(self, "ANCHOR_TOPRIGHT")
        GameTooltip:AddLine("Способности существа", 1, 0.82, 0.42)

        if not record.complete then
            GameTooltip:AddLine("Архив ещё анализирует запись.", 0.75, 0.75, 0.75, true)
        elseif not record.abilities or #record.abilities == 0 then
            GameTooltip:AddLine("В шаблоне существа не найдено активных заклинаний.", 0.75, 0.75, 0.75, true)
            GameTooltip:AddLine("Способности из SmartAI/C++-скриптов будут подключены следующим слоем.", 0.58, 0.58, 0.58, true)
        else
            for _, ability in ipairs(record.abilities) do
                local name, icon, castTime = clientSpellInfo(ability.id)
                local prefix = icon and ("|T" .. tostring(icon) .. ":16:16|t ") or ""
                GameTooltip:AddLine(prefix .. (name or ("Заклинание #" .. tostring(ability.id))), 0.95, 0.86, 0.65)

                local details = schoolName(ability.school)
                if ability.channeled then
                    details = details .. " • поддерживаемое"
                elseif castTime > 0 then
                    details = details .. string.format(" • каст %.1fс", castTime / 1000)
                else
                    details = details .. " • мгновенное"
                end

                local cd = math.max(tonumber(ability.recovery) or 0, tonumber(ability.categoryRecovery) or 0)
                if cd > 0 then details = details .. string.format(" • КД %.1fс", cd / 1000) end
                GameTooltip:AddLine(details, 0.72, 0.72, 0.72, true)
            end
        end
        GameTooltip:Show()
    end)
    infoButton:SetScript("OnLeave", function() GameTooltip:Hide() end)
    infoButton:Hide()
    return infoButton
end

local function refreshUI()
    local main = _G.ForeverEncyclopediaV21Frame
    if not main or not main:IsShown() then
        if infoButton then infoButton:Hide() end
        return
    end

    scrubInternalClass(main)
    selectedEntry = findSelectedEntry(main) or selectedEntry
    local button = ensureButton()
    local record = selectedEntry and creatures[selectedEntry]
    if not button or not record or (record.level or 0) < 4 then
        if button then button:Hide() end
        return
    end

    button.entry = selectedEntry
    if not record.complete then
        button.text:SetText("Способности: анализ…")
    elseif not record.abilities or #record.abilities == 0 then
        button.text:SetText("Способности: штатных не найдено")
    else
        button.text:SetText("Способности: " .. tostring(#record.abilities) .. "  •  наведите для подробностей")
    end
    button:Show()
end

local function parseTalent(msg)
    if msg:sub(1, 9) == "CREATURE|" then
        local _, entry, level = strsplit("|", msg)
        entry, level = tonumber(entry), tonumber(level) or 0
        if not entry then return end
        currentTalentEntry = entry
        creatures[entry] = creatures[entry] or { abilities = {} }
        creatures[entry].level = level
        if level >= 4 then sendInspect(entry) end
    elseif msg:sub(1, 6) == "CBASE|" and currentTalentEntry then
        local _, name = strsplit("|", msg)
        if name and name ~= "" then
            creatures[currentTalentEntry] = creatures[currentTalentEntry] or { abilities = {} }
            creatures[currentTalentEntry].name = name
            nameToEntry[name] = currentTalentEntry
        end
    elseif msg == "CEND" then
        currentTalentEntry = nil
    end
end

local function parseRuntime(msg)
    if msg:sub(1, 7) == "BSTART|" then
        local _, entry, count = strsplit("|", msg)
        entry = tonumber(entry)
        if not entry then return end
        creatures[entry] = creatures[entry] or {}
        creatures[entry].abilities = {}
        creatures[entry].expected = tonumber(count) or 0
        creatures[entry].complete = false
    elseif msg:sub(1, 7) == "BSPELL|" then
        local _, entry, spellId, school, recovery, categoryRecovery, channeled, positive = strsplit("|", msg)
        entry = tonumber(entry)
        if not entry then return end
        creatures[entry] = creatures[entry] or { abilities = {} }
        creatures[entry].abilities = creatures[entry].abilities or {}
        creatures[entry].abilities[#creatures[entry].abilities + 1] = {
            id = tonumber(spellId) or 0,
            school = tonumber(school) or 0,
            recovery = tonumber(recovery) or 0,
            categoryRecovery = tonumber(categoryRecovery) or 0,
            channeled = tonumber(channeled) == 1,
            positive = tonumber(positive) == 1,
        }
    elseif msg:sub(1, 5) == "BEND|" then
        local _, entry = strsplit("|", msg)
        entry = tonumber(entry)
        if entry and creatures[entry] then creatures[entry].complete = true end
        refreshUI()
    end
end

local events = CreateFrame("Frame")
events:RegisterEvent("ADDON_LOADED")
events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent", function(_, event, ...)
    if event == "ADDON_LOADED" then
        registerPrefixes()
        return
    end

    local prefix, msg = ...
    msg = tostring(msg or "")
    if prefix == TAL_RES then parseTalent(msg)
    elseif prefix == RUNTIME_RES then parseRuntime(msg) end
end)

events:SetScript("OnUpdate", function(_, dt)
    elapsed = elapsed + dt
    if elapsed < 0.25 then return end
    elapsed = 0
    refreshUI()
end)
