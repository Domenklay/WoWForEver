-- Single-owner subclass page for WoW Forever 1.60.x.
-- One panel owns class selection, abilities and the subclass talent tree. The
-- server remains authoritative for progression, talents, resources and casts.

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
local talentDefs={
 [1001]={name="Мастерство",desc="+2% эффективности подкласса за ранг.",tier=0,max=5,icon=135932},
 [1002]={name="Запас сил",desc="+5% максимума дополнительных ресурсов за ранг.",tier=0,max=5,icon=136097},
 [2001]={name="Экономия",desc="-3% стоимости способностей подкласса за ранг.",tier=1,max=5,icon=136075},
 [2002]={name="Восстановление",desc="+10% восстановления маны и энергии за ранг.",tier=1,max=5,icon=136052},
 [3001]={name="Совершенство",desc="+3% эффективности подкласса за ранг.",tier=2,max=5,icon=136101},
 [3002]={name="Боевой ритм",desc="+5% восстановления ресурсов и генерации ярости за ранг.",tier=2,max=5,icon=132333},
}
local talentOrder={1001,1002,2001,2002,3001,3002}
local talentBranches={{1001,2001,3001},{1002,2002,3002}}
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
 ["no subclass talent points"]="Нет свободных очков талантов подкласса.",
 ["subclass talent tier locked"]="Сначала потратьте 5 очков в предыдущем ряду.",
 ["subclass talents can only be changed in a rest area"]="Таланты подкласса меняются только в городе или таверне.",
 ["Freepick purchases require level 10 and a rest area outside combat"]="Для покупки нужны 10-й уровень, город или таверна и выход из боя.",
 ["Freepick XP belongs to the primary class"]="В Freepick весь опыт получает основной класс.",
 ["command unavailable in Freepick ability prototype"]="Эта функция пока недоступна в пробном Freepick.",
 ["selection unchanged"]="Изменений нет.",
}

local owner,host,tab,panel,header,left,right
local cards,spellNodes,talentNodes={},{},{}
local titleText,detailText,statusText,xpText,noticeText
local learnButton,activeButton,xpButton,clearButton
local modeAbilities,modeTalents,viewTitle
local abilityContent,spellGrid,emptySpells,resourceBar
local talentContent,talentPoints,talentNote,resetTalents
local state,pending,selectedClass
local built=false
local customActive=false
local currentMode="abilities"
local nativeHooks=setmetatable({}, {__mode="k"})

local function debug(text) if _G.ForeverSubclassDebugAdd then _G.ForeverSubclassDebugAdd("TALENTS "..tostring(text)) end end
local function send(payload) if _G.ForeverSubclassDirectSend then return _G.ForeverSubclassDirectSend(payload,true) end return false end
local function className(id) return classInfo[id] and classInfo[id].name or ("Класс "..tostring(id or 0)) end
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
 local f=parent:CreateFontString(nil,"OVERLAY",font or "GameFontHighlight");f:SetText(text or "");return f
end
local function makeBackdrop(parent,alpha)
 local template=BackdropTemplateMixin and "BackdropTemplate" or nil
 local f=CreateFrame("Frame",nil,parent,template)
 if f.SetBackdrop then
  f:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=true,tileSize=16,edgeSize=10,insets={left=3,right=3,top=3,bottom=3}})
  f:SetBackdropColor(0.015,0.015,0.015,alpha or 0.96);f:SetBackdropBorderColor(0.30,0.34,0.40,0.95)
 end
 f:EnableMouse(false);return f
end
local function setClassIcon(texture,token)
 texture:SetTexture("Interface\\GLUES\\CHARACTERCREATE\\UI-CHARACTERCREATE-CLASSES")
 local c=CLASS_ICON_TCOORDS and CLASS_ICON_TCOORDS[token]
 if c then texture:SetTexCoord(c[1],c[2],c[3],c[4]) else texture:SetTexture(134400);texture:SetTexCoord(0,1,0,1) end
end
local function makeButton(parent,text,width,callback)
 local b=CreateFrame("Button",nil,parent,"UIPanelButtonTemplate")
 b:SetSize(width or 128,28);b:SetText(text);b:RegisterForClicks("LeftButtonUp");b:SetScript("OnClick",callback);return b
end
local function setButtonEnabled(button,enabled)
 if not button then return end
 button:SetEnabled(enabled and true or false);button:SetAlpha(enabled and 1 or 0.45)
