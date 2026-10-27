-- Single-owner talent UI for ForeverSubclass on WoW Forever 1.60.x.
-- Replaces the previous layered TalentTab/Compat/PanelV2 stack.
-- Server remains authoritative; this file only renders FSR1 and sends FSC1 requests.

local RESPONSE="FSR1"
local classOrder={1,2,3,4,5,7,8,9,11}
local classInfo={
 [1]={name="Воин",token="WARRIOR"},[2]={name="Паладин",token="PALADIN"},
 [3]={name="Охотник",token="HUNTER"},[4]={name="Разбойник",token="ROGUE"},
 [5]={name="Жрец",token="PRIEST"},[7]={name="Шаман",token="SHAMAN"},
 [8]={name="Маг",token="MAGE"},[9]={name="Чернокнижник",token="WARLOCK"},
 [11]={name="Друид",token="DRUID"},
}
local powerNames={[0]="Мана",[1]="Ярость",[3]="Энергия"}
local errors={
 ["module disabled or unsupported primary class"]="Модуль подклассов выключен или основной класс не поддерживается.",
 ["primary class has not reached subclass unlock level"]="Подкласс открывается с 10-го уровня.",
 ["subclass can only be switched in a rest area"]="Менять подкласс можно только в городе или таверне.",
 ["cannot edit in combat or while casting"]="Нельзя менять подкласс в бою, после смерти или во время заклинания.",
 ["class has not been learned"]="Сначала изучите этот класс.",
 ["spell unavailable or not enough power"]="Способность недоступна или не хватает ресурса.",
 ["subclass level is too low for this spell"]="Уровень подкласса недостаточен.",
 ["not enough subclass ability slots"]="Все 8 слотов способностей уже заняты.",
 ["no active subclass"]="Сначала активируйте подкласс.",
 ["selection unchanged"]="Изменений нет.",
}

local host,tab,panel,left,right,header
local cards,spellNodes={},{}
local titleText,detailText,statusText,xpText,noticeText,resourceBar,spellGrid,emptySpells
local learnButton,activeButton,xpButton,clearButton
local state,pending,selectedClass
local built=false
local customActive=false
local nativeHooks=setmetatable({}, {__mode="k"})

local function debug(text)
 if _G.ForeverSubclassDebugAdd then _G.ForeverSubclassDebugAdd("TALENTS "..tostring(text)) end
end

local function send(payload)
 if _G.ForeverSubclassDirectSend then return _G.ForeverSubclassDirectSend(payload,true) end
 return false
end

local function className(id)
 return classInfo[id] and classInfo[id].name or ("Класс "..tostring(id or 0))
end
local function spellName(id)
 if C_Spell and C_Spell.GetSpellName then return C_Spell.GetSpellName(id) or ("Заклинание "..id) end
 if GetSpellInfo then return GetSpellInfo(id) or ("Заклинание "..id) end
 return "Заклинание "..id
end
local function spellTexture(id)
 if C_Spell and C_Spell.GetSpellTexture then return C_Spell.GetSpellTexture(id) or 134400 end
 if GetSpellTexture then return GetSpellTexture(id) or 134400 end
 return 134400
end
local function label(parent,font,text)
 local f=parent:CreateFontString(nil,"OVERLAY",font or "GameFontHighlight")
 f:SetText(text or "")
 return f
end
local function makeBackdrop(parent,alpha)
 local template=BackdropTemplateMixin and "BackdropTemplate" or nil
 local f=CreateFrame("Frame",nil,parent,template)
 if f.SetBackdrop then
  f:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=true,tileSize=16,edgeSize=10,insets={left=3,right=3,top=3,bottom=3}})
  f:SetBackdropColor(0.015,0.015,0.015,alpha or 0.96)
  f:SetBackdropBorderColor(0.44,0.32,0.13,0.95)
 end
 f:EnableMouse(false)
 return f
end
local function setClassIcon(texture,token)
 texture:SetTexture("Interface\\GLUES\\CHARACTERCREATE\\UI-CHARACTERCREATE-CLASSES")
 local c=CLASS_ICON_TCOORDS and CLASS_ICON_TCOORDS[token]
 if c then texture:SetTexCoord(c[1],c[2],c[3],c[4]) else texture:SetTexture(134400);texture:SetTexCoord(0,1,0,1) end
