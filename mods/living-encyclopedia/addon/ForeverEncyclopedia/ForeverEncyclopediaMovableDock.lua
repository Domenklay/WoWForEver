local ADDON = "ForeverEncyclopedia"
local REQUEST, RESPONSE = "FEB1", "FBR1"
local TALENT_RESPONSE = "FTR1"
local SERVER_TARGET = "SERVER"
local VERSION = "0.9.7"

local dock, manaBar, manaText
local abilityButtons = {}
local state = { mana=0, maxMana=100, mask=0, cooldowns={0,0,0}, companion=false, casts=false }

local function db()
    ForeverEncyclopediaDB = ForeverEncyclopediaDB or {}
    ForeverEncyclopediaDB.movableDock = ForeverEncyclopediaDB.movableDock or {}
    return ForeverEncyclopediaDB.movableDock
end

local function register(prefix)
    if C_ChatInfo and C_ChatInfo.RegisterAddonMessagePrefix then pcall(C_ChatInfo.RegisterAddonMessagePrefix, prefix) end
end

local function send(payload)
    register(REQUEST); register(RESPONSE)
    if C_ChatInfo and C_ChatInfo.SendAddonMessage then
        pcall(C_ChatInfo.SendAddonMessage, REQUEST, payload, "WHISPER", SERVER_TARGET)
    end
end

local function unlocked(bit)
    if bit32 then return bit32.band(state.mask or 0, bit) ~= 0 end
    return (state.mask or 0) % (bit * 2) >= bit
end

local function hideOldDocks()
    for _, name in ipairs({
        "ForeverEncyclopediaSafeDock",
        "ForeverEncyclopediaV21BookDock",
        "ForeverEncyclopediaV2BookDock",
        "ForeverEncyclopediaBookDock",
    }) do
        local f = _G[name]
        if f and f ~= dock then
            f:Hide(); f:SetAlpha(0); f:EnableMouse(false)
        end
    end
end

local function border(frame)
    local function e(a,b,w,h)
        local t=frame:CreateTexture(nil,"BORDER"); t:SetColorTexture(0.42,0.27,0.08,1); t:SetPoint(a); t:SetPoint(b)
        if w then t:SetWidth(w) end; if h then t:SetHeight(h) end
    end
    e("TOPLEFT","TOPRIGHT",nil,1); e("BOTTOMLEFT","BOTTOMRIGHT",nil,1); e("TOPLEFT","BOTTOMLEFT",1,nil); e("TOPRIGHT","BOTTOMRIGHT",1,nil)
end

local function savePosition()
    if not dock then return end
    local cx, cy = dock:GetCenter(); local ux, uy = UIParent:GetCenter()
    if not cx or not cy or not ux or not uy then return end
    local d=db(); d.x=cx-ux; d.y=cy-uy
end

local function place()
    if not dock then return end
    dock:ClearAllPoints()
    local d=db()
    if d.x and d.y then
        dock:SetPoint("CENTER", UIParent, "CENTER", d.x, d.y)
    else
        -- Default: along the very bottom edge, left of the main action bars.
        dock:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", 18, 18)
    end
end

local defs={
    {bit=1,icon="Interface\\Icons\\Spell_Holy_PowerWordShield",name="Охранная печать"},
    {bit=2,icon="Interface\\Icons\\Spell_Holy_Heal",name="Целительная пометка"},
    {bit=4,icon="Interface\\Icons\\Spell_Arcane_Arcane01",name="Тактическая подсказка"},
}

local function update()
    if not dock then return end
    local maxMana=math.max(1,tonumber(state.maxMana) or 100); local mana=math.max(0,math.min(maxMana,tonumber(state.mana) or 0))
    manaBar:SetMinMaxValues(0,maxMana); manaBar:SetValue(mana); manaText:SetText(mana.."/"..maxMana)
    for i,b in ipairs(abilityButtons) do
        local ok=unlocked(defs[i].bit); b.icon:SetAlpha(ok and 1 or 0.22); b.lock:SetShown(not ok)
        local sec=tonumber(state.cooldowns[i]) or 0
        if b.cooldown and b.cooldown.SetCooldown then
            if sec>0 then b.cooldown:SetCooldown(GetTime(),sec) elseif b.cooldown.Clear then b.cooldown:Clear() end
        end
    end
end

