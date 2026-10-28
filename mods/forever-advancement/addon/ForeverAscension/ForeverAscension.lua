local REQUEST,RESPONSE="FAC1","FAR1"
local order={11,3,8,2,5,4,7,9,1}
local classes={
 [1]={"Warrior","Воин","WARRIOR"},[2]={"Paladin","Паладин","PALADIN"},
 [3]={"Hunter","Охотник","HUNTER"},[4]={"Rogue","Разбойник","ROGUE"},
 [5]={"Priest","Жрец","PRIEST"},[7]={"Shaman","Шаман","SHAMAN"},
 [8]={"Mage","Маг","MAGE"},[9]={"Warlock","Чернокнижник","WARLOCK"},[11]={"Druid","Друид","DRUID"},
}
local classCoords={WARRIOR={0,0.25,0,0.25},MAGE={0.25,0.49609375,0,0.25},ROGUE={0.49609375,0.7421875,0,0.25},
 DRUID={0.7421875,0.98828125,0,0.25},HUNTER={0,0.25,0.25,0.5},SHAMAN={0.25,0.49609375,0.25,0.5},
 PRIEST={0.49609375,0.7421875,0.25,0.5},WARLOCK={0.7421875,0.98828125,0.25,0.5},PALADIN={0,0.25,0.5,0.75}}
local schools={Arcane="Тайная магия",Fire="Огонь",Frost="Лёд",Holy="Свет",Discipline="Послушание",Shadow="Тьма",
 Arms="Оружие",Fury="Неистовство",Protection="Защита",Assassination="Ликвидация",Combat="Бой",Subtlety="Скрытность",
 Balance="Баланс",Restoration="Исцеление",["Feral Combat"]="Сила зверя",Elemental="Стихии",Enhancement="Совершенствование",
 Affliction="Колдовство",Demonology="Демонология",Destruction="Разрушение",["Beast Mastery"]="Повелитель зверей",
 Marksmanship="Стрельба",Survival="Выживание",Retribution="Воздаяние"}
local errors={disabled="Модуль развития выключен.",cannot_edit_now="Нельзя менять набор в бою, после смерти или во время каста.",
 unavailable_or_power="Способность недоступна или не хватает ресурса.",incompatible_or_level="Способность недоступна для изучения на этом уровне.",
 ability_limit="Достигнут предел дополнительных способностей.",select_target="Выберите цель.",already_learned="Способность уже изучена.",
 talent_unavailable="Этот ранг таланта пока недоступен.",talent_requirements="Не хватает очков или не выполнены требования предыдущих рядов."}
local byClass,byId={},{ }
for id in pairs(classes) do byClass[id]={} end
for _,entry in ipairs(ForeverAscensionCatalog or {}) do
 byId[entry.ID]=entry
 for id,info in pairs(classes) do if entry.Class==info[1] then table.insert(byClass[id],entry);break end end
end
local state,pending,compatible=nil,nil,{}
local protocol=0
local window,summary,message,search,previous,nextPage,pageText,selectedText,talentPoints,emptyAbilities,showAllButton
local talentScroll,talentCanvas
local classButtons,tabButtons,abilityNodes,talentNodes,actionButtons,treeTextures,connectors={},{},{},{},{},{},{}
local powerBars=ForeverAscensionResourceBars or {}
local selectedClass,selectedTab,page=8,nil,1
local filter,showAll="",false
local lastRequest,lastPoll,waiting,sentAt=0,0,false,0
local queue={}
local function send(payload)
 local now=GetTime()
 if now-lastRequest<0.2 then if #queue<16 then table.insert(queue,payload) end;return false end
 if not C_ChatInfo or not C_ChatInfo.SendAddonMessage then return false end
 C_ChatInfo.RegisterAddonMessagePrefix(REQUEST);C_ChatInfo.RegisterAddonMessagePrefix(RESPONSE)
 local ok,result=pcall(C_ChatInfo.SendAddonMessage,REQUEST,payload,"WHISPER","SERVER")
 if ok and result~=false then lastRequest=now;if payload=="status" then waiting=true;sentAt=now end;return true end
 return false
end
local function label(parent,text,font)
 local f=parent:CreateFontString(nil,"OVERLAY",font or "GameFontHighlight");f:SetText(text or "");return f
