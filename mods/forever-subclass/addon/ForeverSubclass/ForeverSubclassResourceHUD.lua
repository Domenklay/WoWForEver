-- Player-frame resource integration for ForeverSubclass.
-- Primary class resource stays in the normal Blizzard power slot.
-- A different active-subclass resource is rendered as a compact Blizzard-like
-- strip attached directly beneath it. Druid primary keeps mana as its main bar.

local RESPONSE="FSR1"
local POWER_MANA=0
local POWER_RAGE=1
local POWER_ENERGY=3
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
local secondaryFrame
local nativeTexture="Interface\\TARGETINGFRAME\\UI-StatusBar"

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
 if not nativeBar or not nativeBar.GetStatusBarTexture then return nativeTexture end
 local region=nativeBar:GetStatusBarTexture()
 if region and region.GetTexture then
  local texture=region:GetTexture()
  if texture then return texture end
 end
 return nativeTexture
end

local function colorBar(bar,kind)
 if kind==POWER_RAGE then bar:SetStatusBarColor(0.82,0.08,0.08)
 elseif kind==POWER_ENERGY then bar:SetStatusBarColor(0.95,0.78,0.05)
 else bar:SetStatusBarColor(0.08,0.35,0.92) end
end

local function makePlainBar(parent)
 local bar=CreateFrame("StatusBar",nil,parent)
 bar:SetStatusBarTexture(nativeTexture)
 bar:SetMinMaxValues(0,1)
 bar:SetValue(0)
 bar:EnableMouse(false)
 bar.text=bar:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
 bar.text:SetPoint("CENTER",0,0)
 bar.text:SetTextColor(1,1,1,1)
 return bar
end

local function makeUIShell(parent,height)
 local template=BackdropTemplateMixin and "BackdropTemplate" or nil
 local shell=CreateFrame("Frame",nil,parent,template)
 shell:SetHeight(height)
 shell:EnableMouse(false)
 if shell.SetBackdrop then
  shell:SetBackdrop({
   bgFile="Interface\\Tooltips\\UI-Tooltip-Background",
   edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",
   tile=true,tileSize=8,edgeSize=5,
   insets={left=1,right=1,top=1,bottom=1}
  })
  shell:SetBackdropColor(0.015,0.015,0.015,0.96)
  shell:SetBackdropBorderColor(0.42,0.38,0.27,0.92)
 end
 return shell
end

local function build()
 if frame and mainBar and secondaryBar and secondaryFrame then return true end
 nativeBar=findNativeBar()
 if not nativeBar or not _G.PlayerFrame then return false end
 nativeTexture=getNativeTexture()

 -- Only used when Blizzard changes the displayed power away from the primary
 -- class resource (notably druid bear/cat). For normal classes this stays hidden.
 frame=CreateFrame("Frame","ForeverSubclassPrimaryPowerOverlay",_G.PlayerFrame)
 frame:SetAllPoints(nativeBar)
 frame:SetFrameStrata(nativeBar.GetFrameStrata and nativeBar:GetFrameStrata() or "MEDIUM")
 frame:SetFrameLevel((nativeBar.GetFrameLevel and nativeBar:GetFrameLevel() or 1)+4)
 frame:EnableMouse(false)
 mainBar=makePlainBar(frame)
 mainBar:SetAllPoints(frame)
 frame:Hide()

 -- Blizzard-like secondary resource shell. The shell belongs to PlayerFrame,
 -- so it follows scale, position, visibility and portrait movement automatically.
 local shellHeight=9
 secondaryFrame=makeUIShell(_G.PlayerFrame,shellHeight)
 secondaryFrame:SetFrameStrata(frame:GetFrameStrata())
 secondaryFrame:SetFrameLevel(frame:GetFrameLevel()+1)
 secondaryFrame:SetPoint("TOPLEFT",nativeBar,"BOTTOMLEFT",0,-1)
 secondaryFrame:SetPoint("TOPRIGHT",nativeBar,"BOTTOMRIGHT",0,-1)

 secondaryBar=makePlainBar(secondaryFrame)
 secondaryBar:SetPoint("TOPLEFT",2,-2)
 secondaryBar:SetPoint("BOTTOMRIGHT",-2,2)
 secondaryBar.text:SetFontObject(GameFontHighlightSmall)
 secondaryFrame:Hide()

 debug("attached Blizzard-style secondary resource to PlayerFrame")
 return true
end

local function getUnitPower(kind)
 if kind==nil or not UnitPower or not UnitPowerMax then return nil,nil end
 local maximum=UnitPowerMax("player",kind) or 0
 if maximum<=0 then return nil,nil end
 return UnitPower("player",kind) or 0,maximum
