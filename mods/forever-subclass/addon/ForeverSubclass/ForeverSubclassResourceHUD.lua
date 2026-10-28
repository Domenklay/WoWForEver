-- Persistent multi-resource HUD for ForeverSubclass.
-- Server snapshots remain authoritative; local spend prediction only makes casts feel immediate.
-- IMPORTANT: this module never polls on its own. ForeverSubclass.lua owns the single periodic status poll.

local RESPONSE="FSR1"
local classNames={[1]="Воин",[2]="Паладин",[3]="Охотник",[4]="Разбойник",[5]="Жрец",[7]="Шаман",[8]="Маг",[9]="Чернокнижник",[11]="Друид"}
local powerNames={[0]="Мана",[1]="Ярость",[3]="Энергия"}
local powerOrder={0,1,3}
local pending,state
local frame,bars={},classText

local function sendStatus()
 if _G.ForeverSubclassDirectSend then _G.ForeverSubclassDirectSend("status",true) end
end

local function colorBar(bar,kind)
 if kind==1 then bar:SetStatusBarColor(0.78,0.12,0.12)
 elseif kind==3 then bar:SetStatusBarColor(0.88,0.73,0.08)
 else bar:SetStatusBarColor(0.10,0.35,0.90) end
end

local function build()
 if frame then return true end
 if not _G.PlayerFrame then return false end
 local template=BackdropTemplateMixin and "BackdropTemplate" or nil
 frame=CreateFrame("Frame","ForeverSubclassResourceHUD",UIParent,template)
 frame:SetSize(188,28);frame:SetPoint("TOPLEFT",PlayerFrame,"BOTTOMLEFT",42,-3)
 frame:SetFrameStrata("MEDIUM");frame:SetFrameLevel((PlayerFrame.GetFrameLevel and PlayerFrame:GetFrameLevel() or 1)+10);frame:EnableMouse(false)
 if frame.SetBackdrop then
  frame:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=true,tileSize=16,edgeSize=8,insets={left=2,right=2,top=2,bottom=2}})
  frame:SetBackdropColor(0.02,0.02,0.02,0.82);frame:SetBackdropBorderColor(0.28,0.24,0.16,0.9)
 end
 classText=frame:CreateFontString(nil,"OVERLAY","GameFontNormalSmall");classText:SetPoint("BOTTOMLEFT",frame,"TOPLEFT",2,1)
 for index,kind in ipairs(powerOrder) do
  local row=CreateFrame("StatusBar",nil,frame)
  row:SetSize(180,18);row:SetPoint("TOPLEFT",4,-4-(index-1)*20);row:SetStatusBarTexture("Interface\\TARGETINGFRAME\\UI-StatusBar")
  row.text=row:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall");row.text:SetPoint("CENTER")
  colorBar(row,kind);row.kind=kind;row:Hide();bars[kind]=row
 end
 frame:Hide();return true
end

local function isNativePower(kind)
 return UnitPowerType and select(1,UnitPowerType("player"))==kind
end

local function refresh()
 if not build() then return end
 if not state or not state.active or state.active==0 or not state.powers then frame:Hide();return end
 local visible=0
 for _,kind in ipairs(powerOrder) do
  local row=bars[kind];local p=state.powers[kind]
  if p and not isNativePower(kind) then
   visible=visible+1
   row:ClearAllPoints();row:SetPoint("TOPLEFT",4,-4-(visible-1)*20)
   row:SetMinMaxValues(0,math.max(1,p.max or 1));row:SetValue(math.max(0,p.current or 0));colorBar(row,kind)
   row.text:SetText((powerNames[kind] or "Ресурс").."  "..tostring(p.current or 0).." / "..tostring(p.max or 0));row:Show()
  else row:Hide() end
 end
 if visible==0 then frame:Hide();return end
 frame:SetHeight(8+visible*20)
 classText:SetText((classNames[state.active] or "Подкласс").." - дополнительные ресурсы")
 frame:Show()
end

-- Called by ForeverSubclassCastFeedback after a cast request is actually sent.
-- The next shared FSR1 POWER snapshot corrects this if the native cast is rejected.
_G.ForeverSubclassResourcePredictSpend=function(spellId)
 spellId=tonumber(spellId)
 if not spellId or not state or not state.powers or not state.spells then return end
 local spell=state.spells[spellId]
 if not spell or not spell.selected then
  -- Old action-bar shortcuts can carry an earlier rank. Match by root as well.
  for _,candidate in pairs(state.spells) do
   if candidate.selected and candidate.root==spellId then spell=candidate;break end
  end
 end
 if not spell then return end
 local p=state.powers[spell.power]
 if not p or isNativePower(spell.power) then return end
 p.current=math.max(0,(p.current or 0)-(spell.cost or 0))
 refresh()
 if _G.ForeverSubclassDebugAdd then _G.ForeverSubclassDebugAdd("RESOURCE predict spell="..spellId.." power="..tostring(spell.power).." current="..p.current) end
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
events:RegisterEvent("PLAYER_LOGIN");events:RegisterEvent("PLAYER_ENTERING_WORLD");events:RegisterEvent("UPDATE_SHAPESHIFT_FORM");events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent",function(_,event,...)
 if event=="CHAT_MSG_ADDON" then local prefix,msg=...;if prefix==RESPONSE then parse(msg) end;return end
 -- One event-triggered refresh is fine; there is deliberately no OnUpdate poll here.
 if C_Timer and C_Timer.After then C_Timer.After(0.8,sendStatus) else sendStatus() end
end)
