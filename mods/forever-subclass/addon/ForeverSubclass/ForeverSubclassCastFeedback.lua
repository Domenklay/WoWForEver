-- Small transport wrapper: show virtual-resource spend immediately, then resync from server.
local installed=false
local function install()
 if installed or not _G.ForeverSubclassDirectSend then return false end
 installed=true
 local base=_G.ForeverSubclassDirectSend
 _G.ForeverSubclassDirectSend=function(payload,quiet)
  local spellId=type(payload)=="string" and payload:match("^cast%s+(%d+)$") or nil
  local ok=base(payload,quiet)
  if ok and spellId then
   if _G.ForeverSubclassResourcePredictSpend then _G.ForeverSubclassResourcePredictSpend(tonumber(spellId)) end
   if C_Timer and C_Timer.After then
    C_Timer.After(0.25,function() base("status",true) end)
    C_Timer.After(0.90,function() base("status",true) end)
   end
  end
  return ok
 end
 return true
end
local f=CreateFrame("Frame");f:RegisterEvent("PLAYER_LOGIN");f:RegisterEvent("ADDON_LOADED")
f:SetScript("OnEvent",function() if C_Timer and C_Timer.After then C_Timer.After(0,install);C_Timer.After(0.5,install) else install() end end)
f:SetScript("OnUpdate",function(self,elapsed) self.elapsed=(self.elapsed or 0)+elapsed;if self.elapsed<0.5 then return end;self.elapsed=0;if install() then self:SetScript("OnUpdate",nil) end end)