end
local function button(parent,text,width,fn)
 local b=CreateFrame("Button",nil,parent,"UIPanelButtonTemplate");b:SetSize(width,24);b:SetText(text);b:SetScript("OnClick",fn);return b
end
local function spellName(row)
 local d=compatible[row.ID]
 if GetLocale and GetLocale()=="ruRU" then local text=ForeverAscensionNamesRU[row.Spells and row.Spells[1]];if text then return text end end
 if d and C_Spell and C_Spell.GetSpellName then return C_Spell.GetSpellName(d.spell or row.Spells[1]) or row.Name or tostring(row.ID) end
 return row.Name or ("Запись "..row.ID)
end
local upper,lower="АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯЁ","абвгдежзийклмнопрстуфхцчшщъыьэюяё"
local cyrillic={};for i=1,#upper,2 do cyrillic[upper:sub(i,i+1)]=lower:sub(i,i+1) end
local function fold(text)
 return (string.lower(text or ""):gsub("[\208\209][\128-\191]",function(letter) return cyrillic[letter] or letter end))
end
local function icon(row) return row.Icon and ("Interface\\Icons\\"..row.Icon) or 134400 end
local function name(id) return classes[id] and classes[id][2] or "не выбран" end
local function isTalent(row) return row.Type=="Talent" or row.Type=="TalentAbility" end
local function availableRow(row)
 local flags=row.Flags or 0
 return flags%2==0 and math.floor(flags/8)%2==0 and math.floor(flags/131072)%2==0
end
local function lowerTierSpent(row)
 local spent=0
 if state then for id,rank in pairs(state.talents) do
  local other=byId[id]
  if other and other.Class==row.Class and other.Tab==row.Tab and (other.RequiredTEInvestment or 0)<(row.RequiredTEInvestment or 0) then spent=spent+rank*(other.TECost or 1) end
 end end
 return spent