end

local function isNativeTalentButton(button)
 if not button or button==tab or not button.GetText then return false end
 local ok,text=pcall(button.GetText,button);if not ok or not text then return false end;text=tostring(text)
 return text:find("Основное",1,true) or text:find("Дополнительное",1,true) or text:find("Primary",1,true) or text:find("Secondary",1,true)
end

local function hideCustom()
 customActive=false;if panel then panel:Hide() end;if tab then tab:SetEnabled(true) end
 if GameTooltip then GameTooltip:Hide() end
end
_G.ForeverSubclassHideTalentPanel=hideCustom

local function hookNativeTabs(root,depth)
 if not root or depth>7 or not root.GetChildren then return end
 for _,child in ipairs({root:GetChildren()}) do
  if isNativeTalentButton(child) and not nativeHooks[child] and child.HookScript then
   nativeHooks[child]=true;child:HookScript("OnMouseDown",hideCustom);child:HookScript("OnClick",hideCustom)
  end
  hookNativeTabs(child,depth+1)
 end
end

local function positionTab()
 if not host or not tab then return end
 local candidates={}
 local function collect(root,depth)
  if not root or depth>7 or not root.GetChildren then return end
  for _,child in ipairs({root:GetChildren()}) do if isNativeTalentButton(child) then table.insert(candidates,child) end;collect(child,depth+1) end
 end
 collect(host,0);if owner then collect(owner,0) end
 local anchor,bestLeft
 for _,b in ipairs(candidates) do local x=b.GetLeft and b:GetLeft();if not anchor or (x and (not bestLeft or x>bestLeft)) then anchor,bestLeft=b,x end end
 tab:ClearAllPoints();if anchor then tab:SetPoint("LEFT",anchor,"RIGHT",7,0) else tab:SetPoint("TOPLEFT",host,"TOPLEFT",365,-8) end
 tab:SetFrameStrata(host:GetFrameStrata());tab:SetFrameLevel((anchor and anchor.GetFrameLevel and anchor:GetFrameLevel() or host:GetFrameLevel())+1);tab:Show()
end

local function createCard(id,index)
 local info=classInfo[id];local template=BackdropTemplateMixin and "BackdropTemplate" or nil
 local b=CreateFrame("Button",nil,left,template);b:SetSize(139,84)
 local col=(index-1)%3;local row=math.floor((index-1)/3);b:SetPoint("TOPLEFT",12+col*144,-66-row*89)
 if b.SetBackdrop then
  b:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=true,tileSize=16,edgeSize=9,insets={left=3,right=3,top=3,bottom=3}})
  b:SetBackdropColor(0.03,0.03,0.03,0.96);b:SetBackdropBorderColor(0.25,0.28,0.33,0.95)
 end
 local border=b:CreateTexture(nil,"BORDER");border:SetTexture("Interface\\Buttons\\UI-Quickslot2");border:SetSize(48,48);border:SetPoint("LEFT",7,7)
 local icon=b:CreateTexture(nil,"ARTWORK");icon:SetSize(39,39);icon:SetPoint("CENTER",border);setClassIcon(icon,info.token)
 local name=label(b,"GameFontNormal",info.name);name:SetPoint("TOPLEFT",58,-10);name:SetPoint("RIGHT",-5,0);name:SetJustifyH("LEFT");name:SetWordWrap(false)
 local role=label(b,"GameFontHighlightSmall","Не изучен");role:SetPoint("TOPLEFT",58,-30);role:SetPoint("RIGHT",-5,0);role:SetJustifyH("LEFT")
 local level=label(b,"GameFontHighlightSmall","");level:SetPoint("TOPLEFT",58,-47);level:SetPoint("RIGHT",-5,0);level:SetJustifyH("LEFT")
 local xp=label(b,"GameFontHighlightSmall","");xp:SetPoint("BOTTOMLEFT",8,7);xp:SetPoint("RIGHT",-5,0);xp:SetJustifyH("LEFT");xp:SetTextColor(0.55,0.78,1,1)
 b:RegisterForClicks("LeftButtonUp")
 b:SetScript("OnClick",function() selectedClass=id;if panel and panel.Refresh then panel:Refresh() end end)
 b:SetScript("OnEnter",function(self) if self.SetBackdropBorderColor then self:SetBackdropBorderColor(0.45,0.72,0.95,1) end end)
 b:SetScript("OnLeave",function(self)
  if not self.SetBackdropBorderColor then return end
  if self._selected then self:SetBackdropBorderColor(0.45,0.72,0.95,1)
  elseif self._active then self:SetBackdropBorderColor(0.20,0.76,0.36,1)
  elseif self._primary then self:SetBackdropBorderColor(0.50,0.55,0.65,1)
  else self:SetBackdropBorderColor(0.25,0.28,0.33,0.95) end
 end)
 cards[id]={frame=b,role=role,level=level,xp=xp}
