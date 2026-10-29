ForeverAscensionResourceBars={}
local bars=ForeverAscensionResourceBars
local values={}
local regen={}
local overlay,nativeBar,originalAlpha
local colors={[0]={0.08,0.30,0.85},[3]={0.95,0.73,0.06},[1]={0.78,0.08,0.08}}
local names={[0]="Мана",[3]="Энергия",[1]="Ярость"}
local function frame(value)
 if type(value)=="table" or type(value)=="userdata" then return value end
end
local function findBar()
 if frame(PlayerFrameManaBar) then return PlayerFrameManaBar end
 if not PlayerFrame then return nil end
 if frame(PlayerFrame.ManaBar) then return PlayerFrame.ManaBar end
 if frame(PlayerFrame.manabar) then return PlayerFrame.manabar end
 local content=frame(PlayerFrame.PlayerFrameContent)
 local main=content and frame(content.PlayerFrameContentMain)
 local area=main and frame(main.ManaBarArea)
 return (area and frame(area.ManaBar)) or (main and frame(main.ManaBar))
end
local function restore()
 if nativeBar and originalAlpha and nativeBar.SetAlpha then nativeBar:SetAlpha(originalAlpha) end
 if overlay then overlay:Hide() end
end
local function build()
 if overlay then return true end
 nativeBar=findBar()
 if not PlayerFrame then return false end
 overlay=CreateFrame("Frame","ForeverAscensionPortraitResources",PlayerFrame)
 if nativeBar then
  overlay:SetPoint("TOPLEFT",nativeBar,"TOPLEFT",-1,1)
  overlay:SetPoint("TOPRIGHT",nativeBar,"TOPRIGHT",1,1)
 else
  -- Some 70532 layouts expose the portrait but not their power-bar widget.
  -- Keep all three authoritative pools visible without depending on that name.
  overlay:SetPoint("TOPLEFT",PlayerFrame,"TOPLEFT",76,-52);overlay:SetWidth(122)
 end
 overlay:SetHeight(29);overlay:EnableMouse(false)
 overlay:SetFrameLevel((nativeBar and nativeBar.GetFrameLevel and nativeBar:GetFrameLevel() or PlayerFrame:GetFrameLevel())+5)
 local border=overlay:CreateTexture(nil,"BACKGROUND")
 border:SetAllPoints();border:SetColorTexture(0.12,0.08,0.025,1)
 for i,power in ipairs({0,3,1}) do
  local bar=CreateFrame("StatusBar",nil,overlay)
  bar:SetPoint("TOPLEFT",2,-2-(i-1)*9);bar:SetPoint("TOPRIGHT",-2,-2-(i-1)*9);bar:SetHeight(8)
  bar:SetStatusBarTexture("Interface\\TargetingFrame\\UI-StatusBar")
  bar:SetStatusBarColor(unpack(colors[power]));bar:EnableMouse(false)
  local background=bar:CreateTexture(nil,"BACKGROUND");background:SetAllPoints();background:SetColorTexture(0.015,0.015,0.015,1)
  bar.text=bar:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall");bar.text:SetPoint("CENTER")
  if bar.text.GetFont then local font=bar.text:GetFont();if font then bar.text:SetFont(font,8,"OUTLINE") end end
  bars[i]=bar
 end
 originalAlpha=nativeBar and nativeBar.GetAlpha and nativeBar:GetAlpha() or 1
 overlay:Hide();return true
end
local function refresh()
 if not next(values) or not build() then return end
 for i,power in ipairs({0,3,1}) do
  local data=values[power]
  if not data then restore();return end
  local current,maximum=data.current,data.maximum
  if UnitPowerMax and UnitPowerMax("player",power)>0 then current=UnitPower("player",power);maximum=UnitPowerMax("player",power) end
  bars[i]:SetMinMaxValues(0,math.max(1,maximum));bars[i]:SetValue(current)
  bars[i].text:SetText(names[power].." "..math.floor(current).." / "..math.floor(maximum));bars[i]:Show()
 end
 if nativeBar and nativeBar.SetAlpha and (not InCombatLockdown or not InCombatLockdown()) then nativeBar:SetAlpha(0) end
 overlay:Show()
end
function ForeverAscensionSetResources(powers,rates)
 values=powers or {};regen=rates or {};refresh()
end
function ForeverAscensionResourceValue(power)
 local p=values[power]
 if UnitPowerMax and UnitPowerMax("player",power)>0 then return UnitPower("player",power),UnitPowerMax("player",power) end
 if p then return p.current,p.maximum end
 return nil,nil
end
function ForeverAscensionManaRegen(combat)
 if UnitPowerMax and UnitPowerMax("player",0)>0 and GetManaRegen then
  local normal,battle=GetManaRegen();return combat and battle or normal
 end
 return combat and regen.combat or regen.normal
end
local events=CreateFrame("Frame")
for _,event in ipairs({"PLAYER_LOGIN","ADDON_LOADED","PLAYER_ENTERING_WORLD","UNIT_POWER_UPDATE","UNIT_MAXPOWER","UNIT_DISPLAYPOWER","UPDATE_SHAPESHIFT_FORM","PLAYER_REGEN_ENABLED","PLAYER_LOGOUT"}) do events:RegisterEvent(event) end
events:SetScript("OnEvent",function(_,event,unit)
 if event=="PLAYER_LOGOUT" then restore();return end
 if unit and unit~="player" and event:match("^UNIT_") then return end
 refresh()
end)
