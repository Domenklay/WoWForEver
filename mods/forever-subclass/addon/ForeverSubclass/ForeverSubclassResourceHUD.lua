-- Integrated player-frame resource block for ForeverSubclass.
-- The primary class resource stays on top; the active subclass resource is shown
-- directly beneath it inside the same framed UI element. When no secondary
-- resource is needed the stock Blizzard power bar is left untouched.

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
local stockAlpha
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

 -- Match the stock power bar width, but extend the framed block downward enough
 -- for a true second row. This remains parented to PlayerFrame so it behaves like UI.
 frame:SetPoint("TOPLEFT",nativeBar,"TOPLEFT",0,1)
 frame:SetPoint("TOPRIGHT",nativeBar,"TOPRIGHT",0,1)
 frame:SetHeight(math.max(18,(nativeBar:GetHeight() or 10)+8))

 local outer=frame:CreateTexture(nil,"BACKGROUND",nil,-8)
 outer:SetPoint("TOPLEFT",-2,2);outer:SetPoint("BOTTOMRIGHT",2,-2)
 outer:SetColorTexture(0.02,0.02,0.02,0.98)
 frame._fsubOuter=outer

 local topEdge=frame:CreateTexture(nil,"BORDER")
 topEdge:SetPoint("TOPLEFT",-1,1);topEdge:SetPoint("TOPRIGHT",1,1);topEdge:SetHeight(1);topEdge:SetColorTexture(0.58,0.48,0.24,0.95)
 local bottomEdge=frame:CreateTexture(nil,"BORDER")
 bottomEdge:SetPoint("BOTTOMLEFT",-1,-1);bottomEdge:SetPoint("BOTTOMRIGHT",1,-1);bottomEdge:SetHeight(1);bottomEdge:SetColorTexture(0.15,0.11,0.05,1)
 local leftEdge=frame:CreateTexture(nil,"BORDER")
 leftEdge:SetPoint("TOPLEFT",-1,1);leftEdge:SetPoint("BOTTOMLEFT",-1,-1);leftEdge:SetWidth(1);leftEdge:SetColorTexture(0.33,0.25,0.10,1)
 local rightEdge=frame:CreateTexture(nil,"BORDER")
 rightEdge:SetPoint("TOPRIGHT",1,1);rightEdge:SetPoint("BOTTOMRIGHT",1,-1);rightEdge:SetWidth(1);rightEdge:SetColorTexture(0.33,0.25,0.10,1)

 mainBar=makeRow(frame)
 mainBar:SetPoint("TOPLEFT",2,-2);mainBar:SetPoint("TOPRIGHT",-2,-2)
 mainBar:SetHeight(8)

 local divider=frame:CreateTexture(nil,"ARTWORK")
 divider:SetPoint("TOPLEFT",mainBar,"BOTTOMLEFT",0,-1);divider:SetPoint("TOPRIGHT",mainBar,"BOTTOMRIGHT",0,-1)
 divider:SetHeight(1);divider:SetColorTexture(0,0,0,0.9)

 secondaryBar=makeRow(frame)
 secondaryBar:SetPoint("TOPLEFT",divider,"BOTTOMLEFT",0,-1)
 secondaryBar:SetPoint("TOPRIGHT",divider,"BOTTOMRIGHT",0,-1)
 secondaryBar:SetPoint("BOTTOM",frame,"BOTTOM",0,2)

 frame:Hide()
 debug("built integrated two-row PlayerFrame resource block")
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
end

local function chooseSecondaryPower(primaryKind)
 if not state or not state.powers then return nil end
 local native=nativePowerKind()

 -- A stance/form resource that differs from the primary-class resource gets
 -- priority when it is actually exposed by the active subclass snapshot.
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

local function primaryValues(primaryKind)
 -- Primary class power should remain the real client resource whenever possible.
 local current,maximum=getUnitPower(primaryKind)
 if maximum then return current,maximum end
 -- If the client does not expose that off-form power, use the server snapshot.
 local pool=state and state.powers and state.powers[primaryKind]
 if pool then return pool.current,pool.max end
 return nil,nil
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
 if not secondary then hideCustom();return end

 local primaryCurrent,primaryMax=primaryValues(primaryKind)
 if not primaryMax then hideCustom();return end

 setBar(mainBar,primaryKind,primaryCurrent,primaryMax)
 setBar(secondaryBar,secondary.kind,secondary.current,secondary.max)
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
 p.current=math.max(0,(p.current or 0)-(spell.cost or 0));refresh()
end

local function parse(msg)
 local words={};for w in tostring(msg):gmatch("%S+") do table.insert(words,w) end
 local kind=words[1]
 if kind=="STATE" then pending={primary=tonumber(words[2]) or 0,active=tonumber(words[3]) or 0,spells={},powers={}}
 elseif kind=="POWER" and pending then
  local power=tonumber(words[2]);if power then pending.powers[power]={kind=power,current=tonumber(words[3]) or 0,max=tonumber(words[4]) or 1} end
 elseif kind=="SPELL" and pending then
  local id=tonumber(words[2]);if id then pending.spells[id]={id=id,root=tonumber(words[3]) or id,selected=words[5]=="1",cost=tonumber(words[6]) or 0,power=tonumber(words[7])} end
 elseif kind=="END" and pending then state=pending;pending=nil;refresh() end
end

local events=CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("PLAYER_ENTERING_WORLD")
events:RegisterEvent("UPDATE_SHAPESHIFT_FORM")
events:RegisterEvent("UNIT_DISPLAYPOWER")
events:RegisterEvent("UNIT_POWER_UPDATE")
events:RegisterEvent("UNIT_MAXPOWER")
events:RegisterEvent("PLAYER_LOGOUT")
events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent",function(_,event,...)
 if event=="CHAT_MSG_ADDON" then local prefix,msg=...;if prefix==RESPONSE then parse(msg) end;return end
 if event=="PLAYER_LOGOUT" then setStockVisible(true);return end
 if event=="UNIT_POWER_UPDATE" or event=="UNIT_MAXPOWER" or event=="UNIT_DISPLAYPOWER" then
  local unit=...;if unit and unit~="player" then return end;refresh();return
 end
 if C_Timer and C_Timer.After then C_Timer.After(0.4,function() build();refresh();sendStatus() end) else build();refresh();sendStatus() end
end)
