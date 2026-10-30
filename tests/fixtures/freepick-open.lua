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
  if key=='SetEnabled' then return function(self,value) self.enabled=value end end
  if key=='SetShown' then return function(self,value) self.shown=value end end
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

local customButton
for _,frame in ipairs(frames) do if frame.text=='Кастомное' then customButton=frame end end
assert(customButton)
local function reply(text) events.scripts.OnEvent(events,'CHAT_MSG_ADDON','FSR1',text) end
local customIds={[1463]=true,[282083]=true,[278016]=true}
function GetSpellInfo(id) assert(not customIds[id],'custom ID queried in the native spell database');return 'Native spell' end
reply('STATE 2 5 2 1 8 10000');reply('MODE FREEPICK 1');reply('CLASS 2 20 0 1000')
reply('SPELL 2050 2050 1 1 30 0')
reply('CUSTOM 1463 10 0 1 2 2 0 36 0')
reply('CUSTOM 278016 20 0 1 2 2 768 36 0');reply('END')
assert(customButton.shown)
customButton.scripts.OnClick(customButton)
assert(customButton.enabled==false)
local customNodes={}
for _,frame in ipairs(frames) do
 if type(frame.spell)=='table' and frame.spell.custom and frame.shown then table.insert(customNodes,frame) end
end
assert(#customNodes==2)
GameTooltip=object()
function GameTooltip:SetSpellByID() error('custom tooltip must not show an unrelated Forever spell') end
local requestCount=#requests
local pickups=0
ForeverSubclassPickupSpell=function() pickups=pickups+1 end
for _,node in ipairs(customNodes) do
 node.scripts.OnEnter(node)
 node.scripts.OnClick(node)
 node.scripts.OnDragStart(node)
end
assert(#requests==requestCount and pickups==0)
reply('STATE 2 5 2 2 8 10000');reply('MODE FREEPICK 1');reply('CLASS 2 20 0 1000')
reply('CUSTOM 1463 10 1 1 2 2 0 36 1');reply('END')
local shieldNode
for _,frame in ipairs(frames) do if type(frame.spell)=='table' and frame.spell.id==1463 and frame.shown then shieldNode=frame end end
assert(shieldNode)
shieldNode.scripts.OnClick(shieldNode,'RightButton');assert(requests[#requests]=='cast 1463')
shieldNode.scripts.OnDragStart(shieldNode);assert(pickups==1)
shieldNode.scripts.OnClick(shieldNode,'LeftButton');assert(requests[#requests]=='remove 1463')

dofile(addonDir..'/ForeverSubclassActionBar.lua')
local nativePickups,macroPickups,macroBody=0,0,nil
function PickupSpell() nativePickups=nativePickups+1 end
function GetMacroIndexByName() return 0 end
function CreateMacro(_,_,body) macroBody=body;return 1 end
function PickupMacro(id) assert(id==1);macroPickups=macroPickups+1 end
ForeverSubclassPickupSpell({id=1463,custom=true,selected=true,implemented=true})
assert(nativePickups==0 and macroPickups==1 and macroBody=='#showtooltip 1463\n/fsubcast 1463')
ForeverSubclassPickupSpell({id=278016,custom=true,selected=false,implemented=false})
assert(nativePickups==0 and macroPickups==1)
reply('STATE 1 5 1 0 8 10000');reply('CLASS 1 20 0 1000');reply('CLASS 5 10 0 1000');reply('END')
assert(not customButton.shown)
