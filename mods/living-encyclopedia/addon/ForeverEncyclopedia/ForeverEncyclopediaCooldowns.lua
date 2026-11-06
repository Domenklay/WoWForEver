local RESPONSE = "FTR1"
local cooldowns = {}
local shieldGlow
local pending = { 0, 0, 0 }
local barrier = 0

local function ensure()
    local dock = _G.ForeverEncyclopediaV21BookDock
    if not dock then return false end
    if #cooldowns > 0 then return true end

    for i = 1, 3 do
        local cd = CreateFrame("Cooldown", nil, dock, "CooldownFrameTemplate")
        cd:SetSize(24, 24)
        cd:SetPoint("TOPLEFT", dock, "TOPLEFT", 63 + (i - 1) * 38, -30)
        cd:SetFrameLevel(dock:GetFrameLevel() + 8)
        cooldowns[i] = cd
    end

    shieldGlow = dock:CreateTexture(nil, "OVERLAY")
    shieldGlow:SetPoint("TOPLEFT", dock, "TOPLEFT", 59, -26)
    shieldGlow:SetSize(32, 32)
    shieldGlow:SetTexture("Interface\\Buttons\\UI-ActionButton-Border")
    shieldGlow:SetBlendMode("ADD")
    shieldGlow:SetAlpha(0)

    for i = 1, 3 do
        if pending[i] and pending[i] > 0 and cooldowns[i].SetCooldown then
            cooldowns[i]:SetCooldown(GetTime(), pending[i])
        end
    end
    shieldGlow:SetAlpha(barrier > 0 and 0.75 or 0)
    return true
end

local function applyCooldown(index, seconds)
    seconds = tonumber(seconds) or 0
    pending[index] = seconds
    if not ensure() then return end
    local cd = cooldowns[index]
    if seconds > 0 then
        cd:SetCooldown(GetTime(), seconds)
    elseif cd.Clear then
        cd:Clear()
    end
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("CHAT_MSG_ADDON")
frame:RegisterEvent("PLAYER_LOGIN")
frame:SetScript("OnEvent", function(_, event, prefix, msg)
    if event == "PLAYER_LOGIN" then
        C_Timer.After(1.0, ensure)
        return
    end
    if prefix ~= RESPONSE then return end
    msg = tostring(msg or "")
    if msg:sub(1, 5) ~= "BOOK|" then return end

    local _, _, _, _, _, shieldCd, healCd, supportCd, currentBarrier = strsplit("|", msg)
    applyCooldown(1, shieldCd)
    applyCooldown(2, healCd)
    applyCooldown(3, supportCd)
    barrier = tonumber(currentBarrier) or 0
    if ensure() and shieldGlow then
        shieldGlow:SetAlpha(barrier > 0 and 0.75 or 0)
    end
end)

frame:SetScript("OnUpdate", function()
    if #cooldowns == 0 then ensure() end
end)
