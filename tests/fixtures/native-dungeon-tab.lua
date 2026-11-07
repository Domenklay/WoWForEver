-- Minimal WoW 1.60 UI mock: test the real embedded pane without launching the game.
local frames, messages = {}, {}
local function noop() end
local methods = {}
function methods:GetWidth() return rawget(self,"width") or 470 end
function methods:GetHeight() return rawget(self,"height") or 580 end
function methods:GetFrameLevel() return rawget(self,"level") or 2 end
function methods:GetNumPoints() return rawget(self,"points") or 0 end
function methods:SetWidth(v) self.width=v end
function methods:SetHeight(v) self.height=v end
function methods:SetSize(w,h) self.width=w; self.height=h end
function methods:SetFrameLevel(v) self.level=v end
function methods:SetVertexColor(r,g,b,a) self.rgba={r,g,b,a} end
function methods:SetTexture(v) self.texture=v end
function methods:EnableMouse(v) self.mouseEnabled=v end
function methods:SetPoint(...) self.points=(rawget(self,"points") or 0)+1; self.lastAnchor={...} end
function methods:GetLeft() return rawget(self,"left") end
function methods:GetRight() return rawget(self,"right") end
function methods:SetAllPoints() self.points=1 end
function methods:SetText(v) self.text=v end
function methods:GetText() return self.text or "" end
function methods:SetEnabled(v) self.enabled=v end
function methods:SetScript(n,f) self.scripts[n]=f end
function methods:HookScript(n,f) self.scripts[n]=f end
function methods:Show() self.shown=true; if self.scripts.OnShow then self.scripts.OnShow(self) end end
function methods:Hide() self.shown=false end
function methods:IsShown() return self.shown and (not rawget(self,"parent") or self.parent:IsShown()) end
function methods:SetChecked(v) self.checked=v end
local function make(kind, name, parent)
    local o=setmetatable({kind=kind, name=name, parent=parent, shown=true, scripts={}, children={}},{
        __index=function(_,key)
            if key=="foreverNativeHidden" then return nil end
            return methods[key] or noop
        end,
    })
    if parent then table.insert(parent.children, o) end
    if name then _G[name]=o end
    table.insert(frames,o)
    return o
end
function methods:CreateTexture() return make("Texture", nil, self) end
function methods:CreateFontString() return make("FontString", nil, self) end
function CreateFrame(kind, name, parent) return make(kind, name, parent) end
function wipe(t) for k in pairs(t) do t[k]=nil end end
GameTooltip={SetOwner=noop,AddLine=noop,Show=noop,Hide=noop}
DEFAULT_CHAT_FRAME={AddMessage=noop}
SLASH_FOREVERDUNGEONFINDER1,SLASH_FOREVERDUNGEONFINDER2=nil,nil
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
    SendAddonMessage=function(p,m,c,t) table.insert(messages,{p,m,c,t}); return true end,
}
LFGParentFrame=make("Frame","LFGParentFrame",nil)
LFGParentFrame:SetSize(470,580)
LFGParentFrame:Hide()
if arg[2]=="pve" then
    PVEFrame=make("Frame","PVEFrame",nil)
    PVEFrame:SetSize(470,580)
    PVEFrame:Hide()
end
local expectedHost=PVEFrame or LFGParentFrame
expectedHost.left=16
expectedHost.right=486
if arg[3]=="sidebar" then
    local sidebar=make("Button","PVEFrameTab3",expectedHost)
    sidebar:SetSize(49,49)
    sidebar.left=491
end
local oldRed=CreateFrame("Button","ForeverDungeonFinderGroupFinderTab",expectedHost)
oldRed:SetText("Вход в подземелье")
oldRed:SetSize(166,25)
local oldPane=CreateFrame("Frame","ForeverDungeonFinderGroupFinderPane",expectedHost)
function ShowUIPanel(frame) frame:Show() end

