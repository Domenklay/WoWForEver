-- Keep the addon-owned subclass surface above Blizzard's native talent nodes.
-- The panel starts below the native tab strip, so raising only this subtree cannot
-- cover Primary/Secondary tabs or the PlayerSpellsFrame close button.

local applied=false

local function liftTree(frame,base,depth)
 if not frame or depth>8 then return end
 if frame.SetFrameLevel then pcall(frame.SetFrameLevel,frame,math.min(9950,base+depth*8)) end
 if frame.GetChildren then
  for _,child in ipairs({frame:GetChildren()}) do liftTree(child,base,depth+1) end
 end
end

local function apply()
 local host=_G.PlayerSpellsFrame and _G.PlayerSpellsFrame.TalentsFrame
 local panel=_G.ForeverSubclassTalentPanel
 if not host or not panel then return false end
 local hostLevel=(host.GetFrameLevel and host:GetFrameLevel()) or 100
 -- Native Forever talent nodes have much higher levels than TalentsFrame itself.
 -- 3000 is above those nodes but safely below the 10000 ceiling that previously
 -- caused the whole PlayerSpellsFrame to become unclickable.
 local base=math.min(9000,math.max(3000,hostLevel+2000))
 if panel.SetFrameStrata and host.GetFrameStrata then panel:SetFrameStrata(host:GetFrameStrata()) end
 if panel.SetFrameLevel then panel:SetFrameLevel(base) end
 panel:EnableMouse(false)
 liftTree(panel,base,0)

 local tree=_G.ForeverSubclassTalentTreePanel
 if tree then liftTree(tree,base+300,0) end
 local pet=_G.ForeverSubclassHunterPetPanel
 if pet then liftTree(pet,base+200,0) end

 applied=true
 if _G.ForeverSubclassDebugAdd then
  _G.ForeverSubclassDebugAdd("TALENT_LAYER base="..tostring(base).." panel="..tostring(panel:GetFrameLevel()))
 end
 return true
end

local events=CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
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
