-- Companion school tabs for purchased foreign spells. Native book visibility is
-- client-controlled; do not create class skills (they can teach entire classes).
local data,cast={ },nil
local host,panel,heading,empty,pageText
local tabs,nodes={ },{ }
local selected,page=nil,1
local function text(parent,value,font)
 local label=parent:CreateFontString(nil,"OVERLAY",font or "GameFontHighlightSmall");label:SetText(value or "");return label
end
local function button(parent,value,width,click)
 local b=CreateFrame("Button",nil,parent,"UIPanelButtonTemplate");b:SetSize(width,24);b:SetText(value);b:SetScript("OnClick",click);return b
end
local function groups()
 local result,seen={ },{ }
 for _,row in ipairs(data) do if not seen[row.group] then seen[row.group]=true;table.insert(result,row.group) end end
 table.sort(result);return result,seen
end
local render
local function attach()
 local book=SpellBookFrame or (PlayerSpellsFrame and (PlayerSpellsFrame.SpellBookFrame or PlayerSpellsFrame))
 if not book then return end
 if host==book then return end
 if panel then panel:Hide() end
 host=book
 panel=CreateFrame("Frame","ForeverAscensionSpellbook",host,BackdropTemplateMixin and "BackdropTemplate" or nil)
 panel:SetSize(392,490);panel:SetPoint("TOPLEFT",host,"TOPRIGHT",8,-30);panel:SetClampedToScreen(true)
 if panel.SetBackdrop then panel:SetBackdrop({bgFile="Interface\\Buttons\\WHITE8X8",edgeFile="Interface\\Buttons\\WHITE8X8",edgeSize=1});panel:SetBackdropColor(0.025,0.04,0.065,0.98);panel:SetBackdropBorderColor(0.2,0.3,0.42,1) end
 heading=text(panel,"Книга мультикласса","GameFontNormalLarge");heading:SetPoint("TOPLEFT",16,-16)
 local hint=text(panel,"ЛКМ - применить. Перетащите иконку на панель.");hint:SetPoint("TOPLEFT",16,-42);hint:SetWidth(360);hint:SetJustifyH("LEFT")
 empty=text(panel,"Изучите способность чужого класса в /fa.");empty:SetPoint("CENTER");empty:SetWidth(340);empty:SetJustifyH("CENTER")
 tabs,nodes={ },{ }
 for i=1,27 do
  local b=button(panel,"",116,function(self) selected=self.group;page=1;render() end)
  b:SetPoint("TOPLEFT",16+((i-1)%3)*120,-65-math.floor((i-1)/3)*26);tabs[i]=b;b:Hide()
 end
 for i=1,8 do
  local b=CreateFrame("Button",nil,panel);b:SetSize(176,60)
  b.icon=b:CreateTexture(nil,"ARTWORK");b.icon:SetPoint("TOPLEFT",0,-4);b.icon:SetSize(32,32)
  b.title=text(b,"");b.title:SetPoint("TOPLEFT",40,-4);b.title:SetWidth(132);b.title:SetJustifyH("LEFT")
  b.level=text(b,"");b.level:SetPoint("TOPLEFT",40,-37)
  b:SetHighlightTexture("Interface\\Buttons\\ButtonHilight-Square","ADD")
  b:RegisterForDrag("LeftButton")
  b:SetScript("OnDragStart",function(self) if self.row and PickupSpell then PickupSpell(self.row.spell) end end)
  b:SetScript("OnClick",function(self) if self.row and cast then cast(self.row.entry) end end)
  b:SetScript("OnEnter",function(self) if self.row and GameTooltip then GameTooltip:SetOwner(self,"ANCHOR_RIGHT");GameTooltip:SetSpellByID(self.row.spell);GameTooltip:Show() end end)
  b:SetScript("OnLeave",function() if GameTooltip then GameTooltip:Hide() end end);nodes[i]=b
 end
 local prev=button(panel,"Назад",80,function() page=math.max(1,page-1);render() end);prev:SetPoint("BOTTOMLEFT",16,16)
 local next=button(panel,"Далее",80,function() page=page+1;render() end);next:SetPoint("BOTTOMRIGHT",-16,16)
 pageText=text(panel,"");pageText:SetPoint("BOTTOM",0,23)
end
render=function()
 if not panel then return end
 local list,seen=groups();if not selected or not seen[selected] then selected=list[1];page=1 end
 for i,b in ipairs(tabs) do b.group=list[i];if b.group then b:SetText(b.group);b:SetEnabled(selected~=b.group);b:Show() else b:Hide() end end
 local rows={ };for _,row in ipairs(data) do if row.group==selected then table.insert(rows,row) end end
 local pages=math.max(1,math.ceil(#rows/8));page=math.min(page,pages)
 local top=78+math.ceil(#list/3)*26
 for i,b in ipairs(nodes) do
  b.row=rows[(page-1)*8+i];b:ClearAllPoints();b:SetPoint("TOPLEFT",16+((i-1)%2)*184,-top-math.floor((i-1)/2)*66)
  if b.row then b.icon:SetTexture(b.row.icon);b.title:SetText(b.row.name);b.level:SetText("Уровень "..b.row.level);b:Show() else b:Hide() end
 end
 panel:SetHeight(math.max(410,top+4*66+55));empty:SetShown(#data==0);pageText:SetText(page.." / "..pages)
end
function ForeverAscensionUpdateSpellbook(rows,callback)
 data=rows or { };cast=callback;attach();render()
end
local events=CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN");events:RegisterEvent("ADDON_LOADED")
events:SetScript("OnEvent",function() attach();render() end)