local file=arg[1]
assert(file,"usage: lua tests/fixtures/native-dungeon-tab.lua <source>")
assert(loadfile(file))()
assert(not _G.ForeverDungeonFinderFrame,"Old standalone window was recreated")
assert(not _G.ForeverDungeonFinderMinimapButton,"Old minimap button was recreated")
local tab=_G.ForeverDungeonPortalTab
local pane=_G.ForeverDungeonFinderPane
assert(tab and pane,"Native tab or embedded pane missing")
assert(tab.parent==expectedHost and pane.parent==expectedHost,"Pane is not inside stock LFG")
assert(tab:GetWidth()==50 and tab:GetHeight()==50,"Tab is not a properly sized portal icon")
assert(not oldRed:IsShown() and not oldPane:IsShown(),"Obsolete top red button or overlay remains visible")
assert(tab:GetNumPoints()>=1,"Portal must be anchored")
local a=tab.lastAnchor
assert(a and a[1]=="TOPLEFT","Portal anchor must use top-left placement")
if arg[3]=="sidebar" then
    assert(a[2]==_G.PVEFrameTab3 and a[3]=="BOTTOMLEFT" and a[4]==0 and a[5]==-6,
        "Portal must follow native right-hand sidebar third tab")
else
    assert(a[2]==expectedHost and a[3]=="TOPRIGHT" and a[4]==4 and a[5]==-249,
        "Portal fallback must live OUTSIDE the native top filter area")
end
assert(pane.opaqueBackground and pane.opaqueBackground.texture and pane.opaqueBackground.texture:find("WHITE8X8",1,true),"Missing reliable opaque background texture")
assert(pane.opaqueBackground.rgba and pane.opaqueBackground.rgba[4]==1,"Dungeon panel must have alpha 1")
assert(pane:GetFrameLevel()>expectedHost:GetFrameLevel()+50,"Native content may draw over dungeon panel")
assert(not pane:IsShown(),"Pane should initially be hidden")
assert(type(SlashCmdList.FOREVERDUNGEONFINDER)=="function","/fd missing")
SlashCmdList.FOREVERDUNGEONFINDER()
assert(expectedHost:IsShown() and pane:IsShown(),"Slash command did not open embedded pane")
oldRed:Show()
assert(not oldRed:IsShown(),"Old button revived after OnShow")
assert(not oldRed:IsShown(),"Obsolete red header button must stay hidden after opening")
assert(tab.checked,"Native square was not selected")
local function findButton(text)
    for _,v in ipairs(frames) do
        if v.kind=="Button" and v.text==text then return v end
    end
end
local search
for _,v in ipairs(frames) do if v.kind=="EditBox" then search=v end end
assert(search and search.scripts.OnTextChanged,"Missing in-window dungeon filter")
search:SetText("зул")
search.scripts.OnTextChanged(search)
local filtered
for _,v in ipairs(frames) do
    if v.kind=="Button" and rawget(v,"data") and v.data.name=="Зул'Фаррак" and v:IsShown() then
        filtered=v
    end
end
assert(filtered,"Case-insensitive Cyrillic dungeon search failed")
search:SetText("")
search.scripts.OnTextChanged(search)
local solo=findButton("Войти соло")
local group=findButton("Группой")
assert(solo and group,"In-pane action buttons missing")
assert(group.enabled==false,"Group action must be disabled for solo player")
solo.scripts.OnClick()
assert(#messages==1 and messages[1][1]=="FDF" and messages[1][2]=="SOLO:389" and messages[1][3]=="WHISPER","Solo message mismatch")
now=23
function IsInGroup() return true end
function GetNumGroupMembers() return 3 end
local event
for _,v in ipairs(frames) do
    if v.kind=="Frame" and v.scripts.OnEvent and v ~= pane then event=v end
end
assert(event,"Missing refresh event listener")
event.scripts.OnEvent(event,"GROUP_ROSTER_UPDATE")
assert(group.enabled==true,"Group action not enabled for group leader")
group.scripts.OnClick()
assert(#messages==2 and messages[2][2]=="GROUP:389" and messages[2][3]=="PARTY","Premade-group request mismatch")
tab.scripts.OnClick(tab)
assert(not pane:IsShown() and not tab.checked,"Square does not close embedded pane")
print("Native dungeon UI smoke passed: embedded frame, portal square, FDF solo/group")
