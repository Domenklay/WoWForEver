-- Single server-bound FSC1 transport for WoW Forever 1.60.x.
-- This module is the only periodic status poller. UI modules request explicit
-- snapshots when they are opened or changed; idle polling is intentionally slow.

local REQUEST="FSC1"
local RESPONSE="FSR1"
local SERVER_TARGET="SERVER"
local lastStatusTx=0
local lastRx=0
local waitingStatus=false
local retriedSelf=false
local elapsed=0

local function debug(text)
 if _G.ForeverSubclassDebugAdd then _G.ForeverSubclassDebugAdd("TRANSPORT "..tostring(text)) end
end

local function registerPrefixes()
 if C_ChatInfo and C_ChatInfo.RegisterAddonMessagePrefix then
  pcall(C_ChatInfo.RegisterAddonMessagePrefix,REQUEST)
  pcall(C_ChatInfo.RegisterAddonMessagePrefix,RESPONSE)
 end
end

local function sendRaw(payload,target,quiet)
 if not C_ChatInfo or not C_ChatInfo.SendAddonMessage then
  if not quiet and DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cffff5555[Подклассы]|r Клиент не поддерживает addon-сообщения.") end
  return false
 end
 registerPrefixes()
 local ok,result=pcall(C_ChatInfo.SendAddonMessage,REQUEST,payload,"WHISPER",target)
 if not ok then
  if not quiet and DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cffff5555[Подклассы]|r Не удалось отправить запрос серверу: "..tostring(result)) end
  debug("TX error target="..tostring(target).." "..tostring(result));return false
 end
 if payload~="status" then debug("TX target="..tostring(target).." payload="..tostring(payload).." result="..tostring(result)) end
 return result~=false
end

local function directSend(payload,quiet)
 payload=tostring(payload or "")
 local ok=sendRaw(payload,SERVER_TARGET,quiet)
 if ok and payload=="status" then
  lastStatusTx=GetTime and GetTime() or 0;waitingStatus=true;retriedSelf=false
 end
 return ok
end
_G.ForeverSubclassDirectSend=directSend

SLASH_FOREVERSUBCLASS1="/fsub"
SlashCmdList["FOREVERSUBCLASS"]=function(text)
 text=(text or ""):match("^%s*(.-)%s*$")
 if text=="" then directSend("status",false)
 else directSend(text,false) end
end

local events=CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("PLAYER_ENTERING_WORLD")
events:RegisterEvent("PLAYER_REGEN_DISABLED")
events:RegisterEvent("PLAYER_REGEN_ENABLED")
events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent",function(_,event,...)
 registerPrefixes()
 if event=="CHAT_MSG_ADDON" then
  local prefix,text=...
  if prefix==RESPONSE then
   lastRx=GetTime and GetTime() or 0
   if tostring(text)=="END" then waitingStatus=false;retriedSelf=false end
  end
  return
 end
 local delay=(event=="PLAYER_REGEN_DISABLED" or event=="PLAYER_REGEN_ENABLED") and 0.15 or 1.0
 if C_Timer and C_Timer.After then C_Timer.After(delay,function() directSend("status",true) end)
 else directSend("status",true) end
end)

events:SetScript("OnUpdate",function(_,dt)
 elapsed=elapsed+dt;if elapsed<0.25 then return end;elapsed=0
 if not UnitName or not UnitName("player") then return end
 local now=GetTime and GetTime() or 0
 if waitingStatus then
  if not retriedSelf and now-lastStatusTx>=2.0 then
   local selfTarget=UnitName("player");if selfTarget then retriedSelf=true;sendRaw("status",selfTarget,true) end
  end
  if now-lastStatusTx<6.0 then return end
  waitingStatus=false;debug("status timeout; backing off")
 end

 -- Resources need reasonably fresh data in combat. Out of combat, UI actions and
 -- page opens request their own snapshots, so a ten-second safety poll is enough.
 local interval=(UnitAffectingCombat and UnitAffectingCombat("player")) and 1.0 or 10.0
 if lastStatusTx>0 and lastRx<lastStatusTx then interval=15.0 end
 if now-lastStatusTx>=interval then directSend("status",true) end
end)