end
local function makeButton(parent,text,width,callback)
 local b=CreateFrame("Button",nil,parent,"UIPanelButtonTemplate")
 b:SetSize(width or 128,28);b:SetText(text);b:RegisterForClicks("LeftButtonUp")
 b:SetScript("OnClick",callback)
 return b
end

local function isNativeTalentButton(button)
 if not button or button==tab or not button.GetText then return false end
 local ok,text=pcall(button.GetText,button)
 if not ok or not text then return false end
 text=tostring(text)
 -- Forever appends atlas/color markup to the labels, so exact equality is wrong.
 return text:find("Основное",1,true) or text:find("Дополнительное",1,true)
     or text:find("Primary",1,true) or text:find("Secondary",1,true)
end

local function hideCustom()
 customActive=false
 if panel then panel:Hide() end
 if tab then tab:SetEnabled(true) end
 debug("native talent view")
end
_G.ForeverSubclassHideTalentPanel=hideCustom

local function hookNativeTabs(root,depth)
 if not root or depth>7 or not root.GetChildren then return end
 for _,child in ipairs({root:GetChildren()}) do
  if isNativeTalentButton(child) and not nativeHooks[child] and child.HookScript then
   nativeHooks[child]=true
   child:HookScript("OnMouseDown",hideCustom)
   child:HookScript("OnClick",hideCustom)
  end
  hookNativeTabs(child,depth+1)
 end
end

local function positionTab()
 if not host or not tab then return end
 local candidates={}
 local function collect(root,depth)
  if not root or depth>7 or not root.GetChildren then return end
  for _,child in ipairs({root:GetChildren()}) do
   if isNativeTalentButton(child) then table.insert(candidates,child) end
   collect(child,depth+1)
  end
 end
 collect(host,0)
 if _G.PlayerSpellsFrame then collect(_G.PlayerSpellsFrame,0) end
 local anchor,bestLeft
 for _,b in ipairs(candidates) do
  local left=b.GetLeft and b:GetLeft()
  if not anchor or (left and (not bestLeft or left>bestLeft)) then anchor,bestLeft=b,left end
 end
 tab:ClearAllPoints()
 if anchor then tab:SetPoint("LEFT",anchor,"RIGHT",7,0) else tab:SetPoint("TOPLEFT",host,"TOPLEFT",365,-8) end
 tab:SetFrameStrata(host:GetFrameStrata())
 tab:SetFrameLevel((anchor and anchor.GetFrameLevel and anchor:GetFrameLevel() or host:GetFrameLevel())+1)
 tab:Show()
end

local function showCustom()
 if not panel then return end
 customActive=true
 panel:Show()
 panel:Raise()
 tab:SetEnabled(false)
 send("status")
 if panel.Refresh then panel:Refresh() end
 debug("subclass talent view")
end
_G.ForeverSubclassShowTalentPanel=showCustom

local function createCard(id,index)
 local info=classInfo[id]
 local template=BackdropTemplateMixin and "BackdropTemplate" or nil
 local b=CreateFrame("Button",nil,left,template)
 b:SetSize(139,84)
 local col=(index-1)%3;local row=math.floor((index-1)/3)
 b:SetPoint("TOPLEFT",12+col*144,-66-row*89)
 if b.SetBackdrop then
  b:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=true,tileSize=16,edgeSize=9,insets={left=3,right=3,top=3,bottom=3}})
  b:SetBackdropColor(0.03,0.03,0.03,0.96);b:SetBackdropBorderColor(0.28,0.24,0.16,0.95)
 end
 local border=b:CreateTexture(nil,"BORDER");border:SetTexture("Interface\\Buttons\\UI-Quickslot2");border:SetSize(48,48);border:SetPoint("LEFT",7,7)
 local icon=b:CreateTexture(nil,"ARTWORK");icon:SetSize(39,39);icon:SetPoint("CENTER",border);setClassIcon(icon,info.token)
 local name=label(b,"GameFontNormal",info.name);name:SetPoint("TOPLEFT",58,-10);name:SetPoint("RIGHT",-5,0);name:SetJustifyH("LEFT")
 local role=label(b,"GameFontHighlightSmall","Не изучен");role:SetPoint("TOPLEFT",58,-30);role:SetPoint("RIGHT",-5,0);role:SetJustifyH("LEFT")
 local level=label(b,"GameFontHighlightSmall","");level:SetPoint("TOPLEFT",58,-47);level:SetPoint("RIGHT",-5,0);level:SetJustifyH("LEFT")
 local xp=label(b,"GameFontNormalSmall","");xp:SetPoint("BOTTOMLEFT",8,7);xp:SetPoint("RIGHT",-5,0);xp:SetJustifyH("LEFT");xp:SetTextColor(1,0.72,0.18,1)
 b:RegisterForClicks("LeftButtonUp")
 b:SetScript("OnClick",function() selectedClass=id;if panel and panel.Refresh then panel:Refresh() end end)
 b:SetScript("OnEnter",function(self) if self.SetBackdropBorderColor then self:SetBackdropBorderColor(0.95,0.72,0.20,1) end end)
 b:SetScript("OnLeave",function(self)
  if not self.SetBackdropBorderColor then return end
  if self._selected then self:SetBackdropBorderColor(0.95,0.72,0.20,1)
  elseif self._active then self:SetBackdropBorderColor(0.20,0.76,0.36,1)
  elseif self._primary then self:SetBackdropBorderColor(0.40,0.55,0.78,1)
  else self:SetBackdropBorderColor(0.28,0.24,0.16,0.95) end
 end)
 cards[id]={frame=b,role=role,level=level,xp=xp}