end

local function clearSpellNodes() for _,node in ipairs(spellNodes) do node:Hide() end end
local function visibleSpells(s)
 local out,best={},{};if not s then return out end
 if not s.freepick and (not s.active or s.active==0 or not s.classes[s.active]) then return out end
 local progress=s.classes[s.freepick and s.primary or s.active]
 local level=progress and progress.level or 1
 for _,sp in pairs(s.spells or {}) do if sp.level<=level and (not best[sp.root] or best[sp.root].level<sp.level) then best[sp.root]=sp end end
 for _,sp in pairs(s.spells or {}) do if (best[sp.root] and best[sp.root].id==sp.id) or sp.selected then table.insert(out,sp) end end
 table.sort(out,function(a,b) if a.level==b.level then return a.id<b.id end return a.level<b.level end);return out
end
local function makeSpellNode(index)
 local template=BackdropTemplateMixin and "BackdropTemplate" or nil
 local n=CreateFrame("Button",nil,spellGrid,template);n:SetSize(154,112)
 local col=(index-1)%4;local row=math.floor((index-1)/4);n:SetPoint("TOPLEFT",8+col*159,-8-row*117)
 if n.SetBackdrop then n:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=true,tileSize=16,edgeSize=9,insets={left=3,right=3,top=3,bottom=3}}) end
 local border=n:CreateTexture(nil,"BORDER");border:SetTexture("Interface\\Buttons\\UI-Quickslot2");border:SetSize(51,51);border:SetPoint("TOP",0,-8)
 n.icon=n:CreateTexture(nil,"ARTWORK");n.icon:SetSize(42,42);n.icon:SetPoint("CENTER",border)
 n.name=label(n,"GameFontNormalSmall","");n.name:SetPoint("TOPLEFT",5,-62);n.name:SetPoint("RIGHT",-5,0);n.name:SetJustifyH("CENTER");n.name:SetWordWrap(false)
 n.meta=label(n,"GameFontHighlightSmall","");n.meta:SetPoint("TOPLEFT",5,-80);n.meta:SetPoint("RIGHT",-5,0);n.meta:SetJustifyH("CENTER")
 n.state=label(n,"GameFontHighlightSmall","");n.state:SetPoint("BOTTOM",0,7)
 n:RegisterForClicks("LeftButtonUp");n:RegisterForDrag("LeftButton")
 n:SetScript("OnClick",function(self) if self.spell then send((self.spell.selected and "remove " or "select ")..self.spell.id) end end)
 n:SetScript("OnDragStart",function(self) if self.spell and _G.ForeverSubclassPickupSpell then _G.ForeverSubclassPickupSpell(self.spell) end end)
 n:SetScript("OnEnter",function(self)
  if self.spell and GameTooltip then GameTooltip:SetOwner(self,"ANCHOR_RIGHT");GameTooltip:SetSpellByID(self.spell.id);GameTooltip:AddLine(" ");GameTooltip:AddLine(self.spell.selected and "Нажмите, чтобы убрать способность" or "Нажмите, чтобы выбрать способность",0.45,0.82,1,true);GameTooltip:AddLine("Перетащите на обычную панель действий",0.72,0.72,0.72,true);GameTooltip:Show() end
 end)
 n:SetScript("OnLeave",function() if GameTooltip then GameTooltip:Hide() end end)
 spellNodes[index]=n;return n
end

