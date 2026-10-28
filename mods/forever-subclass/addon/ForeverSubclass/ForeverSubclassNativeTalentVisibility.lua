-- Hide Blizzard talent-tree content while the addon-owned subclass page is visible.
-- This avoids frame-level escalation: native tabs stay usable, native tree body is restored on exit.

local hidden=setmetatable({}, {__mode="k"})

local function buttonText(frame)
 if not frame or not frame.GetText then return nil end
 local ok,text=pcall(frame.GetText,frame)
 return ok and text and tostring(text) or nil
end

local function isNativeTab(frame)
 local text=buttonText(frame)
 if not text then return false end
 return text:find("Основное",1,true) or text:find("Дополнительное",1,true)
     or text:find("Primary",1,true) or text:find("Secondary",1,true)
end

local function containsNativeTab(frame,depth)
 if not frame or depth>5 then return false end
 if isNativeTab(frame) then return true end
 if frame.GetChildren then
  for _,child in ipairs({frame:GetChildren()}) do
   if containsNativeTab(child,depth+1) then return true end
  end
 end
 return false
end

local function shouldKeep(child,panel,tab)
 if child==panel or child==tab then return true end
 local name=child.GetName and child:GetName() or nil
 if name=="ForeverSubclassTalentPanel" or name=="ForeverSubclassTalentTab" then return true end
 return containsNativeTab(child,0)
end

local function hideNativeBody()
 local host=_G.PlayerSpellsFrame and _G.PlayerSpellsFrame.TalentsFrame
 local panel=_G.ForeverSubclassTalentPanel
 local tab=_G.ForeverSubclassTalentTab
 if not host or not panel or not panel:IsShown() or not host.GetChildren then return false end
 for _,child in ipairs({host:GetChildren()}) do
  if child and child.IsShown and child.Hide and child:IsShown() and not shouldKeep(child,panel,tab) then
   hidden[child]=true
   child:Hide()
  end
 end
 return true
end

local function restoreNativeBody()
 for child in pairs(hidden) do
  if child and child.Show then pcall(child.Show,child) end
  hidden[child]=nil
 end
end

local watcher=CreateFrame("Frame")
watcher:RegisterEvent("PLAYER_LOGIN")
watcher:RegisterEvent("PLAYER_ENTERING_WORLD")
watcher:SetScript("OnEvent",function()
 restoreNativeBody()
end)
watcher:SetScript("OnUpdate",function(self,elapsed)
 self.elapsed=(self.elapsed or 0)+elapsed
 if self.elapsed<0.15 then return end
 self.elapsed=0
 local panel=_G.ForeverSubclassTalentPanel
 if panel and panel:IsShown() then hideNativeBody() else restoreNativeBody() end
end)