end

local function clearSpellNodes()
 for _,node in ipairs(spellNodes) do node:Hide() end
end
local function visibleSpells(s)
 local out,best={},{}
 if not s or not s.active or s.active==0 or not s.classes[s.active] then return out end
 local level=s.classes[s.active].level or 1
 for _,sp in pairs(s.spells or {}) do
  if sp.level<=level and (not best[sp.root] or best[sp.root].level<sp.level) then best[sp.root]=sp end
 end
 for _,sp in pairs(s.spells or {}) do
  if (best[sp.root] and best[sp.root].id==sp.id) or sp.selected then table.insert(out,sp) end
 end
 table.sort(out,function(a,b) if a.level==b.level then return a.id<b.id end return a.level<b.level end)
 return out
end
local function makeSpellNode(index)
 local template=BackdropTemplateMixin and "BackdropTemplate" or nil
 local n=CreateFrame("Button",nil,spellGrid,template)
 n:SetSize(158,116)
 local col=(index-1)%4;local row=math.floor((index-1)/4)
 n:SetPoint("TOPLEFT",8+col*164,-8-row*121)
 if n.SetBackdrop then
  n:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=true,tileSize=16,edgeSize=9,insets={left=3,right=3,top=3,bottom=3}})
 end
 local border=n:CreateTexture(nil,"BORDER");border:SetTexture("Interface\\Buttons\\UI-Quickslot2");border:SetSize(51,51);border:SetPoint("TOP",0,-8)
 n.icon=n:CreateTexture(nil,"ARTWORK");n.icon:SetSize(42,42);n.icon:SetPoint("CENTER",border)
 n.name=label(n,"GameFontNormalSmall","");n.name:SetPoint("TOPLEFT",5,-62);n.name:SetPoint("RIGHT",-5,0);n.name:SetJustifyH("CENTER");n.name:SetWordWrap(false)
 n.meta=label(n,"GameFontHighlightSmall","");n.meta:SetPoint("TOPLEFT",5,-80);n.meta:SetPoint("RIGHT",-5,0);n.meta:SetJustifyH("CENTER")
 n.state=label(n,"GameFontHighlightSmall","");n.state:SetPoint("BOTTOM",0,8)
 n:RegisterForClicks("LeftButtonUp")
 n:SetScript("OnClick",function(self) if self.spell then send((self.spell.selected and "remove " or "select ")..self.spell.id) end end)
 n:SetScript("OnEnter",function(self)
  if self.spell and GameTooltip then
   GameTooltip:SetOwner(self,"ANCHOR_RIGHT");GameTooltip:SetSpellByID(self.spell.id);GameTooltip:AddLine(" ")
   GameTooltip:AddLine(self.spell.selected and "Нажмите, чтобы убрать из подкласса" or "Нажмите, чтобы выбрать способность",1,0.82,0.2,true);GameTooltip:Show()
  end
 end)
 n:SetScript("OnLeave",function() if GameTooltip then GameTooltip:Hide() end end)
 spellNodes[index]=n;return n
end

