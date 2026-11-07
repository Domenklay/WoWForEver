-- Shared Forever palette: the same solid surfaces and fine gold rules used by
-- Encyclopedia and Dungeon Finder. All dimensions are UI pixels, never a scaled
-- copy of a standalone dialog inside the native talent window.
local P={RowHeight=60}
ForeverAscensionPresentation=P
local GOLD={0.82,0.59,0.24}
local PALE={0.96,0.87,0.72}
local MUTED={0.67,0.61,0.53}
local DEEP={0.046,0.030,0.022}
local BROWN={0.10,0.065,0.037}
local function solid(parent,layer,color)
 local t=parent:CreateTexture(nil,layer or "BACKGROUND")
 t:SetTexture("Interface\\Buttons\\WHITE8X8");t:SetVertexColor(color[1],color[2],color[3],color[4] or 1)
 return t
end
local function font(f,size,color)
 f:SetFont(STANDARD_TEXT_FONT or "Fonts\\FRIZQT__.TTF",size,"")
 f:SetTextColor(unpack(color or PALE));f:SetShadowOffset(1,-1)
end
local function place(f,parent,x,y,w,h)
 if f.SetParent then f:SetParent(parent) end
 f:ClearAllPoints();f:SetPoint("TOPLEFT",parent,"TOPLEFT",x,-y)
 if w then f:SetWidth(w) end;if h then f:SetHeight(h) end
