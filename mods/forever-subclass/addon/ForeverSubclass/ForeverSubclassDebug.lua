-- Diagnostics for ForeverSubclass. No gameplay authority lives here.
-- /fsubdebug saves a fresh snapshot. /fsubdebug show opens a copyable viewer.
-- /fsubdebug verbose toggles full protocol logging for short diagnostic sessions.

local ADDON="ForeverSubclass"
local MAX_LINES=400
local lines=_G.ForeverSubclassDebugLog or {}
_G.ForeverSubclassDebugLog=lines
local window,editBox,lastFocusDesc
local transportWrapped=false
local errorCaptureInstalled=false
local previousErrorHandler
local verbose=false
local hooks=setmetatable({}, {__mode="k"})

local function now() if date then return date("%H:%M:%S") end return tostring(GetTime and math.floor(GetTime()) or 0) end
local function trim() while #lines>MAX_LINES do table.remove(lines,1) end end
local function add(text)
 table.insert(lines,string.format("[%s] %s",now(),tostring(text or "")));trim();_G.ForeverSubclassDebugLog=lines
 if editBox and editBox:IsShown() then editBox:SetText(table.concat(lines,"\n"));editBox:SetCursorPosition(#editBox:GetText()) end
end
_G.ForeverSubclassDebugAdd=add

local function installErrorCapture()
 if errorCaptureInstalled or not geterrorhandler or not seterrorhandler then return false end
 previousErrorHandler=geterrorhandler()
 local function handler(message)
  local text=tostring(message or "")
  if text:find("ForeverSubclass",1,true) or text:find("FSub",1,true) then add("LUA ERROR "..text) end
  if previousErrorHandler then return previousErrorHandler(message) end
 end
 seterrorhandler(handler);errorCaptureInstalled=true;add("Lua error capture installed");return true
end

local function addonVersion()
 if C_AddOns and C_AddOns.GetAddOnMetadata then return C_AddOns.GetAddOnMetadata(ADDON,"Version") or "?" end
 if GetAddOnMetadata then return GetAddOnMetadata(ADDON,"Version") or "?" end
 return "?"
end
local function frameText(frame)
 if not frame then return nil end
 if frame.GetText then local ok,v=pcall(frame.GetText,frame);if ok and v and v~="" then return tostring(v) end end
 if frame.GetRegions then for _,r in ipairs({frame:GetRegions()}) do if r and r.GetObjectType and r:GetObjectType()=="FontString" and r.GetText then local ok,v=pcall(r.GetText,r);if ok and v and v~="" then return tostring(v) end end end end
end
local function describe(frame)
 if not frame then return "<none>" end
 if type(frame)~="table" and type(frame)~="userdata" then return "<non-frame:"..type(frame).."> "..tostring(frame) end
 local name=frame.GetName and frame:GetName() or nil;local object=frame.GetObjectType and frame:GetObjectType() or "?";local strata=frame.GetFrameStrata and frame:GetFrameStrata() or "?";local level=frame.GetFrameLevel and frame:GetFrameLevel() or -1
 local shown=frame.IsShown and frame:IsShown() and "shown" or "hidden";local mouse=frame.IsMouseEnabled and frame:IsMouseEnabled() and "mouse=1" or "mouse=0";local text=frameText(frame)
 return string.format("%s name=%s strata=%s level=%s %s %s%s",object,name or "<unnamed>",tostring(strata),tostring(level),shown,mouse,text and (" text='"..text.."'") or "")
end
local function currentMouseFocus()
 if GetMouseFoci then local first=GetMouseFoci();if type(first)=="table" then return first[1] end;return first end
 if GetMouseFocus then return GetMouseFocus() end
end
local function hookButtons(root)
 if not root or not root.GetChildren then return end
 for _,child in ipairs({root:GetChildren()}) do
  if child and child.GetObjectType and child:GetObjectType()=="Button" and not hooks[child] then
   hooks[child]=true
   if child.HookScript then
    child:HookScript("OnMouseDown",function(self,b)add("MOUSEDOWN "..tostring(b).." "..describe(self))end)
    child:HookScript("OnClick",function(self,b)add("CLICK "..tostring(b).." "..describe(self))end)
   end
  end
  hookButtons(child)
 end
end
local function wrapTransport()
 if transportWrapped or not _G.ForeverSubclassDirectSend then return false end
 local original=_G.ForeverSubclassDirectSend
 _G.ForeverSubclassDirectSend=function(payload,quiet)
  if payload~="status" or verbose then add("TX FSC1 "..tostring(payload)) end
  local ok,result=pcall(original,payload,quiet)
  if not ok then add("TX ERROR "..tostring(result));return false end
  return result
 end
 transportWrapped=true;add("transport wrapper installed");return true
end
local function refreshHeader()
 local build,buildNumber,buildDate,tocVersion="?","?","?","?";if GetBuildInfo then build,buildNumber,buildDate,tocVersion=GetBuildInfo() end
 add(string.format("CLIENT addon=%s wow=%s build=%s toc=%s",addonVersion(),tostring(build),tostring(buildNumber),tostring(tocVersion)))
 add("FRAME SUBCLASS "..describe(_G.ForeverSubclassTalentPanel));add("FRAME TALENTS "..describe(_G.PlayerSpellsFrame and _G.PlayerSpellsFrame.TalentsFrame));add("FRAME RESOURCE "..describe(_G.ForeverSubclassResourceHUD));add("MOUSEFOCUS SNAPSHOT "..describe(currentMouseFocus()))
 if _G.ForeverSubclassTalentPanel then hookButtons(_G.ForeverSubclassTalentPanel) end
end

local function createWindow()
 if window then return end
 local template=BackdropTemplateMixin and "BackdropTemplate" or nil
 window=CreateFrame("Frame","ForeverSubclassDebugWindow",UIParent,template);window:SetSize(820,520);window:SetPoint("CENTER");window:SetFrameStrata("DIALOG");window:SetFrameLevel(500);window:EnableMouse(true);window:SetMovable(true);window:RegisterForDrag("LeftButton");window:SetScript("OnDragStart",window.StartMoving);window:SetScript("OnDragStop",window.StopMovingOrSizing)
 if window.SetBackdrop then window:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=true,tileSize=16,edgeSize=12,insets={left=3,right=3,top=3,bottom=3}});window:SetBackdropColor(0.02,0.02,0.02,0.98) end
 local close=CreateFrame("Button",nil,window,"UIPanelCloseButton");close:SetPoint("TOPRIGHT",-4,-4);close:SetScript("OnClick",function() window:Hide() end)
 local scroll=CreateFrame("ScrollFrame",nil,window,"UIPanelScrollFrameTemplate");scroll:SetPoint("TOPLEFT",14,-42);scroll:SetPoint("BOTTOMRIGHT",-32,14)
 editBox=CreateFrame("EditBox",nil,scroll);editBox:SetMultiLine(true);editBox:SetAutoFocus(false);editBox:SetFontObject(ChatFontNormal);editBox:SetWidth(760);editBox:EnableMouse(true);editBox:SetScript("OnEscapePressed",function() window:Hide() end);scroll:SetScrollChild(editBox);window:Hide()
