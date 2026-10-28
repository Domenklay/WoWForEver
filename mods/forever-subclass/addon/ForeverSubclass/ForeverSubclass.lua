-- UI and transport only. Class levels, spell permissions and resources live on the server.
local REQUEST, RESPONSE = "FSC1", "FSR1"
local classes = {1,2,3,4,5,7,8,9,11}
local names = {[1]="Воин",[2]="Паладин",[3]="Охотник",[4]="Разбойник",[5]="Жрец",[7]="Шаман",[8]="Маг",[9]="Чернокнижник",[11]="Друид"}
local powerNames = {[0]="Мана",[1]="Ярость",[3]="Энергия"}
local state, pending, selectedClass = nil, nil, 5
local queue, nextSend, nextPoll = {}, 0, 0
local errors = {
 ["module disabled or unsupported primary class"]="Серверный мод выключен или класс не поддержан.",
 ["primary class has not reached subclass unlock level"]="Подкласс открывается с 10-го уровня.",
 ["subclass can only be switched in a rest area"]="Смена подкласса разрешена в городе или таверне.",
 ["cannot edit in combat or while casting"]="Изменять подкласс в бою, после смерти или во время каста нельзя.",
 ["class has not been learned"]="Сначала изучите этот класс.",
 ["spell unavailable or not enough power"]="Способность не выбрана, уровень недостаточен или не хватает ресурса.",
 ["subclass level is too low for this spell"]="Уровень подкласса недостаточен.",
 ["not enough subclass ability slots"]="Не хватает слотов способностей.",
 ["no active subclass"]="Сначала активируйте подкласс.",
 ["select a target"]="Выберите цель.",
 ["saved primary class mismatch"]="Класс персонажа отличается от сохранённого: сообщите администратору.",
 ["subclass talents can only be changed in a rest area"]="Таланты подкласса можно менять только в городе или таверне.",
 ["subclass talents can only be reset in a rest area"]="Сбрасывать таланты подкласса можно только в городе или таверне.",
 ["no subclass talent points"]="Нет свободных очков талантов подкласса.",
 ["subclass talent tier locked"]="Этот ряд талантов пока закрыт.",
 ["hunter pet requires hunter subclass level 10"]="Питомец открывается на 10-м уровне подкласса Охотника.",
 ["select a tameable beast"]="Выберите живого приручаемого зверя.",
 ["selected beast is not tameable by this subclass"]="Этот зверь недоступен для приручения подклассом.",
 ["beast level exceeds hunter subclass level"]="Уровень зверя выше уровня подкласса Охотника.",
}
local frame = CreateFrame("Frame", "ForeverSubclassFrame", UIParent, "BasicFrameTemplateWithInset")
frame:SetSize(560, 530); frame:SetPoint("CENTER"); frame:Hide()
frame:SetMovable(true); frame:EnableMouse(true); frame:RegisterForDrag("LeftButton")
frame:SetScript("OnDragStart", frame.StartMoving); frame:SetScript("OnDragStop", function(self)
 self:StopMovingOrSizing()
 local point,_,relative,x,y=self:GetPoint(); ForeverSubclassUI={point=point,relative=relative,x=x,y=y}
end)
frame.TitleText:SetText("Forever — подклассы")
local function label(parent,x,y,width,text)
 local f=parent:CreateFontString(nil,"OVERLAY","GameFontNormalSmall")
 f:SetPoint("TOPLEFT",x,y); f:SetWidth(width); f:SetJustifyH("LEFT"); f:SetText(text or ""); return f
end
local function button(parent,text,x,y,w,callback)
 local b=CreateFrame("Button",nil,parent,"UIPanelButtonTemplate")
 b:SetSize(w,24); b:SetPoint("TOPLEFT",x,y); b:SetText(text); b:SetScript("OnClick",callback); return b
