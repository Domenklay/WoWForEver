-- Persistent second-resource HUD for ForeverSubclass.
-- Server snapshots remain authoritative; local spend prediction only makes casts feel immediate.

local RESPONSE="FSR1"
local classNames={[1]="Воин",[2]="Паладин",[3]="Охотник",[4]="Разбойник",[5]="Жрец",[7]="Шаман",[8]="Маг",[9]="Чернокнижник",[11]="Друид"}
local powerNames={[0]="Мана",[1]="Ярость",[3]="Энергия"}
local pending,state
local frame,bar,text,classText
local elapsed=0

local function sendStatus()
 if _G.ForeverSubclassDirectSend then _G.ForeverSubclassDirectSend("status",true) end
end

local function build()
 if frame then return true end
 if not _G.PlayerFrame then return false end
 local template=BackdropTemplateMixin and "BackdropTemplate" or nil
 frame=CreateFrame("Frame","ForeverSubclassResourceHUD",UIParent,template)
 frame:SetSize(188,30);frame:SetPoint("TOPLEFT",PlayerFrame,"BOTTOMLEFT",42,-2)
 frame:SetFrameStrata("MEDIUM");frame:SetFrameLevel((PlayerFrame.GetFrameLevel and PlayerFrame:GetFrameLevel() or 1)+10);frame:EnableMouse(false)
 if frame.SetBackdrop then
  frame:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=true,tileSize=16,edgeSize=8,insets={left=2,right=2,top=2,bottom=2}})
  frame:SetBackdropColor(0.02,0.02,0.02,0.82);frame:SetBackdropBorderColor(0.28,0.24,0.16,0.9)
 end
 bar=CreateFrame("StatusBar",nil,frame);bar:SetPoint("TOPLEFT",4,-4);bar:SetPoint("BOTTOMRIGHT",-4,4);bar:SetStatusBarTexture("Interface\\TARGETINGFRAME\\UI-StatusBar")
 text=bar:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall");text:SetPoint("CENTER")
 classText=frame:CreateFontString(nil,"OVERLAY","GameFontNormalSmall");classText:SetPoint("BOTTOMLEFT",frame,"TOPLEFT",2,1)
 frame:Hide();return true
end

local function isNativePower(kind)
 return UnitPowerType and select(1,UnitPowerType("player"))==kind
end

local function refresh()
 if not build() then return end
 if not state or not state.active or state.active==0 or not state.power then frame:Hide();return end
 if isNativePower(state.power.kind) then frame:Hide();return end
 local p=state.power
 bar:SetMinMaxValues(0,math.max(1,p.max or 1));bar:SetValue(math.max(0,p.current or 0))
 if p.kind==1 then bar:SetStatusBarColor(0.78,0.12,0.12) elseif p.kind==3 then bar:SetStatusBarColor(0.88,0.73,0.08) else bar:SetStatusBarColor(0.10,0.35,0.90) end
 text:SetText((powerNames[p.kind] or "Ресурс").."  "..tostring(p.current or 0).." / "..tostring(p.max or 0))
 classText:SetText((classNames[state.active] or "Подкласс").." - второй ресурс")
 frame:Show()
end

-- Called by ForeverSubclassCastFeedback after a cast request is actually sent.
-- The next FSR1 POWER snapshot corrects this immediately if the native cast is rejected.
_G.ForeverSubclassResourcePredictSpend=function(spellId)
 spellId=tonumber(spellId)
 if not spellId or not state or not state.power or not state.spells then return end
 local spell=state.spells[spellId]
 if not spell or not spell.selected or spell.power~=state.power.kind then return end
 if isNativePower(state.power.kind) then return end
 state.power.current=math.max(0,(state.power.current or 0)-(spell.cost or 0))
 refresh()
 if _G.ForeverSubclassDebugAdd then _G.ForeverSubclassDebugAdd("RESOURCE predict spell="..spellId.." current="..state.power.current) end
end

local function parse(msg)
 local words={};for w in tostring(msg):gmatch("%S+") do table.insert(words,w) end
 local kind=words[1]
 if kind=="STATE" then pending={active=tonumber(words[3]) or 0,spells={}}
 elseif kind=="POWER" and pending then pending.power={kind=tonumber(words[2]),current=tonumber(words[3]) or 0,max=tonumber(words[4]) or 1}
 elseif kind=="SPELL" and pending then
  local id=tonumber(words[2]);if id then pending.spells[id]={id=id,selected=words[5]=="1",cost=tonumber(words[6]) or 0,power=tonumber(words[7])} end
 elseif kind=="END" and pending then state=pending;pending=nil;refresh() end
end

local events=CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN");events:RegisterEvent("PLAYER_ENTERING_WORLD");events:RegisterEvent("UPDATE_SHAPESHIFT_FORM");events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent",function(_,event,...)
 if event=="CHAT_MSG_ADDON" then local prefix,msg=...;if prefix==RESPONSE then parse(msg) end;return end
 if C_Timer and C_Timer.After then C_Timer.After(0.8,sendStatus) else sendStatus() end
end)
events:SetScript("OnUpdate",function(_,dt)
 elapsed=elapsed+dt
 local interval=(UnitAffectingCombat and UnitAffectingCombat("player")) and 0.5 or 1.5
 if elapsed<interval then return end
 elapsed=0
 if state and state.active and state.active~=0 then sendStatus() end
end)