local function refresh()
 if not panel or not panel:IsShown() then return end
 if not state then
  titleText:SetText("Подкласс");detailText:SetText("Получаем состояние персонажа...");statusText:SetText("Соединение с сервером...")
  clearSpellNodes();emptySpells:SetText("Ожидание данных от сервера...");emptySpells:Show();return
 end
 if not selectedClass or selectedClass==state.primary then selectedClass=(state.active and state.active~=0 and state.active) or (state.primary~=5 and 5 or 8) end
 local primary=className(state.primary)
 local active=(state.active and state.active~=0) and className(state.active) or "не выбран"
 local primaryLevel=state.classes[state.primary] and state.classes[state.primary].level or (UnitLevel and UnitLevel("player") or 0)
 local activeLevel=(state.active and state.classes[state.active]) and state.classes[state.active].level or 0
 titleText:SetText(primary.." / "..active)
 detailText:SetText(string.format("Основной: ур. %d   |   Подкласс: %s   |   Эффективность: %.1f%%   |   Выбрано: %d из %d",
  primaryLevel,activeLevel>0 and ("ур. "..activeLevel) or "нет",(state.efficiency or 0)/100,state.used or 0,state.budget or 8))
 statusText:SetText("Сервер подключен")
 local target=state.classes[state.xpTarget]
 if target then xpText:SetText("Опыт получает: "..className(state.xpTarget).."   |   Уровень "..target.level.."   |   "..target.xp.." / "..target.next) else xpText:SetText("") end

 for _,id in ipairs(classOrder) do
  local card=cards[id];local progress=state.classes[id]
  local primaryFlag=id==state.primary;local activeFlag=id==state.active;local xpFlag=id==state.xpTarget;local selected=id==selectedClass
  if primaryFlag then card.role:SetText("Основной класс")
  elseif activeFlag then card.role:SetText("Активный подкласс")
  elseif progress then card.role:SetText("Изучен")
  else card.role:SetText("Не изучен") end
  card.level:SetText(progress and ("Уровень "..progress.level) or "")
  card.xp:SetText(xpFlag and not primaryFlag and "Получает опыт" or "")
  card.frame._selected=selected;card.frame._active=activeFlag;card.frame._primary=primaryFlag
  if card.frame.SetBackdropBorderColor then
   if selected then card.frame:SetBackdropBorderColor(0.95,0.72,0.20,1)
   elseif activeFlag then card.frame:SetBackdropBorderColor(0.20,0.76,0.36,1)
   elseif primaryFlag then card.frame:SetBackdropBorderColor(0.40,0.55,0.78,1)
   else card.frame:SetBackdropBorderColor(0.28,0.24,0.16,0.95) end
  end
 end

 local learned=state.classes[selectedClass]~=nil
 local primarySelected=selectedClass==state.primary
 local playerLevel=UnitLevel and UnitLevel("player") or 80
 learnButton:SetEnabled(playerLevel>=10 and not primarySelected and not learned)
 activeButton:SetEnabled(not primarySelected and learned and selectedClass~=state.active)
 xpButton:SetEnabled(learned and selectedClass~=state.xpTarget)
 clearButton:SetEnabled(state.active and state.active~=0)

 clearSpellNodes()
 local list=visibleSpells(state)
 if #list==0 then
  emptySpells:SetText((state.active and state.active~=0) and "На этом уровне пока нет доступных способностей." or "Сначала изучите и активируйте второй класс.");emptySpells:Show()
 else
  emptySpells:Hide()
  for i,sp in ipairs(list) do
   local n=spellNodes[i] or makeSpellNode(i);n.spell=sp;n.icon:SetTexture(spellTexture(sp.id));n.name:SetText(spellName(sp.id))
   n.meta:SetText("Уровень "..sp.level.." | "..(powerNames[sp.power] or "Ресурс").." "..sp.cost)
   n.state:SetText(sp.selected and "Выбрано" or "Нажмите, чтобы выбрать")
   if n.SetBackdrop then
    if sp.selected then n:SetBackdropColor(0.03,0.09,0.04,0.96);n:SetBackdropBorderColor(0.20,0.82,0.36,1)
    else n:SetBackdropColor(0.028,0.028,0.028,0.96);n:SetBackdropBorderColor(0.34,0.28,0.17,0.95) end
   end
   n:Show()
  end
 end
 if state.power and state.active and state.active~=0 then
  local p=state.power;resourceBar:SetMinMaxValues(0,math.max(1,p.max));resourceBar:SetValue(p.current)
  if p.kind==1 then resourceBar:SetStatusBarColor(0.75,0.12,0.12) elseif p.kind==3 then resourceBar:SetStatusBarColor(0.85,0.72,0.10) else resourceBar:SetStatusBarColor(0.10,0.35,0.90) end
  resourceBar.text:SetText((powerNames[p.kind] or "Ресурс").."  "..p.current.." / "..p.max);resourceBar:Show()
 else resourceBar:Hide() end
 noticeText:SetText("Выберите класс слева. Зеленая рамка справа означает выбранную способность.")
