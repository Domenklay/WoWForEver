-- Player-frame resource integration for ForeverSubclass.
-- Primary class resource stays in the normal Blizzard power slot.
-- A different active-subclass resource is rendered as a compact secondary strip
-- attached directly beneath it. Druid primary keeps mana as its main resource.

local RESPONSE="FSR1"
local POWER_MANA=0
local POWER_RAGE=1
local POWER_ENERGY=3
local primaryPowerByClass={
 [1]=POWER_RAGE,   -- Warrior
 [2]=POWER_MANA,   -- Paladin
 [3]=POWER_MANA,   -- Hunter in this Forever ruleset
 [4]=POWER_ENERGY, -- Rogue
 [5]=POWER_MANA,   -- Priest
 [7]=POWER_MANA,   -- Shaman
 [8]=POWER_MANA,   -- Mage
 [9]=POWER_MANA,   -- Warlock
 [11]=POWER_MANA,  -- Druid: mana remains the main bar even in forms
}

local pending,state
local frame,mainBar,secondaryBar,nativeBar
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

local function makeBar(parent,height)
 local bar=CreateFrame("StatusBar",nil,parent)
 bar:SetHeight(height)
 bar:SetStatusBarTexture(nativeTexture)
 bar:SetMinMaxValues(0,1);bar:SetValue(0);bar:EnableMouse(false)

 local bg=bar:CreateTexture(nil,"BACKGROUND")
 bg:SetPoint("TOPLEFT",-1,1);bg:SetPoint("BOTTOMRIGHT",1,-1)
 bg:SetColorTexture(0.02,0.02,0.02,0.94)
 bar._fsubBackground=bg

 local top=bar:CreateTexture(nil,"BORDER");top:SetPoint("TOPLEFT",0,0);top:SetPoint("TOPRIGHT",0,0);top:SetHeight(1);top:SetColorTexture(0.38,0.38,0.38,0.65)
 local bottom=bar:CreateTexture(nil,"BORDER");bottom:SetPoint("BOTTOMLEFT",0,0);bottom:SetPoint("BOTTOMRIGHT",0,0);bottom:SetHeight(1);bottom:SetColorTexture(0,0,0,0.95)
 local left=bar:CreateTexture(nil,"BORDER");left:SetPoint("TOPLEFT",0,0);left:SetPoint("BOTTOMLEFT",0,0);left:SetWidth(1);left:SetColorTexture(0,0,0,0.95)
 local right=bar:CreateTexture(nil,"BORDER");right:SetPoint("TOPRIGHT",0,0);right:SetPoint("BOTTOMRIGHT",0,0);right:SetWidth(1);right:SetColorTexture(0,0,0,0.95)

 bar.text=bar:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
 bar.text:SetPoint("CENTER",0,0);bar.text:SetTextColor(1,1,1,1)
 return bar
end

local function build()
 if frame and mainBar and secondaryBar then return true end
 nativeBar=findNativeBar()
 if not nativeBar or not _G.PlayerFrame then return false end
 nativeTexture=getNativeTexture()

 -- Normally hidden. Used only when Blizzard changes the displayed power away
 -- from the primary class resource (notably druid forms). Most classes keep the
 -- untouched Blizzard bar here.
 frame=CreateFrame("Frame","ForeverSubclassPrimaryPowerOverlay",_G.PlayerFrame)
 frame:SetAllPoints(nativeBar)
 frame:SetFrameStrata(nativeBar.GetFrameStrata and nativeBar:GetFrameStrata() or "MEDIUM")
 frame:SetFrameLevel((nativeBar.GetFrameLevel and nativeBar:GetFrameLevel() or 1)+4)
 frame:EnableMouse(false)
 mainBar=makeBar(frame,math.max(8,nativeBar:GetHeight() or 10));mainBar:SetAllPoints(frame)

 -- Secondary resource is inset and attached directly to the Blizzard power bar.
 -- It moves/scales/hides with PlayerFrame and never floats independently.
 secondaryBar=makeBar(_G.PlayerFrame,7)
 secondaryBar:SetStatusBarTexture(nativeTexture)
 secondaryBar:SetFrameStrata(frame:GetFrameStrata())
 secondaryBar:SetFrameLevel(frame:GetFrameLevel()+1)
 secondaryBar:SetPoint("TOPLEFT",nativeBar,"BOTTOMLEFT",2,-2)
 secondaryBar:SetPoint("TOPRIGHT",nativeBar,"BOTTOMRIGHT",-2,-2)

 frame:Hide();secondaryBar:Hide()
 debug("attached secondary resource strip to PlayerFrame")
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
 bar:SetMinMaxValues(0,maximum);bar:SetValue(current);colorBar(bar,kind)
 bar.text:SetText(tostring(current).." / "..tostring(maximum))
 bar:Show()
