import ctypes
import ctypes.util
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).parents[1]
MODULE=ROOT/'mods/forever-advancement'


def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/name)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


class AdvancementTests(unittest.TestCase):
    def test_catalog_retains_all_original_fields_and_reproducible_outputs(self):
        importer=load('import-ascension-content.py')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in ['catalog','addon/ForeverAscension','server','sql']:(root/name).mkdir(parents=True)
            for name in [p.name for p in (MODULE/'catalog').glob('*.json')]:
                shutil.copy2(MODULE/'catalog'/name,root/'catalog'/name)
            result=importer.generate(root)
            self.assertEqual(result['entries'],23709)
            for name in ['addon/ForeverAscension/Catalog.lua','server/AscensionCatalog.h','sql/world.sql']:
                self.assertEqual((root/name).read_bytes(),(MODULE/name).read_bytes())
            data=json.loads((root/'catalog/CharacterAdvancementData.json').read_text())
            data.append(data[0]);(root/'catalog/CharacterAdvancementData.json').write_text(json.dumps(data))
            with self.assertRaises(ValueError):importer.generate(root)

    def test_archive_member_paths_are_not_extracted(self):
        importer=load('import-ascension-content.py')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in ['catalog','addon/ForeverAscension','server','sql']:(root/name).mkdir(parents=True)
            archive=root/'content.zip'
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('../outside','untrusted')
                for name in ['CharacterAdvancementData.json','SpellRankData.json']:
                    z.writestr('Content/'+name,(MODULE/'catalog'/name).read_bytes())
            importer.import_archive(archive,root)
            self.assertFalse((root.parent/'outside').exists())

    def test_new_addon_replaces_old_and_rollback_preserves_both(self):
        installer=load('install-advancement-addon.py')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);client=root/'client';client.mkdir();(client/'WowB.exe').write_bytes(b'unchanged')
            addons=client/'Interface/AddOns';addons.mkdir(parents=True)
            for name in installer.NAMES:
                (addons/name).mkdir();(addons/name/'custom.lua').write_text(name)
            backup=root/'backup';target=installer.install(client,backup)
            self.assertTrue((target/'Catalog.lua').is_file())
            self.assertFalse((addons/'ForeverSubclass').exists())
            with self.assertRaises(FileExistsError):installer.install(client,backup)
            (target/'user.lua').write_text('new user changes')
            installer.restore(backup)
            for name in installer.NAMES:self.assertEqual((addons/name/'custom.lua').read_text(),name)
            self.assertEqual((backup/'before-restore/ForeverAscension/user.lua').read_text(),'new user changes')
            self.assertEqual((client/'WowB.exe').read_bytes(),b'unchanged')

    def test_first_install_rollback_and_symlink_rejection(self):
        installer=load('install-advancement-addon.py')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);client=root/'client';client.mkdir();(client/'WowB.exe').touch()
            installer.install(client,root/'backup');installer.restore(root/'backup')
            self.assertFalse((client/'Interface/AddOns/ForeverAscension').exists())
            (client/'Interface/AddOns/ForeverSubclass').symlink_to(root,target_is_directory=True)
            with self.assertRaises(ValueError):installer.install(client,root/'second')

    def test_injection_removes_old_engine_and_is_repeatable(self):
        injector=load('inject-advancement.py')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);custom=root/'src/server/scripts/Custom';custom.mkdir(parents=True)
            loader=custom/'custom_script_loader.cpp'
            loader.write_text('void AddSC_forever_subclass();\nvoid AddCustomScripts()\n{\n    AddSC_forever_subclass();\n}\n')
            (custom/'ForeverSubclass').mkdir();(custom/'ForeverSubclass/old.cpp').touch()
            injector.inject(root);first=loader.read_text();injector.inject(root)
            self.assertEqual(loader.read_text(),first)
            self.assertNotIn('forever_subclass',first)
            self.assertEqual(first.count('    AddSC_forever_advancement();'),1)
            self.assertFalse((custom/'ForeverSubclass').exists())


