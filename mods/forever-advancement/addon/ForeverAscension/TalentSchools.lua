-- Native class school identities and Blizzard's own specialization artwork.
-- This is presentation metadata, never a substitute spell/talent catalogue.
local C={schools={},bySkill={}}
ForeverAscensionSchools=C
local definitions={
 {1,26,'arms','Оружие',71,'warrior-arms'},{1,256,'fury','Неистовство',72,'warrior-fury'},{1,257,'protection','Защита',73,'warrior-protection'},
 {2,56,'holy','Свет',65,'paladin-holy'},{2,267,'protection','Защита',66,'paladin-protection'},{2,184,'retribution','Воздаяние',70,'paladin-retribution'},
 {3,50,'beastmastery','Повелитель зверей',253,'hunter-beastmastery'},{3,163,'marksmanship','Стрельба',254,'hunter-marksmanship'},{3,51,'survival','Выживание',255,'hunter-survival'},
 {4,253,'assassination','Ликвидация',259,'rogue-assassination'},{4,38,'combat','Бой',260,'rogue-outlaw'},{4,39,'subtlety','Скрытность',261,'rogue-subtlety'},
 {5,613,'discipline','Послушание',256,'priest-discipline'},{5,594,'holy','Свет',257,'priest-holy'},{5,78,'shadow','Тьма',258,'priest-shadow'},
 {6,0,'blood','Кровь',250,'deathknight-blood'},{6,0,'frost','Лёд',251,'deathknight-frost'},{6,0,'unholy','Нечестивость',252,'deathknight-unholy'},
 {7,375,'elemental','Стихии',262,'shaman-elemental'},{7,373,'enhancement','Совершенствование',263,'shaman-enhancement'},{7,374,'restoration','Исцеление',264,'shaman-restoration'},
 {8,237,'arcane','Тайная магия',62,'mage-arcane'},{8,8,'fire','Огонь',63,'mage-fire'},{8,6,'frost','Лёд',64,'mage-frost'},
 {9,355,'affliction','Колдовство',265,'warlock-affliction'},{9,354,'demonology','Демонология',266,'warlock-demonology'},{9,593,'destruction','Разрушение',267,'warlock-destruction'},
 {10,0,'brewmaster','Хмелевар',268,'monk-brewmaster'},{10,0,'mistweaver','Ткач туманов',270,'monk-mistweaver'},{10,0,'windwalker','Танцующий с ветром',269,'monk-windwalker'},
 {11,574,'balance','Баланс',102,'druid-balance'},{11,134,'feral','Сила зверя',103,'druid-feral'},{11,573,'restoration','Исцеление',105,'druid-restoration'},
}
local upper,lower='АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯЁ','абвгдежзийклмнопрстуфхцчшщъыьэюяё'
local letters={};for i=1,#upper,2 do letters[upper:sub(i,i+1)]=lower:sub(i,i+1) end
local function normal(s) return (string.lower(s or ''):gsub('[\208\209][\128-\191]',function(c)return letters[c] or c end):gsub('[%s%p]','')) end
local aliases={beastmastery={'Beast Mastery'},shadow={'Shadow Magic','Темная магия'},feral={'Feral Combat'},elemental={'Elemental Combat'},combat={'Outlaw'}}
for _,d in ipairs(definitions) do
 local row={owner=d[1],skill=d[2],key=d[3],name=d[4],spec=d[5],atlas='talents-background-'..d[6],order=#(C.schools[d[1]] or {})+1}
 row.aliases={[normal(row.key)]=true,[normal(row.name)]=true}
 for _,name in ipairs(aliases[row.key] or {}) do row.aliases[normal(name)]=true end
 C.schools[row.owner]=C.schools[row.owner] or {};table.insert(C.schools[row.owner],row)
 if row.skill>0 then C.bySkill[row.skill]=row end
end
function C.Resolve(owner,tag,title,skill)
 local row=skill and C.bySkill[skill]
 if row and row.owner==owner then return row end
 local titleKey,tagKey=normal(title),normal(tag)
 for _,candidate in ipairs(C.schools[owner] or {}) do if candidate.aliases[titleKey] or candidate.aliases[tagKey] then return candidate end end
end
function C.IsMount(spell)
 if spell and C_MountJournal and C_MountJournal.GetMountFromSpell then
  local ok,id=pcall(C_MountJournal.GetMountFromSpell,spell);return ok and type(id)=='number' and id>0
 end
 return false
end
function C.Background(row)
 if not row then return end
 local atlas=row.atlas
 if ClassTalentUtil and ClassTalentUtil.GetVisualsForSpecID then local ok,v=pcall(ClassTalentUtil.GetVisualsForSpecID,row.spec);if ok and v and v.background then atlas=v.background end end
 if C_Texture and C_Texture.GetAtlasInfo then local ok,info=pcall(C_Texture.GetAtlasInfo,atlas);if ok and info then return atlas end end
end