local function makeTalentNode(id,col,row)
 local d=talentDefs[id];local template=BackdropTemplateMixin and "BackdropTemplate" or nil
 local n=CreateFrame("Button",nil,talentContent,template);n:SetSize(62,62);n:SetPoint("TOPLEFT",145+(col-1)*275,-92-(row-1)*130)
 if n.SetBackdrop then n:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background",edgeFile="Interface\\Buttons\\UI-ActionButton-Border",tile=false,edgeSize=16,insets={left=4,right=4,top=4,bottom=4}});n:SetBackdropColor(0.02,0.02,0.02,0.98) end
 n.icon=n:CreateTexture(nil,"ARTWORK");n.icon:SetPoint("TOPLEFT",6,-6);n.icon:SetPoint("BOTTOMRIGHT",-6,6);n.icon:SetTexture(d.icon)
 n.rank=label(n,"GameFontNormalSmall","0/"..d.max);n.rank:SetPoint("BOTTOMRIGHT",-3,2);n.rank:SetDrawLayer("OVERLAY",7)
 n.title=label(talentContent,"GameFontHighlight",d.name);n.title:SetPoint("TOP",n,"BOTTOM",0,-5);n.title:SetWidth(190);n.title:SetJustifyH("CENTER")
 n:RegisterForClicks("LeftButtonUp");n:SetScript("OnClick",function() send("talent "..id) end)
 n:SetScript("OnEnter",function(self)
  if GameTooltip then GameTooltip:SetOwner(self,"ANCHOR_RIGHT");GameTooltip:SetText(d.name,1,1,1);GameTooltip:AddLine(d.desc,0.88,0.88,0.88,true);GameTooltip:AddLine("Максимум: "..d.max..". Ряд "..(d.tier+1)..".",0.65,0.72,0.82,true);GameTooltip:Show() end
 end)
 n:SetScript("OnLeave",function() if GameTooltip then GameTooltip:Hide() end end)
 talentNodes[id]=n
end

local function createTalentConnectors()
 for _,branch in ipairs(talentBranches) do
  for i=1,#branch-1 do
   local a=talentNodes[branch[i]];local b=talentNodes[branch[i+1]]
   local line=talentContent:CreateTexture(nil,"BACKGROUND");line:SetColorTexture(0.20,0.34,0.48,0.85);line:SetWidth(3);line:SetPoint("TOP",a,"BOTTOM",0,-16);line:SetPoint("BOTTOM",b,"TOP",0,16)
  end
 end
end

local function choosePower(s)
 if not s or not s.powers then return nil end
 local native=UnitPowerType and select(1,UnitPowerType("player")) or -1
 for _,kind in ipairs({1,3,0}) do local p=s.powers[kind];if p and kind~=native then return p end end
 for _,p in pairs(s.powers) do return p end
end

local function refreshAbilities()
 clearSpellNodes();if not state or (not state.freepick and (not state.active or state.active==0)) then emptySpells:SetText("Сначала изучите и активируйте второй класс.");emptySpells:Show();resourceBar:Hide();return end
 local spells=visibleSpells(state)
 if #spells==0 then emptySpells:SetText("Для текущего уровня доступных способностей пока нет.");emptySpells:Show() else emptySpells:Hide() end
 for index,sp in ipairs(spells) do
  local n=spellNodes[index] or makeSpellNode(index);n.spell=sp;n.icon:SetTexture(spellTexture(sp.id));n.name:SetText(spellName(sp.id));n.meta:SetText("ур. "..sp.level.."   |   "..(powerNames[sp.power] or "Ресурс").." "..sp.cost);n.state:SetText(sp.selected and "Выбрано" or "Нажмите для выбора")
  if n.SetBackdropColor then if sp.selected then n:SetBackdropColor(0.03,0.09,0.04,0.96);n:SetBackdropBorderColor(0.20,0.82,0.36,1) else n:SetBackdropColor(0.028,0.028,0.028,0.96);n:SetBackdropBorderColor(0.30,0.36,0.44,0.95) end end;n:Show()
 end
 local p=choosePower(state)
 if p then resourceBar:SetMinMaxValues(0,math.max(1,p.max));resourceBar:SetValue(p.current);if p.kind==1 then resourceBar:SetStatusBarColor(0.75,0.12,0.12) elseif p.kind==3 then resourceBar:SetStatusBarColor(0.85,0.68,0.10) else resourceBar:SetStatusBarColor(0.10,0.35,0.90) end;resourceBar.text:SetText((powerNames[p.kind] or "Ресурс").." "..p.current.." / "..p.max);resourceBar:Show() else resourceBar:Hide() end
end

