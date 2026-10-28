-- Server-authoritative subclass talent tree overlay.
-- Points/ranks come exclusively from FSR1 TPOINTS/TALENT records.

local RESPONSE="FSR1"
local defs={
 [1001]={name="Мастерство",desc="+2% эффективности подкласса за ранг.",tier=0,max=5,icon=135932},
 [1002]={name="Запас сил",desc="+5% максимума дополнительных ресурсов за ранг.",tier=0,max=5,icon=136097},
 [2001]={name="Экономия",desc="-3% стоимости способностей подкласса за ранг.",tier=1,max=5,icon=136075},
 [2002]={name="Восстановление",desc="+10% восстановления маны и энергии за ранг.",tier=1,max=5,icon=136052},
 [3001]={name="Совершенство",desc="+3% эффективности подкласса за ранг.",tier=2,max=5,icon=136101},
 [3002]={name="Боевой ритм",desc="+5% восстановления ресурсов и генерации ярости за ранг.",tier=2,max=5,icon=132333},
}
local order={1001,1002,2001,2002,3001,3002}
local pending,state
local toggle,panel,pointsText,resetButton
local nodes={}

local function send(payload)
 if _G.ForeverSubclassDirectSend then return _G.ForeverSubclassDirectSend(payload,true) end
 return false
end
local function backdrop(frame)
 if frame.SetBackdrop then
  frame:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=true,tileSize=16,edgeSize=10,insets={left=3,right=3,top=3,bottom=3}})
  frame:SetBackdropColor(0.018,0.018,0.018,0.985);frame:SetBackdropBorderColor(0.34,0.40,0.48,1)
 end
end
local function makeButton(parent,text,width)
 local template=BackdropTemplateMixin and "BackdropTemplate" or nil
 local b=CreateFrame("Button",nil,parent,template);b:SetSize(width or 130,28);backdrop(b)
 b.text=b:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall");b.text:SetPoint("CENTER");b.text:SetText(text);b.text:SetTextColor(0.92,0.92,0.92,1)
 b:SetScript("OnEnter",function(self) if self.SetBackdropBorderColor then self:SetBackdropBorderColor(0.55,0.72,0.92,1) end end)
 b:SetScript("OnLeave",function(self) if self.SetBackdropBorderColor then self:SetBackdropBorderColor(0.34,0.40,0.48,1) end end)
 return b
end
local function build()
 local root=_G.ForeverSubclassTalentPanel
 if not root then return false end
 if panel and panel:GetParent()==root then return true end
 local template=BackdropTemplateMixin and "BackdropTemplate" or nil
 toggle=makeButton(root,"Таланты подкласса",145);toggle:SetPoint("TOPRIGHT",root,"TOPRIGHT",-18,-54)
 panel=CreateFrame("Frame","ForeverSubclassTalentTreePanel",root,template)
 panel:SetPoint("TOPLEFT",root,"TOPLEFT",470,-78);panel:SetPoint("BOTTOMRIGHT",root,"BOTTOMRIGHT",-12,44);backdrop(panel);panel:EnableMouse(true)
 local title=panel:CreateFontString(nil,"OVERLAY","GameFontHighlightLarge");title:SetPoint("TOPLEFT",14,-12);title:SetText("Таланты подкласса");title:SetTextColor(0.95,0.95,0.95,1)
 pointsText=panel:CreateFontString(nil,"OVERLAY","GameFontHighlight");pointsText:SetPoint("TOPRIGHT",-14,-15)
 local note=panel:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall");note:SetPoint("TOPLEFT",title,"BOTTOMLEFT",0,-5);note:SetText("Первое очко на 10-м уровне подкласса, затем ещё одно каждые 2 уровня. Новый ряд требует 5 потраченных очков.")
 resetButton=makeButton(panel,"Сбросить",105);resetButton:SetPoint("BOTTOMRIGHT",-14,12);resetButton:SetScript("OnClick",function() send("talentreset") end)
 for index,id in ipairs(order) do
  local d=defs[id];local n=CreateFrame("Button",nil,panel,template);n:SetSize(265,104);backdrop(n)
  local col=(index-1)%2;local row=math.floor((index-1)/2);n:SetPoint("TOPLEFT",18+col*280,-72-row*116)
  n.icon=n:CreateTexture(nil,"ARTWORK");n.icon:SetSize(45,45);n.icon:SetPoint("TOPLEFT",10,-10);n.icon:SetTexture(d.icon)
  n.name=n:CreateFontString(nil,"OVERLAY","GameFontHighlight");n.name:SetPoint("TOPLEFT",65,-12);n.name:SetPoint("RIGHT",-45,0);n.name:SetJustifyH("LEFT");n.name:SetText(d.name);n.name:SetTextColor(0.94,0.94,0.94,1)
  n.rank=n:CreateFontString(nil,"OVERLAY","GameFontHighlight");n.rank:SetPoint("TOPRIGHT",-10,-13)
  n.desc=n:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall");n.desc:SetPoint("TOPLEFT",65,-36);n.desc:SetPoint("BOTTOMRIGHT",-8,8);n.desc:SetJustifyH("LEFT");n.desc:SetJustifyV("TOP");n.desc:SetWordWrap(true);n.desc:SetText(d.desc)
  n:SetScript("OnClick",function() send("talent "..id) end)
  n:SetScript("OnEnter",function(self)
   if self.SetBackdropBorderColor then self:SetBackdropBorderColor(0.55,0.72,0.92,1) end
   GameTooltip:SetOwner(self,"ANCHOR_RIGHT");GameTooltip:SetText(d.name,0.95,0.95,0.95);GameTooltip:AddLine(d.desc,1,1,1,true)
   GameTooltip:AddLine("Ряд "..(d.tier+1)..". Максимум: "..d.max..".",0.7,0.7,0.7,true);GameTooltip:Show()
  end)
  n:SetScript("OnLeave",function(self) GameTooltip:Hide();if self.SetBackdropBorderColor then self:SetBackdropBorderColor(0.34,0.40,0.48,1) end end)
  nodes[id]=n
 end
 toggle:SetScript("OnClick",function()
  local show=not panel:IsShown();panel:SetShown(show);toggle.text:SetText(show and "Способности" or "Таланты подкласса")
 end)
 panel:Hide();return true