end

local function chooseSecondaryPower(primaryKind)
 if not state or not state.powers then return nil end
 local native=nativePowerKind()

 -- Form/stance resource gets first priority if it differs from the main class
 -- resource and the server exposes it for the active subclass.
 if native~=nil and native~=primaryKind and state.powers[native] then return state.powers[native] end

 local rage=state.powers[POWER_RAGE]
 local energy=state.powers[POWER_ENERGY]
 local mana=state.powers[POWER_MANA]
 if rage and POWER_RAGE~=primaryKind and (rage.current or 0)>0 then return rage end
 if energy and POWER_ENERGY~=primaryKind and (energy.current or 0)>0 then return energy end
 if rage and POWER_RAGE~=primaryKind then return rage end
 if energy and POWER_ENERGY~=primaryKind then return energy end
 if mana and POWER_MANA~=primaryKind then return mana end
 for kind,power in pairs(state.powers) do if kind~=primaryKind then return power end end
 return nil
end

local function refreshPrimaryOverlay(primaryKind)
 local native=nativePowerKind()
 if primaryKind==nil or native==nil or native==primaryKind then frame:Hide();return end

 -- Druid primary remains mana-first even when bear/cat changes Blizzard's native
 -- display to rage/energy. Other classes normally never need this overlay.
 local current,maximum=getUnitPower(primaryKind)
 if not maximum then frame:Hide();return end
 setBar(mainBar,primaryKind,current,maximum);frame:Show()
end

local function refresh()
 if not build() then return end
 if not state or not state.active or state.active==0 then frame:Hide();secondaryBar:Hide();return end

 local primaryKind=primaryPowerKind()
 refreshPrimaryOverlay(primaryKind)
 local secondary=chooseSecondaryPower(primaryKind)
 if secondary then setBar(secondaryBar,secondary.kind,secondary.current,secondary.max)
 else secondaryBar:Hide() end
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
 p.current=math.max(0,(p.current or 0)-(spell.cost or 0));refresh()
end

local function parse(msg)
 local words={};for w in tostring(msg):gmatch("%S+") do table.insert(words,w) end
 local kind=words[1]
 if kind=="STATE" then pending={primary=tonumber(words[2]) or 0,active=tonumber(words[3]) or 0,spells={},powers={}}
 elseif kind=="POWER" and pending then local power=tonumber(words[2]);if power then pending.powers[power]={kind=power,current=tonumber(words[3]) or 0,max=tonumber(words[4]) or 1} end
 elseif kind=="SPELL" and pending then local id=tonumber(words[2]);if id then pending.spells[id]={id=id,root=tonumber(words[3]) or id,selected=words[5]=="1",cost=tonumber(words[6]) or 0,power=tonumber(words[7])} end
 elseif kind=="END" and pending then state=pending;pending=nil;refresh() end
end

local events=CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN");events:RegisterEvent("PLAYER_ENTERING_WORLD");events:RegisterEvent("UPDATE_SHAPESHIFT_FORM")
events:RegisterEvent("UNIT_DISPLAYPOWER");events:RegisterEvent("UNIT_POWER_UPDATE");events:RegisterEvent("UNIT_MAXPOWER");events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent",function(_,event,...)
 if event=="CHAT_MSG_ADDON" then local prefix,msg=...;if prefix==RESPONSE then parse(msg) end;return end
 if event=="UNIT_POWER_UPDATE" or event=="UNIT_MAXPOWER" or event=="UNIT_DISPLAYPOWER" then local unit=...;if unit and unit~="player" then return end;refresh();return end
 if C_Timer and C_Timer.After then C_Timer.After(0.4,function() build();refresh();sendStatus() end) else build();refresh();sendStatus() end
end)
