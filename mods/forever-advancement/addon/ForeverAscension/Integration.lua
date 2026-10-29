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
local micro,talentHost,talentButton
local function attach()
 if InCombatLockdown and InCombatLockdown() then return end
 local anchor=TalentMicroButton or PlayerSpellsMicroButton
 if anchor and not micro then
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
 -- 70532 owns its modern talents in anonymous child panels. A button on
 -- one of those panels can be hidden even while the root is visible.
 local frame=PlayerSpellsFrame or PlayerTalentFrame or TalentFrame or ClassTalentFrame or ClassicTalentFrame
 if frame and frame~=talentHost then
  if talentButton then talentButton:Hide() end
  talentHost=frame
  talentButton=CreateFrame("Button",nil,frame,"UIPanelButtonTemplate")
  talentButton:SetSize(146,24);talentButton:SetText("Мультикласс")
  talentButton:EnableMouse(true);talentButton:SetEnabled(true);talentButton:RegisterForClicks("LeftButtonUp")
  talentButton:SetFrameStrata("DIALOG");talentButton:SetFrameLevel(frame:GetFrameLevel()+100)
  local search
  for _,key in ipairs({"SearchBox","SearchEditBox","SearchBar","SearchContainer"}) do
   local candidate=frame[key]
   if (type(candidate)=="table" or type(candidate)=="userdata") and type(candidate.GetObjectType)=="function" then search=candidate;break end
  end
  if not search then search=PlayerTalentFrameSearchBox or TalentFrameSearchBox end
  if search then
   talentButton:SetPoint("RIGHT",search,"LEFT",-12,0)
  else
   -- Some client layouts do not expose their search widget. Keep the button
   -- in the empty footer instead of guessing coordinates in the header.
   talentButton:SetPoint("BOTTOMRIGHT",frame,"BOTTOMRIGHT",-24,14)
  end
  talentButton:SetScript("OnClick",function()
   if InCombatLockdown and InCombatLockdown() then return end
   -- The native full-screen talent UI can cover a DIALOG window even after
   -- a successful click. Close its top-level panel before opening ours.
   local host=PlayerSpellsFrame and PlayerSpellsFrame.TalentsFrame==frame and PlayerSpellsFrame or frame
   if HideUIPanel then HideUIPanel(host) end
   host:Hide()
   if ForeverAscensionWindow then ForeverAscensionWindow:Hide() end
   if ForeverAscensionToggle then ForeverAscensionToggle() end
  end)
  talentButton:SetScript("OnEnter",function(self) if GameTooltip then GameTooltip:SetOwner(self,"ANCHOR_BOTTOM");GameTooltip:SetText("Мультикласс",1,0.82,0);GameTooltip:AddLine("Способности и таланты других классов",1,1,1);GameTooltip:Show() end end)
  talentButton:SetScript("OnLeave",function() if GameTooltip then GameTooltip:Hide() end end)
  ForeverAscensionTalentButton=talentButton
 end
end
local events=CreateFrame("Frame");events:RegisterEvent("PLAYER_LOGIN");events:RegisterEvent("ADDON_LOADED");events:RegisterEvent("PLAYER_REGEN_ENABLED")
events:SetScript("OnEvent",attach)