end
local function refresh()
 if not build() or not state then return end
 local active=state.active and state.active~=0
 toggle:SetShown(active)
 if not active then panel:Hide();return end
 pointsText:SetText(string.format("Свободно: %d   Потрачено: %d / %d",state.free or 0,state.spent or 0,state.total or 0))
 for _,id in ipairs(order) do
  local n=nodes[id];local t=state.talents[id] or {rank=0,max=defs[id].max,tier=defs[id].tier}
  n.rank:SetText(t.rank.." / "..t.max)
  local unlocked=(state.spent or 0)>=t.tier*5
  if n.SetBackdropColor then
   if t.rank>=t.max then n:SetBackdropColor(0.03,0.12,0.04,0.98)
   elseif unlocked and (state.free or 0)>0 then n:SetBackdropColor(0.035,0.055,0.08,0.98)
   else n:SetBackdropColor(0.025,0.025,0.025,0.98) end
  end
  n:EnableMouse(unlocked and (state.free or 0)>0 and t.rank<t.max)
  n:SetAlpha(unlocked and 1 or 0.48)
 end
 resetButton:EnableMouse((state.spent or 0)>0);resetButton:SetAlpha((state.spent or 0)>0 and 1 or 0.45)
end
local function parse(msg)
 local w={};for token in tostring(msg):gmatch("%S+") do table.insert(w,token) end
 if w[1]=="STATE" then pending={active=tonumber(w[3]) or 0,talents={}}
 elseif w[1]=="TPOINTS" and pending then pending.free=tonumber(w[2]) or 0;pending.spent=tonumber(w[3]) or 0;pending.total=tonumber(w[4]) or 0
 elseif w[1]=="TALENT" and pending then
  local id=tonumber(w[2]);if id then pending.talents[id]={rank=tonumber(w[3]) or 0,max=tonumber(w[4]) or 1,tier=tonumber(w[5]) or 0} end
 elseif w[1]=="END" and pending then state=pending;pending=nil;refresh() end
end
local events=CreateFrame("Frame");events:RegisterEvent("PLAYER_LOGIN");events:RegisterEvent("ADDON_LOADED");events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent",function(_,event,...)
 if event=="CHAT_MSG_ADDON" then local prefix,msg=...;if prefix==RESPONSE then parse(msg) end;return end
 if C_Timer and C_Timer.After then C_Timer.After(0.3,build);C_Timer.After(1.0,build) else build() end
end)
