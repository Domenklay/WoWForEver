-- Action-bar bridge for server-authoritative subclass abilities.
-- Native PickupSpell is preferred. If the client refuses an unlearned subclass
-- spell, a per-character macro is used only as transport; this module then makes
-- the action button look and behave like the represented spell.

local hooked=setmetatable({}, {__mode="k"})
local spellState={}
local localCooldowns={}
local RESPONSE="FSR1"
local function customInfo(id) return _G.ForeverSubclassCustomSpellInfo and _G.ForeverSubclassCustomSpellInfo[id] end

local function chat(msg)
 if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cff67d9ff[Подклассы]|r "..tostring(msg)) end
end
local function spellName(id)
 if customInfo(id) then return customInfo(id).name end
 if C_Spell and C_Spell.GetSpellName then return C_Spell.GetSpellName(id) or ("Заклинание "..id) end
 if GetSpellInfo then return GetSpellInfo(id) or ("Заклинание "..id) end
 return "Заклинание "..id
end
local function spellTexture(id)
 if customInfo(id) then id=customInfo(id).displayID;if not id then return 134400 end end
 if C_Spell and C_Spell.GetSpellTexture then return C_Spell.GetSpellTexture(id) or 134400 end
 if GetSpellTexture then return GetSpellTexture(id) or 134400 end
 return 134400
end
local function cast(id)
 id=tonumber(id);if not id then return end
 if _G.ForeverSubclassDirectSend then _G.ForeverSubclassDirectSend("cast "..id,true) else chat("Транспорт подклассов ещё не загружен.") end
end
_G.ForeverSubclassCast=cast

SLASH_FOREVERSUBCLASSCAST1="/fsubcast"
SlashCmdList["FOREVERSUBCLASSCAST"]=function(msg)
 local id=tonumber((msg or ""):match("^%s*(%d+)%s*$"))
 if not id then chat("Использование: /fsubcast SPELL_ID");return end
 cast(id)
end

local function cursorHasSpell()
 if CursorHasSpell then local ok,value=pcall(CursorHasSpell);if ok and value then return true end end
 if GetCursorInfo then local ok,kind=pcall(GetCursorInfo);if ok and kind=="spell" then return true end end
 if C_Cursor and C_Cursor.GetCursorInfo then local ok,info=pcall(C_Cursor.GetCursorInfo);if ok and info and (info.type=="spell" or info.kind=="spell") then return true end end
 return false
end

local function pickupNative(id)
 if not PickupSpell then return false end
 if ClearCursor then ClearCursor() end
 local ok=pcall(PickupSpell,id)
 if ok and cursorHasSpell() then return true end
 if ClearCursor then ClearCursor() end
 return false
end

local function macroBody(id)
 local info=customInfo(id);local display=info and info.displayID or (not info and id)
 return "#showtooltip"..(display and (" "..tostring(display)) or "").."\n/fsubcast "..tostring(id)
end
local function macroInternalName(id) return "FSub"..tostring(id) end

local function pickupFallback(id)
 if not CreateMacro or not PickupMacro or not GetMacroIndexByName then return false end
 local name=macroInternalName(id);local body=macroBody(id);local icon=spellTexture(id)
 local index=GetMacroIndexByName(name);local ok,result
 if not index or index==0 then ok,result=pcall(CreateMacro,name,icon,body,true);if ok then index=result end
 elseif EditMacro then pcall(EditMacro,index,name,icon,body) end
 if not index or index==0 then return false end
 if ClearCursor then ClearCursor() end
 return pcall(PickupMacro,index)
end

local function pickup(spell)
 if not spell or not spell.id then return end
 if InCombatLockdown and InCombatLockdown() then chat("Перетаскивать способности на панель можно только вне боя.");return end
 local id=tonumber(spell.id)
 if spell.custom and (not spell.selected or not spell.implemented) then chat("Кастомная способность пока недоступна.");return end
 if not spell.custom and pickupNative(id) then return end
 if pickupFallback(id) then chat("Способность добавлена на обычную панель действий.");return end
 chat("Не удалось взять способность на курсор.")
end
_G.ForeverSubclassPickupSpell=pickup

local function parseMacroSpell(index)
 if not index or not GetMacroBody then return nil end
 local body=GetMacroBody(index);if not body then return nil end
 return tonumber(tostring(body):match("/fsubcast%s+(%d+)"))
end

local function actionSlot(button)
 if not button then return nil end
 if ActionButton_GetPagedID then local ok,value=pcall(ActionButton_GetPagedID,button);if ok and value then return value end end
 return button.action
end

local function getButtonSpell(button)
 local slot=actionSlot(button);if not slot or not GetActionInfo then return nil end
 local kind,id=GetActionInfo(slot)
 if kind~="macro" then return nil end
 return parseMacroSpell(id)
end

local function queryNativeCooldown(id)
 if customInfo(id) then id=customInfo(id).displayID;if not id then return nil,nil end end
 if C_Spell and C_Spell.GetSpellCooldown then
  local ok,info=pcall(C_Spell.GetSpellCooldown,id)
  if ok and info and (info.duration or 0)>0 then return info.startTime or 0,info.duration or 0 end
 end
 if GetSpellCooldown then
  local ok,start,duration=pcall(GetSpellCooldown,id)
  if ok and duration and duration>0 then return start or 0,duration end
 end
 return nil,nil
end