end

local function build()
 host=_G.PlayerSpellsFrame and _G.PlayerSpellsFrame.TalentsFrame
 if not host or built then return built end
 built=true
 tab=CreateFrame("Button","ForeverSubclassTalentTab",host,"UIPanelButtonTemplate")
 tab:SetSize(76,26);tab:SetText("Подкласс");tab:RegisterForClicks("LeftButtonUp");tab:SetScript("OnClick",showCustom)

 local template=BackdropTemplateMixin and "BackdropTemplate" or nil
 panel=CreateFrame("Frame","ForeverSubclassTalentPanel",host,template)
 panel:SetPoint("TOPLEFT",host,"TOPLEFT",0,-44);panel:SetPoint("BOTTOMRIGHT",host,"BOTTOMRIGHT",0,0)
 panel:SetFrameStrata(host:GetFrameStrata());panel:SetFrameLevel(host:GetFrameLevel()+2);panel:EnableMouse(false)
 if panel.SetBackdrop then panel:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=true,tileSize=16,edgeSize=10,insets={left=3,right=3,top=3,bottom=3}});panel:SetBackdropColor(0.01,0.01,0.01,0.985);panel:SetBackdropBorderColor(0.44,0.32,0.13,1) end
 _G.ForeverSubclassPanelV2=panel
 panel.Refresh=refresh

 header=makeBackdrop(panel,0.93);header:SetPoint("TOPLEFT",10,-10);header:SetPoint("TOPRIGHT",-10,-10);header:SetHeight(72)
 titleText=label(header,"GameFontNormalLarge","Подкласс");titleText:SetPoint("TOPLEFT",14,-11)
 detailText=label(header,"GameFontHighlightSmall","");detailText:SetPoint("TOPLEFT",14,-35);detailText:SetWidth(800);detailText:SetJustifyH("LEFT")
 statusText=label(header,"GameFontHighlightSmall","Соединение с сервером...");statusText:SetPoint("TOPRIGHT",-14,-13);statusText:SetTextColor(0.35,0.9,0.45,1)
 xpText=label(header,"GameFontHighlightSmall","");xpText:SetPoint("BOTTOMRIGHT",-14,10)

 left=makeBackdrop(panel,0.94);left:SetPoint("TOPLEFT",10,-91);left:SetPoint("BOTTOMLEFT",10,45);left:SetWidth(452)
 local lt=label(left,"GameFontNormalLarge","Второй путь");lt:SetPoint("TOPLEFT",12,-12)
 local lh=label(left,"GameFontHighlightSmall","Класс развивается отдельно. Основной класс и броня сохраняются.");lh:SetPoint("TOPLEFT",lt,"BOTTOMLEFT",0,-4);lh:SetWidth(420);lh:SetJustifyH("LEFT")
 for i,id in ipairs(classOrder) do createCard(id,i) end
 learnButton=makeButton(left,"Изучить",125,function() if selectedClass then send("learn "..selectedClass) end end);learnButton:SetPoint("BOTTOMLEFT",12,13)
 activeButton=makeButton(left,"Активировать",125,function() if selectedClass then send("active "..selectedClass) end end);activeButton:SetPoint("LEFT",learnButton,"RIGHT",8,0)
 xpButton=makeButton(left,"Направить опыт",132,function() if selectedClass then send("xp "..selectedClass) end end);xpButton:SetPoint("LEFT",activeButton,"RIGHT",8,0)
 clearButton=CreateFrame("Button",nil,left,"UIPanelButtonTemplate");clearButton:SetSize(150,22);clearButton:SetPoint("BOTTOMLEFT",12,48);clearButton:SetText("Отключить подкласс");clearButton:RegisterForClicks("LeftButtonUp");clearButton:SetScript("OnClick",function() send("clear") end)

 right=makeBackdrop(panel,0.94);right:SetPoint("TOPLEFT",472,-91);right:SetPoint("BOTTOMRIGHT",-10,45)
 local rt=label(right,"GameFontNormalLarge","Способности подкласса");rt:SetPoint("TOPLEFT",14,-12)
 local rh=label(right,"GameFontHighlightSmall","До 8 способностей. Наведите мышь на способность, чтобы увидеть обычное описание.");rh:SetPoint("TOPLEFT",rt,"BOTTOMLEFT",0,-4);rh:SetWidth(620);rh:SetJustifyH("LEFT")
 resourceBar=CreateFrame("StatusBar",nil,right);resourceBar:SetPoint("TOPRIGHT",-14,-13);resourceBar:SetSize(205,18);resourceBar:SetStatusBarTexture("Interface\\TARGETINGFRAME\\UI-StatusBar");resourceBar.text=label(resourceBar,"GameFontHighlightSmall","");resourceBar.text:SetPoint("CENTER");resourceBar:Hide()
 spellGrid=CreateFrame("Frame",nil,right);spellGrid:SetPoint("TOPLEFT",10,-57);spellGrid:SetPoint("BOTTOMRIGHT",-10,10);spellGrid:EnableMouse(false)
 emptySpells=label(spellGrid,"GameFontHighlight","Сначала активируйте подкласс.");emptySpells:SetPoint("CENTER",0,25);emptySpells:SetWidth(520);emptySpells:SetJustifyH("CENTER")
 noticeText=label(panel,"GameFontHighlightSmall","");noticeText:SetPoint("BOTTOMLEFT",16,16);noticeText:SetPoint("RIGHT",-16,0);noticeText:SetJustifyH("LEFT")
 panel:Hide()

 hookNativeTabs(host,0);if _G.PlayerSpellsFrame then hookNativeTabs(_G.PlayerSpellsFrame,0) end
 positionTab()
 if host.HookScript then host:HookScript("OnShow",function() hookNativeTabs(host,0);positionTab();if not customActive then panel:Hide() end end);host:HookScript("OnHide",hideCustom) end
 if _G.PlayerSpellsFrame and _G.PlayerSpellsFrame.HookScript then _G.PlayerSpellsFrame:HookScript("OnHide",hideCustom) end
 return true
