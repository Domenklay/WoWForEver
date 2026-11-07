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
function Frame:GetFrameLevel() return self.level or 100 end
function Frame:RegisterEvent() end
function Frame:EnableMouse() end
function Frame:EnableMouseWheel() end
function Frame:SetScrollChild(child) self.scrollChild=child end
function Frame:GetScrollChild() return self.scrollChild end
function Frame:SetVerticalScroll(n) self.scrollOffset=n end
function Frame:GetVerticalScroll() return self.scrollOffset or 0 end
function Frame:GetVerticalScrollRange() return math.max(0,(self.scrollChild and self.scrollChild:GetHeight() or 0)-self:GetHeight()) end
function Frame:SetKeepModelOnHide() end
function Frame:ClearModel() self.modelId=nil end
function Frame:SetCreature(entry) self.modelId=entry end
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
    mana=70,maxMana=106,ranks={},appearances={living_book={unlocked=true}},
    selectedAppearance="living_book",
    catalogPage=1,catalogPages=2,catalogTotal=42,catalogKnown=9,catalogLoaded=true,
    infoLevel=2,creatureInfo={},recentZones={{entry=7}},recentZonesLoaded=true,
    recentItems={{entry=19019,map=0,zone=7}},recentItemsLoaded=true,
    catalog={{entry=33,known=true,name="Волк",creatureType=1,class=0},
             {entry=42,known=false,name="",creatureType=0,class=0}},
}
local calls={status=0,catalog=0,zones=0,items=0,buy={},info={},appearance={}}
ForeverEncyclopediaUIBridge={
    state=state,catalog=catalog,
    RequestStatus=function()calls.status=calls.status+1 end,
    RequestCatalog=function(n)calls.catalog=calls.catalog+1 end,
    RequestZones=function()calls.zones=calls.zones+1 end,
    RequestItems=function()calls.items=calls.items+1 end,
    RequestCreatureInfo=function(n)calls.info[#calls.info+1]=n end,
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

local function click(text)
    for i=#Frames,1,-1 do
        local f=Frames[i]
        if f.visible and f.scripts.OnClick and not f.disabled then
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
        if f.type=="PlayerModel" and f.parent and f.parent:IsShown() and f:IsShown() then
            local p=f.parent
            while p and p~=legacy and p:IsShown() do p=p.parent end
            if p==legacy then found[#found+1]=f end
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
assert(click("Коллекция"),"Collection subtab is missing")
assert(click("Существа"),"Clickable collected-knowledge category missing")
assert(calls.catalog>=1,"Creature category must request the real catalog")
assert(click("Волк"),"Known creature row missing")
local preview=visibleModels()
assert(#preview>=1,"Creature 3D PlayerModel preview missing")
assert(preview[#preview].modelId==33,"Creature model must use the server entry, not a placeholder")
assert(preview[#preview].scripts.OnMouseWheel,"Mouse wheel zoom missing")
preview[#preview].scripts.OnMouseWheel(preview[#preview],1)
assert(preview[#preview].zoom,"Creature zoom must update camera")
assert(calls.info[#calls.info]==33,"Clicked creature must request server-backed data")
assert(click("Назад к коллекции"),"The in-window archive back button is missing")
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
assert(click("Таланты"),"Talent view unavailable after appearance preview")

legacy:SelectPage(1)
assert(not legacy.Pages[4]:IsShown(),"Blizzard's original tab must hide the book")
assert(legacy.title~="Живая энциклопедия","Original native page title must return")
assert(api.Open())
assert(legacy.currentPage==4 and legacy.Pages[4]:IsShown())
assert(api.Open())
assert(not legacy:IsShown(),"Clicking /ency a second time must close the window")
print("ENCYCLOPEDIA LEGACY NATIVE PAGE MOCK PASSED")