end
local headline=label(frame,15,-34,525,"Ожидание ответа сервера…")
local progress=label(frame,15,-57,525,"")
local message=label(frame,15,-477,525,"/fsub — открыть окно. Основной класс и броня не меняются.")
local lastNotice, lastNoticeAt = nil, 0
local function say(text)
 message:SetText(text)
 if lastNotice==text and GetTime()-lastNoticeAt<10 then return end
 lastNotice=text;lastNoticeAt=GetTime()
 DEFAULT_CHAT_FRAME:AddMessage("|cff67d9ff[Подклассы]|r "..text)
end
local function send(text)
 if #queue<8 then table.insert(queue,text) end
end
local classButtons={}
for index,id in ipairs(classes) do
 local classId=id
 classButtons[id]=button(frame,names[id],15+((index-1)%3)*177,-86-math.floor((index-1)/3)*28,172,function() selectedClass=classId; if frame.Refresh then frame.Refresh() end end)
end
button(frame,"Изучить",15,-178,125,function() send("learn "..selectedClass) end)
button(frame,"Активировать",150,-178,125,function() send("active "..selectedClass) end)
button(frame,"Направить XP",285,-178,125,function() send("xp "..selectedClass) end)
button(frame,"Выключить",420,-178,125,function() send("clear") end)
label(frame,15,-210,525,"Выберите способности в пределах 8 слотов. Кнопка «Каст» использует выбранную в игре цель.")
local scroll=CreateFrame("ScrollFrame","ForeverSubclassScroll",frame,"UIPanelScrollFrameTemplate")
scroll:SetPoint("TOPLEFT",15,-240); scroll:SetSize(505,225)
local content=CreateFrame("Frame",nil,scroll); content:SetSize(500,225); scroll:SetScrollChild(content)
local rows={}
-- Legacy fallback bar. The persistent multi-resource HUD hides this duplicate when available.
local power=CreateFrame("StatusBar","ForeverSubclassPowerBar",UIParent)
power:SetSize(235,19); power:SetPoint("CENTER",UIParent,"CENTER",0,-200)
power:SetStatusBarTexture("Interface\\TARGETINGFRAME\\UI-StatusBar"); power:SetStatusBarColor(0.1,0.35,0.95)
power.text=power:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall"); power.text:SetPoint("CENTER"); power:Hide()
local function spellName(id)
 if C_Spell and C_Spell.GetSpellName then return C_Spell.GetSpellName(id) or ("Заклинание "..id) end
 return (GetSpellInfo and GetSpellInfo(id)) or ("Заклинание "..id)
end
local function fallbackPower(s)
 if not s or not s.powers then return nil end
 local native=UnitPowerType and select(1,UnitPowerType("player")) or -1
 for _,kind in ipairs({0,1,3}) do if s.powers[kind] and kind~=native then return s.powers[kind] end end
 for _,kind in ipairs({0,1,3}) do if s.powers[kind] then return s.powers[kind] end end
 return nil
