local panel,toggle
local rows={}
local function number(value)
 if type(value)=="string" then return value end
 if type(value)~="number" then return "-" end
 if value==math.floor(value) then return tostring(value) end
 return string.format("%.1f",value)
end
local function call(fn,...)
 if type(fn)~="function" then return nil end
 return fn(...)
end
local function resource(power)
 if not ForeverAscensionResourceValue then return "-" end
 local current,maximum=ForeverAscensionResourceValue(power)
 return current and (number(current).." / "..number(maximum)) or "-"
end
local function stat(id)
 local base,effective=call(UnitStat,"player",id);return effective or base
end
local function attack(fn)
 local base,positive,negative=call(fn,"player")
 return base and base+(positive or 0)+(negative or 0)
end
local function percent(fn,...)
 local value=call(fn,...);return value and (number(value).."%") or "-"
end
local function damage(fn)
 local low,high=call(fn,"player");return low and (number(math.floor(low)).."-"..number(math.ceil(high or low)))
end
local function rating(id,fn)
 local base=call(fn);local bonus=id and call(GetCombatRatingBonus,id)
 if base==nil and bonus==nil then return nil end
 return number((base or 0)+(bonus or 0)).."%"
end
local sections={
 {"Ресурсы",{
  {"Здоровье",function() local current,maximum=call(UnitHealth,"player"),call(UnitHealthMax,"player");return current and (number(current).." / "..number(maximum)) end},
  {"Мана",function() return resource(0) end},{"Энергия",function() return resource(3) end},{"Ярость",function() return resource(1) end},
 }},
 {"Основные характеристики",{
  {"Сила",function() return stat(1) end},{"Ловкость",function() return stat(2) end},{"Выносливость",function() return stat(3) end},
  {"Интеллект",function() return stat(4) end},{"Дух",function() return stat(5) end},
 }},
 {"Ближний бой",{
  {"Урон",function() return damage(UnitDamage) end},{"Скорость оружия",function() return call(UnitAttackSpeed,"player") end},
  {"Сила атаки",function() return attack(UnitAttackPower) end},{"Меткость",function() return rating(CR_HIT_MELEE,GetHitModifier) end},
  {"Критический удар",function() return percent(GetCritChance) end},{"Мастерство",function() return call(GetExpertise) end},
 }},
 {"Дальний бой",{
  {"Урон",function() local _,low,high=call(UnitRangedDamage,"player");return low and (number(math.floor(low)).."-"..number(math.ceil(high or low))) end},
  {"Скорость оружия",function() return call(UnitRangedDamage,"player") end},{"Сила атаки",function() return attack(UnitRangedAttackPower) end},
  {"Меткость",function() return rating(CR_HIT_RANGED,GetHitModifier) end},{"Критический удар",function() return percent(GetRangedCritChance) end},
 }},
 {"Заклинания",{
  {"Сила заклинаний",function() if not GetSpellBonusDamage then return nil end;local maximum=0;for school=2,7 do maximum=math.max(maximum,GetSpellBonusDamage(school) or 0) end;return maximum end},
  {"Бонус лечения",function() return call(GetSpellBonusHealing) end},{"Меткость",function() return rating(CR_HIT_SPELL,GetSpellHitModifier) end},
  {"Критический удар",function() return percent(GetSpellCritChance,2) end},{"Скорость",function() return percent(GetHaste) end},
  {"Мана / сек.",function() if ForeverAscensionManaRegen then return ForeverAscensionManaRegen(false) end;return call(GetManaRegen) end},
  {"Мана / сек. в бою",function() if ForeverAscensionManaRegen then return ForeverAscensionManaRegen(true) end;local _,combat=call(GetManaRegen);return combat end},
 }},
 {"Защита",{
  {"Броня",function() local base,effective=call(UnitArmor,"player");return effective or base end},
  {"Навык защиты",function() local base,bonus=call(UnitDefense,"player");return base and base+(bonus or 0) end},
  {"Уклонение",function() return percent(GetDodgeChance) end},{"Парирование",function() return percent(GetParryChance) end},
  {"Блокирование",function() return percent(GetBlockChance) end},
  {"Устойчивость",function() return CR_RESILIENCE_CRIT_TAKEN and call(GetCombatRating,CR_RESILIENCE_CRIT_TAKEN) end},
 }},
 {"Сопротивления",{}},
}
for index,title in ipairs({"Свет","Огонь","Природа","Лёд","Тьма","Тайная магия"}) do
 local school=index
 table.insert(sections[#sections][2],{title,function() local base,effective=call(UnitResistance,"player",school);return effective or base end})
end
local function refresh()
 if not panel or not panel:IsShown() then return end
 for _,row in ipairs(rows) do row.value:SetText(number(row.read())) end
end
local function build()
 if panel then return true end
 if not CharacterFrame then return false end
 panel=CreateFrame("Frame","ForeverAscensionCharacterStats",CharacterFrame,BackdropTemplateMixin and "BackdropTemplate" or nil)
 panel:SetSize(285,610);panel:SetPoint("TOPLEFT",CharacterFrame,"TOPRIGHT",-8,-18)
 panel:SetFrameLevel((CharacterFrame.GetFrameLevel and CharacterFrame:GetFrameLevel() or 1)+4)
 if panel.SetBackdrop then
  panel:SetBackdrop({bgFile="Interface\\DialogFrame\\UI-DialogBox-Background",edgeFile="Interface\\DialogFrame\\UI-DialogBox-Border",tile=true,tileSize=32,edgeSize=24,insets={left=6,right=6,top=6,bottom=6}})
  panel:SetBackdropColor(0.08,0.06,0.035,0.98)
 end
 local title=panel:CreateFontString(nil,"OVERLAY","GameFontNormalLarge");title:SetPoint("TOP",0,-16);title:SetText("Все характеристики")
 local scroll=CreateFrame("ScrollFrame",nil,panel);scroll:SetPoint("TOPLEFT",10,-45);scroll:SetPoint("BOTTOMRIGHT",-10,12)
 local canvas=CreateFrame("Frame",nil,scroll);canvas:SetSize(265,1000);scroll:SetScrollChild(canvas);scroll:EnableMouseWheel(true)
 scroll:SetScript("OnMouseWheel",function(self,delta) self:SetVerticalScroll(math.max(0,math.min(math.max(0,canvas:GetHeight()-550),(self:GetVerticalScroll() or 0)-delta*34))) end)
 local y=-4
 for _,section in ipairs(sections) do
  local header=canvas:CreateFontString(nil,"OVERLAY","GameFontNormal");header:SetPoint("TOPLEFT",18,y);header:SetText(section[1]);y=y-24
  for _,entry in ipairs(section[2]) do
   local label=canvas:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall");label:SetPoint("TOPLEFT",18,y);label:SetText(entry[1])
   local value=canvas:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall");value:SetPoint("TOPRIGHT",-18,y)
   table.insert(rows,{title=entry[1],read=entry[2],value=value});y=y-17
  end
  y=y-10
 end
 canvas:SetHeight(-y+14);panel:Hide()
 toggle=CreateFrame("Button","ForeverAscensionStatsToggle",CharacterFrame,"UIPanelButtonTemplate")
 toggle:SetSize(145,22);toggle:SetPoint("TOPRIGHT",-24,-32);toggle:SetText("Все характеристики")
 toggle:SetScript("OnClick",function() if panel:IsShown() then panel:Hide() else panel:Show();refresh() end end)
 if CharacterFrame.HookScript then CharacterFrame:HookScript("OnHide",function() panel:Hide() end) end
 ForeverAscensionStatRows=rows
 return true
end
local events=CreateFrame("Frame")
for _,event in ipairs({"PLAYER_LOGIN","ADDON_LOADED","UNIT_STATS","UNIT_AURA","UNIT_ATTACK_POWER","UNIT_RANGED_ATTACK_POWER","UNIT_RESISTANCES","UNIT_MAXHEALTH","UNIT_POWER_UPDATE","COMBAT_RATING_UPDATE","PLAYER_EQUIPMENT_CHANGED"}) do events:RegisterEvent(event) end
events:SetScript("OnEvent",function() build();refresh() end)
events:SetScript("OnUpdate",function(self,elapsed) self.elapsed=(self.elapsed or 0)+elapsed;if self.elapsed>=0.5 then self.elapsed=0;build();refresh() end end)
