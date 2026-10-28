-- Clear tooltips that can remain orphaned when PlayerSpells/subclass pages are hidden
-- during a disconnect or rapid tab switch. This file never creates visual frames.

local hooked=setmetatable({}, {__mode="k"})

local function hideTooltip()
 if GameTooltip and GameTooltip.Hide then pcall(GameTooltip.Hide,GameTooltip) end
end

local function hook(frame)
 if not frame or hooked[frame] or not frame.HookScript then return end
 hooked[frame]=true
 frame:HookScript("OnHide",hideTooltip)
end

local function apply()
 hook(_G.PlayerSpellsFrame)
 hook(_G.ForeverSubclassTalentPanel)
 hook(_G.ForeverSubclassTalentTreePanel)
 hook(_G.ForeverSubclassSpellBookPanel)
end

local events=CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("PLAYER_ENTERING_WORLD")
events:RegisterEvent("ADDON_LOADED")
events:SetScript("OnEvent",function(_,event)
 if event=="PLAYER_ENTERING_WORLD" then hideTooltip() end
 apply()
 if C_Timer and C_Timer.After then C_Timer.After(0.5,apply);C_Timer.After(1.5,apply) end
end)