end
local function surface(f,color,outline)
 if f.SetBackdrop then f:SetBackdrop(nil) end
 if not f.foreverFill then f.foreverFill=solid(f,"BACKGROUND",color);f.foreverFill:SetAllPoints() end
 f.foreverFill:SetVertexColor(unpack(color))
 if outline and not f.foreverRules then
  f.foreverRules={}
  for _,spec in ipairs({{"TOPLEFT","TOPRIGHT",nil,1},{"BOTTOMLEFT","BOTTOMRIGHT",nil,1},{"TOPLEFT","BOTTOMLEFT",1,nil},{"TOPRIGHT","BOTTOMRIGHT",1,nil}}) do
   local t=solid(f,"BORDER",GOLD);t:SetPoint(spec[1],f,spec[1]);t:SetPoint(spec[2],f,spec[2]);if spec[3] then t:SetWidth(spec[3]) else t:SetHeight(spec[4]) end
   f.foreverRules[#f.foreverRules+1]=t
  end
 end
end
function P.Button(parent,text,width,fn)
 local b=CreateFrame("Button",nil,parent,"UIPanelButtonTemplate");b:SetSize(width,28)
 local word=b.GetFontString and b:GetFontString()
 if type(word)~="table" and type(word)~="userdata" then word=b:CreateFontString(nil,"OVERLAY","GameFontHighlight");word:SetPoint("CENTER");b:SetFontString(word) end
 b.Text=word;font(word,13,PALE);b:SetText(text);b:SetScript("OnClick",fn)
 return b
end
function P.BranchButton(parent,fn)
 local ok,b=pcall(CreateFrame,"Button",nil,parent,"TabSystemButtonArtTemplate")
 if not ok then return P.Button(parent,"",160,fn) end
 b.isTabOnTop=true;b.selectedFontObject=GameFontHighlight or "GameFontHighlight";b.unselectedFontObject=GameFontNormal or "GameFontNormal"
 if b.HandleRotation then b:HandleRotation() end
 b:SetSize(160,32);b:SetText("");b:SetScript("OnClick",fn);b.foreverNativeArt=true
 return b
end
function P.Panel(parent,x,y,w,h)
 local f=CreateFrame("Frame",nil,parent,"InsetFrameTemplate");place(f,parent,x,-y,w,h);surface(f,BROWN,false);return f
end
function P.ClassButton(b,selected,active)
 if not b.foreverFill then
  surface(b,DEEP,false)
  b.foreverAccent=solid(b,"ARTWORK",GOLD);b.foreverAccent:SetPoint("TOPLEFT");b.foreverAccent:SetPoint("BOTTOMLEFT");b.foreverAccent:SetWidth(3)
  b:SetScript("OnEnter",function() if not b.foreverSelected then b.foreverFill:SetVertexColor(0.16,0.11,0.06,1) end end)
  b:SetScript("OnLeave",function() if not b.foreverSelected then b.foreverFill:SetVertexColor(unpack(DEEP)) end end)
 end
 b.foreverSelected=selected
 b.foreverFill:SetVertexColor(selected and 0.25 or DEEP[1],selected and 0.16 or DEEP[2],selected and 0.065 or DEEP[3],1)
 b.foreverAccent:SetShown(selected or active);b.glow:Hide()
 b.name:SetTextColor(unpack(selected and {1,0.87,0.48} or PALE))
end
function P.Row(n,width)
 if n.foreverStyledWidth==width then return end
 n.foreverStyledWidth=width
 n:SetWidth(width)
 if not n.foreverFill then
  n.foreverFill=solid(n,"BACKGROUND",{0.14,0.10,0.06,0.35});n.foreverFill:SetAllPoints()
  local line=solid(n,"BORDER",{0.30,0.23,0.14,0.6});line:SetPoint("BOTTOMLEFT",6,0);line:SetPoint("BOTTOMRIGHT",-6,0);line:SetHeight(1)
 end
 n:SetHeight(P.RowHeight);n.icon:SetSize(40,40);n.icon:ClearAllPoints();n.icon:SetPoint("TOPLEFT",8,-9);n.border:SetSize(55,55)
 place(n.name,n,60,9,math.max(100,width-70),29);font(n.name,14,PALE);n.name:SetWordWrap(true);n.name:SetMaxLines(2)
 place(n.note,n,60,39,math.max(100,width-70),16);font(n.note,12,MUTED)
end
function P.Apply(w,r,width,height)
 width=math.max(900,width);height=math.max(540,height)
 surface(w,DEEP,false)
 local margin,gap=16,12
 local sidebar=math.floor(math.max(174,math.min(196,width*0.165)))
 local ability=math.floor(math.max(292,math.min(338,width*0.28)))
 local bodyY,bodyH=94,height-138
 local ax=margin+sidebar+gap;local tx=ax+ability+gap;local tw=width-tx-margin
 r.width=width;r.height=height;r.abilityWidth=ability-38;r.talentWidth=tw-40;r.talentX=tx
 place(r.sidebar,w,margin,bodyY,sidebar,bodyH)
 place(r.abilities,w,ax,bodyY,ability,bodyH)
 place(r.talents,w,tx,bodyY,tw,bodyH)
 surface(r.sidebar,{0.015,0.012,0.010,0.78},false)
 surface(r.abilities,{0.01,0.01,0.01,0.80},false);surface(r.talents,{0.01,0.01,0.01,0.40},false)
 if not r.pageTitle then
  r.pageTitle=w:CreateFontString(nil,"OVERLAY","GameFontNormalLarge");r.pageTitle:SetText("Мультикласс")
  r.classTitle=r.sidebar:CreateFontString(nil,"OVERLAY","GameFontNormal");r.classTitle:SetText("КЛАССЫ")
  r.searchHint=r.search:CreateFontString(nil,"OVERLAY","GameFontHighlight");r.searchHint:SetPoint("LEFT",8,0);r.searchHint:SetText("Поиск способности");font(r.searchHint,13,MUTED)
  r.footer=solid(w,"BACKGROUND",BROWN);r.footer:SetPoint("BOTTOMLEFT",0,0);r.footer:SetPoint("BOTTOMRIGHT",0,0);r.footer:SetHeight(34)
  r.classArt={};for i=1,3 do local t=w:CreateTexture(nil,"BACKGROUND",nil,1);r.classArt[i]=t end
  r.nativeBackground=r.talents:CreateTexture(nil,"BACKGROUND",nil,1);r.nativeBackground:SetAllPoints();r.nativeBackground:SetAlpha(0.85)
  r.watermark=r.talents:CreateTexture(nil,"BACKGROUND");r.watermark:SetTexture("Interface\\GLUES\\CHARACTERCREATE\\UI-CHARACTERCREATE-CLASSES");r.watermark:SetSize(220,220);r.watermark:SetPoint("BOTTOMRIGHT",-24,40);r.watermark:SetAlpha(0.075)
  r.emptyCard=CreateFrame("Frame",nil,r.talents)
  r.emptyIcon=r.emptyCard:CreateTexture(nil,"ARTWORK");r.emptyIcon:SetTexture("Interface\\Icons\\INV_Misc_Book_11");r.emptyIcon:SetSize(46,46);r.emptyIcon:SetPoint("TOP",0,0)
  r.emptyTitle=r.emptyCard:CreateFontString(nil,"OVERLAY","GameFontNormalLarge");r.emptyTitle:SetPoint("TOP",r.emptyIcon,"BOTTOM",0,-18);font(r.emptyTitle,20,GOLD)
  r.emptyText=r.emptyCard:CreateFontString(nil,"OVERLAY","GameFontHighlight");r.emptyText:SetPoint("TOP",r.emptyTitle,"BOTTOM",0,-14);font(r.emptyText,14,PALE);r.emptyText:SetJustifyH("CENTER");r.emptyText:SetWordWrap(true)
  r.nativeTalents=P.Button(r.emptyCard,"Открыть родные таланты",232,function() if ForeverAscensionNativeTalentTab then ForeverAscensionNativeTalentTab.Close() end end)
  r.nativeTalents:SetPoint("TOP",r.emptyText,"BOTTOM",0,-22)
 end
 place(r.pageTitle,w,margin+8,14,300,26);font(r.pageTitle,22,GOLD)
 place(r.summary,w,margin+8,44,width-440,18);font(r.summary,13,PALE)
 place(r.progress,w,margin+8,65,width-530,16);font(r.progress,12,MUTED)
 r.search:ClearAllPoints();r.search:SetPoint("TOPRIGHT",w,"TOPRIGHT",-148,-19);r.search:SetSize(218,26);r.search:SetFontObject("GameFontHighlight")
 r.reload:ClearAllPoints();r.reload:SetPoint("TOPRIGHT",w,"TOPRIGHT",-margin,-18);r.reload:SetSize(112,28)
 r.activate:ClearAllPoints();r.activate:SetPoint("TOPRIGHT",w,"TOPRIGHT",-margin,-56);r.activate:SetSize(168,26)
 r.xp:ClearAllPoints();r.xp:SetPoint("TOPRIGHT",w,"TOPRIGHT",-426,-56)
 font(r.xpLabel,12,PALE)
 place(r.classTitle,r.sidebar,10,12,sidebar-20,18);font(r.classTitle,12,MUTED)
 local row=math.max(30,math.min(42,math.floor((bodyH-38)/#r.order)))
 for i,id in ipairs(r.order) do
  local b=r.classes[id];place(b,r.sidebar,4,34+(i-1)*row,sidebar-8,row-1)
  b.icon:ClearAllPoints();b.icon:SetPoint("LEFT",9,0);b.icon:SetSize(30,30)
  if b.border then b.border:SetSize(42,42) end
  b.name:ClearAllPoints();b.name:SetPoint("LEFT",b.icon,"RIGHT",10,0);b.name:SetWidth(sidebar-64);font(b.name,14,PALE)
  P.ClassButton(b,false,false)
 end
 place(r.abilityTitle,r.abilities,16,14,ability-32,23);font(r.abilityTitle,18,GOLD)
 place(r.selected,r.abilities,16,40,ability-32,20);font(r.selected,14,PALE)
 r.abilityScroll:ClearAllPoints();r.abilityScroll:SetPoint("TOPLEFT",r.abilities,"TOPLEFT",8,-72);r.abilityScroll:SetPoint("BOTTOMRIGHT",r.abilities,"BOTTOMRIGHT",-30,44)
 r.abilityCanvas:SetWidth(r.abilityWidth)
 r.filter:ClearAllPoints();r.filter:SetPoint("BOTTOMLEFT",r.abilities,"BOTTOMLEFT",12,10);r.filter:SetSize(ability-24,25)
 r.find:ClearAllPoints();r.find:SetPoint("BOTTOMRIGHT",r.talents,"BOTTOMRIGHT",-12,10);r.find:SetSize(166,25)
 r.hint:Hide()
 place(r.talentTitle,r.talents,16,14,tw-155,24);font(r.talentTitle,18,GOLD)
 r.points:ClearAllPoints();r.points:SetPoint("TOPRIGHT",r.talents,"TOPRIGHT",-16,-20);font(r.points,12,PALE)
 r.talentScroll:ClearAllPoints();r.talentScroll:SetPoint("TOPLEFT",r.talents,"TOPLEFT",12,-82);r.talentScroll:SetPoint("BOTTOMRIGHT",r.talents,"BOTTOMRIGHT",-30,45)
 r.talentCanvas:SetWidth(r.talentWidth)
 for i,t in ipairs(r.classArt) do place(t,w,(i-1)*width/3,bodyY,width/3,bodyH) end
 r.emptyCard:ClearAllPoints();r.emptyCard:SetPoint("CENTER",r.talents,"CENTER",0,-4);r.emptyCard:SetSize(math.min(440,tw-56),236)
 r.emptyText:SetWidth(math.min(420,tw-64));r.emptyText:SetHeight(74)
 r.emptyTitle:SetWidth(tw-60);r.emptyTitle:SetJustifyH("CENTER")
 place(r.message,w,24,height-25,width-48,19);font(r.message,12,MUTED)
end
function P.Refresh(r,context)
 if not r.width then return end
 r.watermark:Hide()
 local schools=ForeverAscensionSchools
 local atlas=schools and schools.Background(context.school)
 if atlas then r.nativeBackground:SetAtlas(atlas);r.nativeBackground:Show() else r.nativeBackground:Hide() end
 for i,t in ipairs(r.classArt) do
  local row=schools and schools.schools[context.owner] and schools.schools[context.owner][i]
  local art=schools and schools.Background(row)
  if art then t:SetAtlas(art);t:SetAlpha(0.70);t:Show() else t:Hide() end
 end
 local empty=context.talents==0
 r.emptyCard:SetShown(empty);r.talentScroll:SetShown(not empty)
 r.oldEmpty:Hide()
 r.searchHint:SetShown((r.search:GetText() or "")=="")
 if empty then
  local primary=context.primary
  r.emptyTitle:SetText(primary and "Таланты основного класса" or "Дерево подкласса")
  r.emptyText:SetText(context.native and "В этой ветке нет талантов по выбранному фильтру.\nВыберите другую ветку или очистите поиск." or primary and "Ваше родное дерево доступно во вкладке «Основное».\nСпособности класса можно просматривать слева." or "Деревья подклассов станут доступны после обновления сервера.\nСейчас можно выбирать и изучать способности слева.")
  r.nativeTalents:SetShown(primary and not context.native)
 end
 for i,b in ipairs(r.tabs) do
  if b.tab then
   b:SetParent(r.talents)
   local tabWidth=math.min(160,(r.talentWidth+8)/math.max(1,context.branches)-6)
   place(b,r.talents,16+(i-1)*(tabWidth+6),47,tabWidth,32)
   local selected=b.tab==context.selectedTab
   if b.foreverNativeArt and b.SetTabSelected then b:SetTabSelected(selected) end
   if b.Text then font(b.Text,13,PALE);b.Text:SetWidth(tabWidth-18);b.Text:SetHeight(18) end
  end
 end
 for _,n in ipairs(r.rows) do P.Row(n,r.abilityWidth) end
end
