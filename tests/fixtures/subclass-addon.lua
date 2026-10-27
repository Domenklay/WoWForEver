-- Minimal WoW UI API double; exercises transport and server-authoritative updates.
local frames,buttons,labels={}, {}, {}
local function object()
 local o={scripts={},shown=true}
 return setmetatable(o,{__index=function(t,k)
  if k=="SetScript" then return function(self,event,f) self.scripts[event]=f end end
  if k=="SetText" then return function(self,text) self.text=text end end
  if k=="SetValue" then return function(self,value) self.value=value end end
  if k=="Show" then return function(self) local old=self.shown;self.shown=true;if not old and self.scripts.OnShow then self.scripts.OnShow(self) end end end
  if k=="Hide" then return function(self) self.shown=false end end
  if k=="IsShown" then return function(self) return self.shown end end
  if k=="CreateFontString" then return function() local f=object();table.insert(labels,f);return f end end
  if k=="GetPoint" then return function() return "CENTER",nil,"CENTER",0,0 end end
  return function() end
 end})
end
UIParent=object();DEFAULT_CHAT_FRAME={AddMessage=function() end};SlashCmdList={}
function CreateFrame(kind,name,parent,template)
 local f=object();f.TitleText=object()
 if name then _G[name]=f end
 if kind=="Button" then table.insert(buttons,f) end
 table.insert(frames,f);return f
end
local clock=0
function GetTime() return clock end
function UnitName() return "Kay" end
function UnitFullName() return "Kay","Forever" end
function GetNormalizedRealmName() return "Forever" end
C_Spell={GetSpellName=function(id) return "Spell "..id end}
local sent={};local prefixes={}
C_ChatInfo={RegisterAddonMessagePrefix=function(prefix) prefixes[prefix]=true end,
 SendAddonMessage=function(prefix,text,channel,target) table.insert(sent,{prefix,text,channel,target}) end}
dofile(argAddon)
local events=frames[#frames]
events.scripts.OnEvent(events,"PLAYER_LOGIN")
assert(prefixes.FSC1 and prefixes.FSR1)
clock=1;events.scripts.OnUpdate(events)
assert(#sent==1 and sent[1][2]=="status" and sent[1][3]=="WHISPER" and sent[1][4]=="Kay")
local function recv(text,sender)
 events.scripts.OnEvent(events,"CHAT_MSG_ADDON","FSR1",text,"WHISPER",sender or "Kay")
end
local function snapshot(mana,sender)
 recv("STATE 1 5 5 1 8",sender);recv("CLASS 1 40 0 1000",sender);recv("CLASS 5 1 200 400",sender)
 recv("POWER 0 "..mana.." 200",sender);recv("SPELL 2050 2050 1 1 30 0",sender);recv("END",sender)
end
snapshot(100)
assert(ForeverSubclassPowerBar.value==100 and ForeverSubclassPowerBar.shown)
snapshot(999,"AnotherPlayer")
assert(ForeverSubclassPowerBar.value==100)
local cast
for _,b in ipairs(buttons) do if b.text=="Каст" and b.shown then cast=b end end
assert(cast);cast.scripts.OnClick(cast)
clock=2;events.scripts.OnUpdate(events)
assert(sent[#sent][2]=="cast 2050")
assert(ForeverSubclassPowerBar.value==100) -- Never deduct authoritative power client-side.
snapshot(70)
assert(ForeverSubclassPowerBar.value==70)
assert(not ForeverSubclassFrame.shown)
SlashCmdList.FOREVERSUBCLASS("")
assert(ForeverSubclassFrame.shown)
recv("ERROR primary class has not reached subclass unlock level")
print("Addon transport, sender filtering, cast command and authoritative power updates passed")
