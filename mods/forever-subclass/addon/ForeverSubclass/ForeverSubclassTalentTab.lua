-- Talent-window integration for ForeverSubclass.
-- This file is UI/transport only: the server remains authoritative for class progress,
-- spell permissions, resources and casts.

local REQUEST, RESPONSE = "FSC1", "FSR1"
local classes = {1,2,3,4,5,7,8,9,11}
local names = {[1]="Воин",[2]="Паладин",[3]="Охотник",[4]="Разбойник",[5]="Жрец",[7]="Шаман",[8]="Маг",[9]="Чернокнижник",[11]="Друид"}
local powerNames = {[0]="Мана",[1]="Ярость",[3]="Энергия"}
local errors = {
 ["module disabled or unsupported primary class"]="Серверный мод выключен или класс не поддержан.",
 ["primary class has not reached subclass unlock level"]="Подкласс открывается с 10-го уровня основного класса.",
 ["subclass can only be switched in a rest area"]="Смена подкласса разрешена в городе или таверне.",
 ["cannot edit in combat or while casting"]="Изменять подкласс в бою, после смерти или во время каста нельзя.",
 ["class has not been learned"]="Сначала изучите этот класс.",
 ["spell unavailable or not enough power"]="Способность не выбрана, уровень недостаточен или не хватает ресурса.",
 ["subclass level is too low for this spell"]="Уровень подкласса недостаточен.",
 ["not enough subclass ability slots"]="Не хватает слотов способностей.",
 ["no active subclass"]="Сначала активируйте подкласс.",
 ["select a target"]="Выберите цель.",
 ["saved primary class mismatch"]="Класс персонажа отличается от сохранённого: сообщите администратору.",
}

local state, pending
local selectedClass = 5
local queue, nextSend, nextPoll = {}, 0, 0
local host, tab, panel, scroll, content
local classButtons, rows = {}, {}
local headline, progress, notice, powerBar
local learnButton, activeButton, xpButton, clearButton
local installed = false
local nativeHooks = {}

local function say(text)
 if notice then notice:SetText(text or "") end
 if DEFAULT_CHAT_FRAME and text and text ~= "" then
  DEFAULT_CHAT_FRAME:AddMessage("|cff67d9ff[Подклассы]|r "..text)
 end
end

local function send(text)
 if not text or text == "" then return end
 if text == "status" then
  for _,v in ipairs(queue) do if v == "status" then return end end
 end
 if #queue < 8 then table.insert(queue,text) end
end

local function spellName(id)
 if C_Spell and C_Spell.GetSpellName then return C_Spell.GetSpellName(id) or ("Заклинание "..id) end
 if GetSpellInfo then return GetSpellInfo(id) or ("Заклинание "..id) end
 return "Заклинание "..id
end

local function spellTexture(id)
 if C_Spell and C_Spell.GetSpellTexture then return C_Spell.GetSpellTexture(id) end
 if GetSpellTexture then return GetSpellTexture(id) end
 return 134400
end

local function makeLabel(parent,point,relative,relativePoint,x,y,width,font)
 local f=parent:CreateFontString(nil,"OVERLAY",font or "GameFontNormal")
 f:SetPoint(point,relative,relativePoint,x,y)
 if width then f:SetWidth(width);f:SetJustifyH("LEFT") end
 return f
end

local function makeButton(parent,text,w,h,callback)
 local b=CreateFrame("Button",nil,parent,"UIPanelButtonTemplate")
 b:SetSize(w,h or 26);b:SetText(text or "")
 b:SetScript("OnClick",callback)
 return b
end

local function findHost()
 return _G.PlayerSpellsFrame or _G.ClassTalentFrame or _G.PlayerTalentFrame or _G.TalentFrame
end

