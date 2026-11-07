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
-- Follow Encyclopedia's native Pages/Tabs adapter. No replacement native talent window.
local talentHost,talentButton,talentPage,nativeIndex
local camelotOwner,camelotSelected,camelotHidden,camelotRestore,camelotPosition,pendingNativeOpen
local function isCamelot()
 return WOW_PROJECT_ID==18 or (WOW_PROJECT_CAMELOT~=nil and WOW_PROJECT_ID==WOW_PROJECT_CAMELOT)
end
local function root()
 return PlayerTalentFrame or TalentFrame or ClassTalentFrame or ClassicTalentFrame or (PlayerSpellsFrame and PlayerSpellsFrame.TalentsFrame) or PlayerSpellsFrame
end
local function showContent()
 if ForeverAscensionShowIn then ForeverAscensionShowIn(talentPage) end
end
-- Forever replaces the visible talent loadout strip. The inherited retail
-- TabSystem is hidden. The visible 301x32 strip is TalentsFrame.TabSystem;
-- ButtonsParent is the clipped, high-level node canvas, not a tab container.
local function camelot()
 local owner=PlayerSpellsFrame
 local host=owner and owner.TalentsFrame
 if type(host)~="table" and type(host)~="userdata" then return false end
 local strip=host.TabSystem
 if type(strip)~="table" and type(strip)~="userdata" then return false end
 if talentHost==host and camelotOwner==owner then if camelotPosition then camelotPosition() end;return true end
 if talentButton then talentButton:Hide() end;if talentPage then talentPage:Hide() end
 talentHost=host;camelotOwner=owner;nativeIndex=nil;camelotSelected=false;camelotHidden={}
 talentPage=CreateFrame("Frame","ForeverAscensionCamelotTalentPage",host)
 talentPage:SetPoint("TOPLEFT",host,"TOPLEFT",5,-45);talentPage:SetPoint("BOTTOMRIGHT",host,"BOTTOMRIGHT",-5,5)
 local level=host:GetFrameLevel()
 for _,child in ipairs({host:GetChildren()}) do level=math.max(level,child:GetFrameLevel()) end
 talentPage:SetFrameStrata(host:GetFrameStrata());talentPage:SetFrameLevel(level+10)
 local background=talentPage:CreateTexture(nil,"BACKGROUND");background:SetAllPoints();background:SetColorTexture(0.025,0.022,0.018,1)
 talentPage:EnableMouse(true);talentPage:Hide();talentPage:SetScript("OnShow",showContent)
 talentButton=nil
 for _,template in ipairs({"TabSystemButtonArtTemplate","PanelTopTabButtonTemplate","CharacterFrameTabButtonTemplate","UIPanelButtonTemplate"}) do
  local ok,button=pcall(CreateFrame,"Button",nil,host,template)
  if ok and button then talentButton=button;talentButton.foreverNativeArt=template=="TabSystemButtonArtTemplate";break end
 end
 if not talentButton then talentButton=CreateFrame("Button",nil,host) end
 ForeverAscensionCamelotTalentTab=talentButton
 talentButton:SetSize(146,32);talentButton:SetText("Мультикласс");talentButton:SetID(3)
 if talentButton.foreverNativeArt then
  talentButton.isTabOnTop=true;talentButton.selectedFontObject=GameFontHighlight or "GameFontHighlight";talentButton.unselectedFontObject=GameFontNormal or "GameFontNormal"
  if talentButton.HandleRotation then talentButton:HandleRotation() end
 end
 local function setSelected(value)
  if talentButton.foreverNativeArt then talentButton:SetTabSelected(value)
  elseif value and PanelTemplates_SelectTab then pcall(PanelTemplates_SelectTab,talentButton)
  elseif not value and PanelTemplates_DeselectTab then pcall(PanelTemplates_DeselectTab,talentButton) end
  local text=talentButton.Text or (talentButton.GetFontString and talentButton:GetFontString())
  if (type(text)=="table" or type(text)=="userdata") and text.SetFont then text:SetFont(STANDARD_TEXT_FONT or "Fonts\\FRIZQT__.TTF",14,"");text:SetHeight(18) end
 end
 setSelected(false)
 talentButton:SetFrameStrata(host:GetFrameStrata());talentButton:SetFrameLevel(level+20)
 local savedNativeTab
 local function restore()
  camelotSelected=false;talentPage:Hide()
  local hidden=camelotHidden;camelotHidden={}
  for child in pairs(hidden) do child:Show() end
  if savedNativeTab and strip.selectedTabID==0 and type(strip.SetTabVisuallySelected)=="function" then strip:SetTabVisuallySelected(savedNativeTab) end
  setSelected(false)
 end
 camelotRestore=restore
 local hooked=setmetatable({}, {__mode="k"})
 local function visit(parent,depth,fn)
  if depth>5 or not parent.GetChildren then return end
  for _,child in ipairs({parent:GetChildren()}) do
   if child~=talentButton and child~=talentPage and child~=owner.SpecFrame and child~=owner.SpellBookFrame then fn(child);visit(child,depth+1,fn) end
  end
 end
 local function position()
  if owner.IsInspecting and owner:IsInspecting() then restore();talentButton:Hide();return end
  visit(strip,0,function(child)
   if child.HookScript and not hooked[child] then
    hooked[child]=true
    -- Native tabs may use Frame mouse handlers rather than Button OnClick.
    for _,script in ipairs({"OnMouseDown","OnMouseUp","OnClick"}) do pcall(child.HookScript,child,script,restore) end
   end
  end)
  talentButton:ClearAllPoints();talentButton:SetPoint("LEFT",strip,"RIGHT",5,0)
  local width=146
  for _,tab in ipairs({strip:GetChildren()}) do
   if tab.GetObjectType and tab:GetObjectType()=="Button" and tab:GetWidth()>=80 and tab:GetWidth()<=220 then width=tab:GetWidth();break end
  end
  talentButton:SetSize(width,32)
  local top,bottom=host:GetTop(),strip:GetBottom()
  if top and bottom and top-bottom>=0 and top-bottom<120 then
   talentPage:ClearAllPoints();talentPage:SetPoint("TOPLEFT",host,"TOPLEFT",5,-(top-bottom+4));talentPage:SetPoint("BOTTOMRIGHT",host,"BOTTOMRIGHT",-5,5)
  end
  talentButton:Show()
 end
 camelotPosition=position
 talentButton:SetScript("OnClick",function()
  if InCombatLockdown and InCombatLockdown() then return end
  if owner.IsInspecting and owner:IsInspecting() then return end
  if not camelotSelected then
   savedNativeTab=type(strip.selectedTabID)=="number" and strip.selectedTabID or nil
   if savedNativeTab and type(strip.SetTabVisuallySelected)=="function" then strip:SetTabVisuallySelected(0) end
   camelotHidden={}
   for _,child in ipairs({host:GetChildren()}) do
    if child~=strip and child~=talentPage and child~=talentButton and child:IsShown() then camelotHidden[child]=true;child:Hide() end
   end
  end
  camelotSelected=true;talentPage:Show();showContent()
  setSelected(true)
 end)
 -- Switching a native loadout or closing the window restores its own content.
 host:HookScript("OnHide",restore)
 host:HookScript("OnShow",position)
 strip:HookScript("OnShow",position)
 strip:HookScript("OnSizeChanged",position)
 position()
 ForeverAscensionTalentButton=talentButton;ForeverAscensionTalentPage=talentPage
 return true
