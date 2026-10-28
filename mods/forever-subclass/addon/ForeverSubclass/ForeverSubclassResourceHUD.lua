-- Integrated player-frame resource block for ForeverSubclass.
-- Primary class resource stays on top; one different subclass/form resource is shown
-- beneath it. Native class power slots are always read directly from the client.

local RESPONSE="FSR1"
local POWER_MANA=0
local POWER_RAGE=1
local POWER_ENERGY=3
local RAGE_DECAY_PER_SECOND=3

local primaryPowerByClass={
 [1]=POWER_RAGE,
 [2]=POWER_MANA,
 [3]=POWER_MANA,
 [4]=POWER_ENERGY,
 [5]=POWER_MANA,
 [7]=POWER_MANA,
 [8]=POWER_MANA,
 [9]=POWER_MANA,
 [11]=POWER_MANA,
}

local pending,state
local frame,mainBar,secondaryBar,nativeBar
local stockAlpha
local rageVisualFraction=0
local fallbackTexture="Interface\\TARGETINGFRAME\\UI-StatusBar"

local function debug(text)
 if _G.ForeverSubclassDebugAdd then _G.ForeverSubclassDebugAdd("RESOURCE "..tostring(text)) end
end

local function sendStatus()
 if _G.ForeverSubclassDirectSend then _G.ForeverSubclassDirectSend("status",true) end
end

local function nativePowerKind()
 if not UnitPowerType then return nil end
 return select(1,UnitPowerType("player"))
end

local function primaryPowerKind()
 if state and state.primary then return primaryPowerByClass[state.primary] end
 return nativePowerKind()
end

local function findNativeBar()
 if _G.PlayerFrameManaBar and _G.PlayerFrameManaBar.GetObjectType then return _G.PlayerFrameManaBar end
 local pf=_G.PlayerFrame
 if not pf then return nil end
 if pf.ManaBar and pf.ManaBar.GetObjectType then return pf.ManaBar end
 local content=pf.PlayerFrameContent
 local main=content and content.PlayerFrameContentMain
 local area=main and main.ManaBarArea
 local bar=area and area.ManaBar
 if bar and bar.GetObjectType then return bar end
 return nil
end

local function getNativeTexture()
 if not nativeBar or not nativeBar.GetStatusBarTexture then return fallbackTexture end
 local region=nativeBar:GetStatusBarTexture()
 if region and region.GetTexture then
  local texture=region:GetTexture()
  if texture then return texture end
 end
 return fallbackTexture
end

local function colorBar(bar,kind)
 if kind==POWER_RAGE then bar:SetStatusBarColor(0.82,0.08,0.08)
 elseif kind==POWER_ENERGY then bar:SetStatusBarColor(0.95,0.78,0.05)
 else bar:SetStatusBarColor(0.08,0.35,0.92) end
end

local function makeRow(parent)
 local bar=CreateFrame("StatusBar",nil,parent)
 bar:SetStatusBarTexture(getNativeTexture())
 bar:SetMinMaxValues(0,1);bar:SetValue(0);bar:EnableMouse(false)
 local bg=bar:CreateTexture(nil,"BACKGROUND")
 bg:SetAllPoints();bg:SetColorTexture(0.015,0.015,0.015,0.95)
 bar.text=bar:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
 bar.text:SetPoint("CENTER",0,0);bar.text:SetTextColor(1,1,1,1)
 return bar
end

local function setStockVisible(visible)
 if not nativeBar then return end
 if stockAlpha==nil and nativeBar.GetAlpha then stockAlpha=nativeBar:GetAlpha() end
 if nativeBar.SetAlpha then nativeBar:SetAlpha(visible and (stockAlpha or 1) or 0) end
end