local function setCooldown(button,id)
 if not button or not id then return end
 if not button._fsubCooldown then
  button._fsubCooldown=CreateFrame("Cooldown",nil,button,"CooldownFrameTemplate")
  local anchor=button.icon or button.Icon or button
  button._fsubCooldown:SetAllPoints(anchor)
  button._fsubCooldown:SetFrameLevel((button.GetFrameLevel and button:GetFrameLevel() or 1)+8)
 end
 local start,duration=queryNativeCooldown(id)
 local cached=localCooldowns[id]
 local now=GetTime and GetTime() or 0
 if (not duration or duration<=0) and cached and cached.start+cached.duration>now then start,duration=cached.start,cached.duration end
 if duration and duration>0 then
  if button._fsubCooldown.SetCooldown then button._fsubCooldown:SetCooldown(start or 0,duration) end
  button._fsubCooldown:Show()
 else
  if button._fsubCooldown.Clear then button._fsubCooldown:Clear() end
  button._fsubCooldown:Hide()
 end
end

local function showTooltip(button,id)
 if not GameTooltip or not id then return end
 GameTooltip:SetOwner(button,"ANCHOR_RIGHT")
 GameTooltip:ClearLines()
 if customInfo(id) then
  GameTooltip:SetText(customInfo(id).name);GameTooltip:AddLine(customInfo(id).description,0.88,0.88,0.88,true)
 elseif GameTooltip.SetSpellByID then
  local ok=pcall(GameTooltip.SetSpellByID,GameTooltip,id)
  if not ok then GameTooltip:SetText(spellName(id)) end
 else GameTooltip:SetText(spellName(id)) end
 local sp=spellState[id]
 if sp then
  GameTooltip:AddLine(" ")
  GameTooltip:AddLine(sp.custom and "Способность Freepick" or "Способность подкласса",0.45,0.82,1,true)
  GameTooltip:AddLine("Уровень "..tostring(sp.level or 1)..(sp.custom and "" or ("   Стоимость: "..tostring(sp.cost or 0))),0.78,0.78,0.78,true)
 end
 GameTooltip:Show()
end

local function decorate(button)
 if not button then return end
 local id=getButtonSpell(button)
 button._fsubSpellId=id
 if not id then
  if button._fsubCooldown then button._fsubCooldown:Hide() end
  return
 end
 local icon=button.icon or button.Icon
 if icon and icon.SetTexture then icon:SetTexture(spellTexture(id)) end
 local nameRegion=button.Name or button.name
 if nameRegion and nameRegion.SetText then nameRegion:SetText(spellName(id)) end
 setCooldown(button,id)
 if not hooked[button] and button.HookScript then
  hooked[button]=true
  button:HookScript("OnEnter",function(self) if self._fsubSpellId then showTooltip(self,self._fsubSpellId) end end)
  button:HookScript("OnLeave",function() if GameTooltip then GameTooltip:Hide() end end)
 end
end

local buttonPrefixes={"ActionButton","MultiBarBottomLeftButton","MultiBarBottomRightButton","MultiBarRightButton","MultiBarLeftButton","MultiBar5Button","MultiBar6Button","MultiBar7Button"}
local function scanButtons()
 for _,prefix in ipairs(buttonPrefixes) do
  for i=1,12 do local b=_G[prefix..i];if b then decorate(b) end end
 end
end

_G.ForeverSubclassCooldownStart=function(spellId)
 local id=tonumber(spellId);if not id then return end
 local start,duration=queryNativeCooldown(id)
 if not duration or duration<=0 then
  local ms=GetSpellBaseCooldown and GetSpellBaseCooldown(id) or 0
  if ms and ms>0 then start=GetTime and GetTime() or 0;duration=ms/1000 end
 end
 if duration and duration>0 then localCooldowns[id]={start=start or (GetTime and GetTime() or 0),duration=duration} end
 scanButtons()
end
_G.ForeverSubclassCooldownSync=function(spellId)
 local id=tonumber(spellId);if not id then return end
 local start,duration=queryNativeCooldown(id)
 if duration and duration>0 then localCooldowns[id]={start=start,duration=duration}
 elseif localCooldowns[id] and (localCooldowns[id].start+localCooldowns[id].duration)<(GetTime and GetTime() or 0) then localCooldowns[id]=nil end
 scanButtons()
end

local pending
local function parse(msg)
 local w={};for token in tostring(msg):gmatch("%S+") do table.insert(w,token) end
 if w[1]=="STATE" then pending={spells={}}
 elseif w[1]=="SPELL" and pending then
  local id=tonumber(w[2]);if id then pending.spells[id]={id=id,root=tonumber(w[3]),level=tonumber(w[4]) or 1,selected=w[5]=="1",cost=tonumber(w[6]) or 0,power=tonumber(w[7])} end
 elseif w[1]=="CUSTOM" and pending then
  local id=tonumber(w[2]);if id then pending.spells[id]={id=id,root=id,custom=true,level=tonumber(w[3]) or 10,selected=w[4]=="1",implemented=w[10]=="1",cost=0,power=0} end
 elseif w[1]=="END" and pending then spellState=pending.spells;pending=nil;scanButtons() end
end

local events=CreateFrame("Frame")
for _,event in ipairs({"PLAYER_LOGIN","PLAYER_ENTERING_WORLD","ACTIONBAR_SLOT_CHANGED","UPDATE_MACROS","ACTIONBAR_PAGE_CHANGED","CHAT_MSG_ADDON"}) do events:RegisterEvent(event) end
events:SetScript("OnEvent",function(_,event,...)
 if event=="CHAT_MSG_ADDON" then local prefix,msg=...;if prefix==RESPONSE then parse(msg) end;return end
 if C_Timer and C_Timer.After then C_Timer.After(0.1,scanButtons);C_Timer.After(0.8,scanButtons) else scanButtons() end
end)

if hooksecurefunc then
 if _G.ActionButton_Update then hooksecurefunc("ActionButton_Update",function(button) if button then decorate(button) end end) end
 if _G.ActionButton_UpdateAction then hooksecurefunc("ActionButton_UpdateAction",function(button) if button then decorate(button) end end) end
end