local function loadTalentUI()
 if findHost() then return true end
 local loader = C_AddOns and C_AddOns.LoadAddOn or LoadAddOn
 if not loader then return false end
 for _,addon in ipairs({"Blizzard_PlayerSpells","Blizzard_ClassTalentUI","Blizzard_TalentUI"}) do
  pcall(loader,addon)
  if findHost() then return true end
 end
 return findHost() ~= nil
end

local function collectButtons(root,out,depth)
 if not root or depth > 5 or not root.GetChildren then return end
 local children={root:GetChildren()}
 for _,child in ipairs(children) do
  if child and child ~= tab then
   if child.GetObjectType and child:GetObjectType()=="Button" then table.insert(out,child) end
   collectButtons(child,out,depth+1)
  end
 end
end

local nativeTabText = {
 ["Основное"]=true,["Дополнительное"]=true,["Primary"]=true,["Secondary"]=true,
 ["Main"]=true,["Дополнительные"]=true,
}

local function deactivate()
 if panel then panel:Hide() end
 if tab then
  tab:SetEnabled(true)
  if PanelTemplates_DeselectTab then pcall(PanelTemplates_DeselectTab,tab) end
 end
end

local function positionTab()
 if not host or not tab then return end
 tab:ClearAllPoints()
 local buttons={};collectButtons(host,buttons,0)
 local anchor
 for _,b in ipairs(buttons) do
  local text
  if b.GetText then local ok,value=pcall(b.GetText,b);if ok then text=value end end
  if text and nativeTabText[text] then
   if not nativeHooks[b] and b.HookScript then
    nativeHooks[b]=true;b:HookScript("OnClick",deactivate)
   end
   local left=b.GetLeft and b:GetLeft()
   local best=anchor and anchor.GetLeft and anchor:GetLeft()
   if not anchor or (left and (not best or left>best)) then anchor=b end
  end
 end
 if anchor then tab:SetPoint("LEFT",anchor,"RIGHT",7,0)
 else tab:SetPoint("TOPLEFT",host,"TOPLEFT",370,-45) end
end

local function bestVisibleSpells(s)
 local result,best={},{}
 if not s or not s.active or s.active==0 then return result end
 local activeState=s.classes[s.active]
 if not activeState then return result end
 for _,spell in pairs(s.spells) do
  if spell.level<=activeState.level and (not best[spell.root] or best[spell.root].level<spell.level) then best[spell.root]=spell end
 end
 for _,spell in pairs(s.spells) do
  if (best[spell.root] and best[spell.root].id==spell.id) or spell.selected then table.insert(result,spell) end
 end
 table.sort(result,function(a,b)
  if a.level==b.level then return a.id<b.id end
  return a.level<b.level
 end)
 return result
end