local function build()
 if frame and mainBar and secondaryBar then return true end
 nativeBar=findNativeBar()
 if not nativeBar or not _G.PlayerFrame then return false end

 frame=CreateFrame("Frame","ForeverSubclassResourceHUD",_G.PlayerFrame)
 frame:SetFrameStrata(nativeBar.GetFrameStrata and nativeBar:GetFrameStrata() or "MEDIUM")
 frame:SetFrameLevel((nativeBar.GetFrameLevel and nativeBar:GetFrameLevel() or 1)+10)
 frame:EnableMouse(false)
 frame:SetPoint("TOPLEFT",nativeBar,"TOPLEFT",0,1)
 frame:SetPoint("TOPRIGHT",nativeBar,"TOPRIGHT",0,1)
 frame:SetHeight(math.max(18,(nativeBar:GetHeight() or 10)+8))

 local outer=frame:CreateTexture(nil,"BACKGROUND",nil,-8)
 outer:SetPoint("TOPLEFT",-2,2);outer:SetPoint("BOTTOMRIGHT",2,-2)
 outer:SetColorTexture(0.02,0.02,0.02,0.98)

 local topEdge=frame:CreateTexture(nil,"BORDER")
 topEdge:SetPoint("TOPLEFT",-1,1);topEdge:SetPoint("TOPRIGHT",1,1);topEdge:SetHeight(1);topEdge:SetColorTexture(0.58,0.48,0.24,0.95)
 local bottomEdge=frame:CreateTexture(nil,"BORDER")
 bottomEdge:SetPoint("BOTTOMLEFT",-1,-1);bottomEdge:SetPoint("BOTTOMRIGHT",1,-1);bottomEdge:SetHeight(1);bottomEdge:SetColorTexture(0.15,0.11,0.05,1)
 local leftEdge=frame:CreateTexture(nil,"BORDER")
 leftEdge:SetPoint("TOPLEFT",-1,1);leftEdge:SetPoint("BOTTOMLEFT",-1,-1);leftEdge:SetWidth(1);leftEdge:SetColorTexture(0.33,0.25,0.10,1)
 local rightEdge=frame:CreateTexture(nil,"BORDER")
 rightEdge:SetPoint("TOPRIGHT",1,1);rightEdge:SetPoint("BOTTOMRIGHT",1,-1);rightEdge:SetWidth(1);rightEdge:SetColorTexture(0.33,0.25,0.10,1)

 mainBar=makeRow(frame)
 mainBar:SetPoint("TOPLEFT",2,-2);mainBar:SetPoint("TOPRIGHT",-2,-2);mainBar:SetHeight(8)

 local divider=frame:CreateTexture(nil,"ARTWORK")
 divider:SetPoint("TOPLEFT",mainBar,"BOTTOMLEFT",0,-1);divider:SetPoint("TOPRIGHT",mainBar,"BOTTOMRIGHT",0,-1)
 divider:SetHeight(1);divider:SetColorTexture(0,0,0,0.9)

 secondaryBar=makeRow(frame)
 secondaryBar:SetPoint("TOPLEFT",divider,"BOTTOMLEFT",0,-1)
 secondaryBar:SetPoint("TOPRIGHT",divider,"BOTTOMRIGHT",0,-1)
 secondaryBar:SetPoint("BOTTOM",frame,"BOTTOM",0,2)

 frame:Hide()
 debug("built native-aware primary+secondary PlayerFrame power block")
 return true
end

local function getUnitPower(kind)
 if kind==nil or not UnitPower or not UnitPowerMax then return nil,nil end
 local maximum=UnitPowerMax("player",kind) or 0
 if maximum<=0 then return nil,nil end
 return UnitPower("player",kind) or 0,maximum
end

local function hasNativeClientPower(kind)
 local _,maximum=getUnitPower(kind)
 return maximum~=nil and maximum>0
end

local function setBar(bar,kind,current,maximum)
 maximum=math.max(1,tonumber(maximum) or 1)
 current=math.max(0,tonumber(current) or 0)
 bar:SetMinMaxValues(0,maximum);bar:SetValue(current);colorBar(bar,kind)
 bar.text:SetText(tostring(math.floor(current+0.5)).." / "..tostring(math.floor(maximum+0.5)))
end

local function primaryValues(primaryKind)
 if state and state.basePower and state.basePower.kind==primaryKind and state.basePower.max>0 then
  return state.basePower.current,state.basePower.max
 end
 return getUnitPower(primaryKind)
end

local function chooseSecondaryPower(primaryKind)
 if not state or not state.powers then return nil end
 local display=nativePowerKind()

 if display~=nil and display~=primaryKind and state.powers[display] then
  return {kind=display,live=hasNativeClientPower(display),server=state.powers[display]}
 end

 local order={POWER_RAGE,POWER_ENERGY,POWER_MANA}
 for _,kind in ipairs(order) do
  local power=state.powers[kind]
  if power and kind~=primaryKind then
   return {kind=kind,live=hasNativeClientPower(kind),server=power}
  end
 end
 return nil
end

local function secondaryValues(secondary)
 if not secondary then return nil,nil end
 if secondary.live then
  local current,maximum=getUnitPower(secondary.kind)
  if maximum then return current,maximum end
 end
 return secondary.server.current,secondary.server.max
end

local function hideCustom()
 if frame then frame:Hide() end
 setStockVisible(true)
end