-- Read-only report of the actual client's spellbook API and frame implementation.
function ForeverAscensionNativeBookReport()
 local lines={"ForeverAscension native spellbook report"}
 local function add(value) lines[#lines+1]=tostring(value) end
 local function scalar(value)
  if type(value)=="table" then
   local fields={};for key,item in pairs(value) do if type(item)=="string" or type(item)=="number" or type(item)=="boolean" then fields[#fields+1]=tostring(key).."="..tostring(item):sub(1,160) end end
   table.sort(fields);return "{"..table.concat(fields,", ").."}"
  end
  return tostring(value):sub(1,180)
 end
 local function query(name,fn,...)
  if type(fn)~="function" then add(name..": unavailable");return end
  local values={pcall(fn,...)}
  if not values[1] then add(name..": "..scalar(values[2]));return end
  local out={};for i=2,math.min(#values,12) do out[#out+1]=scalar(values[i]) end
  add(name..": "..table.concat(out," | "));return values[2]
 end
 local function source(name,fn)
  if type(fn)~="function" then return end
  if debug and debug.getinfo then
   local ok,info=pcall(debug.getinfo,fn,"S")
   if ok and info then add(name..": "..tostring(info.source)..":"..tostring(info.linedefined));return end
  end
  add(name..": function")
 end
 query("Build",GetBuildInfo)
 if UnitClass then local _,class,id=UnitClass("player");add("Class: "..tostring(class).." / "..tostring(id)) end
 local count=query("GetNumSpellTabs",GetNumSpellTabs)
 if type(count)=="number" then for i=1,math.min(count,32) do query("GetSpellTabInfo "..i,GetSpellTabInfo,i) end end
 if C_SpellBook then
  local apis={};for key,fn in pairs(C_SpellBook) do if type(fn)=="function" then apis[#apis+1]=key end end;table.sort(apis);add("C_SpellBook APIs: "..table.concat(apis,", "))
  local num=query("C_SpellBook.GetNumSpellBookSkillLines",C_SpellBook.GetNumSpellBookSkillLines)
  if type(num)=="number" then for i=1,math.min(num,32) do query("SkillLine "..i,C_SpellBook.GetSpellBookSkillLineInfo,i) end end
 end
 -- This client can load renamed native panels that have no legacy globals.
 if EnumerateFrames then
  local frame=EnumerateFrames();local count=0
  while frame and count<80 do
   local name=frame.GetName and frame:GetName()
   if type(name)=="string" and (name:lower():find("talent",1,true) or name:lower():find("spellbook",1,true) or name:lower():find("playerspell",1,true)) and not name:find("ForeverAscension",1,true) then
    count=count+1
    local parent=frame.GetParent and frame:GetParent()
    add("Native panel: "..name.." shown="..tostring(frame.IsShown and frame:IsShown()).." parent="..tostring(parent and parent.GetName and parent:GetName()))
   end
   frame=EnumerateFrames(frame)
  end
 end
 if C_SpellBook and C_SpellBook.GetSpellBookItemInfo then
  local bank=Enum and Enum.SpellBookSpellBank and Enum.SpellBookSpellBank.Player or 0
  for slot=1,80 do
   local ok,info=pcall(C_SpellBook.GetSpellBookItemInfo,slot,bank)
   if not ok or not info then break end
   add("Book slot "..slot..": "..scalar(info))
  end
 end
 for _,name in ipairs({"SpellBook_UpdatePlayerTab","SpellBook_GetSpellBookSlot","ToggleSpellBook"}) do source(name,_G[name]) end
 for _,name in ipairs({"SpellBookFrame","PlayerSpellsFrame","PlayerTalentFrame","TalentFrame","ClassTalentFrame","ClassicTalentFrame"}) do
  local frame=_G[name]
  if frame then
   add("Frame: "..name)
   for _,field in ipairs({"bookType","selectedSkillLine","selectedSkillLineOffset","selectedSkillLineNumSlots","selectedTab","activeTab"}) do
    local value=frame[field];if type(value)=="string" or type(value)=="number" or type(value)=="boolean" then add(name.."."..field..": "..tostring(value)) end
   end
   if frame.GetScript then local ok,fn=pcall(frame.GetScript,frame,"OnShow");if ok then source(name.." OnShow script",fn) end end
   for _,method in ipairs({"Update","UpdateSkillLineTabs","UpdateSkillLineSelection","UpdateTabs","OnEvent"}) do source(name.."."..method,frame[method]) end
  end
 end
 if ForeverAscensionTalentButton then
  local button=ForeverAscensionTalentButton
  query("Talent button strata",button.GetFrameStrata,button)
  query("Talent button level",button.GetFrameLevel,button)
  query("Talent button mouse",button.IsMouseEnabled,button)
 end
 if C_Spell and C_Spell.GetSpellInfo then
  for _,id in ipairs({1515,883,2641,6991,339,133,168}) do query("Native spell "..id,C_Spell.GetSpellInfo,id) end
 end
 add("Multiclass talent button: "..tostring(ForeverAscensionTalentButton~=nil))
 local report=table.concat(lines,"\n")
 if type(ForeverAscensionUI)~="table" then ForeverAscensionUI={} end
 ForeverAscensionUI.nativeSpellbookReport=report
 return report
end
function ForeverAscensionShowNativeBookReport()
 local report=ForeverAscensionNativeBookReport()
 local frame=ForeverAscensionBookDebug
 if not frame then
  frame=CreateFrame("Frame","ForeverAscensionBookDebug",UIParent,"BasicFrameTemplateWithInset")
  frame:SetSize(760,480);frame:SetPoint("CENTER");frame:SetFrameStrata("DIALOG");frame:SetClampedToScreen(true)
  if frame.TitleText then frame.TitleText:SetText("Штатная книга: диагностика (Ctrl+C)") end
  local scroll=CreateFrame("ScrollFrame",nil,frame,"UIPanelScrollFrameTemplate");scroll:SetPoint("TOPLEFT",16,-42);scroll:SetPoint("BOTTOMRIGHT",-32,16)
  local edit=CreateFrame("EditBox",nil,scroll);edit:SetWidth(690);edit:SetMultiLine(true);edit:SetAutoFocus(false);edit:SetFontObject(GameFontHighlightSmall or "GameFontHighlightSmall");edit:SetMaxLetters(50000);scroll:SetScrollChild(edit)
  edit:SetScript("OnEscapePressed",function() frame:Hide() end);frame.edit=edit
 end
 local _,breaks=report:gsub("\n","")
 frame.edit:SetHeight(math.max(400,(breaks+math.ceil(#report/100))*14));frame.edit:SetText(report);frame:Show();frame.edit:SetFocus();frame.edit:HighlightText()
end
