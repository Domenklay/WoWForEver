local REQUEST,RESPONSE="FAC1","FAR1"
local order={11,3,8,2,5,4,7,9,1}
local classes={
 [1]={"Warrior","Воин","WARRIOR"},[2]={"Paladin","Паладин","PALADIN"},
 [3]={"Hunter","Охотник","HUNTER"},[4]={"Rogue","Разбойник","ROGUE"},
 [5]={"Priest","Жрец","PRIEST"},[7]={"Shaman","Шаман","SHAMAN"},
 [8]={"Mage","Маг","MAGE"},[9]={"Warlock","Чернокнижник","WARLOCK"},[11]={"Druid","Друид","DRUID"},
}
local errors={disabled="Модуль выключен или основной класс не поддерживается.",
  cannot_edit_now="Нельзя менять способности в бою, после смерти или во время каста.",
 unavailable_or_power="Способность недоступна или не хватает ресурса.",
 incompatible_or_level="Способность не адаптирована или уровень персонажа недостаточен.",
 ability_limit="Достигнут предел дополнительных способностей.",select_target="Выберите цель.",
 already_learned="Способность уже изучена."}
local byClass,byId={},{ }
for id in pairs(classes) do byClass[id]={} end
for _,entry in ipairs(ForeverAscensionCatalog or {}) do
 byId[entry.ID]=entry
 for id,info in pairs(classes) do if entry.Class==info[1] then table.insert(byClass[id],entry);break end end
end
local state,pending,compatible=nil,nil,{}
local window,summary,message,search,activate,previous,nextPage,pageText,selectedText
local classButtons,tabButtons,abilityNodes,talentNodes,powerBars,actionButtons={},{},{},{},{},{}
local selectedClass,selectedTab,page=8,nil,1
local filter=""
local lastRequest,lastPoll,waiting,sentAt=0,0,false,0
local queue={}
local function send(payload)
 local now=GetTime()
 if now-lastRequest<0.2 then if #queue<16 then table.insert(queue,payload) end;return false end
 if not C_ChatInfo or not C_ChatInfo.SendAddonMessage then return false end
 C_ChatInfo.RegisterAddonMessagePrefix(REQUEST);C_ChatInfo.RegisterAddonMessagePrefix(RESPONSE)
 local ok,result=pcall(C_ChatInfo.SendAddonMessage,REQUEST,payload,"WHISPER","SERVER")
 if ok and result~=false then
  lastRequest=now
  if payload=="status" then waiting=true;sentAt=now end
  return true
 end
 return false
end
local function label(parent,text,font)
 local f=parent:CreateFontString(nil,"OVERLAY",font or "GameFontHighlight");f:SetText(text or "");return f
end
local function button(parent,text,width,fn)
 local b=CreateFrame("Button",nil,parent,"UIPanelButtonTemplate");b:SetSize(width,26);b:SetText(text);b:SetScript("OnClick",fn);return b
end
local function spellName(row)
 local d=compatible[row.ID]
 if GetLocale and GetLocale()=="ruRU" then
  local translated=ForeverAscensionNamesRU[row.Spells and row.Spells[1]]
  if translated then return translated end
 end
 if d and C_Spell and C_Spell.GetSpellName then return C_Spell.GetSpellName(d.spell) or row.Name or tostring(row.ID) end
 return row.Name or ("Запись "..row.ID)
end
local function icon(row)
 if row.Icon then return "Interface\\Icons\\"..row.Icon end
 return 134400
end
local function name(id) return classes[id] and classes[id][2] or "не выбран" end
local refresh
local function tooltip(self)
 local row=self.entry;if not row or not GameTooltip then return end
 GameTooltip:SetOwner(self,"ANCHOR_RIGHT")
 local d=compatible[row.ID]
 if d and GameTooltip.SetSpellByID then GameTooltip:SetSpellByID(d.spell) else GameTooltip:SetText(spellName(row)) end
 GameTooltip:AddLine("Ascension: "..row.ID.." · "..tostring(row.Tab),1,0.82,0.3)
 GameTooltip:AddLine("AE "..tostring(row.AECost or 0).." / TE "..tostring(row.TECost or 0).." (исходные данные)",0.7,0.7,0.7,true)
 if d and state and d.owner==state.primary then GameTooltip:AddLine("Способности основного класса изучаются штатно.",0.8,0.9,1,true)
 elseif d then GameTooltip:AddLine("ЛКМ — изучить/забыть; ПКМ — применить.",0.8,0.9,1,true)
 else GameTooltip:AddLine("Нет проверенной реализации в Forever. Изучение отключено.",1,0.5,0.3,true) end
 GameTooltip:Show()