local function refresh()
 if not build() then return end
 if not state or not state.active or state.active==0 then hideCustom();return end

 local primaryKind=primaryPowerKind()
 local secondary=chooseSecondaryPower(primaryKind)
 if not secondary or secondary.kind==primaryKind then hideCustom();return end

 local primaryCurrent,primaryMax=primaryValues(primaryKind)
 local secondaryCurrent,secondaryMax=secondaryValues(secondary)
 if not primaryMax or not secondaryMax then hideCustom();return end

 setBar(mainBar,primaryKind,primaryCurrent,primaryMax)
 setBar(secondaryBar,secondary.kind,secondaryCurrent,secondaryMax)
 setStockVisible(false)
 frame:Show()
end

_G.ForeverSubclassResourcePredictSpend=function(spellId)
 spellId=tonumber(spellId)
 if not spellId or not state or not state.powers or not state.spells then return end
 local spell=state.spells[spellId]
 if not spell or not spell.selected then
  for _,candidate in pairs(state.spells) do if candidate.selected and candidate.root==spellId then spell=candidate;break end end
 end
 if not spell then return end
 local p=state.powers[spell.power]
 if not p or spell.power==primaryPowerKind() then return end
 -- Native class slots are updated by UNIT_POWER_UPDATE; only predict virtual pools.
 if not hasNativeClientPower(spell.power) then p.current=math.max(0,(p.current or 0)-(spell.cost or 0)) end
 refresh()
end

local function parse(msg)
 local words={};for w in tostring(msg):gmatch("%S+") do table.insert(words,w) end
 local kind=words[1]
 if kind=="STATE" then
  pending={primary=tonumber(words[2]) or 0,active=tonumber(words[3]) or 0,spells={},powers={},basePower=nil}
 elseif kind=="BASEPOWER" and pending then
  local power=tonumber(words[2]);if power then pending.basePower={kind=power,current=tonumber(words[3]) or 0,max=tonumber(words[4]) or 1} end
 elseif kind=="POWER" and pending then
  local power=tonumber(words[2]);if power then pending.powers[power]={kind=power,current=tonumber(words[3]) or 0,max=tonumber(words[4]) or 1} end
 elseif kind=="SPELL" and pending then
  local id=tonumber(words[2]);if id then pending.spells[id]={id=id,root=tonumber(words[3]) or id,selected=words[5]=="1",cost=tonumber(words[6]) or 0,power=tonumber(words[7])} end
 elseif kind=="END" and pending then
  state=pending;pending=nil;rageVisualFraction=0;refresh()
 end
end

local events=CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("PLAYER_ENTERING_WORLD")
events:RegisterEvent("UPDATE_SHAPESHIFT_FORM")
events:RegisterEvent("UNIT_DISPLAYPOWER")
events:RegisterEvent("UNIT_POWER_UPDATE")
events:RegisterEvent("UNIT_MAXPOWER")
events:RegisterEvent("PLAYER_REGEN_DISABLED")
events:RegisterEvent("PLAYER_REGEN_ENABLED")
events:RegisterEvent("PLAYER_LOGOUT")
events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent",function(_,event,...)
 if event=="CHAT_MSG_ADDON" then local prefix,msg=...;if prefix==RESPONSE then parse(msg) end;return end
 if event=="PLAYER_LOGOUT" then setStockVisible(true);return end
 if event=="PLAYER_REGEN_DISABLED" or event=="PLAYER_REGEN_ENABLED" then rageVisualFraction=0;refresh();return end
 if event=="UNIT_POWER_UPDATE" or event=="UNIT_MAXPOWER" or event=="UNIT_DISPLAYPOWER" then
  local unit=...;if unit and unit~="player" then return end;refresh();return
 end
 if C_Timer and C_Timer.After then C_Timer.After(0.4,function() build();refresh();sendStatus() end) else build();refresh();sendStatus() end
end)

events:SetScript("OnUpdate",function(_,elapsed)
 -- Only virtual rage needs interpolation. Druid/warrior native rage is handled by
 -- the core and read directly from UnitPower even when it is not the display power.
 if not state or not state.active or UnitAffectingCombat("player") then return end
 local rage=state.powers and state.powers[POWER_RAGE]
 if not rage or hasNativeClientPower(POWER_RAGE) or rage.current<=0 then return end
 rageVisualFraction=rageVisualFraction+RAGE_DECAY_PER_SECOND*elapsed
 local whole=math.floor(rageVisualFraction)
 if whole<=0 then return end
 rageVisualFraction=rageVisualFraction-whole
 rage.current=math.max(0,rage.current-whole)
 refresh()
end)
