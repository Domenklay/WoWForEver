-- Hunter subclass pet controls. The actual pet is a normal server Pet saved by TrinityCore.

local RESPONSE="FSR1"
local pending,state
local panel,status,tame,call,dismiss
local function send(payload) if _G.ForeverSubclassDirectSend then return _G.ForeverSubclassDirectSend(payload,true) end return false end
local function style(frame)
 if frame.SetBackdrop then
  frame:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=true,tileSize=16,edgeSize=9,insets={left=3,right=3,top=3,bottom=3}})
  frame:SetBackdropColor(0.02,0.02,0.02,0.96);frame:SetBackdropBorderColor(0.43,0.32,0.14,0.95)
 end
end
local function button(parent,text,width)
 local template=BackdropTemplateMixin and "BackdropTemplate" or nil
 local b=CreateFrame("Button",nil,parent,template);b:SetSize(width or 110,27);style(b)
 b.text=b:CreateFontString(nil,"OVERLAY","GameFontNormalSmall");b.text:SetPoint("CENTER");b.text:SetText(text)
 b:SetScript("OnEnter",function(self) if self.SetBackdropBorderColor then self:SetBackdropBorderColor(1,0.78,0.2,1) end end)
 b:SetScript("OnLeave",function(self) if self.SetBackdropBorderColor then self:SetBackdropBorderColor(0.43,0.32,0.14,0.95) end end)
 return b
end
local function build()
 local root=_G.ForeverSubclassTalentPanel
 if not root then return false end
 if panel and panel:GetParent()==root then return true end
 local template=BackdropTemplateMixin and "BackdropTemplate" or nil
 panel=CreateFrame("Frame","ForeverSubclassHunterPetPanel",root,template);panel:SetSize(405,70);panel:SetPoint("BOTTOMRIGHT",root,"BOTTOMRIGHT",-26,52);style(panel)
 local title=panel:CreateFontString(nil,"OVERLAY","GameFontNormal");title:SetPoint("TOPLEFT",10,-9);title:SetText("Питомец Охотника")
 status=panel:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall");status:SetPoint("LEFT",title,"RIGHT",10,0)
 tame=button(panel,"Приручить",105);tame:SetPoint("BOTTOMLEFT",10,8);tame:SetScript("OnClick",function() send("tame") end)
 call=button(panel,"Призвать",105);call:SetPoint("LEFT",tame,"RIGHT",8,0);call:SetScript("OnClick",function() send("petcall") end)
 dismiss=button(panel,"Убрать",105);dismiss:SetPoint("LEFT",call,"RIGHT",8,0);dismiss:SetScript("OnClick",function() send("petdismiss") end)
 panel:Hide();return true
end
local function enable(b,value) b:EnableMouse(value);b:SetAlpha(value and 1 or 0.42) end
local function refresh()
 if not build() or not state then return end
 local show=state.active==3
 panel:SetShown(show);if not show then return end
 if not state.unlocked then
  status:SetText("|cff888888Откроется на 10 уровне подкласса|r");enable(tame,false);enable(call,false);enable(dismiss,false);return
 end
 if state.petActive then
  status:SetText("|cff55dd77Питомец активен|r");enable(tame,false);enable(call,false);enable(dismiss,true)
 else
  status:SetText("|cffffcc44Выберите зверя или призовите сохранённого|r");enable(tame,true);enable(call,true);enable(dismiss,false)
 end
end
local function parse(msg)
 local w={};for token in tostring(msg):gmatch("%S+") do table.insert(w,token) end
 if w[1]=="STATE" then pending={active=tonumber(w[3]) or 0,unlocked=false,petActive=false}
 elseif w[1]=="FEATURE" and pending and w[2]=="HUNTER_PET" then pending.unlocked=w[4]=="1";pending.petActive=w[5]=="1"
 elseif w[1]=="END" and pending then state=pending;pending=nil;refresh() end
end
local events=CreateFrame("Frame");events:RegisterEvent("PLAYER_LOGIN");events:RegisterEvent("ADDON_LOADED");events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent",function(_,event,...)
 if event=="CHAT_MSG_ADDON" then local prefix,msg=...;if prefix==RESPONSE then parse(msg) end;return end
 if C_Timer and C_Timer.After then C_Timer.After(0.3,build);C_Timer.After(1.0,build) else build() end
end)
