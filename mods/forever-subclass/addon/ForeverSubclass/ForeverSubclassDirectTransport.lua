-- Direct server-bound FSC1 transport for WoW Forever 1.60.x.
-- UI modules own their own buttons; this file never rewires frames or click handlers.

local REQUEST="FSC1"
local RESPONSE="FSR1"
local SERVER_TARGET="SERVER"

local function registerPrefixes()
 if C_ChatInfo and C_ChatInfo.RegisterAddonMessagePrefix then
  pcall(C_ChatInfo.RegisterAddonMessagePrefix,REQUEST)
  pcall(C_ChatInfo.RegisterAddonMessagePrefix,RESPONSE)
 end
end

local function directSend(payload,quiet)
 if not C_ChatInfo or not C_ChatInfo.SendAddonMessage then
  if not quiet and DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cffff5555[Подклассы]|r Клиент не поддерживает addon-сообщения.") end
  return false
 end
 registerPrefixes()
 local ok,result=pcall(C_ChatInfo.SendAddonMessage,REQUEST,payload,"WHISPER",SERVER_TARGET)
 if not ok then
  if not quiet and DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cffff5555[Подклассы]|r Не удалось отправить запрос серверу: "..tostring(result)) end
  return false
 end
 return result~=false
end
_G.ForeverSubclassDirectSend=directSend

local legacySlash=SlashCmdList and SlashCmdList["FOREVERSUBCLASS"]
if SlashCmdList and legacySlash then
 SlashCmdList["FOREVERSUBCLASS"]=function(text)
  text=(text or ""):match("^%s*(.-)%s*$")
  if text=="status" or text=="clear" or text:match("^learn%s+%d+$") or text:match("^active%s+%d+$")
   or text:match("^xp%s+%d+$") or text:match("^select%s+%d+$") or text:match("^remove%s+%d+$")
   or text:match("^cast%s+%d+$") or text:match("^debuglevel%s+%d+%s+%d+$") then
   directSend(text);return
  end
  legacySlash(text)
  if not text:match("%S") then directSend("status",true) end
 end
end

local events=CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN");events:RegisterEvent("ADDON_LOADED")
events:SetScript("OnEvent",function(_,event)
 registerPrefixes()
 if event=="PLAYER_LOGIN" then
  if C_Timer and C_Timer.After then C_Timer.After(1.0,function() directSend("status",true) end) else directSend("status",true) end
 end
end)