end
local function modern()
 local frame=PlayerSpellsFrame
 if not frame or type(frame.AddNamedTab)~="function" or type(frame.SetTab)~="function" or type(frame.GetTabButton)~="function" then return false end
 if talentHost==frame and nativeIndex then return true end
 if talentButton then talentButton:Hide() end;if talentPage then talentPage:Hide() end
 talentHost=frame
 talentPage=CreateFrame("Frame","ForeverAscensionNativeTalentPage",frame)
 talentPage:SetPoint("TOPLEFT",frame,"TOPLEFT",5,-35);talentPage:SetPoint("BOTTOMRIGHT",frame,"BOTTOMRIGHT",-5,30)
 talentPage:EnableMouse(true);talentPage:Hide();talentPage:SetScript("OnShow",showContent)
 nativeIndex=frame:AddNamedTab("Мультикласс",talentPage)
 talentButton=frame:GetTabButton(nativeIndex)
 local available=frame.IsTabAvailable
 if type(available)=="function" then
  frame.IsTabAvailable=function(self,id,...)
   if id==nativeIndex then return not (type(self.IsInspecting)=="function" and self:IsInspecting()) end
   return available(self,id,...)
  end
 end
 local title=frame.UpdateFrameTitle
 if type(title)=="function" then
  frame.UpdateFrameTitle=function(self,...)
   if self:GetTab()==nativeIndex and self.SetTitle then self:SetTitle("Таланты: Мультикласс") else return title(self,...) end
  end
 end
 ForeverAscensionTalentButton=talentButton;ForeverAscensionTalentPage=talentPage
 return true
