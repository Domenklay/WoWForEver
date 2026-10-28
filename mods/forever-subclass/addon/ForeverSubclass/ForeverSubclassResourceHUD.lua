-- Player-frame resource integration for ForeverSubclass.
-- Layout follows familiar WoW unit-frame conventions:
--   health (Blizzard) -> active combat resource -> secondary mana/native resource.
-- No detached HUD is created; everything is parented to PlayerFrame.

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
 if kind==1 then bar:SetStatusBarColor(0.82,0.08,0.08)
 elseif kind==3 then bar:SetStatusBarColor(0.95,0.78,0.05)
 else bar:SetStatusBarColor(0.08,0.35,0.92) end
end

local function makeBar(parent,height)
 local template=BackdropTemplateMixin and "BackdropTemplate" or nil
 local bar=CreateFrame("StatusBar",nil,parent,template)
 bar:SetHeight(height)
 bar:SetStatusBarTexture("Interface\\TARGETINGFRAME\\UI-StatusBar")
 bar:SetMinMaxValues(0,1);bar:SetValue(0);bar:EnableMouse(false)
 if bar.SetBackdrop then
  bar:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=true,tileSize=8,edgeSize=5,insets={left=1,right=1,top=1,bottom=1}})
  bar:SetBackdropColor(0.01,0.01,0.01,0.95)
  bar:SetBackdropBorderColor(0.34,0.31,0.23,0.95)
 end
 bar.text=bar:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
 bar.text:SetPoint("CENTER",0,0);bar.text:SetTextColor(1,1,1,1)
 return bar
end

local function build()
 if frame and mainBar and secondaryBar then return true end
 nativeBar=findNativeBar()
 if not nativeBar or not _G.PlayerFrame then return false end

 frame=CreateFrame("Frame","ForeverSubclassResourceHUD",_G.PlayerFrame)
 frame:SetFrameStrata(nativeBar.GetFrameStrata and nativeBar:GetFrameStrata() or "MEDIUM")
 frame:SetFrameLevel((nativeBar.GetFrameLevel and nativeBar:GetFrameLevel() or 1)+7)
 frame:EnableMouse(false);frame:SetAllPoints(nativeBar)

 mainBar=makeBar(frame,math.max(10,nativeBar:GetHeight() or 12));mainBar:SetAllPoints(frame)

 secondaryBar=makeBar(_G.PlayerFrame,8)
 secondaryBar:SetFrameStrata(frame:GetFrameStrata());secondaryBar:SetFrameLevel(frame:GetFrameLevel()+1)
 secondaryBar:SetPoint("TOPLEFT",nativeBar,"BOTTOMLEFT",0,-1)
 secondaryBar:SetPoint("TOPRIGHT",nativeBar,"BOTTOMRIGHT",0,-1)

 frame:Hide();secondaryBar:Hide();debug("attached resource stack to PlayerFrame")
 return true
end

local function chooseSubclassPower()
 if not state or not state.powers then return nil end
 local native=nativePowerKind();local rage=state.powers[1];local energy=state.powers[3];local mana=state.powers[0]
 if rage and rage.kind~=native and (rage.current or 0)>0 then return rage end
 if energy and energy.kind~=native and (energy.current or 0)>0 then return energy end
 if rage and rage.kind~=native then return rage end
 if energy and energy.kind~=native then return energy end
 if mana and mana.kind~=native then return mana end
 for kind,power in pairs(state.powers) do if kind~=native then return power end end
 return nil
end

local function setBar(bar,kind,current,maximum,showName)
 maximum=math.max(1,tonumber(maximum) or 1);current=math.max(0,tonumber(current) or 0)
 bar:SetMinMaxValues(0,maximum);bar:SetValue(current);colorBar(bar,kind)
 if showName then bar.text:SetText((powerNames[kind] or "Ресурс").."  "..current.." / "..maximum)
 else bar.text:SetText(current.." / "..maximum) end
 bar:Show()
end

local function getNativeValues(kind)
 if kind==nil or not UnitPower or not UnitPowerMax then return nil,nil end
 local maximum=UnitPowerMax("player",kind) or 0;if maximum<=0 then return nil,nil end
 return UnitPower("player",kind) or 0,maximum
end

local function chooseSecondaryKind(primary)
 local native=nativePowerKind()
 if native~=nil and (not primary or native~=primary.kind) then
  local _,maximum=getNativeValues(native);if maximum and maximum>0 then return native end
 end
 if native~=0 and (not primary or primary.kind~=0) then
  local _,maximum=getNativeValues(0);if maximum and maximum>0 then return 0 end
 end
 return nil
end

local function refreshSecondary(primary)
 if not secondaryBar then return end
 local kind=chooseSecondaryKind(primary);if kind==nil then secondaryBar:Hide();return end
 local current,maximum=getNativeValues(kind);if not maximum then secondaryBar:Hide();return end
 setBar(secondaryBar,kind,current,maximum,true)
end

local function refresh()
 if not build() then return end
 if not state or not state.active or state.active==0 then frame:Hide();secondaryBar:Hide();return end
 local primary=chooseSubclassPower()
 if primary then setBar(mainBar,primary.kind,primary.current,primary.max,true);frame:Show() else frame:Hide() end
 refreshSecondary(primary)
end

_G.ForeverSubclassResourcePredictSpend=function(spellId)
 spellId=tonumber(spellId)
 if not spellId or not state or not state.powers or not state.spells then return end
 local spell=state.spells[spellId]
 if not spell or not spell.selected then
  for _,candidate in pairs(state.spells) do if candidate.selected and candidate.root==spellId then spell=candidate;break end end
 end
 if not spell then return end
 local p=state.powers[spell.power];if not p or spell.power==nativePowerKind() then return end
 p.current=math.max(0,(p.current or 0)-(spell.cost or 0));refresh()
end

local function parse(msg)
 local words={};for w in tostring(msg):gmatch("%S+") do table.insert(words,w) end
 local kind=words[1]
 if kind=="STATE" then pending={active=tonumber(words[3]) or 0,spells={},powers={}}
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
