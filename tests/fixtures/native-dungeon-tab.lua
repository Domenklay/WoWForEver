-- Test actual Forever 70658 native Group Finder page model, not a guessed
-- PVEFrame overlay. Derived from Blizzard_GroupFinder_VanillaStyle/parent Lua.
local frames, messages = {}, {}
local function noop() end
local methods = {}
function methods:GetWidth() return rawget(self,"width") or 48 end
function methods:GetHeight() return rawget(self,"height") or 48 end
function methods:GetFrameLevel() return rawget(self,"level") or 2 end
function methods:GetID() return rawget(self,"id") or 0 end
function methods:SetID(n) self.id=n end
function methods:SetWidth(v) self.width=v end
function methods:SetHeight(v) self.height=v end
function methods:SetSize(w,h) self.width=w;self.height=h end
function methods:SetFrameLevel(v) self.level=v end
function methods:SetVertexColor(r,g,b,a) self.rgba={r,g,b,a} end
function methods:SetTexture(v) self.texture=v end
function methods:EnableMouse(v) self.mouseEnabled=v end
function methods:SetPoint(...)
    self.lastAnchor={...}
    self.anchors=rawget(self,"anchors") or {}
    table.insert(self.anchors,{...})
end
function methods:SetAllPoints() self.allPoints=true end
function methods:SetText(v) self.text=v end
function methods:GetText() return rawget(self,"text") or "" end
function methods:SetEnabled(v) self.enabled=v end
function methods:SetScript(n,f) self.scripts[n]=f end
function methods:HookScript(n,fn)
    local old=self.scripts[n]
    self.scripts[n]=old and function(...) old(...);fn(...) end or fn
end
function methods:SetCustomOnMouseUpHandler(fn) self.customOnMouseUp=fn end
function methods:Show()
    if self.shown then return end
    self.shown=true
    if self.scripts.OnShow then self.scripts.OnShow(self) end
end
function methods:Hide()
    if not self.shown then return end
    self.shown=false
    if self.scripts.OnHide then self.scripts.OnHide(self) end
end
function methods:SetShown(v) if v then self:Show() else self:Hide() end end
function methods:IsShown()
    return self.shown and (not rawget(self,"parent") or self.parent:IsShown())
end
function methods:SetChecked(v) self.checked=v end
local function make(kind,name,parent,template)
    local o=setmetatable({
        kind=kind,name=name,parent=parent,template=template,shown=true,
        scripts={},children={},
    },{__index=function(_,key)
        if key=="foreverNativeHidden" then return nil end
        return methods[key] or noop
    end})
    if parent then table.insert(parent.children,o) end
    if name then _G[name]=o end
    table.insert(frames,o)
    if template=="LFGVanillaRightTabTemplate" then
        o.Icon=make("Texture",nil,o,nil)
        o.width=48;o.height=48
    end
    return o
end
function methods:CreateTexture() return make("Texture",nil,self,nil) end
function methods:CreateFontString() return make("FontString",nil,self,nil) end
function CreateFrame(kind,name,parent,template) return make(kind,name,parent,template) end
function wipe(t) for k in pairs(t) do t[k]=nil end end
function hooksecurefunc(object,method,fn)
    assert(type(object[method])=="function","Cannot hook absent native method")
    local old=object[method]
    object[method]=function(self,...)
        local v=old(self,...)
        fn(self,...)
        return v
    end
end
function PanelTemplates_SetTab(frame,index) frame.selectedTab=index end