local function refreshTalents()
 if not state or not state.active or state.active==0 then talentPoints:SetText("Активируйте подкласс, чтобы открыть его дерево.");talentNote:SetText("");for _,n in pairs(talentNodes) do n:SetAlpha(0.35);n:Disable() end;setButtonEnabled(resetTalents,false);return end
 local activeLevel=state.classes[state.active] and state.classes[state.active].level or 1
 talentPoints:SetText("Очки талантов: "..tostring(state.talentFree or 0).."   Потрачено: "..tostring(state.talentSpent or 0).." / "..tostring(state.talentTotal or 0))
 talentNote:SetText("Подкласс: "..className(state.active).."   |   уровень "..activeLevel..". Первый пункт открывается на 10-м уровне; следующий ряд требует 5 потраченных очков.")
 for _,id in ipairs(talentOrder) do
  local n=talentNodes[id];local d=talentDefs[id];local t=state.talents[id] or {rank=0,max=d.max,tier=d.tier};local unlocked=(state.talentSpent or 0)>=t.tier*5;local available=unlocked and (state.talentFree or 0)>0 and t.rank<t.max
  n.rank:SetText(t.rank.."/"..t.max);n:SetAlpha(unlocked and 1 or 0.35);if available then n:Enable() else n:Disable() end
  if n.SetBackdropBorderColor then if t.rank>=t.max then n:SetBackdropBorderColor(0.20,0.82,0.36,1) elseif available then n:SetBackdropBorderColor(0.45,0.72,0.95,1) else n:SetBackdropBorderColor(0.25,0.28,0.33,0.9) end end
 end
 setButtonEnabled(resetTalents,(state.talentSpent or 0)>0)
end

local function setMode(mode)
 currentMode=(not (state and state.freepick) and mode=="talents") and "talents" or "abilities"
 if abilityContent then abilityContent:SetShown(currentMode=="abilities") end
 if talentContent then talentContent:SetShown(currentMode=="talents") end
 if modeAbilities then modeAbilities:SetEnabled(currentMode~="abilities") end
 if modeTalents then modeTalents:SetEnabled(not (state and state.freepick) and currentMode~="talents") end
 if viewTitle then viewTitle:SetText(currentMode=="talents" and "Древо талантов подкласса" or "Способности подкласса") end
 if currentMode=="talents" then refreshTalents() else refreshAbilities() end
end

local function refresh()
 if not panel or not panel:IsShown() then return end
 if not state then titleText:SetText("Подкласс");detailText:SetText("Получаем состояние персонажа...");statusText:SetText("Соединение с сервером...");return end
 if not selectedClass or selectedClass==state.primary then selectedClass=(state.active and state.active~=0 and state.active) or (state.primary~=5 and 5 or 8) end
 local primaryLevel=state.classes[state.primary] and state.classes[state.primary].level or (UnitLevel and UnitLevel("player") or 0)
 local activeName=(state.active and state.active~=0) and className(state.active) or "не выбран"
 local activeLevel=(state.active and state.classes[state.active]) and state.classes[state.active].level or 0
 titleText:SetText(className(state.primary).." / "..activeName)
 detailText:SetText(string.format("Основной %d   |   Подкласс %s   |   Эфф. %.1f%%   |   Способности %d/%d",primaryLevel,activeLevel>0 and activeLevel or "-",(state.efficiency or 0)/100,state.used or 0,state.budget or 8))
 statusText:SetText("Сервер подключен")
 local target=state.classes[state.xpTarget]
 if target then xpText:SetText("XP -> "..className(state.xpTarget).." "..target.level..": "..target.xp.."/"..target.next) else xpText:SetText("") end

 for _,id in ipairs(classOrder) do
  local card=cards[id];local progress=state.classes[id];local primaryFlag=id==state.primary;local activeFlag=id==state.active;local xpFlag=id==state.xpTarget;local selected=id==selectedClass
  if primaryFlag then card.role:SetText("Основной класс") elseif activeFlag then card.role:SetText(state.freepick and "Каталог навыков" or "Активный подкласс") elseif progress then card.role:SetText("Изучен") else card.role:SetText("Не изучен") end
  card.level:SetText(progress and ("Уровень "..progress.level) or "");card.xp:SetText(xpFlag and "Получает опыт" or "")
  card.frame._selected=selected;card.frame._active=activeFlag;card.frame._primary=primaryFlag
  if card.frame.SetBackdropBorderColor then if selected then card.frame:SetBackdropBorderColor(0.45,0.72,0.95,1) elseif activeFlag then card.frame:SetBackdropBorderColor(0.20,0.76,0.36,1) elseif primaryFlag then card.frame:SetBackdropBorderColor(0.50,0.55,0.65,1) else card.frame:SetBackdropBorderColor(0.25,0.28,0.33,0.95) end end
 end
 local chosen=state.classes[selectedClass];local isPrimary=selectedClass==state.primary
 setButtonEnabled(learnButton,not isPrimary and not chosen and primaryLevel>=10);setButtonEnabled(activeButton,not isPrimary and chosen~=nil and selectedClass~=state.active);setButtonEnabled(xpButton,chosen~=nil or isPrimary);setButtonEnabled(clearButton,state.active and state.active~=0)
 setMode(currentMode)
 if state.freepick then
  titleText:SetText(className(state.primary).." + Freepick")
  detailText:SetText(string.format("Основной уровень %d   |   AE %d/%d   |   Каталог: %s",primaryLevel,state.used or 0,state.budget or 8,activeName))
  activeButton:SetText("Открыть каталог");setButtonEnabled(learnButton,false);setButtonEnabled(xpButton,false);setButtonEnabled(clearButton,false)
  noticeText:SetText("Freepick: лечение жреца + Frostbolt мага одновременно. Навык стоит 1 AE; повторный клик возвращает AE. Покупки в городе/таверне. Таланты — следующим этапом.")
 else
  activeButton:SetText("Активировать")
  noticeText:SetText("Выберите класс слева. Способности и таланты активного подкласса находятся справа.")
 end
