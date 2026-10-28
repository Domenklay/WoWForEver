-- Player-frame resource integration for ForeverSubclass.
-- The active subclass resource is presented as the main power bar when it differs
-- from the player's native resource. The native resource is then mirrored as a
-- thin secondary bar below it. Server FSR1 snapshots remain authoritative.

local RESPONSE="FSR1"
local powerNames={[0]="Мана",[1]="Ярость",[3]="Энергия"}
local pending,state
local frame,mainBar,secondaryBar,nativeBar

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

local function colorBar(bar,kind)
 if kind==1 then bar:SetStatusBarColor(0.78,0.10,0.10)
 elseif kind==3 then bar:SetStatusBarColor(0.86,0.67,0.08)
 else bar:SetStatusBarColor(0.08,0.32,0.82) end
end

local function addBackground(bar,alpha)
 local bg=bar:CreateTexture(nil,"BACKGROUND")
 bg:SetAllPoints();bg:SetColorTexture(0.015,0.015,0.015,alpha or 0.92)
 bar._fsubBackground=bg
end

local function build()
 if frame and mainBar and secondaryBar then return true end
 nativeBar=findNativeBar()
 if not nativeBar or not _G.PlayerFrame then return false end

 frame=CreateFrame("Frame","ForeverSubclassResourceHUD",UIParent)
 frame:SetFrameStrata(nativeBar.GetFrameStrata and nativeBar:GetFrameStrata() or "MEDIUM")
 frame:SetFrameLevel((nativeBar.GetFrameLevel and nativeBar:GetFrameLevel() or 1)+8)
 frame:EnableMouse(false)
 frame:SetAllPoints(nativeBar)

 mainBar=CreateFrame("StatusBar",nil,frame)
 mainBar:SetAllPoints(frame)
 mainBar:SetStatusBarTexture("Interface\\TARGETINGFRAME\\UI-StatusBar")
 addBackground(mainBar,0.96)
 mainBar.text=mainBar:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
 mainBar.text:SetPoint("CENTER",0,0)
 mainBar:EnableMouse(false)

 secondaryBar=CreateFrame("StatusBar",nil,UIParent)
 secondaryBar:SetFrameStrata(frame:GetFrameStrata())
 secondaryBar:SetFrameLevel(frame:GetFrameLevel()+1)
 secondaryBar:SetStatusBarTexture("Interface\\TARGETINGFRAME\\UI-StatusBar")
 secondaryBar:SetHeight(6)
 secondaryBar:SetPoint("TOPLEFT",nativeBar,"BOTTOMLEFT",0,-1)
 secondaryBar:SetPoint("TOPRIGHT",nativeBar,"BOTTOMRIGHT",0,-1)
 addBackground(secondaryBar,0.94)
 secondaryBar:EnableMouse(false)

 frame:Hide();secondaryBar:Hide()
 debug("HUD built on native power bar")
 return true
end

local function chooseSubclassPower()
 if not state or not state.powers then return nil end
 local native=nativePowerKind()
 local rage=state.powers[1]
 local energy=state.powers[3]
 local mana=state.powers[0]
 -- Prefer an actively used physical resource, then any other subclass resource.
 if rage and rage.kind~=native and (rage.current or 0)>0 then return rage end
 if energy and energy.kind~=native and (energy.current or 0)>0 then return energy end
 if rage and rage.kind~=native then return rage end
 if energy and energy.kind~=native then return energy end
 if mana and mana.kind~=native then return mana end
 for kind,power in pairs(state.powers) do if kind~=native then return power end end
 return nil
end

local function refreshNativeSecondary()
 if not secondaryBar or not secondaryBar:IsShown() then return end
 local native=nativePowerKind()
 if native==nil or not UnitPower or not UnitPowerMax then secondaryBar:Hide();return end
 local maximum=math.max(1,UnitPowerMax("player",native) or 1)
 local current=math.max(0,UnitPower("player",native) or 0)
 secondaryBar:SetMinMaxValues(0,maximum);secondaryBar:SetValue(current);colorBar(secondaryBar,native)
end

local function refresh()
 if not build() then return end
 if not state or not state.active or state.active==0 then frame:Hide();secondaryBar:Hide();return end
 local power=chooseSubclassPower()
 if not power then frame:Hide();secondaryBar:Hide();return end

 mainBar:SetMinMaxValues(0,math.max(1,power.max or 1))
 mainBar:SetValue(math.max(0,power.current or 0));colorBar(mainBar,power.kind)
 mainBar.text:SetText((powerNames[power.kind] or "Ресурс").."  "..tostring(power.current or 0).." / "..tostring(power.max or 0))
 frame:Show();secondaryBar:Show();refreshNativeSecondary()
end

-- Called immediately after a subclass cast request. The next FSR1 POWER snapshot
-- corrects this prediction if the server rejects the cast.
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
 if not p or spell.power==nativePowerKind() then return end
 p.current=math.max(0,(p.current or 0)-(spell.cost or 0));refresh()
end

local function parse(msg)
 local words={};for w in tostring(msg):gmatch("%S+") do table.insert(words,w) end
 local kind=words[1]
 if kind=="STATE" then pending={active=tonumber(words[3]) or 0,spells={},powers={}}
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
events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent",function(_,event,...)
 if event=="CHAT_MSG_ADDON" then local prefix,msg=...;if prefix==RESPONSE then parse(msg) end;return end
 if event=="UNIT_POWER_UPDATE" or event=="UNIT_MAXPOWER" or event=="UNIT_DISPLAYPOWER" then
  local unit=...;if unit and unit~="player" then return end;refreshNativeSecondary();return
 end
 if C_Timer and C_Timer.After then C_Timer.After(0.4,function() build();refresh();sendStatus() end) else build();refresh();sendStatus() end
end)
