-- Single server-bound FSC1 transport for WoW Forever 1.60.x.
-- This module is the only periodic status poller. UI modules may request explicit
-- actions/status, but no second legacy whisper loop is loaded anymore.

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
  debug("TX error target="..tostring(target).." "..tostring(result))
  return false
 end
 debug("TX target="..tostring(target).." payload="..tostring(payload).." result="..tostring(result))
 return result~=false
end

local function directSend(payload,quiet)
 payload=tostring(payload or "")
 local ok=sendRaw(payload,SERVER_TARGET,quiet)
 if ok and payload=="status" then
  lastStatusTx=GetTime and GetTime() or 0
  waitingStatus=true
  retriedSelf=false
 end
 return ok
end
_G.ForeverSubclassDirectSend=directSend

SLASH_FOREVERSUBCLASS1="/fsub"
SlashCmdList["FOREVERSUBCLASS"]=function(text)
 text=(text or ""):match("^%s*(.-)%s*$")
 if text=="" then
  directSend("status",false)
  if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cff67d9ff[Подклассы]|r Запрошено состояние сервера.") end
 else
  directSend(text,false)
 end
end

local events=CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("PLAYER_ENTERING_WORLD")
events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent",function(_,event,...)
 registerPrefixes()
 if event=="CHAT_MSG_ADDON" then
  local prefix,text=...
  if prefix==RESPONSE then
   lastRx=GetTime and GetTime() or 0
   if tostring(text):match("^END$") then
    waitingStatus=false
    retriedSelf=false
   end
  end
  return
 end
 if C_Timer and C_Timer.After then
  C_Timer.After(1.0,function() directSend("status",true) end)
 else
  directSend("status",true)
 end
end)

events:SetScript("OnUpdate",function(_,dt)
 elapsed=elapsed+dt
 if elapsed<0.25 then return end
 elapsed=0
 if not UnitName or not UnitName("player") then return end
 local now=GetTime and GetTime() or 0

 -- If the special SERVER target receives no response, make one conservative
 -- retry addressed to the character. The core FSC1 endpoint consumes the packet
 -- before normal whisper target resolution. Never spam retries.
 if waitingStatus then
  if not retriedSelf and now-lastStatusTx>=2.0 then
   local selfTarget=UnitName("player")
   if selfTarget then
    retriedSelf=true
    sendRaw("status",selfTarget,true)
   end
  end
  if now-lastStatusTx<6.0 then return end
  waitingStatus=false
  debug("status timeout; backing off")
 end

 local interval=(UnitAffectingCombat and UnitAffectingCombat("player")) and 1.25 or 3.0
 -- After a timeout, do not hammer a broken transport. Retry slowly until an RX arrives.
 if lastStatusTx>0 and lastRx<lastStatusTx then interval=10.0 end
 if now-lastStatusTx>=interval then directSend("status",true) end
end)