end

local function setBar(bar,kind,current,maximum)
 maximum=math.max(1,tonumber(maximum) or 1)
 current=math.max(0,tonumber(current) or 0)
 bar:SetMinMaxValues(0,maximum)
 bar:SetValue(current)
 colorBar(bar,kind)
 bar.text:SetText(tostring(current).." / "..tostring(maximum))
 bar:Show()
end

local function chooseSecondaryPower(primaryKind)
 if not state or not state.powers then return nil end
 local native=nativePowerKind()

 -- If a druid form/stance exposes a resource that belongs to the active
 -- subclass, prefer that as the secondary bar.
 if native~=nil and native~=primaryKind and state.powers[native] then
  return state.powers[native]
 end

 local rage=state.powers[POWER_RAGE]
 local energy=state.powers[POWER_ENERGY]
 local mana=state.powers[POWER_MANA]
 if rage and POWER_RAGE~=primaryKind and (rage.current or 0)>0 then return rage end
 if energy and POWER_ENERGY~=primaryKind and (energy.current or 0)>0 then return energy end
 if rage and POWER_RAGE~=primaryKind then return rage end
 if energy and POWER_ENERGY~=primaryKind then return energy end
 if mana and POWER_MANA~=primaryKind then return mana end
 for kind,power in pairs(state.powers) do
  if kind~=primaryKind then return power end
 end
 return nil
end

local function refreshPrimaryOverlay(primaryKind)
 local native=nativePowerKind()
 if primaryKind==nil or native==nil or native==primaryKind then
  frame:Hide()
  return
 end
 local current,maximum=getUnitPower(primaryKind)
 if not maximum then frame:Hide();return end
 setBar(mainBar,primaryKind,current,maximum)
 frame:Show()
end

local function refresh()
 if not build() then return end
 if not state or not state.active or state.active==0 then
  frame:Hide()
  secondaryFrame:Hide()
  return
 end

 local primaryKind=primaryPowerKind()
 refreshPrimaryOverlay(primaryKind)
 local secondary=chooseSecondaryPower(primaryKind)
 if secondary then
  setBar(secondaryBar,secondary.kind,secondary.current,secondary.max)
  secondaryFrame:Show()
 else
  secondaryFrame:Hide()
 end
end

_G.ForeverSubclassResourcePredictSpend=function(spellId)
 spellId=tonumber(spellId)
 if not spellId or not state or not state.powers or not state.spells then return end
 local spell=state.spells[spellId]
 if not spell or not spell.selected then
  for _,candidate in pairs(state.spells) do
   if candidate.selected and candidate.root==spellId then spell=candidate;break end
  end
 end
 if not spell then return end
 local p=state.powers[spell.power]
 if not p or spell.power==primaryPowerKind() then return end
 p.current=math.max(0,(p.current or 0)-(spell.cost or 0))
 refresh()
end

local function parse(msg)
 local words={}
 for w in tostring(msg):gmatch("%S+") do table.insert(words,w) end
 local kind=words[1]
 if kind=="STATE" then
  pending={primary=tonumber(words[2]) or 0,active=tonumber(words[3]) or 0,spells={},powers={}}
 elseif kind=="POWER" and pending then
  local power=tonumber(words[2])
  if power then pending.powers[power]={kind=power,current=tonumber(words[3]) or 0,max=tonumber(words[4]) or 1} end
 elseif kind=="SPELL" and pending then
  local id=tonumber(words[2])
  if id then pending.spells[id]={id=id,root=tonumber(words[3]) or id,selected=words[5]=="1",cost=tonumber(words[6]) or 0,power=tonumber(words[7])} end
 elseif kind=="END" and pending then
  state=pending
  pending=nil
  refresh()
 end
end

local events=CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("PLAYER_ENTERING_WORLD")
events:RegisterEvent("UPDATE_SHAPESHIFT_FORM")
events:RegisterEvent("UNIT_DISPLAYPOWER")
events:RegisterEvent("UNIT_POWER_UPDATE")
events:RegisterEvent("UNIT_MAXPOWER")
events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent",function(_,event,...)
 if event=="CHAT_MSG_ADDON" then
  local prefix,msg=...
  if prefix==RESPONSE then parse(msg) end
  return
 end
 if event=="UNIT_POWER_UPDATE" or event=="UNIT_MAXPOWER" or event=="UNIT_DISPLAYPOWER" then
  local unit=...
  if unit and unit~="player" then return end
  refresh()
  return
 end
 if C_Timer and C_Timer.After then
  C_Timer.After(0.4,function() build();refresh();sendStatus() end)
 else
  build();refresh();sendStatus()
 end
end)