end

SLASH_FOREVERSUBCLASSDEBUG1="/fsubdebug"
SlashCmdList["FOREVERSUBCLASSDEBUG"]=function(msg)
 msg=(msg or ""):lower():match("^%s*(.-)%s*$")
 if msg=="clear" then wipe(lines);add("log cleared");return end
 if msg=="verbose" then verbose=not verbose;add("verbose protocol logging="..tostring(verbose));return end
 refreshHeader();add("snapshot saved; /reload or logout before collecting from WTF")
 if msg=="show" then createWindow();editBox:SetText(table.concat(lines,"\n"));editBox:SetHeight(math.max(480,#lines*14));window:Show() end
end

local events=CreateFrame("Frame");events:RegisterEvent("PLAYER_LOGIN");events:RegisterEvent("ADDON_LOADED");events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent",function(_,event,...)
 if event=="CHAT_MSG_ADDON" then
  local prefix,text,channel,sender=...
  if prefix=="FSR1" then
   local kind=tostring(text):match("^(%S+)")
   if verbose or kind=="STATE" or kind=="POWER" or kind=="ERROR" then add(string.format("RX %s channel=%s sender=%s %s",tostring(prefix),tostring(channel),tostring(sender),tostring(text))) end
  end
  return
 end
 if event=="PLAYER_LOGIN" then add("PLAYER_LOGIN");installErrorCapture();refreshHeader() end
end)
events:SetScript("OnUpdate",function(self,elapsed)
 self._elapsed=(self._elapsed or 0)+elapsed;if self._elapsed<0.50 then return end;self._elapsed=0
 installErrorCapture();wrapTransport()
 local root=_G.ForeverSubclassTalentPanel;if root and root:IsShown() then hookButtons(root);local desc=describe(currentMouseFocus());if desc~=lastFocusDesc then lastFocusDesc=desc;if verbose then add("MOUSEFOCUS "..desc) end end end
end)