end
local function node(parent,index,colWidth)
 local b=CreateFrame("Button",nil,parent)
 b:SetSize(colWidth-8,55);local col=(index-1)%2;local row=math.floor((index-1)/2)
 b:SetPoint("TOPLEFT",col*colWidth,-row*62)
 b.icon=b:CreateTexture(nil,"ARTWORK");b.icon:SetSize(38,38);b.icon:SetPoint("LEFT")
 b.name=label(b,"","GameFontNormalSmall");b.name:SetPoint("TOPLEFT",44,-3);b.name:SetWidth(colWidth-56);b.name:SetJustifyH("LEFT")
 b.note=label(b,"","GameFontHighlightSmall");b.note:SetPoint("TOPLEFT",44,-25);b.note:SetWidth(colWidth-56);b.note:SetJustifyH("LEFT")
 b:SetHighlightTexture("Interface\\Buttons\\ButtonHilight-Square","ADD")
 b:RegisterForClicks("LeftButtonUp","RightButtonUp")
 b:SetScript("OnClick",function(self,mouse)
  local entry=self.entry;if not state or not entry then return end
  local d=compatible[entry.ID]
  if not d or d.owner==state.primary or d.level>state.level then return end
  if mouse=="RightButton" then if state.learned[entry.ID] then send("cast "..entry.ID) end
  else send((state.learned[entry.ID] and "unlearn " or "learn ")..entry.ID) end
 end)
 b:SetScript("OnEnter",tooltip);b:SetScript("OnLeave",function() GameTooltip:Hide() end)
 return b
end
local function visible()
 local abilities,talents={},{}
 for _,row in ipairs(byClass[selectedClass] or {}) do
  if (not selectedTab or row.Tab==selectedTab) and (filter=="" or string.find(string.lower(spellName(row)),filter,1,true)) then
   if row.Type=="Ability" then table.insert(abilities,row)
   elseif row.Type=="Talent" or row.Type=="TalentAbility" then table.insert(talents,row) end
  end
 end
 local function sort(a,b)
  local x,y=a.RequiredLevel or 1,b.RequiredLevel or 1
  return x==y and a.ID<b.ID or x<y
 end
 table.sort(abilities,sort);table.sort(talents,sort)
 return abilities,talents
end
local function render(nodes,rows)
 for index,n in ipairs(nodes) do
  local row=rows[(page-1)*12+index];n.entry=row
  if row then
   n.icon:SetTexture(icon(row));n.name:SetText(spellName(row))
   local d=compatible[row.ID];local learned=state and state.learned[row.ID]
   if not d then n.note:SetText("Не адаптировано");n:SetAlpha(0.5)
   elseif state and d.owner==state.primary then n.note:SetText("Основной класс · книга заклинаний");n:SetAlpha(0.7)
   elseif state and d.level>state.level then n.note:SetText("Требуется уровень "..d.level);n:SetAlpha(0.6)
   elseif learned then n.note:SetText("Изучено · ПКМ: применить");n:SetAlpha(1)
   else n.note:SetText("Ур. "..d.level.." · изучить");n:SetAlpha(1) end
   n:Show()
  else n:Hide() end
 end
end
local function updatePowers()
 if not state then return end
 for i,power in ipairs({0,3,1}) do
  local bar=powerBars[i];local p=state.powers[power]
  if bar and p then
   local current,maximum=p.current,p.maximum
   if UnitPowerMax and UnitPowerMax("player",power)>0 then current=UnitPower("player",power);maximum=UnitPowerMax("player",power) end
   bar:SetMinMaxValues(0,math.max(1,maximum));bar:SetValue(current)
   bar.text:SetText(({[0]="Мана",[1]="Ярость",[3]="Энергия"})[power].." "..current.." / "..maximum);bar:Show()
  elseif bar then bar:Hide() end
 end
