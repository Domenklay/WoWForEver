-- Lua 5.1 runtime fixture: Blizzard's real Legacy frame has three Pages/Tabs.
-- Confirm the encyclopedia becomes a fourth native page without replacing them.
local dir=assert(arg[1],"Path to the Encyclopedia addon is required")
local Frames={}
local Region={}
Region.__index=Region
function Region:SetPoint() end
function Region:SetSize(w,h) self.w=w;self.h=h end
function Region:SetWidth(w) self.w=w end
function Region:SetHeight(h) self.h=h end
function Region:SetAllPoints() end
function Region:SetTexture(s) self.texture=s end
function Region:SetVertexColor(...) self.vertex={...} end
function Region:SetText(s) self.text=s end
function Region:SetTextColor(...) self.color={...} end
function Region:SetWordWrap(flag) self.wrap=flag end
function Region:SetMaxLines(n) self.maxLines=n end
function Region:GetStringHeight() return 16+math.floor(#(self.text or "")/44)*12 end
function Region:SetJustifyH() end
function Region:SetTexCoord() end
function Region:SetDesaturated() end
function Region:SetAlpha() end
function Region:SetBlendMode() end
function Region:SetShown(yes) self.visible=yes end
function Region:Hide() self.visible=false end
function Region:Show() self.visible=true end
local Frame={}
Frame.__index=Frame
function Frame:SetPoint() end
function Frame:SetAllPoints() end
function Frame:ClearAllPoints() end
function Frame:SetSize(w,h) self.w=w;self.h=h end
function Frame:SetWidth(w) self.w=w end
function Frame:SetHeight(h) self.h=h end
function Frame:GetHeight() return self.h or 0 end
function Frame:GetWidth() return self.w or 0 end
function Frame:SetFrameLevel(n) self.level=n end
function Frame:SetBackdrop(v) self.backdrop=v end
function Frame:SetBackdropBorderColor(...) self.borderColor={...} end
function Frame:SetBackdropColor(...) self.backdropColor={...} end
function Frame:GetFrameLevel() return self.level or 100 end
function Frame:RegisterEvent() end
function Frame:EnableMouse() end
function Frame:EnableMouseWheel() end
function Frame:SetAutoFocus(b) self.autoFocus=b end
function Frame:SetText(s) self.text=s end
function Frame:GetText() return self.text or "" end
function Frame:ClearFocus() self.focused=false end
function Frame:SetScrollChild(child) self.scrollChild=child end
function Frame:GetScrollChild() return self.scrollChild end
function Frame:SetVerticalScroll(n) self.scrollOffset=n end
function Frame:GetVerticalScroll() return self.scrollOffset or 0 end
function Frame:GetVerticalScrollRange() return math.max(0,(self.scrollChild and self.scrollChild:GetHeight() or 0)-self:GetHeight()) end
function Frame:SetKeepModelOnHide() end
function Frame:EnableMouse(x) self.mouse=x end
function Frame:ClearModel() self.modelId=nil end
function Frame:SetCreature(entry,display)
    self.creatureEntry=entry
    self.modelId=entry
    self.requestedDisplay=display
end
function Frame:SetDisplayInfo(display)
    self.displayId=display
    self.modelId=display
    if self.scripts.OnModelLoaded then self.scripts.OnModelLoaded(self) end
end
function Frame:GetDisplayInfo() return self.displayId or 0 end
function Frame:SetCamera() end
function Frame:SetUnit(unit) self.unit=unit;self.modelId="player"; if self.scripts.OnModelLoaded then self.scripts.OnModelLoaded(self) end end
function Frame:SetPortraitZoom() end
function Frame:SetCamDistanceScale(zoom) self.zoom=zoom end
function Frame:SetRotation(angle) self.rotation=angle end
function Frame:RefreshCamera() end
function Frame:SetScript(kind,fn) self.scripts[kind]=fn end
function Frame:SetShown(yes) if yes then self:Show() else self:Hide() end end
function Frame:Show()
    if not self.visible then
        self.visible=true
        if self.scripts.OnShow then self.scripts.OnShow(self) end
    end
end
function Frame:Hide() self.visible=false end
function Frame:IsShown() return self.visible end
function Frame:SetID(id) self.id=id end
function Frame:GetID() return self.id end
function Frame:SetChecked(yes) self.checked=yes end
function Frame:Disable() self.disabled=true end
function Frame:SetTitle(title) self.title=title end
function Frame:SetCustomOnMouseUpHandler(fn) self.mouseUp=fn end
function Frame:CreateTexture(_,layer)
    local t=setmetatable({layer=layer},Region)
    self.regions[#self.regions+1]=t
    return t
end
function Frame:CreateFontString(_,layer,style)
    local f=setmetatable({layer=layer,style=style},Region)
    self.regions[#self.regions+1]=f
    return f
end
function CreateFrame(kind,name,parent,template)
    local f=setmetatable({type=kind,name=name,parent=parent,template=template,
        scripts={},regions={},visible=true,children={}},Frame)
    if parent then parent.children[#parent.children+1]=f end
    if name then _G[name]=f end
    if template=="LegacySystemTabTemplate" then f.Icon=f:CreateTexture(nil,"ARTWORK") end
    Frames[#Frames+1]=f
    return f
end
function wipe(t) for k in pairs(t) do t[k]=nil end end
local messages={}
DEFAULT_CHAT_FRAME={AddMessage=function(_,s)messages[#messages+1]=s end}
GameTooltip={}
function GameTooltip:SetOwner() end
function GameTooltip:AddLine() end
function GameTooltip:Show() end
function GameTooltip:Hide() end
function GameTooltip:SetHyperlink(link) self.lastLink=link end
function GameTooltip:ClearLines() self.lastLink=nil end
-- This simulation models the actual 70658 pet journal display-ID path.
C_PetJournal={
  GetPetInfoBySpeciesID=function(species)
    local display=({[1159]=46938,[1174]=47348,[2893]=97329})[species]
    return nil,nil,nil,nil,nil,nil,nil,nil,nil,nil,nil,display
  end
}
C_Item={
  GetItemInfo=function(entry) return entry==1001 and "Древнее перо" or "Редкий предмет" end,
  GetItemIconByID=function() return "Interface\\Icons\\INV_Feather_01" end,
}
function ShowUIPanel(f) f:Show() end
function HideUIPanel(f) f:Hide() end
InCombatLockdown=function() return false end
GetCursorPosition=function() return 200,200 end
C_Timer={After=function(_,fn) fn() end}
C_AddOns={LoadAddOn=function() return true end}

dofile(dir.."/ForeverEncyclopediaTalentData.lua")
dofile(dir.."/ForeverEncyclopediaTalentOverrides.lua")
local catalog=assert(ForeverEncyclopediaTalentCatalog)
local state={
    online=true,total=21,creatures=9,items=6,zones=6,
    knowledgeTotal=35,knowledgeSpent=6,knowledgeAvailable=29,
    mana=70,maxMana=106,ranks={},appearances={
        living_book={unlocked=true},
        test_lofty_libram={unlocked=true},
        test_animated_tome={unlocked=true},
        test_gusting_grimoire={unlocked=true},
        test_agitated_tome={unlocked=true},
        test_troubled_tome={unlocked=true},
        test_chromies_codex={unlocked=true}
    },
    selectedAppearance="living_book",
    catalogPage=1,catalogPages=2,catalogTotal=42,catalogKnown=9,catalogLoaded=true,
    infoLevel=2,creatureInfo={},recentZones={{entry=7}},recentZonesLoaded=true,
    lootSupported=true,lootByCreature={
      [33]={items={
        {entry=1001,chance=12.5,quest=false,lootMode=1,group=0,minCount=1,maxCount=1},
        {entry=1002,chance=0,quest=false,lootMode=1,group=1,minCount=1,maxCount=1}
      },loaded=true,loading=false}
    },
    recentItems={{entry=19019,map=0,zone=7}},recentItemsLoaded=true,
    catalog={{entry=33,known=true,name="Волк",creatureType=1,class=0},
             {entry=42,known=false,name="",creatureType=0,class=0}},
}
local calls={status=0,catalog=0,zones=0,items=0,buy={},info={},appearance={},loot={}}
ForeverEncyclopediaUIBridge={
    state=state,catalog=catalog,
    RequestStatus=function()calls.status=calls.status+1 end,
    RequestCatalog=function(n)calls.catalog=calls.catalog+1 end,
    RequestZones=function()calls.zones=calls.zones+1 end,
    RequestItems=function()calls.items=calls.items+1 end,
    RequestCreatureInfo=function(n)calls.info[#calls.info+1]=n end,
    RequestCreatureLoot=function(n)calls.loot[#calls.loot+1]=n end,
    BuyTalent=function(key)calls.buy[#calls.buy+1]=key end,
    SelectAppearance=function(key)calls.appearance[#calls.appearance+1]=key end,
    AreaName=function(id)return "Зона "..id end,
}
local legacy=CreateFrame("Frame","LegacySystemFrame")
legacy.Pages={CreateFrame("Frame"),CreateFrame("Frame"),CreateFrame("Frame")}
legacy.Tabs={CreateFrame("Frame"),CreateFrame("Frame"),CreateFrame("Frame")}
legacy.LegacyTreeTab=legacy.Tabs[3]
function legacy:SelectPage(id)
    self.currentPage=id
    for i,page in ipairs(self.Pages) do page:SetShown(i==id) end
    for _,tab in ipairs(self.Tabs) do tab:SetChecked(tab:GetID()==id) end
end
for i,p in ipairs(legacy.Pages) do
    p:SetScript("OnShow",function()legacy:SetTitle("Старинное дерево "..i)end)
end
local originals={}
for i=1,3 do originals[i]=legacy.Pages[i] end
legacy:SelectPage(3)
local title=legacy.title

dofile(dir.."/ForeverEncyclopediaLegacy.lua")
local api=assert(ForeverEncyclopediaLegacy)
assert(api.Install(),"Unable to install fourth Legacy page")
assert(api.Install(),"Reinstall is not idempotent")
assert(#legacy.Pages==4 and #legacy.Tabs==4,"Expected exactly four native pages/tabs")
for i=1,3 do assert(legacy.Pages[i]==originals[i],"A native page was overwritten") end
assert(ForeverEncyclopediaLegacyTab:GetID()==4)
assert(ForeverEncyclopediaLegacyTab.iconTexture=="Interface\\Icons\\INV_Misc_Book_09")
assert(legacy.title==title and legacy.currentPage==3)

local function currentlyVisible(frame)
    local f=frame
    while f do
        if not f.visible then return false end
        if f==legacy then return true end
        f=f.parent
    end
    return false
end
local function click(text)
    for i=#Frames,1,-1 do
        local f=Frames[i]
        if currentlyVisible(f) and f.scripts.OnClick and not f.disabled then
            for _,r in ipairs(f.regions) do
                if r.text==text then f.scripts.OnClick(f);return true end
            end
        end
    end
    return false
end
assert(api.Open(),"Native window should be available")
local function countObjects(kind)
    local n=0
    for _,f in ipairs(Frames) do if f.type==kind then n=n+1 end end
    return n
end
local function visibleModels()
    local found={}
    for _,f in ipairs(Frames) do
        if f.type=="PlayerModel" and currentlyVisible(f) then
            found[#found+1]=f
        end
    end
    return found
end
assert(legacy.currentPage==4 and legacy.Pages[4]:IsShown())
assert(legacy.title=="Живая энциклопедия")
assert(not legacy.Pages[1]:IsShown() and not legacy.Pages[3]:IsShown())
assert(calls.status>=1)
assert(click("Изучить за 3 знаний"),"Real purchase button missing")
assert(calls.buy[1]=="aegis_unlock","Purchase must be sent as FET1 with canonical key")
assert(#calls.buy==1)
-- A pending buy must not be sent repeatedly before the server reply.
assert(not click("Изучить за 3 знаний"))
api.Refresh("talents") -- server acknowledges and delivers a new status
assert(countObjects("ScrollFrame")>=2,"Talent tree/detail ScrollFrame missing")
local treeScroll
for _,f in ipairs(Frames) do
    if f.type=="ScrollFrame" and currentlyVisible(f) and f.scrollChild and f.scrollChild:GetHeight()>600 then treeScroll=f end
end
assert(treeScroll and treeScroll.scripts.OnMouseWheel,"Scrollable full talent tree missing")
treeScroll.scripts.OnMouseWheel(treeScroll,-1)
assert(treeScroll:GetVerticalScroll()>0,"Mouse wheel must move the talent tree")
-- A fully studied talent must never show 'Изучить за 0 знаний'.
state.ranks.aegis_unlock=1
api.Refresh("talents")
assert(not click("Изучить за 0 знаний"),"Max-ranked talent must have no buy button")
state.ranks.aegis_unlock=0
api.Refresh("talents")
assert(click("Коллекция"),"Collection subtab is missing")
assert(click("Существа"),"Clickable collected-knowledge category missing")
assert(calls.catalog>=1,"Creature category must request the real catalog")
-- The archive must show around 10 rows, not 4, without sacrificing 3D.
local archiveScroll
for _,f in ipairs(Frames) do
    if f.type=="ScrollFrame" and currentlyVisible(f) and f.scrollChild
        and f:GetHeight()==286 and f.parent and f.parent:GetWidth()==390 then
        archiveScroll=f
    end
end
assert(archiveScroll,"Full-height creature chooser scroll missing")
assert(archiveScroll.parent:GetHeight()==395,"Creature list should use nearly entire window height")
local rowWidgets=0
for _,child in ipairs(archiveScroll.scrollChild.children or {}) do
    if child.type=="Button" and child:GetHeight()==27 then rowWidgets=rowWidgets+1 end
end
assert(rowWidgets>=10 and rowWidgets<=12,
       "Archive should reuse 10-11 small row widgets, not show just 4")
assert(click("Волк"),"Known creature row missing")
local lootButtons=0
for _,f in ipairs(Frames) do
    if currentlyVisible(f) and f.scripts.OnEnter then
        for _,region in ipairs(f.regions) do
            if region.text=="Древнее перо" then
                lootButtons=lootButtons+1
                f.scripts.OnEnter(f)
                assert(GameTooltip.lastLink=="item:1001","Native item hyperlink tooltip did not open")
                f.scripts.OnLeave(f)
            end
        end
    end
end
assert(lootButtons>=1,"Visible loot item with real name is missing")
local creatureModels=visibleModels()
assert(creatureModels[#creatureModels].parent:GetWidth()==182,
       "Creature 3D plate must be smaller to fit the loot list")
assert(click("Волк"),"Known creature row missing")
assert(not click("Далее"),"Archive must no longer have pagination Next")
assert(not click("Назад"),"Archive must no longer have pagination Back")
assert(click("Все типы v"),"Creature type dropdown missing")
assert(click("Звери"),"Creature type option missing")
assert(not click("???"),"Unknown type should not match a Beast filter")
assert(click("Звери v"),"Selected creature filter must be visible")
assert(click("Все типы"),"Reset to all creature types missing")
local preview=visibleModels()
assert(#preview>=1,"Creature 3D PlayerModel preview missing")
assert(preview[#preview].modelId==33,"Creature model must use the server entry, not a placeholder")
assert(preview[#preview].scripts.OnMouseWheel,"Mouse wheel zoom missing")
preview[#preview].scripts.OnMouseWheel(preview[#preview],1)
assert(preview[#preview].zoom,"Creature zoom must update camera")
assert(calls.info[#calls.info]==33,"Clicked creature must request server-backed data")
-- Full account archive on new server: additional zones are selectable and no
-- page controls appear even when the returned list exceeds one server page.
state.archiveSupported=true
state.archiveLoaded=true
state.archiveAll={
  {entry=33,known=true,name="Волк",creatureType=1,classification=0,map=1,zone=7},
  {entry=500,known=true,name="Повелитель пепла",creatureType=3,classification=1,map=1,zone=88},
}
state.zone=7
state.catalogAll={
  {entry=33,known=true,name="Волк",creatureType=1,map=1,zone=7},
  {entry=42,known=false,name="",creatureType=0,map=1,zone=7},
}
state.catalogAllLoaded=true
api.Refresh("archive")
assert(click("Все доступные зоны v"),"Location selection menu missing")
assert(click("Зона 88"),"Other discovered zone should be an option")
assert(click("Повелитель пепла"),"A creature from another zone must appear after filtering")
local otherZoneModel=visibleModels()
assert(otherZoneModel[#otherZoneModel].modelId==500,"Wrong model after location filtering")
assert(click("Зона 88 v"),"Location selection should show chosen zone")
assert(click("Все доступные зоны"),"Unable to reset zone filter")
-- Long archives must be virtualised, not create a button per monster.
for id=10001,11001 do
    state.archiveAll[#state.archiveAll+1]={
        entry=id,known=true,name="Бестиарий "..id,creatureType=1,
        classification=0,map=1,zone=7
    }
end
local previousFrameCount=#Frames
api.Refresh("archive")
assert(#Frames-previousFrameCount<140,"Archive renders too many GUI rows for 1000 discoveries")
local monsterScroller
for _,f in ipairs(Frames) do
    if f.type=="ScrollFrame" and currentlyVisible(f) and f.scrollChild
        and f.scrollChild:GetHeight()>20000 then
        monsterScroller=f
    end
end
assert(monsterScroller and monsterScroller.scripts.OnMouseWheel,
       "Full archive needs a virtualized wheel-scrollable monster list")
monsterScroller.scripts.OnMouseWheel(monsterScroller,-1)
assert(monsterScroller:GetVerticalScroll()>0)
assert(click("К коллекции"),"The compact archive return button is missing")
assert(click("Локации"),"Zone category missing")
assert(calls.zones>=1)
assert(click("Назад к коллекции"))
assert(click("Предметы"),"Items category missing")
assert(calls.items>=1,"Clicking items must request existing server REC 2 protocol")
assert(click("Назад к коллекции"))
api.Refresh("mana")
assert(legacy.Pages[4]:IsShown(),"Status refresh must not close the page")
assert(click("Облики"),"Appearance tab missing")
local appearanceModels=visibleModels()
assert(#appearanceModels>=1,"Appearance 3D PlayerModel missing")
assert(appearanceModels[#appearanceModels].modelId==171120,"Appearance preview must use the real unlocked creature")
assert(appearanceModels[#appearanceModels].scripts.OnMouseDown and appearanceModels[#appearanceModels].scripts.OnMouseWheel)
local testBooks={
    {"Парящий манускрипт",68806,"test_lofty_libram"},
    {"Оживший фолиант",171120,"test_animated_tome"},
    {"Парящий гримуар",69208,"test_gusting_grimoire"},
    {"Беспокойная книга",101633,"test_agitated_tome"},
    {"Драконий фолиант",198511,"test_troubled_tome"},
    {"Кодекс Хроми",227052,"test_chromies_codex"}
}
for _,skin in ipairs(testBooks) do
    assert(click(skin[1]),"Missing test appearance: "..skin[1])
    local list=visibleModels()
    if skin[2]==68806 then
        assert(list[#list].displayId==46938,"Lofty Libram should use real Display ID")
    elseif skin[2]==69208 then
        assert(list[#list].displayId==47348,"Gusting Grimoire should use real Display ID")
    elseif skin[2]==171120 then
        assert(list[#list].displayId==97329,"Animated Tome should use pet-journal display ID")
    else
        assert(list[#list].creatureEntry==skin[2],"Wrong NPC model for "..skin[1])
    end
    assert(click("Выбрать облик"),"Available test skin must be selectable: "..skin[1])
    assert(calls.appearance[#calls.appearance]==skin[3],"Wrong server appearance key for "..skin[1])
end
assert(click("Живая книга"),"Cannot return to the original base appearance")
assert(visibleModels()[#visibleModels()].displayId==97329,
       "The default base skin must use the pet journal rather than a silent creature-cache lookup")
assert(click("Проверить 3D"),"The player render-control button is missing")
assert(visibleModels()[#visibleModels()].unit=="player",
       "3D control must load a visibly distinct player without changing the selected book skin")
assert(click("Таланты"),"Talent view unavailable after appearance preview")

legacy:SelectPage(1)
assert(not legacy.Pages[4]:IsShown(),"Blizzard's original tab must hide the book")
assert(legacy.title~="Живая энциклопедия","Original native page title must return")
assert(api.Open())
assert(legacy.currentPage==4 and legacy.Pages[4]:IsShown())
assert(api.Open())
assert(not legacy:IsShown(),"Clicking /ency a second time must close the window")
print("ENCYCLOPEDIA LEGACY NATIVE PAGE MOCK PASSED")