end
local function refresh()
 for _,row in ipairs(rows) do row.select:Hide(); row.cast:Hide() end
 if not state then return end
 local primary=names[state.primary] or tostring(state.primary)
 local active=names[state.active] or "нет"
 headline:SetText(primary.." + "..active.."   Слоты: "..state.used.."/"..state.budget..string.format("   %.1f%%",state.efficiency/100))
 local target=state.classes[state.xpTarget]
 if target then progress:SetText("XP → "..(names[state.xpTarget] or state.xpTarget)..": уровень "..target.level..", "..target.xp.."/"..target.next) else progress:SetText("") end
 for _,id in ipairs(classes) do
  local c=state.classes[id]; local text=names[id]..(c and (" ["..c.level.."]") or " [не изучен]")
  if id==selectedClass then text="> "..text end
  if id==state.primary then text=text.." •" end
  classButtons[id]:SetText(text)
 end
 local visible={}
 for _,s in pairs(state.spells) do table.insert(visible,s) end
 table.sort(visible,function(a,b) if a.level==b.level then return a.id<b.id end return a.level<b.level end)
 for index,s in ipairs(visible) do
  local spell=s; local row=rows[index]
  if not row then
   row={}; rows[index]=row
   row.select=button(content,"",0,-(index-1)*29,370,function() end)
   row.cast=button(content,"Каст",380,-(index-1)*29,95,function() end)
  end
  row.select:SetText((spell.selected and "[✓] " or "[ ] ")..spellName(spell.id).." — "..spell.cost)
  row.select:SetScript("OnClick",function() send((spell.selected and "remove " or "select ")..spell.id) end)
  row.cast:SetScript("OnClick",function() send("cast "..spell.id) end)
  row.cast:SetEnabled(spell.selected); row.select:Show(); row.cast:Show()
 end
 content:SetHeight(math.max(225,#visible*29))
 if _G.ForeverSubclassResourceHUD then power:Hide();return end
 local p=state.active~=0 and fallbackPower(state) or nil
 if p then
  power:SetMinMaxValues(0,math.max(1,p.max)); power:SetValue(p.current)
  if p.kind==1 then power:SetStatusBarColor(0.8,0.1,0.1) elseif p.kind==3 then power:SetStatusBarColor(0.72,0.60,0.10) else power:SetStatusBarColor(0.1,0.35,0.95) end
  power.text:SetText((powerNames[p.kind] or "Ресурс")..": "..p.current.."/"..p.max); power:Show()
 else power:Hide() end
end
frame.Refresh=refresh
frame:SetScript("OnShow",function() send("status") end)
local events=CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN"); events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent",function(_,event,prefix,text,channel,sender)
 if event=="PLAYER_LOGIN" then
  if not C_ChatInfo or not C_ChatInfo.RegisterAddonMessagePrefix then say("Нет API сообщений аддонов: эта сборка не поддержана."); return end
  C_ChatInfo.RegisterAddonMessagePrefix(REQUEST); C_ChatInfo.RegisterAddonMessagePrefix(RESPONSE)
  if ForeverSubclassUI then local p=ForeverSubclassUI; frame:ClearAllPoints();frame:SetPoint(p.point or "CENTER",UIParent,p.relative or "CENTER",p.x or 0,p.y or 0) end
  send("status");return
 end
 if prefix~=RESPONSE or channel~="WHISPER" then return end
 local name,realm=UnitFullName("player");local full=name.."-"..(realm or GetNormalizedRealmName())
 if sender~=name and sender~=full then return end
 local words={};for word in text:gmatch("%S+") do table.insert(words,word) end
 local kind=words[1]
 if kind=="ERROR" then say(errors[text:sub(7)] or text:sub(7));return end
 if kind=="STATE" then
  pending={primary=tonumber(words[2]),active=tonumber(words[3]),xpTarget=tonumber(words[4]),used=tonumber(words[5]),budget=tonumber(words[6]),efficiency=tonumber(words[7]) or 0,classes={},spells={},powers={}}
 elseif pending and kind=="CLASS" then pending.classes[tonumber(words[2])]={level=tonumber(words[3]),xp=tonumber(words[4]),next=tonumber(words[5])}
 elseif pending and kind=="POWER" then local k=tonumber(words[2]);if k then pending.powers[k]={kind=k,current=tonumber(words[3]) or 0,max=tonumber(words[4]) or 1} end
 elseif pending and kind=="SPELL" then
  local id=tonumber(words[2]);pending.spells[id]={id=id,root=tonumber(words[3]),level=tonumber(words[4]),selected=words[5]=="1",cost=tonumber(words[6]),power=tonumber(words[7])}
 elseif pending and kind=="END" then state=pending;pending=nil;refresh() end
end)
events:SetScript("OnUpdate",function()
 local now=GetTime()
 if now>=nextPoll then
  nextPoll=now+1.5
  if (frame:IsShown() or (state and state.active~=0)) and #queue==0 then send("status") end
 end
 if now<nextSend or #queue==0 or not C_ChatInfo or not C_ChatInfo.SendAddonMessage or not UnitName("player") then return end
 nextSend=now+0.20
 C_ChatInfo.SendAddonMessage(REQUEST,table.remove(queue,1),"WHISPER",UnitName("player"))
end)
SLASH_FOREVERSUBCLASS1="/fsub"
SlashCmdList["FOREVERSUBCLASS"]=function(text)
 if text and text:match("%S") then send(text) elseif frame:IsShown() then frame:Hide() else frame:Show() end
end