end

local function showCustom()
 if not panel then return end;customActive=true;panel:Show();panel:Raise();tab:SetEnabled(false);send("status");refresh();debug("subclass view")
end

local function build(allowStandalone)
 if built then return true end
 owner=_G.PlayerSpellsFrame;host=owner and owner.TalentsFrame
 if not owner or not host then
  if not allowStandalone then return false end
  owner=CreateFrame("Frame","ForeverSubclassStandaloneFrame",UIParent,"BasicFrameTemplateWithInset")
  owner:SetSize(1200,740);owner:SetPoint("CENTER");owner:SetClampedToScreen(true)
  owner:SetMovable(true);owner:EnableMouse(true);owner:RegisterForDrag("LeftButton")
  owner:SetScript("OnDragStart",function(self) self:StartMoving() end)
  owner:SetScript("OnDragStop",function(self) self:StopMovingOrSizing() end)
  if owner.TitleText then owner.TitleText:SetText("Forever — Freepick / Подклассы") end
  UISpecialFrames=UISpecialFrames or {};table.insert(UISpecialFrames,"ForeverSubclassStandaloneFrame")
  host=owner
 end
 built=true
 tab=CreateFrame("Button","ForeverSubclassTalentTab",host,"UIPanelButtonTemplate");tab:SetSize(76,26);tab:SetText("Подкласс");tab:RegisterForClicks("LeftButtonUp");tab:SetScript("OnClick",showCustom)
 local template=BackdropTemplateMixin and "BackdropTemplate" or nil
 panel=CreateFrame("Frame","ForeverSubclassTalentPanel",owner,template);panel:SetPoint("TOPLEFT",host,"TOPLEFT",0,-44);panel:SetPoint("BOTTOMRIGHT",host,"BOTTOMRIGHT",0,0);panel:SetFrameStrata("HIGH");panel:SetFrameLevel((owner.GetFrameLevel and owner:GetFrameLevel() or 100)+20);panel:EnableMouse(false)
 if panel.SetBackdrop then panel:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=true,tileSize=16,edgeSize=10,insets={left=3,right=3,top=3,bottom=3}});panel:SetBackdropColor(0.01,0.01,0.01,0.985);panel:SetBackdropBorderColor(0.30,0.34,0.40,1) end
 _G.ForeverSubclassPanelV2=panel;panel.Refresh=refresh

 header=makeBackdrop(panel,0.93);header:SetPoint("TOPLEFT",10,-10);header:SetPoint("TOPRIGHT",-10,-10);header:SetHeight(72)
 titleText=label(header,"GameFontNormalLarge","Подкласс");titleText:SetPoint("TOPLEFT",14,-10)
 statusText=label(header,"GameFontHighlightSmall","Соединение с сервером...");statusText:SetPoint("TOPRIGHT",-14,-12);statusText:SetTextColor(0.35,0.9,0.45,1)
 detailText=label(header,"GameFontHighlightSmall","");detailText:SetPoint("BOTTOMLEFT",14,12);detailText:SetWidth(650);detailText:SetJustifyH("LEFT")
 xpText=label(header,"GameFontHighlightSmall","");xpText:SetPoint("BOTTOMRIGHT",-14,12);xpText:SetWidth(360);xpText:SetJustifyH("RIGHT");xpText:SetTextColor(0.55,0.78,1,1)

 left=makeBackdrop(panel,0.94);left:SetPoint("TOPLEFT",10,-91);left:SetPoint("BOTTOMLEFT",10,45);left:SetWidth(452)
 local lt=label(left,"GameFontNormalLarge","Второй класс");lt:SetPoint("TOPLEFT",12,-12)
 local lh=label(left,"GameFontHighlightSmall","У каждого изученного класса свой уровень и опыт.");lh:SetPoint("TOPLEFT",lt,"BOTTOMLEFT",0,-4);lh:SetWidth(420);lh:SetJustifyH("LEFT")
 for i,id in ipairs(classOrder) do createCard(id,i) end
 clearButton=makeButton(left,"Отключить подкласс",150,function() send("clear") end);clearButton:SetPoint("BOTTOMLEFT",12,48);clearButton:SetHeight(22)
 learnButton=makeButton(left,"Изучить",125,function() if selectedClass then send("learn "..selectedClass) end end);learnButton:SetPoint("BOTTOMLEFT",12,13)
 activeButton=makeButton(left,"Активировать",125,function() if selectedClass then send("active "..selectedClass) end end);activeButton:SetPoint("LEFT",learnButton,"RIGHT",8,0)
 xpButton=makeButton(left,"Направить опыт",132,function() if selectedClass then send("xp "..selectedClass) end end);xpButton:SetPoint("LEFT",activeButton,"RIGHT",8,0)

 right=makeBackdrop(panel,0.94);right:SetPoint("TOPLEFT",472,-91);right:SetPoint("BOTTOMRIGHT",-10,45)
 viewTitle=label(right,"GameFontNormalLarge","Способности подкласса");viewTitle:SetPoint("TOPLEFT",14,-12)
 modeTalents=makeButton(right,"Таланты",105,function() setMode("talents") end);modeTalents:SetPoint("TOPRIGHT",-12,-9);modeTalents:SetHeight(24)
 modeAbilities=makeButton(right,"Способности",115,function() setMode("abilities") end);modeAbilities:SetPoint("RIGHT",modeTalents,"LEFT",-6,0);modeAbilities:SetHeight(24)

 abilityContent=CreateFrame("Frame",nil,right);abilityContent:SetPoint("TOPLEFT",8,-45);abilityContent:SetPoint("BOTTOMRIGHT",-8,8);abilityContent:EnableMouse(false)
 local rh=label(abilityContent,"GameFontHighlightSmall","До 8 способностей. Клик выбирает способность, перетаскивание кладёт её на обычную панель.");rh:SetPoint("TOPLEFT",6,-2);rh:SetWidth(555);rh:SetJustifyH("LEFT")
 resourceBar=CreateFrame("StatusBar",nil,abilityContent);resourceBar:SetPoint("TOPRIGHT",-6,-1);resourceBar:SetSize(190,18);resourceBar:SetStatusBarTexture("Interface\\TARGETINGFRAME\\UI-StatusBar");resourceBar.text=label(resourceBar,"GameFontHighlightSmall","");resourceBar.text:SetPoint("CENTER");resourceBar:Hide()
 spellGrid=CreateFrame("Frame",nil,abilityContent);spellGrid:SetPoint("TOPLEFT",0,-32);spellGrid:SetPoint("BOTTOMRIGHT",0,0);spellGrid:EnableMouse(false)
 emptySpells=label(spellGrid,"GameFontHighlight","Сначала активируйте подкласс.");emptySpells:SetPoint("CENTER",0,25);emptySpells:SetWidth(520);emptySpells:SetJustifyH("CENTER")

 talentContent=CreateFrame("Frame",nil,right);talentContent:SetPoint("TOPLEFT",8,-45);talentContent:SetPoint("BOTTOMRIGHT",-8,8);talentContent:EnableMouse(false)
 talentPoints=label(talentContent,"GameFontHighlight","");talentPoints:SetPoint("TOPLEFT",8,-4);talentPoints:SetWidth(310);talentPoints:SetJustifyH("LEFT")
 talentNote=label(talentContent,"GameFontHighlightSmall","");talentNote:SetPoint("TOPLEFT",8,-27);talentNote:SetWidth(620);talentNote:SetJustifyH("LEFT");talentNote:SetWordWrap(true)
 for row=1,3 do for col=1,2 do makeTalentNode(talentBranches[col][row],col,row) end end
 createTalentConnectors()
 resetTalents=makeButton(talentContent,"Сбросить таланты",145,function() send("talentreset") end);resetTalents:SetPoint("BOTTOMRIGHT",-8,6);resetTalents:SetHeight(24)
 talentContent:Hide()

 noticeText=label(panel,"GameFontHighlightSmall","");noticeText:SetPoint("BOTTOMLEFT",16,16);noticeText:SetPoint("RIGHT",-16,0);noticeText:SetJustifyH("LEFT")
 panel:Hide();hookNativeTabs(host,0);hookNativeTabs(owner,0);positionTab()
 if host.HookScript then host:HookScript("OnShow",function() hookNativeTabs(host,0);positionTab();if not customActive then panel:Hide() end end);host:HookScript("OnHide",hideCustom) end
 if owner.HookScript then owner:HookScript("OnHide",hideCustom) end
 return true