MOCK=r'''
_G=_G or _ENV
unpack=table.unpack
frames={};named={};sent={};SlashCmdList={};UISpecialFrames={}
local methods={}
function methods:SetScript(k,f) self.scripts[k]=f end
function methods:Show() self.shown=true end
function methods:Hide() self.shown=false end
function methods:IsShown() return self.shown~=false end
function methods:SetEnabled(value) self.enabled=value end
function methods:SetText(text) self.text=text end
function methods:GetText() return self.text or '' end
function methods:SetValue(value) self.value=value end
function methods:SetMinMaxValues(lo,hi) self.maximum=hi end
local function object(kind,name,parent)
 local o={kind=kind,name=name,parent=parent,scripts={}}
 setmetatable(o,{__index=function(_,key) return methods[key] or (key:match('^[A-Z]') and function() end) end})
 table.insert(frames,o);if name then named[name]=o;_G[name]=o end;return o
end
function methods:CreateTexture() return object('Texture',nil,self) end
function methods:CreateFontString() return object('Font',nil,self) end
function CreateFrame(kind,name,parent,template)
 local o=object(kind,name,parent)
 if template=='BasicFrameTemplateWithInset' then o.TitleText=object('Font',nil,o) end
 return o
end
UIParent=CreateFrame('Frame');PlayerFrame=CreateFrame('Frame')
GameTooltip=object('Tooltip')
local now=100
function GetTime() return now end
function advance() now=now+1 end
function UnitName() return 'Tester' end
function GetUnitName() return 'Tester-Realm' end
function UnitAffectingCombat() return false end
function UnitPowerMax(_,power) return power==1 and 100 or 0 end
function UnitPower() return 25 end
C_ChatInfo={RegisterAddonMessagePrefix=function() end,SendAddonMessage=function(prefix,text,channel,target) table.insert(sent,text);return true end}
'''


@unittest.skipUnless(ctypes.util.find_library('lua5.4'),'Lua 5.4 required')
class AdvancementUITests(unittest.TestCase):
    def lua(self,assertions):
        lib=ctypes.CDLL(ctypes.util.find_library('lua5.4'))
        lib.luaL_newstate.restype=ctypes.c_void_p;lib.luaL_openlibs.argtypes=[ctypes.c_void_p]
        lib.luaL_loadstring.argtypes=[ctypes.c_void_p,ctypes.c_char_p]
        lib.lua_pcallk.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_longlong,ctypes.c_void_p]
        lib.lua_tolstring.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p];lib.lua_tolstring.restype=ctypes.c_char_p
        lib.lua_close.argtypes=[ctypes.c_void_p];state=lib.luaL_newstate()
        try:
            lib.luaL_openlibs(state)
            for chunk in [MOCK,(MODULE/'addon/ForeverAscension/Catalog.lua').read_text(),
                          (MODULE/'addon/ForeverAscension/ForeverAscension.lua').read_text()+'\n'+assertions]:
                status=lib.luaL_loadstring(state,chunk.encode())
                if not status:status=lib.lua_pcallk(state,0,0,0,0,None)
                if status:self.fail(lib.lua_tolstring(state,-1,None).decode())
        finally:lib.lua_close(state)

    def test_real_catalog_menu_and_mixed_class_purchases_survive_filter_and_polls(self):
        self.lua(r'''
assert(#ForeverAscensionCatalog==23709)
SlashCmdList.FOREVERASCENSION('')
assert(named.ForeverAscensionWindow:IsShown() and sent[#sent]=='status')
local mage,priest
for _,row in ipairs(ForeverAscensionCatalog) do
 if row.Class=='Mage' and row.Type=='Ability' and row.Name=='Frostbolt' and not mage then mage=row.ID end
 if row.Class=='Priest' and row.Type=='Ability' and row.Name=='Flash Heal' and not priest then priest=row.ID end
end
assert(mage and priest)
parse('STATE 1 20 2 8');parse('CATALOG')
parse('ENTRY '..mage..' 116 4 0 8');parse('ENTRY '..priest..' 2061 20 0 5')
parse('POWER 0 400 500');parse('POWER 1 25 100');parse('POWER 3 90 100')
parse('LEARNED '..mage);parse('LEARNED '..priest);parse('END')
assert(state.learned[mage] and state.learned[priest])
assert(powerBars[1].value==400 and powerBars[2].value==90 and powerBars[3].value==25)
classButtons[5].scripts.OnClick()
assert(selectedClass==5 and state.learned[mage] and state.learned[priest])
parse('STATE 1 20 2 8');parse('LEARNED '..mage);parse('LEARNED '..priest);parse('END')
assert(compatible[mage] and compatible[priest])
advance();actionButtons[1].scripts.OnClick(actionButtons[1]);assert(sent[#sent]:match('^cast '))
selectedClass=8;selectedTab=nil;page=1;filter='frostbolt';refresh()
local clicked=false
for _,n in ipairs(abilityNodes) do if n.entry and n.entry.ID==mage then advance();n.scripts.OnClick(n,'LeftButton');clicked=true end end
assert(clicked and sent[#sent]=='unlearn '..mage)
''')

    def test_unadapted_talents_and_native_primary_cannot_be_purchased(self):
        self.lua(r'''
open();parse('STATE 8 20 0 8');parse('END')
local row=byClass[8][1]
local b=abilityNodes[1];b.entry=row
advance();local count=#sent;b.scripts.OnClick(b,'LeftButton');assert(#sent==count)
compatible[row.ID]={owner=8,level=1,spell=116}
b.scripts.OnClick(b,'LeftButton');assert(#sent==count)
parse('ERROR ability_limit');assert(message.text==errors.ability_limit)
''')


if __name__=='__main__':unittest.main()