end
local refresh
local function tooltip(self)
 local row=self.entry;if not row or not GameTooltip then return end
 local d=compatible[row.ID]
 local rank=state and state.talents[row.ID] or 0
 local tipSpell=d and (d.spell or row.Spells[math.max(1,rank)])
 GameTooltip:SetOwner(self,"ANCHOR_RIGHT")
 if tipSpell and GameTooltip.SetSpellByID then GameTooltip:SetSpellByID(tipSpell) else GameTooltip:SetText(spellName(row),1,0.82,0.25) end
 local description=ForeverAscensionDescriptionsRU and ForeverAscensionDescriptionsRU[row.Spells and row.Spells[1]]
 if description and not d then GameTooltip:AddLine(description,0.9,0.85,0.7,true) end
 GameTooltip:AddLine((schools[row.Tab] or row.Tab).." · уровень "..tostring(d and d.level or row.RequiredLevel or 1),0.75,0.7,0.6,true)
 if isTalent(row) then
  local rank=state and state.talents[row.ID] or 0
  GameTooltip:AddLine("Ранг "..rank.." / "..tostring(d and d.max or #row.Spells).." · "..tostring(d and d.cost or row.TECost or 1).." TE за ранг",1,0.82,0.3)
  if (row.RequiredTEInvestment or 0)>0 then GameTooltip:AddLine("Требуется "..row.RequiredTEInvestment.." TE в предыдущих рядах этой школы.",0.8,0.75,0.65,true) end
 end
 if d and state and d.owner==state.primary then GameTooltip:AddLine("Это ваш основной класс. Его способности и таланты изучаются штатно.",0.8,0.8,0.8,true)
 elseif d then GameTooltip:AddLine(isTalent(row) and "ЛКМ — вложить очко. ПКМ — вернуть ранг." or "ЛКМ — изучить / забыть. ПКМ — применить.",0.5,0.9,0.5,true)
 else GameTooltip:AddLine("Для этой записи ещё нет совместимого обработчика Forever.",0.9,0.5,0.35,true) end
 GameTooltip:Show()
end
local function makeNode(parent,talent)
 local b=CreateFrame("Button",nil,parent)
 b:SetSize(talent and 44 or 188,talent and 42 or 54)
 b.icon=b:CreateTexture(nil,"ARTWORK");b.icon:SetSize(talent and 32 or 36,talent and 32 or 36);b.icon:SetPoint("TOPLEFT",4,-4)
 b.border=b:CreateTexture(nil,"OVERLAY");b.border:SetTexture("Interface\\Buttons\\UI-Quickslot2");b.border:SetSize(talent and 47 or 52,talent and 47 or 52);b.border:SetPoint("CENTER",b.icon)
 if talent then
  b.note=label(b,"","GameFontNormalSmall");b.note:SetPoint("BOTTOMRIGHT",5,-2)
 else
  b.name=label(b,"","GameFontNormalSmall");b.name:SetPoint("TOPLEFT",48,-5);b.name:SetWidth(132);b.name:SetJustifyH("LEFT");b.name:SetTextColor(0.18,0.11,0.04)
  b.note=label(b,"","GameFontHighlightSmall");b.note:SetPoint("TOPLEFT",48,-29);b.note:SetWidth(132);b.note:SetJustifyH("LEFT");b.note:SetTextColor(0.32,0.22,0.12)
 end
 b:SetHighlightTexture("Interface\\Buttons\\ButtonHilight-Square","ADD");b:RegisterForClicks("LeftButtonUp","RightButtonUp")
 b:SetScript("OnClick",function(self,mouse)
  local row=self.entry;if not row or not state then return end
  local d=compatible[row.ID];if not d or d.owner==state.primary or d.level>state.level then return end
  if isTalent(row) then send((mouse=="RightButton" and "untalent " or "talent ")..row.ID)
  elseif mouse=="RightButton" then if state.learned[row.ID] then send("cast "..row.ID) end
  else send((state.learned[row.ID] and "unlearn " or "learn ")..row.ID) end
 end)
 b:SetScript("OnEnter",tooltip);b:SetScript("OnLeave",function() GameTooltip:Hide() end)
 return b
end
local function visible()
 local canonical={}
 for _,row in ipairs(byClass[selectedClass] or {}) do
  if availableRow(row) and (row.Type=="Ability" or isTalent(row)) then
   local key=row.Type..":"..row.Tab..":"..tostring(row.Name or row.Spells[1] or row.ID)
   local previousRow=canonical[key]
   if not previousRow or (compatible[row.ID] and not compatible[previousRow.ID]) or
      ((compatible[row.ID]~=nil)==(compatible[previousRow.ID]~=nil) and row.ID<previousRow.ID) then canonical[key]=row end
  end
 end
 local abilities,talents={},{}
 for _,row in pairs(canonical) do
  local matches=not selectedTab or row.Tab==selectedTab
  if matches and (filter=="" or string.find(fold(spellName(row)),filter,1,true)) then
   if isTalent(row) then table.insert(talents,row)
   elseif showAll or compatible[row.ID] then table.insert(abilities,row) end
  end
 end
 local function sort(a,b) local x,y=a.RequiredLevel or 1,b.RequiredLevel or 1;return x==y and a.ID<b.ID or x<y end
 table.sort(abilities,sort);table.sort(talents,sort)
 return abilities,talents
end
local function renderAbilities(rows)
 for index,n in ipairs(abilityNodes) do
  local row=rows[(page-1)*16+index];n.entry=row
  if row then
   n.icon:SetTexture(icon(row));n.name:SetText(spellName(row));local d=compatible[row.ID]
   local learned=state and state.learned[row.ID]
   if not d then n.note:SetText("Не перенесено")
   elseif state and d.owner==state.primary then n.note:SetText("Основной класс")
   elseif state and d.level>state.level then n.note:SetText("Уровень "..d.level)
   elseif learned then n.note:SetText("Изучено")
   else n.note:SetText("Изучить · ур. "..d.level) end
   local locked=not d or (state and d.level>state.level)
   n:SetAlpha(locked and 0.55 or 1)
   if n.icon.SetDesaturated then n.icon:SetDesaturated(locked and true or false) end
   n.border:SetVertexColor(learned and 0.3 or 0.8,learned and 1 or 0.65,0.25);n:Show()
  else n:Hide() end
 end
end
local function renderTalents(rows)
 local maxTier=0;local positions={}
 for index,row in ipairs(rows) do
  local n=talentNodes[index] or makeNode(talentCanvas,true);talentNodes[index]=n;n.entry=row
  local tier=math.floor((row.RequiredTEInvestment or 0)/3);local column=math.max(1,math.min(4,row.Column or 1))
  maxTier=math.max(maxTier,tier)
  local x,y=65+(column-1)*107,-16-tier*47
  n:ClearAllPoints();n:SetPoint("TOPLEFT",x,y);positions[row.ID]={x=x+20,y=y-20}
  local d=compatible[row.ID];local rank=state and state.talents[row.ID] or 0
  local max=d and d.max or #row.Spells
  n.icon:SetTexture(icon(row));n.note:SetText(rank.."/"..max)
  local locked=not d or not state or d.level>state.level or lowerTierSpent(row)<(row.RequiredTEInvestment or 0)
  if n.icon.SetDesaturated then n.icon:SetDesaturated(locked and true or false) end
  n:SetAlpha(d and 1 or 0.5);n.border:SetVertexColor(rank>0 and 0.3 or 0.85,rank>0 and 1 or 0.7,0.2)
  n.note:SetTextColor(rank==max and 0.3 or 1,rank==max and 1 or 0.82,rank==max and 0.3 or 0.2);n:Show()
 end
 for i=#rows+1,#talentNodes do talentNodes[i]:Hide() end
 for _,line in ipairs(connectors) do line:Hide() end
 local lineCount=0
 for _,row in ipairs(rows) do
  local child=positions[row.ID]
  for _,id in ipairs(row.RequiredIDs or {}) do
   local parent=positions[id]
   if parent and child and parent.x==child.x and parent.y>child.y then
    lineCount=lineCount+1;local line=connectors[lineCount] or talentCanvas:CreateTexture(nil,"BACKGROUND")
    connectors[lineCount]=line;line:ClearAllPoints();line:SetColorTexture(0.65,0.49,0.16,0.8)
    line:SetPoint("TOPLEFT",parent.x-1,parent.y-16);line:SetSize(2,math.max(1,parent.y-child.y-32));line:Show()
   end
  end
 end
 talentCanvas:SetHeight(math.max(470,(maxTier+1)*47+30))
end
local function updatePowers()
 if state and ForeverAscensionSetResources then ForeverAscensionSetResources(state.powers,state.regen) end
end
local function background()
 local token=classes[selectedClass][1]..tostring(selectedTab or ""):gsub("%s","")
 for i,corner in ipairs({"TopLeft","TopRight","BottomLeft","BottomRight"}) do
  treeTextures[i]:SetTexture("Interface\\TalentFrame\\"..token.."-"..corner)
 end
end
refresh=function()
 if not window then return end
 if state then
  summary:SetText("Основной класс: "..name(state.primary).."  ·  Уровень "..state.level.."  ·  Умения "..state.used.."/"..state.limit)
  talentPoints:SetText("Очки талантов: "..(state.talentFree or 0).." / "..(state.talentTotal or 0))
 else summary:SetText("Ожидаем состояние персонажа…");talentPoints:SetText("Очки талантов: —") end
 local tabs,seen={},{ }
 for _,row in ipairs(byClass[selectedClass] or {}) do if availableRow(row) and not seen[row.Tab] then seen[row.Tab]=true;table.insert(tabs,row.Tab) end end
 table.sort(tabs)
 if not selectedTab or not seen[selectedTab] then selectedTab=tabs[1] end
 for i,b in ipairs(tabButtons) do local tab=tabs[i];b.tab=tab;if tab then b:SetText(schools[tab] or tab);b:SetEnabled(tab~=selectedTab);b:Show() else b:Hide() end end
 for id,b in pairs(classButtons) do
  b.glow:SetShown(id==selectedClass)
  local count=0;if state then for learned in pairs(state.learned) do local row=byId[learned];if row and row.Class==classes[id][1] then count=count+1 end end end
  b.count:SetText(count>0 and tostring(count) or "")
 end
 selectedText:SetText(name(selectedClass).."  ·  "..tostring(schools[selectedTab] or selectedTab or ""));background()
 local abilities,talents=visible();local pages=math.max(1,math.ceil(#abilities/16));page=math.min(page,pages)
 renderAbilities(abilities);renderTalents(talents)
 emptyAbilities:SetShown(#abilities==0)
 emptyAbilities:SetText(showAll and "Здесь пока нет записей." or "В этой школе пока нет доступных умений.\nНажмите «Все умения», чтобы открыть весь каталог.")
 pageText:SetText(page.." / "..pages);previous:SetEnabled(page>1);nextPage:SetEnabled(page<pages)
 showAllButton:SetText(showAll and "Только доступные" or "Все умения")
 local learned={};if state then for id in pairs(state.learned) do if compatible[id] then table.insert(learned,id) end end end;table.sort(learned)
 for i,b in ipairs(actionButtons) do b.entry=byId[learned[i]];if b.entry then b.icon:SetTexture(icon(b.entry));b:Show() else b:Hide() end end
 if state and protocol<2 then message:SetText("Для талантов и нового каталога обновите сервер до версии 1.1.") end
 updatePowers()
end
local function panel(parent,x,y,width,height,paper)
 local f=CreateFrame("Frame",nil,parent,BackdropTemplateMixin and "BackdropTemplate" or nil);f:SetPoint("TOPLEFT",x,y);f:SetSize(width,height)
 if f.SetBackdrop then f:SetBackdrop({bgFile="Interface\\DialogFrame\\UI-DialogBox-Background",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=true,tileSize=32,edgeSize=12,insets={left=3,right=3,top=3,bottom=3}});f:SetBackdropColor(0.12,0.08,0.035,1) end
 local fill=f:CreateTexture(nil,"BACKGROUND");fill:SetPoint("TOPLEFT",4,-4);fill:SetPoint("BOTTOMRIGHT",-4,4);fill:SetColorTexture(paper and 0.85 or 0.1,paper and 0.77 or 0.065,paper and 0.58 or 0.03,1)
 if paper then local parchment=f:CreateTexture(nil,"BORDER");parchment:SetAllPoints(fill);parchment:SetTexture("Interface\\QuestFrame\\QuestBG");parchment:SetVertexColor(0.95,0.88,0.72,1) end
 return f
end
local function build()
 if window then return end
 window=CreateFrame("Frame","ForeverAscensionWindow",UIParent,"BasicFrameTemplateWithInset")
 window:SetSize(1040,730);window:SetPoint("CENTER");window:SetFrameStrata("DIALOG");window:SetClampedToScreen(true)
 if GetScreenHeight and GetScreenWidth then window:SetScale(math.min(1,(GetScreenWidth()-40)/1040,(GetScreenHeight()-40)/730)) end
 if window.TitleText then window.TitleText:SetText("Развитие персонажа — мультиклассы") end
 window:SetMovable(true);window:EnableMouse(true);window:RegisterForDrag("LeftButton")
 window:SetScript("OnDragStart",window.StartMoving);window:SetScript("OnDragStop",window.StopMovingOrSizing)
 if UISpecialFrames then table.insert(UISpecialFrames,"ForeverAscensionWindow") end
 for i,id in ipairs(order) do
  local b=CreateFrame("Button",nil,window);b:SetSize(102,69);b:SetPoint("TOPLEFT",18+(i-1)*112,-30)
  b.icon=b:CreateTexture(nil,"ARTWORK");b.icon:SetSize(38,38);b.icon:SetPoint("TOP",0,-4)
  b.icon:SetTexture("Interface\\GLUES\\CHARACTERCREATE\\UI-CHARACTERCREATE-CLASSES")
  local coords=(CLASS_ICON_TCOORDS and CLASS_ICON_TCOORDS[classes[id][3]]) or classCoords[classes[id][3]];if coords then b.icon:SetTexCoord(unpack(coords)) else b.icon:SetTexture(134400) end
  local border=b:CreateTexture(nil,"OVERLAY");border:SetTexture("Interface\\Buttons\\UI-Quickslot2");border:SetSize(54,54);border:SetPoint("CENTER",b.icon)
  b.glow=b:CreateTexture(nil,"OVERLAY");b.glow:SetTexture("Interface\\Buttons\\UI-ActionButton-Border");b.glow:SetBlendMode("ADD");b.glow:SetSize(64,64);b.glow:SetPoint("CENTER",b.icon)
  b.name=label(b,classes[id][2],"GameFontNormalSmall");b.name:SetPoint("BOTTOM",0,3)
  b.count=label(b,"","GameFontHighlightSmall");b.count:SetPoint("RIGHT",b.icon,"RIGHT",4,-13)
  b:SetScript("OnClick",function() selectedClass=id;selectedTab=nil;page=1;talentScroll:SetVerticalScroll(0);refresh() end);classButtons[id]=b
 end
 for i=1,8 do
  local b=button(window,"",120,function(self) selectedTab=self.tab;page=1;talentScroll:SetVerticalScroll(0);refresh() end)
  b:SetPoint("TOPLEFT",20+(i-1)*124,-108);tabButtons[i]=b
 end
 summary=label(window,"","GameFontHighlightSmall");summary:SetPoint("TOPLEFT",25,-143)
 selectedText=label(window,"","GameFontNormalLarge");selectedText:SetPoint("TOPLEFT",27,-169)
 search=CreateFrame("EditBox",nil,window,"InputBoxTemplate");search:SetSize(190,22);search:SetPoint("TOPRIGHT",-171,-165);search:SetAutoFocus(false)
 search:SetScript("OnTextChanged",function(self) filter=fold(self:GetText());page=1;refresh() end);search:SetScript("OnEscapePressed",function(self) self:ClearFocus() end)
 local reload=button(window,"Обновить",125,function() send("status") end);reload:SetPoint("TOPRIGHT",-25,-165)
 local left=panel(window,18,-201,410,470,true)
 local heading=label(left,"Способности","GameFontNormalLarge");heading:SetPoint("TOP",0,-14);heading:SetTextColor(0.23,0.14,0.04)
 local abilityCanvas=CreateFrame("Frame",nil,left);abilityCanvas:SetPoint("TOPLEFT",12,-47);abilityCanvas:SetSize(386,410)
 for i=1,16 do local n=makeNode(abilityCanvas,false);n:SetPoint("TOPLEFT",((i-1)%2)*194,-math.floor((i-1)/2)*51);abilityNodes[i]=n end
 emptyAbilities=label(abilityCanvas,"","GameFontHighlight");emptyAbilities:SetPoint("CENTER",0,0);emptyAbilities:SetWidth(340);emptyAbilities:SetTextColor(0.25,0.17,0.08)
 local right=panel(window,438,-201,584,470,false)
 for i=1,4 do local texture=right:CreateTexture(nil,"BORDER");texture:SetSize(288,231);texture:SetPoint("TOPLEFT",4+((i-1)%2)*288,-4-math.floor((i-1)/2)*231);texture:SetVertexColor(0.8,0.73,0.63);treeTextures[i]=texture end
 local title=label(right,"Таланты","GameFontNormalLarge");title:SetPoint("TOPLEFT",25,-14)
 talentPoints=label(right,"","GameFontNormal");talentPoints:SetPoint("TOPRIGHT",-25,-16)
 talentScroll=CreateFrame("ScrollFrame","ForeverAscensionTalentScroll",right);talentScroll:SetPoint("TOPLEFT",10,-44);talentScroll:SetPoint("BOTTOMRIGHT",-10,8)
 talentCanvas=CreateFrame("Frame",nil,talentScroll);talentCanvas:SetSize(560,470);talentScroll:SetScrollChild(talentCanvas);talentScroll:EnableMouseWheel(true)
 talentScroll:SetScript("OnMouseWheel",function(self,delta) local current=self:GetVerticalScroll() or 0;self:SetVerticalScroll(math.max(0,math.min(math.max(0,talentCanvas:GetHeight()-410),current-delta*40))) end)
 previous=button(window,"Назад",80,function() page=math.max(1,page-1);refresh() end);previous:SetPoint("BOTTOMLEFT",24,29)
 nextPage=button(window,"Далее",80,function() page=page+1;refresh() end);nextPage:SetPoint("LEFT",previous,"RIGHT",61,0)
 pageText=label(window,"");pageText:SetPoint("LEFT",previous,"RIGHT",12,0)
 showAllButton=button(window,"Все умения",135,function() showAll=not showAll;page=1;refresh() end);showAllButton:SetPoint("LEFT",nextPage,"RIGHT",9,0)
 message=label(window,"ЛКМ — изучить. ПКМ — вернуть ранг таланта или применить умение.","GameFontHighlightSmall");message:SetPoint("BOTTOMLEFT",26,10);message:SetWidth(985);message:SetJustifyH("LEFT")
 local hint=label(window,"Прокрутка колёсиком · Требования предыдущих рядов указаны в подсказках","GameFontHighlightSmall");hint:SetPoint("BOTTOMRIGHT",-28,36)
 local actions=CreateFrame("Frame","ForeverAscensionActions",UIParent);actions:SetSize(400,42);actions:SetPoint("BOTTOM",0,155)
 for i=1,8 do
  local b=CreateFrame("Button",nil,actions);b:SetSize(40,40);b:SetPoint("LEFT",(i-1)*48,0)
  b.icon=b:CreateTexture(nil,"ARTWORK");b.icon:SetAllPoints()
  local border=b:CreateTexture(nil,"OVERLAY");border:SetTexture("Interface\\Buttons\\UI-Quickslot2");border:SetSize(54,54);border:SetPoint("CENTER")
  b:SetScript("OnClick",function(self) if self.entry then send("cast "..self.entry.ID) end end)
  b:SetScript("OnEnter",tooltip);b:SetScript("OnLeave",function() GameTooltip:Hide() end);b:Hide();actionButtons[i]=b
 end
 window:Hide();refresh()
end
local function open() build();window:Show();refresh();send("status") end
SLASH_FOREVERASCENSION1="/ascension";SLASH_FOREVERASCENSION2="/fa";SLASH_FOREVERASCENSION3="/fsub"
SlashCmdList.FOREVERASCENSION=function(text) if not text or text=="" then open() else send(text) end end
local function parse(text)
 local words={};for w in tostring(text):gmatch("%S+") do table.insert(words,w) end;local kind=words[1]
 if kind=="PROTOCOL" then protocol=tonumber(words[2]) or 0;return end
 if kind=="ERROR" then if message then message:SetText(errors[words[2]] or text:sub(7)) end;return end
 if kind=="STATE" then pending={primary=tonumber(words[2]),level=tonumber(words[3]),used=tonumber(words[4]),limit=tonumber(words[5]),powers={},regen={},learned={},talents={},talentFree=0,talentSpent=0,talentTotal=0}
 elseif kind=="CATALOG" and pending then compatible={}
 elseif kind=="POWER" and pending then pending.powers[tonumber(words[2])]={current=tonumber(words[3]),maximum=tonumber(words[4])}
 elseif kind=="REGEN" and pending then pending.regen={normal=tonumber(words[2]),combat=tonumber(words[3])}
 elseif kind=="ENTRY" and pending then compatible[tonumber(words[2])]={kind="ability",spell=tonumber(words[3]),level=tonumber(words[4]),owner=tonumber(words[6])}
 elseif kind=="TENTRY" and pending then compatible[tonumber(words[2])]={kind="talent",max=tonumber(words[3]),level=tonumber(words[4]),cost=tonumber(words[5]),investment=tonumber(words[6]),owner=tonumber(words[7])}
 elseif kind=="TPOINTS" and pending then pending.talentFree=tonumber(words[2]);pending.talentSpent=tonumber(words[3]);pending.talentTotal=tonumber(words[4])
 elseif kind=="TALENT" and pending then pending.talents[tonumber(words[2])]=tonumber(words[3])
 elseif kind=="LEARNED" and pending then pending.learned[tonumber(words[2])]=true
 elseif kind=="END" and pending then state=pending;pending=nil;waiting=false;refresh() end
end
local events=CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN");events:RegisterEvent("CHAT_MSG_ADDON");events:RegisterEvent("UNIT_POWER_UPDATE");events:RegisterEvent("UNIT_MAXPOWER")
events:SetScript("OnEvent",function(_,event,...)
 if event=="CHAT_MSG_ADDON" then local prefix,text,channel,sender=...;if prefix==RESPONSE and (not sender or sender==UnitName("player") or (GetUnitName and sender==GetUnitName("player",true))) then parse(text) end
 elseif event=="PLAYER_LOGIN" then build();send("status")
 else local unit=...;if unit=="player" then updatePowers() end end
end)
events:SetScript("OnUpdate",function(_,elapsed)
 lastPoll=lastPoll+elapsed
 if #queue>0 and GetTime()-lastRequest>=0.2 then send(table.remove(queue,1)) end
 if waiting and GetTime()-sentAt>6 then waiting=false;if message then message:SetText("Нет ответа сервера. Проверьте версию модуля развития.") end end
 local interval=UnitAffectingCombat("player") and 1 or 10
 if lastPoll>=interval and #queue==0 then lastPoll=0;if state then send("poll") end end
end)