GameTooltip={SetOwner=noop,AddLine=noop,Show=noop,Hide=noop}
DEFAULT_CHAT_FRAME={AddMessage=noop}
SlashCmdList={}
function UnitName() return "TestHero" end
function IsInGroup() return false end
function IsInRaid() return false end
function UnitIsGroupLeader() return true end
function GetNumGroupMembers() return 1 end
local now=20
function GetTime() return now end
function IsLoggedIn() return true end
C_ChatInfo={
    RegisterAddonMessagePrefix=function(p) assert(p=="FDF");return true end,
    SendAddonMessage=function(p,m,c,t)
        table.insert(messages,{p,m,c,t})
        return true
    end,
}
LFGParentFrame=make("Frame","LFGParentFrame",nil,nil)
LFGParentFrame:SetSize(458,535)
LFGParentFrame:SetFrameLevel(5)
LFGParentFrame:Hide()
LFGParentFrame.selectedTab=1
LFGParentFrame.ListingTab=CreateFrame("Frame","NativeListingTab",LFGParentFrame)
LFGParentFrame.BrowsingTab=CreateFrame("Frame","NativeBrowseTab",LFGParentFrame)
LFGParentFrame.WhoListingTab=CreateFrame("Frame","NativeWhoTab",LFGParentFrame)
for _,t in ipairs({LFGParentFrame.ListingTab,LFGParentFrame.BrowsingTab,LFGParentFrame.WhoListingTab}) do
    t:SetSize(48,48)
end
LFGListingFrame=CreateFrame("Frame","LFGListingFrame",LFGParentFrame)
LFGBrowseFrame=CreateFrame("Frame","LFGBrowseFrame",LFGParentFrame)
LFGWhoListFrame=CreateFrame("Frame","LFGWhoListFrame",LFGParentFrame)
LFGBrowseFrame:Hide();LFGWhoListFrame:Hide()
function LFGParentFrame:UpdateTabs()
    self.ListingTab:SetChecked(self.selectedTab==1)
    self.BrowsingTab:SetChecked(self.selectedTab==2)
    self.WhoListingTab:SetChecked(self.selectedTab==3)
end
local function nativeSelect(index)
    PanelTemplates_SetTab(LFGParentFrame,index)
    LFGListingFrame:SetShown(index==1)
    LFGBrowseFrame:SetShown(index==2)
    LFGWhoListFrame:SetShown(index==3)
    LFGParentFrame:UpdateTabs()
end
LFGParentFrame:SetScript("OnShow",function(self)
    nativeSelect(self.selectedTab)
end)
function ShowUIPanel(frame) frame:Show() end

-- Obsolete stand-alone client controls must remain suppressed.
local oldRed=CreateFrame("Button","ForeverDungeonFinderGroupFinderTab",LFGParentFrame)
oldRed:SetText("Вход в подземелье")
local oldPane=CreateFrame("Frame","ForeverDungeonFinderGroupFinderPane",LFGParentFrame)

local path=arg[1]
assert(path,"usage: lua native-dungeon-tab.lua <ForeverDungeonFinder.lua>")
assert(loadfile(path))()
assert(not _G.ForeverDungeonFinderFrame,"Old detached dungeon frame recreated")
assert(not _G.ForeverDungeonFinderMinimapButton,"Old minimap addon recreated")
local tab=_G.ForeverDungeonPortalTab
local pane=_G.ForeverDungeonFinderPane
assert(tab and pane,"Native sidebar and page are missing")
assert(tab.parent==LFGParentFrame and pane.parent==LFGParentFrame,"Wrong LFG parent")
assert(tab.template=="LFGVanillaRightTabTemplate","Must use real Blizzard side-tab template")
assert(tab:GetID()==4,"Native dungeon tab must have ID=4")
assert(tab.Icon and tab.Icon.texture=="Interface\Icons\Spell_Arcane_PortalStormWind","Portal icon not inherited")
assert(tab.lastAnchor[1]=="TOPLEFT" and tab.lastAnchor[2]==LFGParentFrame.WhoListingTab
    and tab.lastAnchor[3]=="BOTTOMLEFT" and tab.lastAnchor[4]==0 and tab.lastAnchor[5]==-2,
    "New portal must attach to third native sidebar tab")
assert(tab:GetWidth()==LFGParentFrame.WhoListingTab:GetWidth(),"Sidebar icon width differs from native")
assert(tab:GetHeight()==LFGParentFrame.WhoListingTab:GetHeight(),"Sidebar icon height differs from native")
assert(pane.opaqueBackground and pane.opaqueBackground.rgba[4]==1,"Page background not opaque")
assert(pane.anchors[1][1]=="TOPLEFT" and pane.anchors[1][2]==LFGParentFrame
    and pane.anchors[1][4]==5 and pane.anchors[1][5]==-36,"Pane must be native page anchored below title")
