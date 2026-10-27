-- Action-bar bridge for server-authoritative subclass abilities.
-- Preferred path: selected abilities are true TrinityCore temporary spells, so PickupSpell
-- creates an ordinary WoW action button. Macro/FSC1 remains a compatibility fallback.

local hooked=setmetatable({}, {__mode="k"})

local function chat(msg)
 if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cff67d9ff[Подклассы]|r "..tostring(msg)) end
end
local function spellName(id)
 if C_Spell and C_Spell.GetSpellName then return C_Spell.GetSpellName(id) or ("Заклинание "..id) end
 if GetSpellInfo then return GetSpellInfo(id) or ("Заклинание "..id) end
 return "Заклинание "..id
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
 if ok and cursorHasSpell() then
  if _G.ForeverSubclassDebugAdd then _G.ForeverSubclassDebugAdd("ACTIONBAR native PickupSpell="..id) end
  return true
 end
 if ClearCursor then ClearCursor() end
 return false
end

local function pickupFallback(id)
 if not CreateMacro or not PickupMacro or not GetMacroIndexByName then return false end
 local display=spellName(id);local name="FSub"..tostring(id)
 local body="#showtooltip "..display.."\n/fsubcast "..tostring(id)
 local icon="INV_MISC_QUESTIONMARK"
 local index=GetMacroIndexByName(name);local ok,result
 if not index or index==0 then ok,result=pcall(CreateMacro,name,icon,body,true);if ok then index=result end
 else if EditMacro then pcall(EditMacro,index,name,icon,body) end end
 if not index or index==0 then return false end
 if ClearCursor then ClearCursor() end
 local picked=pcall(PickupMacro,index)
 if picked and _G.ForeverSubclassDebugAdd then _G.ForeverSubclassDebugAdd("ACTIONBAR fallback macro spell="..id.." macro="..tostring(index)) end
 return picked
end

local function pickup(spell)
 if not spell or not spell.id then return end
 if InCombatLockdown and InCombatLockdown() then chat("Перетаскивать способности на панель можно только вне боя.");return end
 local id=tonumber(spell.id)
 if pickupNative(id) then return end
 if pickupFallback(id) then
  chat("Клиент ещё не увидел временный спелл; использован резервный ярлык.")
  return
 end
 chat("Не удалось взять способность на курсор.")
end

local function wireButton(button)
 if not button or hooked[button] or not button.spell then return end
 hooked[button]=true
 if button.RegisterForDrag then button:RegisterForDrag("LeftButton") end
 button:SetScript("OnDragStart",function(self) pickup(self.spell) end)
 if button.HookScript then button:HookScript("OnEnter",function(self)
  if self.spell and GameTooltip then
   GameTooltip:AddLine(" ");GameTooltip:AddLine("Перетащите на обычную панель действий",0.35,0.85,1,true)
   GameTooltip:AddLine("Используется обычный временный WoW-спелл; ярлык — только резерв.",0.7,0.7,0.7,true);GameTooltip:Show()
  end
 end) end
end

local function scan()
 local panel=_G.ForeverSubclassSpellBookPanel;if not panel then return false end
 if panel.GetChildren then for _,child in ipairs({panel:GetChildren()}) do if child and child.GetObjectType and child:GetObjectType()=="Button" and child.spell then wireButton(child) end end end
 return true
end
local events=CreateFrame("Frame");events:RegisterEvent("PLAYER_LOGIN");events:RegisterEvent("ADDON_LOADED")
events:SetScript("OnEvent",function() if C_Timer and C_Timer.After then C_Timer.After(0.5,scan);C_Timer.After(1.5,scan);C_Timer.After(3,scan) else scan() end end)
events:SetScript("OnUpdate",function(self,elapsed) self.elapsed=(self.elapsed or 0)+elapsed;if self.elapsed<0.5 then return end;self.elapsed=0;scan() end)
