-- Lua 5.1: exercise the real FEC1 parser, not only a UI bridge stub.
-- No network, database or game installation is used.
local dir=assert(arg[1])
SlashCmdList={}
local events
local pending={}
local outgoing={}
C_Timer={After=function(_,fn) pending[#pending+1]=fn end}
C_ChatInfo={
    RegisterAddonMessagePrefix=function() return true end,
    SendAddonMessage=function(prefix,msg)
        outgoing[#outgoing+1]={prefix=prefix,msg=msg}
        return true
    end
}
local function fakeFrame()
    local f={scripts={}}
    function f:RegisterEvent() end
    function f:SetScript(name,fn) self.scripts[name]=fn end
    events=f
    return f
end
CreateFrame=function() return fakeFrame() end
function wipe(t) for k in pairs(t) do t[k]=nil end end
local function split(delim,source)
    local out={}
    local start=1
    while true do
        local i,j=string.find(source,delim,start,true)
        if not i then out[#out+1]=string.sub(source,start);break end
        out[#out+1]=string.sub(source,start,i-1)
        start=j+1
    end
    return unpack(out)
end
strsplit=split
dofile(dir.."/ForeverEncyclopediaTalentData.lua")
dofile(dir.."/ForeverEncyclopediaTalentOverrides.lua")
dofile(dir.."/ForeverEncyclopediaV21.lua")
local bridge=assert(ForeverEncyclopediaUIBridge)
local state=bridge.state
assert(type(bridge.RequestFullCatalog)=="function")
assert(type(bridge.RequestFullArchive)=="function")
local function incoming(message)
    assert(events.scripts.OnEvent)
    events.scripts.OnEvent(events,"CHAT_MSG_ADDON","FER1",message)
end
local sentCatalog={}
local sentArchive={}
local function handleOutgoing(payload)
    if payload:match("^catalog ") then
        local page=tonumber(payload:match("^catalog (%d+)"))
        sentCatalog[#sentCatalog+1]=page
        incoming(("CATHEAD|7|%d|3|5|2|5|2"):format(page))
        local data={
            [1]={"CAT|33|1|1|0|Волк","CAT|42|0|0|0|"},
            [2]={"CAT|43|0|0|0|","CAT|44|0|0|0|"},
            [3]={"CAT|45|1|3|0|Демон"},
        }
        for _,line in ipairs(data[page] or {}) do incoming(line) end
        incoming("CATEND")
    elseif payload:match("^archive ") then
        local page=tonumber(payload:match("^archive (%d+)"))
        sentArchive[#sentArchive+1]=page
        incoming(("ARHEAD|%d|2|3"):format(page))
        local data={
            [1]={"AR|33|1|0|Волк|0|7","AR|500|3|1|Демон из пепла|1|88"},
            [2]={"AR|501|6|0|Забытый воин|1|88"},
        }
        for _,line in ipairs(data[page] or {}) do incoming(line) end
        incoming("AREND")
    else
        error("Unexpected FEC1 payload: "..payload)
    end
end

incoming("CURRENT 0 7 7")
incoming("CAPS ARCHIVE1")
assert(state.archiveSupported)
bridge.RequestFullCatalog()

local steps=0
while #pending>0 or #outgoing>0 do
    steps=steps+1
    assert(steps<60,"The catalogue transport loop is stuck")
    local callback=table.remove(pending,1)
    if callback then callback() end
    while #outgoing>0 do
        local msg=table.remove(outgoing,1)
        assert(msg.prefix=="FEC1")
        handleOutgoing(msg.msg)
    end
end

assert(state.catalogAllLoaded and not state.catalogAllLoading)
assert(state.archiveLoaded and not state.archiveLoading)
assert(#state.catalogAll==5,"Zone catalogue must combine all three server pages")
assert(#state.archiveAll==3,"Account archive must combine both server pages")
assert(table.concat(sentCatalog,",")=="1,2,3","Catalogue pages must arrive in order")
assert(table.concat(sentArchive,",")=="1,2","Account archive pages must arrive in order")
assert(state.archiveAll[2].zone==88 and state.archiveAll[2].entry==500)
assert(state.catalogAll[5].known==true and state.catalogAll[5].entry==45)
-- Repeat a catalogue load and abandon it before its queued first request is sent.
bridge.RequestFullCatalog()
incoming("CURRENT 0 99 99")
events.scripts.OnEvent(events,"ZONE_CHANGED_NEW_AREA")
local count=#sentCatalog
for _=1,5 do
    local callback=table.remove(pending,1)
    if callback then callback() end
end
assert(#sentCatalog==count,"Abandoned zone requests must not leak into the next zone")
print("ENCYCLOPEDIA PAGED CATALOGUE / GLOBAL ARCHIVE PROTOCOL MOCK PASSED")