assert(pane.anchors[2][1]=="BOTTOMRIGHT" and pane.anchors[2][2]==LFGParentFrame
    and pane.anchors[2][4]==-5 and pane.anchors[2][5]==5,"Pane must fill parent content")
assert(not oldRed:IsShown() and not oldPane:IsShown(),"Previous overlay red UI is still visible")
assert(not pane:IsShown(),"Native dungeon page must start hidden")
assert(type(SlashCmdList.FOREVERDUNGEONFINDER)=="function","/fd missing")

SlashCmdList.FOREVERDUNGEONFINDER()
assert(LFGParentFrame:IsShown() and LFGParentFrame.selectedTab==4,"/fd didn't select native page 4")
assert(pane:IsShown(),"Dungeon page not displayed")
assert(not LFGListingFrame:IsShown() and not LFGBrowseFrame:IsShown()
    and not LFGWhoListFrame:IsShown(),"A native LFG page was left under dungeon page")
assert(tab.checked,"Fourth tab isn't checked")

-- Verify the native page mechanism restores original UI, not just an overlay.
nativeSelect(2)
assert(LFGBrowseFrame:IsShown(),"Native browse page not restored")
assert(not pane:IsShown() and not tab.checked,"Dungeon page remained visible after native selection")
assert(LFGParentFrame.BrowsingTab.checked,"Native browser side tab selection lost")
assert(tab.customOnMouseUp,"Inherited tab missing native mouse handler")
tab.customOnMouseUp(tab,"LeftButton",true)
assert(LFGParentFrame.selectedTab==4 and pane:IsShown(),"Real right-side tab cannot reopen page 4")

oldRed:Show()
assert(not oldRed:IsShown(),"Obsolete red button reappeared")
local function findButton(text)
    for _,v in ipairs(frames) do
        if v.kind=="Button" and v.text==text then return v end
    end
end
local search
for _,v in ipairs(frames) do if v.kind=="EditBox" then search=v end end
assert(search and search.scripts.OnTextChanged,"In-page search missing")
search:SetText("зул")
search.scripts.OnTextChanged(search)
local found=false
for _,v in ipairs(frames) do
    if v.kind=="Button" and rawget(v,"data")
        and v.data.name=="Зул'Фаррак" and v:IsShown() then found=true end
end
assert(found,"Cyrillic dungeon search failed")
search:SetText("")
search.scripts.OnTextChanged(search)

local solo=findButton("Войти соло")
local group=findButton("Группой")
assert(solo and group,"Solo/premade controls absent")
assert(group.enabled==false,"Premade button enabled while solo")
solo.scripts.OnClick()
assert(#messages==1 and messages[1][1]=="FDF" and messages[1][2]=="SOLO:389"
    and messages[1][3]=="WHISPER","FDF solo payload changed")
now=23
function IsInGroup() return true end
function GetNumGroupMembers() return 3 end
local events
for _,v in ipairs(frames) do if v.kind=="Frame" and v.scripts.OnEvent and v~=pane then events=v end end
assert(events and events.scripts.OnEvent,"Missing party update observer")
events.scripts.OnEvent(events,"GROUP_ROSTER_UPDATE")
assert(group.enabled==true,"Premade action not enabled for party leader")
group.scripts.OnClick()
assert(#messages==2 and messages[2][2]=="GROUP:389" and messages[2][3]=="PARTY","FDF group payload changed")
LFGParentFrame:Hide()
assert(not pane:IsShown(),"Page remained visible after closing native window")
LFGParentFrame:Show()
assert(pane:IsShown() and LFGParentFrame.selectedTab==4,"Native page not restored when reopening LFG")
nativeSelect(3)
assert(LFGWhoListFrame:IsShown() and not pane:IsShown(),"Native Who list not restored")
print("PASS: genuine fourth native LFG tab, page switching, FDF and search")