local function create()
    if dock then return end
    hideOldDocks()
    dock=CreateFrame("Frame","ForeverEncyclopediaMovableDock",UIParent)
    dock:SetSize(164,46); dock:SetFrameStrata("HIGH"); dock:SetClampedToScreen(true); dock:SetMovable(true); dock:EnableMouse(true)
    dock:RegisterForDrag("LeftButton")
    dock:SetScript("OnDragStart",function(self) self:StartMoving() end)
    dock:SetScript("OnDragStop",function(self) self:StopMovingOrSizing(); savePosition() end)
    place()

    local book=CreateFrame("Button",nil,dock); book:SetSize(42,42); book:SetPoint("LEFT",0,0); book:RegisterForClicks("LeftButtonUp","RightButtonUp")
    local bg=book:CreateTexture(nil,"BACKGROUND"); bg:SetAllPoints(); bg:SetColorTexture(0.035,0.020,0.010,0.94); border(book)
    local ic=book:CreateTexture(nil,"ARTWORK"); ic:SetPoint("TOPLEFT",4,-4); ic:SetPoint("BOTTOMRIGHT",-4,4); ic:SetTexture("Interface\\Icons\\INV_Misc_Book_09")
    book:SetScript("OnClick",function(_,button)
        if button=="RightButton" then send("companion toggle") else local h=SlashCmdList and SlashCmdList["FOREVERENCYCLOPEDIAV21"]; if h then h() end end
    end)
    book:SetScript("OnEnter",function(self)
        GameTooltip:SetOwner(self,"ANCHOR_TOP"); GameTooltip:AddLine("Живая энциклопедия",1,0.82,0.42)
        GameTooltip:AddLine("ЛКМ: открыть",0.78,0.78,0.78); GameTooltip:AddLine("ПКМ: спутник",0.78,0.78,0.78)
        GameTooltip:AddLine("Панель можно перетаскивать мышью за свободное место.",0.68,0.68,0.68,true); GameTooltip:Show()
    end); book:SetScript("OnLeave",function() GameTooltip:Hide() end)

    manaBar=CreateFrame("StatusBar",nil,dock); manaBar:SetPoint("TOPLEFT",48,-2); manaBar:SetSize(112,9); manaBar:SetStatusBarTexture("Interface\\TargetingFrame\\UI-StatusBar"); manaBar:SetStatusBarColor(0.18,0.36,0.72)
    local mb=manaBar:CreateTexture(nil,"BACKGROUND"); mb:SetAllPoints(); mb:SetColorTexture(0.015,0.015,0.022,0.92); border(manaBar)
    manaText=manaBar:CreateFontString(nil,"OVERLAY","GameFontNormalSmall"); manaText:SetPoint("CENTER")

    for i,def in ipairs(defs) do
        local b=CreateFrame("Button",nil,dock); b:SetSize(30,30); b:SetPoint("TOPLEFT",48+(i-1)*37,-14)
        local bb=b:CreateTexture(nil,"BACKGROUND"); bb:SetAllPoints(); bb:SetColorTexture(0.035,0.022,0.012,0.96); border(b)
        b.icon=b:CreateTexture(nil,"ARTWORK"); b.icon:SetPoint("TOPLEFT",3,-3); b.icon:SetPoint("BOTTOMRIGHT",-3,3); b.icon:SetTexture(def.icon)
        b.lock=b:CreateFontString(nil,"OVERLAY","GameFontNormalSmall"); b.lock:SetPoint("CENTER"); b.lock:SetText("×"); b.lock:SetTextColor(0.72,0.58,0.46)
        b.cooldown=CreateFrame("Cooldown",nil,b,"CooldownFrameTemplate"); b.cooldown:SetAllPoints(b.icon); b.cooldown:SetFrameLevel(b:GetFrameLevel()+5)
        b:SetScript("OnEnter",function(self) GameTooltip:SetOwner(self,"ANCHOR_TOP"); GameTooltip:AddLine(def.name,1,0.82,0.42); GameTooltip:AddLine(unlocked(def.bit) and "Изучено" or "Не изучено",0.72,0.72,0.72); GameTooltip:Show() end)
        b:SetScript("OnLeave",function() GameTooltip:Hide() end); abilityButtons[i]=b
    end
    update()
end

local function parseBook(msg)
    local _,mask,mana,maxMana,shieldCd,healCd,supportCd,_,companion,casts=strsplit("|",msg)
    state.mask=tonumber(mask) or state.mask; state.mana=tonumber(mana) or state.mana; state.maxMana=tonumber(maxMana) or state.maxMana
    state.cooldowns[1]=tonumber(shieldCd) or 0; state.cooldowns[2]=tonumber(healCd) or 0; state.cooldowns[3]=tonumber(supportCd) or 0
    state.companion=tonumber(companion)==1; state.casts=tonumber(casts)==1; update()
end

local function updateVersionLabel()
    local main=_G.ForeverEncyclopediaV21Frame; if not main or not main.GetRegions then return end
    local function scan(frame)
        local regions={frame:GetRegions()}
        for _,r in ipairs(regions) do
            if r and r.GetObjectType and r:GetObjectType()=="FontString" and r.GetText then
                local t=r:GetText(); if type(t)=="string" and t:find("^Forever Encyclopedia ") then r:SetText("Forever Encyclopedia "..VERSION.." V2.1") end
            end
        end
        if frame.GetChildren then for _,c in ipairs({frame:GetChildren()}) do scan(c) end end
    end
    scan(main)
end

SLASH_FOREVERENCYDOCK1="/encydock"
SlashCmdList["FOREVERENCYDOCK"]=function(msg)
    msg=tostring(msg or ""):lower():match("^%s*(.-)%s*$")
    if msg=="reset" then local d=db(); d.x=nil; d.y=nil; place() end
end

local events=CreateFrame("Frame"); events:RegisterEvent("ADDON_LOADED"); events:RegisterEvent("PLAYER_ENTERING_WORLD"); events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent",function(_,event,...)
    if event=="ADDON_LOADED" then local name=...; if name~=ADDON then return end; register(REQUEST); register(RESPONSE); register(TALENT_RESPONSE); return end
    if event=="CHAT_MSG_ADDON" then local prefix,msg=...; msg=tostring(msg or ""); if prefix==RESPONSE and msg:sub(1,5)=="BOOK|" then parseBook(msg) end; return end
    if event=="PLAYER_ENTERING_WORLD" then C_Timer.After(0.9,function() create(); hideOldDocks(); send("status"); updateVersionLabel() end) end
end)

local elapsed=0
events:SetScript("OnUpdate",function(_,dt)
    elapsed=elapsed+dt; if elapsed<0.25 then return end; elapsed=0
    hideOldDocks(); updateVersionLabel()
end)