end

_G.ForeverSubclassShowTalentPanel=function()
 if InCombatLockdown and InCombatLockdown() then return false,"Откройте окно Freepick после выхода из боя." end
 if not built then
  local loader=(C_AddOns and C_AddOns.LoadAddOn) or LoadAddOn
  if loader then
   pcall(loader,"Blizzard_PlayerSpells")
   pcall(loader,"Blizzard_ClassTalentUI")
  end
 end
 if not build(true) then return false,"Не удалось создать окно Freepick." end
 owner:Show();host:Show();showCustom()
 return true
end

local function parse(text)
 local words={};for w in tostring(text):gmatch("%S+") do table.insert(words,w) end;local kind=words[1]
 if kind=="ERROR" then local raw=tostring(text):sub(7);if noticeText then noticeText:SetText(errors[raw] or raw) end;if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cffff5555[Подклассы]|r "..(errors[raw] or raw)) end;return
 elseif kind=="STATE" then pending={primary=tonumber(words[2]),active=tonumber(words[3]),xpTarget=tonumber(words[4]),used=tonumber(words[5]) or 0,budget=tonumber(words[6]) or 8,efficiency=tonumber(words[7]) or 0,classes={},spells={},powers={},talents={},talentFree=0,talentSpent=0,talentTotal=0}
 elseif pending and kind=="MODE" then pending.freepick=words[2]=="FREEPICK"
 elseif pending and kind=="CLASS" then pending.classes[tonumber(words[2])]={level=tonumber(words[3]) or 1,xp=tonumber(words[4]) or 0,next=tonumber(words[5]) or 0}
 elseif pending and kind=="POWER" then local p=tonumber(words[2]);if p then pending.powers[p]={kind=p,current=tonumber(words[3]) or 0,max=tonumber(words[4]) or 1} end
 elseif pending and kind=="SPELL" then local id=tonumber(words[2]);if id then pending.spells[id]={id=id,root=tonumber(words[3]),level=tonumber(words[4]) or 1,selected=words[5]=="1",cost=tonumber(words[6]) or 0,power=tonumber(words[7])} end
 elseif pending and kind=="TPOINTS" then pending.talentFree=tonumber(words[2]) or 0;pending.talentSpent=tonumber(words[3]) or 0;pending.talentTotal=tonumber(words[4]) or 0
 elseif pending and kind=="TALENT" then local id=tonumber(words[2]);if id then pending.talents[id]={rank=tonumber(words[3]) or 0,max=tonumber(words[4]) or 1,tier=tonumber(words[5]) or 0} end
 elseif pending and kind=="END" then state=pending;pending=nil;if panel and panel:IsShown() then refresh() end end
end

local events=CreateFrame("Frame");events:RegisterEvent("PLAYER_LOGIN");events:RegisterEvent("ADDON_LOADED");events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent",function(_,event,...)
 if event=="CHAT_MSG_ADDON" then local prefix,text=...;if prefix==RESPONSE then parse(text) end;return end
 local function setup() if build() then hookNativeTabs(host,0);hookNativeTabs(owner,0);positionTab() end end
 if C_Timer and C_Timer.After then C_Timer.After(0,setup);C_Timer.After(0.4,setup);C_Timer.After(1.2,setup) else setup() end
end)