local function refresh()
 if not panel or not panel:IsShown() then return end
 if not state then
  headline:SetText("Ожидание ответа сервера…")
  progress:SetText("")
  send("status")
  return
 end
 if selectedClass==state.primary and state.active and state.active~=0 then selectedClass=state.active end
 local primary=names[state.primary] or tostring(state.primary)
 local active=names[state.active] or "нет"
 headline:SetText(primary.."  +  "..active..string.format("     Эффективность: %.1f%%     Слоты: %d/%d",(state.efficiency or 0)/100,state.used or 0,state.budget or 0))
 local target=state.classes[state.xpTarget]
 if target then
  progress:SetText("Опыт направлен в «"..(names[state.xpTarget] or tostring(state.xpTarget)).."»: уровень "..target.level.."   "..target.xp.." / "..target.next)
 else progress:SetText("") end

 for _,id in ipairs(classes) do
  local c=state.classes[id]
  local text=(names[id] or id)..(c and ("  ур. "..c.level) or "  не изучен")
  if id==state.primary then text=text.."  • основной" end
  if id==state.active then text=text.."  • активен" end
  if id==state.xpTarget then text=text.."  • XP" end
  if id==selectedClass then text="> "..text end
  classButtons[id]:SetText(text)
 end

 local learned=state.classes[selectedClass]~=nil
 local isPrimary=selectedClass==state.primary
 local level=UnitLevel and UnitLevel("player") or 80
 learnButton:SetEnabled(level>=10 and not isPrimary and not learned)
 activeButton:SetEnabled(not isPrimary and learned)
 xpButton:SetEnabled(learned or isPrimary)
 clearButton:SetEnabled(state.active and state.active~=0)

 for _,row in ipairs(rows) do row.frame:Hide() end
 local visible=bestVisibleSpells(state)
 for index,spell in ipairs(visible) do
  local row=rows[index]
  if not row then
   row={};rows[index]=row
   row.frame=CreateFrame("Frame",nil,content)
   row.frame:SetSize(620,38);row.frame:SetPoint("TOPLEFT",0,-(index-1)*40)
   row.icon=row.frame:CreateTexture(nil,"ARTWORK");row.icon:SetSize(32,32);row.icon:SetPoint("LEFT",2,0)
   row.name=makeLabel(row.frame,"LEFT",row.icon,"RIGHT",8,7,285,"GameFontNormal")
   row.meta=makeLabel(row.frame,"LEFT",row.icon,"RIGHT",8,-9,285,"GameFontHighlightSmall")
   row.select=makeButton(row.frame,"Выбрать",95,25,function() end);row.select:SetPoint("RIGHT",-108,0)
   row.cast=makeButton(row.frame,"Каст",95,25,function() end);row.cast:SetPoint("RIGHT",-7,0)
  end
  local localSpell=spell
  row.icon:SetTexture(spellTexture(spell.id))
  row.name:SetText((spell.selected and "✓  " or "")..spellName(spell.id))
  row.meta:SetText("Требуется ур. "..spell.level.."   •   "..(powerNames[spell.power] or "Ресурс")..": "..spell.cost)
  row.select:SetText(spell.selected and "Убрать" or "Выбрать")
  row.select:SetScript("OnClick",function() send((localSpell.selected and "remove " or "select ")..localSpell.id) end)
  row.cast:SetScript("OnClick",function() send("cast "..localSpell.id) end)
  row.cast:SetEnabled(spell.selected)
  row.frame:Show()
 end
 content:SetHeight(math.max(220,#visible*40))

 if state.power and state.active and state.active~=0 then
  local p=state.power
  powerBar:SetMinMaxValues(0,math.max(1,p.max));powerBar:SetValue(p.current)
  if p.kind==1 then powerBar:SetStatusBarColor(0.75,0.12,0.12)
  elseif p.kind==3 then powerBar:SetStatusBarColor(0.85,0.72,0.10)
  else powerBar:SetStatusBarColor(0.10,0.35,0.90) end
  powerBar.text:SetText((powerNames[p.kind] or "Ресурс").."  "..p.current.." / "..p.max)
  powerBar:Show()
 else powerBar:Hide() end

 if level<10 then notice:SetText("Подкласс откроется на 10-м уровне основного класса.")
 elseif not state.active or state.active==0 then notice:SetText("Выберите класс слева, изучите его и активируйте. Опыт можно направлять отдельно.")
 else notice:SetText("Способности подкласса ограничены 8 слотами. Все расчёты и ресурсы проверяет сервер.") end
end

local function activate()
 if not panel then return end
 panel:Show();panel:Raise()
 if tab then
  tab:SetEnabled(false)
  if PanelTemplates_SelectTab then pcall(PanelTemplates_SelectTab,tab) end
 end
 send("status");refresh()
end

local function createPanel()
 local backdrop = BackdropTemplateMixin and "BackdropTemplate" or nil
 panel=CreateFrame("Frame","ForeverSubclassTalentPanel",host,backdrop)
 panel:SetPoint("TOPLEFT",host,"TOPLEFT",8,-83)
 panel:SetPoint("BOTTOMRIGHT",host,"BOTTOMRIGHT",-8,8)
 panel:SetFrameLevel((host.GetFrameLevel and host:GetFrameLevel() or 1)+80)
 if panel.SetBackdrop then
  panel:SetBackdrop({bgFile="Interface\\Tooltips\\UI-Tooltip-Background",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=true,tileSize=16,edgeSize=12,insets={left=3,right=3,top=3,bottom=3}})
  panel:SetBackdropColor(0.025,0.025,0.025,0.98)
  panel:SetBackdropBorderColor(0.45,0.35,0.18,1)
 end
 panel:EnableMouse(true)

 headline=makeLabel(panel,"TOPLEFT",panel,"TOPLEFT",18,-16,900,"GameFontNormalLarge")
 progress=makeLabel(panel,"TOPLEFT",panel,"TOPLEFT",18,-43,900,"GameFontHighlight")
 makeLabel(panel,"TOPLEFT",panel,"TOPLEFT",18,-74,420,"GameFontNormal"):SetText("Классы")
 makeLabel(panel,"TOPLEFT",panel,"TOPLEFT",482,-74,600,"GameFontNormal"):SetText("Способности активного подкласса")

 for index,id in ipairs(classes) do
  local classId=id
  local b=makeButton(panel,names[id],142,30,function() selectedClass=classId;refresh() end)
  local col=(index-1)%3;local row=math.floor((index-1)/3)
  b:SetPoint("TOPLEFT",18+col*146,-98-row*34)
  classButtons[id]=b
 end

 learnButton=makeButton(panel,"Изучить",103,27,function() send("learn "..selectedClass) end);learnButton:SetPoint("TOPLEFT",18,-207)
 activeButton=makeButton(panel,"Активировать",103,27,function() send("active "..selectedClass) end);activeButton:SetPoint("LEFT",learnButton,"RIGHT",7,0)
 xpButton=makeButton(panel,"XP сюда",103,27,function() send("xp "..selectedClass) end);xpButton:SetPoint("LEFT",activeButton,"RIGHT",7,0)
 clearButton=makeButton(panel,"Отключить",103,27,function() send("clear") end);clearButton:SetPoint("LEFT",xpButton,"RIGHT",7,0)

 local help=makeLabel(panel,"TOPLEFT",panel,"TOPLEFT",18,-245,425,"GameFontHighlightSmall")
 help:SetText("Основной класс и его броня не меняются. Подкласс получает свой уровень, ресурс и выбранные способности.")

 powerBar=CreateFrame("StatusBar",nil,panel)
 powerBar:SetPoint("TOPLEFT",18,-294);powerBar:SetSize(425,22)
 powerBar:SetStatusBarTexture("Interface\\TARGETINGFRAME\\UI-StatusBar")
 powerBar.text=powerBar:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall");powerBar.text:SetPoint("CENTER")
 powerBar:Hide()

 scroll=CreateFrame("ScrollFrame","ForeverSubclassTalentScroll",panel,"UIPanelScrollFrameTemplate")
 scroll:SetPoint("TOPLEFT",482,-98);scroll:SetPoint("BOTTOMRIGHT",-34,58)
 content=CreateFrame("Frame",nil,scroll);content:SetSize(620,220);scroll:SetScrollChild(content)

 notice=makeLabel(panel,"BOTTOMLEFT",panel,"BOTTOMLEFT",18,18,1040,"GameFontHighlightSmall")
 panel:SetScript("OnShow",function() nextPoll=0;send("status") end)
 panel:Hide()
end

local function createTab()
 local ok,created=pcall(CreateFrame,"Button","ForeverSubclassTalentTab",host,"PanelTopTabButtonTemplate")
 if not ok or not created then created=CreateFrame("Button","ForeverSubclassTalentTab",host,"UIPanelButtonTemplate") end
 tab=created;tab:SetSize(145,30);tab:SetText("Подкласс")
 tab:SetScript("OnClick",activate)
 positionTab()
end

local function attach()
 if installed then return true end
 host=findHost();if not host then return false end
 createPanel();createTab();installed=true
 if host.HookScript then
  host:HookScript("OnShow",function() positionTab() end)
  host:HookScript("OnHide",deactivate)
 end
 positionTab()
 return true
end

local function openTalentTab()
 if not findHost() then loadTalentUI() end
 if not attach() then return false end
 if not host:IsShown() then
  if _G.PlayerSpellsFrame_Toggle then pcall(_G.PlayerSpellsFrame_Toggle)
  elseif _G.ToggleTalentFrame then pcall(_G.ToggleTalentFrame)
  elseif _G.PlayerTalentFrame_Toggle then pcall(_G.PlayerTalentFrame_Toggle)
  elseif ShowUIPanel then pcall(ShowUIPanel,host)
  else host:Show() end
 end
 positionTab();activate();return true
end

_G.ForeverSubclassOpenTalentTab=openTalentTab

-- Keep direct /fsub commands from the legacy transport, but make plain /fsub open
-- the talent tab. If this client build exposes no supported talent host, fall back
-- to the original standalone window.
local legacySlash=SlashCmdList and SlashCmdList["FOREVERSUBCLASS"]
if SlashCmdList and legacySlash then
 SlashCmdList["FOREVERSUBCLASS"]=function(text)
  if text and text:match("%S") then return legacySlash(text) end
  if not openTalentTab() then return legacySlash("") end
 end
end

local events=CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN");events:RegisterEvent("ADDON_LOADED");events:RegisterEvent("CHAT_MSG_ADDON")
events:SetScript("OnEvent",function(_,event,...)
 if event=="PLAYER_LOGIN" then
  if C_ChatInfo and C_ChatInfo.RegisterAddonMessagePrefix then C_ChatInfo.RegisterAddonMessagePrefix(REQUEST);C_ChatInfo.RegisterAddonMessagePrefix(RESPONSE) end
  attach();return
 end
 if event=="ADDON_LOADED" then attach();return end
 local prefix,text,channel,sender=...
 if prefix~=RESPONSE or channel~="WHISPER" then return end
 local name,realm=UnitFullName("player");local full=name.."-"..(realm or GetNormalizedRealmName())
 if sender~=name and sender~=full then return end
 local words={};for word in text:gmatch("%S+") do table.insert(words,word) end
 local kind=words[1]
 if kind=="ERROR" then say(errors[text:sub(7)] or text:sub(7));return end
 if kind=="STATE" then
  pending={primary=tonumber(words[2]),active=tonumber(words[3]),xpTarget=tonumber(words[4]),used=tonumber(words[5]) or 0,budget=tonumber(words[6]) or 8,efficiency=tonumber(words[7]) or 0,classes={},spells={}}
 elseif pending and kind=="CLASS" then pending.classes[tonumber(words[2])]={level=tonumber(words[3]),xp=tonumber(words[4]),next=tonumber(words[5])}
 elseif pending and kind=="POWER" then pending.power={kind=tonumber(words[2]),current=tonumber(words[3]),max=tonumber(words[4])}
 elseif pending and kind=="SPELL" then
  local id=tonumber(words[2]);pending.spells[id]={id=id,root=tonumber(words[3]),level=tonumber(words[4]),selected=words[5]=="1",cost=tonumber(words[6]),power=tonumber(words[7])}
 elseif pending and kind=="END" then state=pending;pending=nil;refresh() end
end)

events:SetScript("OnUpdate",function()
 local now=GetTime()
 if installed and panel and panel:IsShown() and now>=nextPoll then nextPoll=now+1.75;send("status") end
 if now<nextSend or #queue==0 or not C_ChatInfo or not C_ChatInfo.SendAddonMessage or not UnitName("player") then return end
 nextSend=now+0.20
 C_ChatInfo.SendAddonMessage(REQUEST,table.remove(queue,1),"WHISPER",UnitName("player"))
end)