end
refresh=function()
 if not window then return end
 if state then
  summary:SetText("Основной: "..name(state.primary).."   Уровень: "..state.level.."   Способности: "..state.used.."/"..state.limit)
  activate:SetEnabled(true)
 else summary:SetText("Ожидаем сервер. Если ответа нет, проверьте установку ForeverAdvancement.");activate:SetEnabled(false) end
 selectedText:SetText(name(selectedClass).." · "..tostring(selectedTab or "Все вкладки"))
 local tabs,seen={},{ }
 for _,row in ipairs(byClass[selectedClass] or {}) do if not seen[row.Tab] then seen[row.Tab]=true;table.insert(tabs,row.Tab) end end
 table.sort(tabs)
 for i,b in ipairs(tabButtons) do
  local tab=tabs[i];b.tab=tab;if tab then b:SetText(tab);b:SetEnabled(tab~=selectedTab);b:Show() else b:Hide() end
 end
 local abilities,talents=visible();local pages=math.max(1,math.ceil(math.max(#abilities,#talents)/12));page=math.min(page,pages)
 render(abilityNodes,abilities);render(talentNodes,talents)
 pageText:SetText(page.." / "..pages);previous:SetEnabled(page>1);nextPage:SetEnabled(page<pages)
 local learned={}
 if state then for id in pairs(state.learned) do local d=compatible[id];if d then table.insert(learned,id) end end end
 table.sort(learned)
 for i,b in ipairs(actionButtons) do
  b.entry=byId[learned[i]]
  if b.entry then b.icon:SetTexture(icon(b.entry));b:Show() else b:Hide() end
 end
 updatePowers()
end
local function build()
 if window then return end
 window=CreateFrame("Frame","ForeverAscensionWindow",UIParent,"BasicFrameTemplateWithInset")
 window:SetSize(1120,680);window:SetPoint("CENTER");window:SetFrameStrata("DIALOG")
 if window.TitleText then window.TitleText:SetText("Character Advancement — Forever Multiclass") end
 window:SetMovable(true);window:EnableMouse(true);window:RegisterForDrag("LeftButton")
 window:SetScript("OnDragStart",window.StartMoving);window:SetScript("OnDragStop",window.StopMovingOrSizing)
 if UISpecialFrames then table.insert(UISpecialFrames,"ForeverAscensionWindow") end
 for i,id in ipairs(order) do
  local b=button(window,classes[id][2],110,function() selectedClass=id;selectedTab=nil;page=1;refresh() end)
  b:SetPoint("TOPLEFT",17+(i-1)*121,-34);classButtons[id]=b
 end
 for i=1,8 do
  local b=button(window,"",125,function(self) selectedTab=self.tab;page=1;refresh() end)
  b:SetPoint("TOPLEFT",17+(i-1)*135,-65);tabButtons[i]=b
 end
 summary=label(window,"");summary:SetPoint("TOPLEFT",20,-103)
 selectedText=label(window,"","GameFontNormalLarge");selectedText:SetPoint("TOPLEFT",20,-132)
 activate=button(window,"Обновить каталог",210,function() send("status") end);activate:SetPoint("TOPRIGHT",-20,-125)
 search=CreateFrame("EditBox",nil,window,"InputBoxTemplate");search:SetSize(220,24);search:SetPoint("TOPRIGHT",-250,-126);search:SetAutoFocus(false)
 search:SetScript("OnTextChanged",function(self) filter=string.lower(self:GetText() or "");page=1;refresh() end)
 search:SetScript("OnEscapePressed",function(self) self:ClearFocus() end)
 local leftTitle=label(window,"Способности","GameFontNormalLarge");leftTitle:SetPoint("TOPLEFT",24,-172)
 local rightTitle=label(window,"Таланты","GameFontNormalLarge");rightTitle:SetPoint("TOPLEFT",574,-172)
 local left=CreateFrame("Frame",nil,window);left:SetPoint("TOPLEFT",24,-205);left:SetSize(520,380)
 local right=CreateFrame("Frame",nil,window);right:SetPoint("TOPLEFT",574,-205);right:SetSize(520,380)
 for i=1,12 do abilityNodes[i]=node(left,i,260);talentNodes[i]=node(right,i,260) end
 previous=button(window,"Назад",90,function() page=math.max(1,page-1);refresh() end);previous:SetPoint("BOTTOMLEFT",24,48)
 nextPage=button(window,"Далее",90,function() page=page+1;refresh() end);nextPage:SetPoint("LEFT",previous,"RIGHT",70,0)
 pageText=label(window,"");pageText:SetPoint("LEFT",previous,"RIGHT",12,0)
 message=label(window,"Серые записи ещё не адаптированы. Стоимость AE/TE сохранена для справки; лимит способностей задаёт сервер.","GameFontHighlightSmall")
 message:SetPoint("BOTTOMLEFT",24,17);message:SetWidth(1060);message:SetJustifyH("LEFT")
 local hud=CreateFrame("Frame","ForeverAscensionResources",UIParent);hud:SetSize(220,60);hud:SetPoint("TOPLEFT",PlayerFrame or UIParent,"BOTTOMLEFT",25,-4)
 for i,power in ipairs({0,3,1}) do
  local bar=CreateFrame("StatusBar",nil,hud);bar:SetPoint("TOPLEFT",0,-(i-1)*19);bar:SetSize(220,17)
  bar:SetStatusBarTexture("Interface\\TARGETINGFRAME\\UI-StatusBar")
  local color=power==0 and {0.1,0.35,0.9} or power==1 and {0.8,0.1,0.1} or {0.9,0.75,0.1}
  bar:SetStatusBarColor(unpack(color));bar.text=label(bar,"");bar.text:SetPoint("CENTER");bar:Hide();powerBars[i]=bar
 end
 local actions=CreateFrame("Frame","ForeverAscensionActions",UIParent);actions:SetSize(440,42);actions:SetPoint("BOTTOM",0,155)
 for i=1,8 do
  local b=CreateFrame("Button",nil,actions);b:SetSize(40,40);b:SetPoint("LEFT",(i-1)*48,0)
  b.icon=b:CreateTexture(nil,"ARTWORK");b.icon:SetAllPoints()
  b:SetScript("OnClick",function(self) if self.entry then send("cast "..self.entry.ID) end end)
  b:SetScript("OnEnter",tooltip);b:SetScript("OnLeave",function() GameTooltip:Hide() end)
  b:Hide();actionButtons[i]=b
 end
 window:Hide();refresh()
end
local function open()
 build();window:Show();refresh();send("status")
end
SLASH_FOREVERASCENSION1="/ascension"
SLASH_FOREVERASCENSION2="/fa"
SLASH_FOREVERASCENSION3="/fsub"
SlashCmdList.FOREVERASCENSION=function(text)
 if not text or text=="" then open() else send(text) end
end
local function parse(text)
 local words={};for w in tostring(text):gmatch("%S+") do table.insert(words,w) end
 local kind=words[1]
 if kind=="ERROR" then if message then message:SetText(errors[words[2]] or text:sub(7)) end;return end
 if kind=="STATE" then pending={primary=tonumber(words[2]),level=tonumber(words[3]),used=tonumber(words[4]),limit=tonumber(words[5]),powers={},learned={}}
 elseif kind=="CATALOG" and pending then compatible={}
 elseif kind=="POWER" and pending then pending.powers[tonumber(words[2])]={current=tonumber(words[3]),maximum=tonumber(words[4])}
 elseif kind=="ENTRY" and pending then compatible[tonumber(words[2])]={spell=tonumber(words[3]),level=tonumber(words[4]),owner=tonumber(words[6])}
 elseif kind=="LEARNED" and pending then pending.learned[tonumber(words[2])]=true
 elseif kind=="END" and pending then state=pending;pending=nil;waiting=false;refresh() end
end
local events=CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN");events:RegisterEvent("CHAT_MSG_ADDON");events:RegisterEvent("UNIT_POWER_UPDATE");events:RegisterEvent("UNIT_MAXPOWER")
events:SetScript("OnEvent",function(_,event,...)
 if event=="CHAT_MSG_ADDON" then
  local prefix,text,channel,sender=...
  if prefix==RESPONSE and (not sender or sender==UnitName("player") or (GetUnitName and sender==GetUnitName("player",true))) then parse(text) end
 elseif event=="PLAYER_LOGIN" then build();send("status")
 else local unit=...;if unit=="player" then updatePowers() end end
end)
events:SetScript("OnUpdate",function(_,elapsed)
 lastPoll=lastPoll+elapsed
 if #queue>0 and GetTime()-lastRequest>=0.2 then send(table.remove(queue,1)) end
 if waiting and GetTime()-sentAt>6 then waiting=false;if message then message:SetText("Нет ответа ForeverAdvancement. Проверьте модуль сервера.") end end
 local interval=UnitAffectingCombat("player") and 1 or 10
 if lastPoll>=interval and #queue==0 then lastPoll=0;if state then send("poll") end end
end)
