-- Keep the subclass page independent from Blizzard's TalentsFrame hit-test tree.
-- The page is parented to PlayerSpellsFrame and anchored only over the content area
-- below the native tab strip. No native frames are hidden/reparented and no extreme
-- frame levels/strata are used.

local applied=false

local function apply()
 local owner=_G.PlayerSpellsFrame
 local host=owner and owner.TalentsFrame
 local panel=_G.ForeverSubclassTalentPanel
 if not owner or not host or not panel then return false end

 if panel:GetParent()~=owner then panel:SetParent(owner) end
 panel:ClearAllPoints()
 panel:SetPoint("TOPLEFT",host,"TOPLEFT",0,-44)
 panel:SetPoint("BOTTOMRIGHT",host,"BOTTOMRIGHT",0,0)
 panel:SetFrameStrata("HIGH")
 panel:SetFrameLevel((owner.GetFrameLevel and owner:GetFrameLevel() or 100)+20)
 panel:EnableMouse(false)

 -- Interactive descendants keep their own mouse handling, while the root never
 -- blocks Primary/Secondary tabs or the close button above this rectangle.
 applied=true
 if _G.ForeverSubclassDebugAdd then
  _G.ForeverSubclassDebugAdd("TALENT_HOST parent=PlayerSpellsFrame level="..tostring(panel:GetFrameLevel()))
 end
 return true
end

local events=CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("PLAYER_ENTERING_WORLD")
events:RegisterEvent("ADDON_LOADED")
events:SetScript("OnEvent",function()
 if C_Timer and C_Timer.After then
  C_Timer.After(0,apply)
  C_Timer.After(0.5,apply)
  C_Timer.After(1.5,apply)
 else apply() end
end)
events:SetScript("OnUpdate",function(self,elapsed)
 self.elapsed=(self.elapsed or 0)+elapsed
 if self.elapsed<0.5 then return end
 self.elapsed=0
 if apply() and applied then self:SetScript("OnUpdate",nil) end
end)