end

local function parse(text)
 local words={};for w in tostring(text):gmatch("%S+") do table.insert(words,w) end
 local kind=words[1]
 if kind=="ERROR" then
  local raw=tostring(text):sub(7);noticeText:SetText(errors[raw] or raw);if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cffff5555[Подклассы]|r "..(errors[raw] or raw)) end;return
 elseif kind=="STATE" then
  pending={primary=tonumber(words[2]),active=tonumber(words[3]),xpTarget=tonumber(words[4]),used=tonumber(words[5]) or 0,budget=tonumber(words[6]) or 8,efficiency=tonumber(words[7]) or 0,classes={},spells={}}
 elseif pending and kind=="CLASS" then pending.classes[tonumber(words[2])]={level=tonumber(words[3]) or 1,xp=tonumber(words[4]) or 0,next=tonumber(words[5]) or 0}
 elseif pending and kind=="POWER" then pending.power={kind=tonumber(words[2]),current=tonumber(words[3]) or 0,max=tonumber(words[4]) or 1}
 elseif pending and kind=="SPELL" then local id=tonumber(words[2]);pending.spells[id]={id=id,root=tonumber(words[3]),level=tonumber(words[4]) or 1,selected=words[5]=="1",cost=tonumber(words[6]) or 0,power=tonumber(words[7])}
 elseif pending and kind=="END" then state=pending;pending=nil;if panel and panel:IsShown() then refresh() end end
end

local events=CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN");events:RegisterEvent("ADDON_LOADED");events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent",function(_,event,...)
 if event=="CHAT_MSG_ADDON" then local prefix,text=...;if prefix==RESPONSE then parse(text) end;return end
 if C_Timer and C_Timer.After then C_Timer.After(0,build);C_Timer.After(0.3,build);C_Timer.After(1,build) else build() end
end)
events:SetScript("OnUpdate",function(self,elapsed)
 self.elapsed=(self.elapsed or 0)+elapsed;if self.elapsed<0.5 then return end;self.elapsed=0
 if not built then build();return end
 hookNativeTabs(host,0);if _G.PlayerSpellsFrame then hookNativeTabs(_G.PlayerSpellsFrame,0) end
 positionTab()
 if not customActive and panel and panel:IsShown() then panel:Hide() end
end)