end
local function attach()
 if InCombatLockdown and InCombatLockdown() then return false end
 if camelot() then return true end
 if isCamelot() then return false end -- wait for the inner talent strip, not a hidden retail tab
 if modern() then return true end
 local frame=root();if not frame then return false end
 if frame==talentHost and talentButton then return true end
 if talentButton then talentButton:Hide() end;if talentPage then talentPage:Hide() end
 talentHost=frame
 talentPage=CreateFrame("Frame",nil,frame);talentPage:SetPoint("TOPLEFT",frame,"TOPLEFT",5,-82);talentPage:SetPoint("BOTTOMRIGHT",frame,"BOTTOMRIGHT",-5,5)
 talentPage:SetFrameLevel(frame:GetFrameLevel()+50);talentPage:EnableMouse(true);talentPage:Hide()
 talentPage:SetScript("OnShow",showContent)
 local template
 for _,candidate in ipairs({"PanelTopTabButtonTemplate","CharacterFrameTabButtonTemplate"}) do
  local ok,result=pcall(CreateFrame,"Button",nil,frame,candidate);if ok and result then talentButton=result;template=candidate;break end
 end
 if not template then talentButton=CreateFrame("Button",nil,frame) end
 talentButton:SetSize(155,30);talentButton:SetText("Мультикласс")
 talentButton:SetFrameLevel(frame:GetFrameLevel()+60);talentButton:EnableMouse(true);talentButton:SetEnabled(true)
 local tabs=type(frame.Tabs)=="table" and frame.Tabs or nil
 local last=tabs and tabs[#tabs] or frame.SecondaryTab or frame.PrimaryTab or _G.PlayerTalentFrameTab2 or _G.PlayerTalentFrameTab1
 if (type(last)=="table" or type(last)=="userdata") and last.GetObjectType then talentButton:SetPoint("LEFT",last,"RIGHT",5,0)
 else talentButton:SetPoint("TOPLEFT",frame,"TOPLEFT",395,-49) end
 if PanelTemplates_TabResize then pcall(PanelTemplates_TabResize,talentButton,20) end
 if tabs and type(frame.Pages)=="table" and type(frame.SelectPage)=="function" then
  nativeIndex=#frame.Pages+1;talentButton:SetID(nativeIndex)
  table.insert(tabs,talentButton);table.insert(frame.Pages,talentPage)
  talentButton:SetScript("OnClick",function() if not InCombatLockdown or not InCombatLockdown() then frame:SelectPage(nativeIndex) end end)
 else
  nativeIndex=nil
  -- Some client revisions use top tabs without exposing Pages. Keep their own callbacks.
  talentButton:SetScript("OnClick",function()
   if InCombatLockdown and InCombatLockdown() then return end
   talentPage:Show();showContent()
   if PanelTemplates_SelectTab then pcall(PanelTemplates_SelectTab,talentButton) end
  end)
  local originals=tabs or {frame.PrimaryTab,frame.SecondaryTab,_G.PlayerTalentFrameTab1,_G.PlayerTalentFrameTab2}
  for _,tab in pairs(originals) do if tab and tab.HookScript then
   local function restore() talentPage:Hide();if PanelTemplates_DeselectTab then pcall(PanelTemplates_DeselectTab,talentButton) end end
   tab:HookScript("OnClick",restore);tab:HookScript("OnMouseUp",restore)
  end end
 end
 talentButton:SetScript("OnEnter",function(self) if GameTooltip then GameTooltip:SetOwner(self,"ANCHOR_BOTTOM");GameTooltip:SetText("Мультикласс",1,0.82,0);GameTooltip:AddLine("Способности, ветки талантов и владение выбранного класса",1,1,1);GameTooltip:Show() end end)
 talentButton:SetScript("OnLeave",function() if GameTooltip then GameTooltip:Hide() end end)
 ForeverAscensionTalentButton=talentButton;ForeverAscensionTalentPage=talentPage
 return true
end
ForeverAscensionNativeTalentTab={Install=attach,Open=function()
 if InCombatLockdown and InCombatLockdown() then return false end
 if not attach() then
  if C_AddOns and C_AddOns.LoadAddOn then
   for _,name in ipairs({"Blizzard_PlayerSpells","Blizzard_ClassTalentUI","Blizzard_TalentUI"}) do pcall(C_AddOns.LoadAddOn,name);if attach() then break end end
  end
 end
 if not talentHost and isCamelot() then
  -- Load-on-demand children may appear one frame after their owner. Keep /fa
  -- on that native owner while events/deferred installation finish the request.
  pendingNativeOpen=true
  if PlayerSpellsFrame then
   if ShowUIPanel then ShowUIPanel(PlayerSpellsFrame) else PlayerSpellsFrame:Show() end
   if PlayerSpellsFrame.talentTabID and type(PlayerSpellsFrame.SetTab)=="function" then PlayerSpellsFrame:SetTab(PlayerSpellsFrame.talentTabID) end
  end
  if C_Timer and C_Timer.After then C_Timer.After(0,function() if pendingNativeOpen and attach() then ForeverAscensionNativeTalentTab.Open() end end) end
  return true
 end
 if not talentHost then return false end
 pendingNativeOpen=false
 local top=PlayerSpellsFrame and PlayerSpellsFrame.TalentsFrame==talentHost and PlayerSpellsFrame or talentHost
 if ShowUIPanel then ShowUIPanel(top) else top:Show() end
 if camelotOwner and top.talentTabID and type(top.SetTab)=="function" then top:SetTab(top.talentTabID) end
 if talentHost~=top then talentHost:Show() end
 if nativeIndex then
  if talentHost==PlayerSpellsFrame and type(talentHost.SetTab)=="function" then talentHost:SetTab(nativeIndex) else talentHost:SelectPage(nativeIndex) end
 else talentButton:GetScript("OnClick")() end
 return true
end,Close=function()
 if camelotRestore then camelotRestore()
 elseif talentHost==PlayerSpellsFrame and talentHost.talentTabID then talentHost:SetTab(talentHost.talentTabID)
 elseif nativeIndex and talentHost.SelectPage then talentHost:SelectPage(1)
 elseif talentPage then talentPage:Hide() end
end}
local events=CreateFrame("Frame");events:RegisterEvent("PLAYER_LOGIN");events:RegisterEvent("ADDON_LOADED");events:RegisterEvent("PLAYER_REGEN_ENABLED")
local function tryAttach()
 if attach() and pendingNativeOpen then ForeverAscensionNativeTalentTab.Open() end
end
events:SetScript("OnEvent",function()
 tryAttach()
 if C_Timer and C_Timer.After then C_Timer.After(0,tryAttach);C_Timer.After(0.2,tryAttach) end
end)

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
