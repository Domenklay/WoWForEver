-- Use native spell APIs; no companion spellbook and no replacement action bar.
function ForeverAscensionPickupSpell(spell)
 if not spell or (InCombatLockdown and InCombatLockdown()) then return false end
 if C_Spell and C_Spell.PickupSpell then C_Spell.PickupSpell(spell);return true end
 if PickupSpell then PickupSpell(spell);return true end
 -- Older clients expose pickup by native book slot only.
 if GetSpellBookItemInfo and PickupSpellBookItem then
  for slot=1,1024 do
   local kind,id=GetSpellBookItemInfo(slot,BOOKTYPE_SPELL or "spell")
   if not kind then break end
   if id==spell then PickupSpellBookItem(slot,BOOKTYPE_SPELL or "spell");return true end
  end
 end
 return false
end
local micro
local function attach()
 local anchor=TalentMicroButton or PlayerSpellsMicroButton
 if not anchor or micro then return end
 micro=CreateFrame("Button","ForeverAscensionMicroButton",anchor)
 -- Keep the native bar's existing layout intact; this sits immediately above
 -- its talent button, rather than covering the adjacent quest button.
 micro:SetSize(28,32);micro:SetPoint("BOTTOM",anchor,"TOP",0,2)
 local icon=micro:CreateTexture(nil,"ARTWORK");icon:SetPoint("TOPLEFT",3,-3);icon:SetPoint("BOTTOMRIGHT",-3,3);icon:SetTexture("Interface\\Icons\\INV_Misc_Book_09")
 local border=micro:CreateTexture(nil,"OVERLAY");border:SetAllPoints();border:SetTexture("Interface\\Buttons\\UI-Quickslot2")
 micro:SetHighlightTexture("Interface\\Buttons\\ButtonHilight-Square","ADD")
 micro:SetScript("OnClick",function() if ForeverAscensionToggle then ForeverAscensionToggle() end end)
 micro:SetScript("OnEnter",function(self) if GameTooltip then GameTooltip:SetOwner(self,"ANCHOR_RIGHT");GameTooltip:SetText("Мультиклассы",1,0.82,0);GameTooltip:AddLine("Развитие персонажа (/fa)",1,1,1);GameTooltip:Show() end end)
 micro:SetScript("OnLeave",function() if GameTooltip then GameTooltip:Hide() end end)
end
local events=CreateFrame("Frame");events:RegisterEvent("PLAYER_LOGIN");events:RegisterEvent("ADDON_LOADED")
events:SetScript("OnEvent",attach)
