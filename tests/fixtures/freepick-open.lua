-- Exercise the actual slash handler and lazy UI opener without a game client.
local function object()
 local o={scripts={},shown=false}
 return setmetatable(o,{__index=function(_,key)
  if key=='CreateFontString' or key=='CreateTexture' then return function() return object() end end
  if key=='GetFrameLevel' then return function() return 10 end end
  if key=='GetFrameStrata' then return function() return 'HIGH' end end
  if key=='GetChildren' then return function() end end
  if key=='GetText' then return function(self) return self.text end end
  if key=='SetText' then return function(self,text) self.text=text end end
  if key=='SetScript' then return function(self,event,fn) self.scripts[event]=fn end end
  if key=='Show' then return function(self) self.shown=true end end
  if key=='Hide' then return function(self) self.shown=false end end
  if key=='IsShown' then return function(self) return self.shown end end
  return function() end
 end})
end
local frames,requests,messages,loads={},{},{},{}
UIParent=object();SlashCmdList={};UISpecialFrames={}
DEFAULT_CHAT_FRAME={AddMessage=function(_,text) table.insert(messages,text) end}
function CreateFrame(kind,name,parent)
 local f=object();f.parent=parent;f.TitleText=object()
 if name then _G[name]=f end
 table.insert(frames,f);return f
end
local inCombat=false
function InCombatLockdown() return inCombat end
function GetTime() return 1 end
C_ChatInfo={RegisterAddonMessagePrefix=function() end,SendAddonMessage=function(_,payload) table.insert(requests,payload);return true end}
C_AddOns={LoadAddOn=function(name)
 table.insert(loads,name)
 if nativeUI and name=='Blizzard_PlayerSpells' then
  PlayerSpellsFrame=object();PlayerSpellsFrame.TalentsFrame=object()
 end
 return nativeUI
end}
dofile(addonDir..'/ForeverSubclassDirectTransport.lua')
dofile(addonDir..'/ForeverSubclassTalents.lua')
local events=frames[#frames]
-- A server error before opening the UI must be visible without indexing a missing label.
events.scripts.OnEvent(events,'CHAT_MSG_ADDON','FSR1','ERROR module disabled or unsupported primary class')
assert(#messages==1)
inCombat=true;SlashCmdList.FOREVERSUBCLASS('')
assert(not ForeverSubclassTalentPanel and #messages==2)
inCombat=false;SlashCmdList.FOREVERSUBCLASS('')
assert(#loads>=1)
assert(ForeverSubclassTalentPanel and ForeverSubclassTalentPanel.shown)
assert(ForeverSubclassTalentPanel.parent.shown)
if nativeUI then
 assert(PlayerSpellsFrame.shown and PlayerSpellsFrame.TalentsFrame.shown)
 assert(not ForeverSubclassStandaloneFrame)
else
 assert(ForeverSubclassStandaloneFrame.shown)
 assert(UISpecialFrames[1]=='ForeverSubclassStandaloneFrame')
end
assert(requests[#requests]=='status')
local count=#frames
SlashCmdList.FOREVERSUBCLASS('')
assert(#frames==count and ForeverSubclassTalentPanel.shown)
SlashCmdList.FOREVERSUBCLASS('select 116')
assert(requests[#requests]=='select 116')
assert(#messages==2)
