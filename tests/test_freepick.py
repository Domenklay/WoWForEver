"""Exercise actual C++ purchase policy; integration tests cover the shared injector/AddOn."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'mods/forever-subclass'

class FreepickTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('g++'), 'g++ required')
    def test_multiclass_purchase_cast_refund_and_reload(self):
        with tempfile.TemporaryDirectory() as temp:
            exe = Path(temp)/'freepick'
            subprocess.run(['g++', '-std=c++17', '-O2', '-I', str(MODULE/'vendor/include'),
                str(MODULE/'vendor/src/SubclassSystem.cpp'), str(MODULE/'vendor/tests/test_freepick.cpp'),
                '-o', str(exe)], check=True, capture_output=True)
            subprocess.run([str(exe)], check=True, capture_output=True)

    def test_mode_has_separate_storage_and_explicit_backup_installer(self):
        server=(MODULE/'server/ForeverSubclass.cpp').read_text()
        freepick_save=server.split('if (Freepick())\n    {\n        // Never write legacy')[1].split('CharacterDatabaseTransaction tx=CharacterDatabase.BeginTransaction();',2)[1]
        self.assertNotIn('forever_character_subclass_',freepick_save)
        installer=(ROOT/'scripts/subclass-mod.sh').read_text()
        self.assertLess(installer.index('gzip -t'),installer.index('set_freepick "$freepick_install"'))
        self.assertIn('cp "$backup/env.before" .env',installer)
        self.assertIn('check-subclass-ready.py --mode',installer)
        for table in ('state','spells','resources'):
            self.assertIn('forever_character_freepick_'+table,(MODULE/'sql/characters.sql').read_text())

    def test_addon_keeps_purchases_from_both_schools_when_filter_changes(self):
        import ctypes
        import ctypes.util
        library=ctypes.util.find_library('lua5.4')
        if not library:
            self.skipTest('Lua 5.4 required')
        lua=ctypes.CDLL(library)
        lua.luaL_newstate.restype=ctypes.c_void_p
        lua.luaL_openlibs.argtypes=[ctypes.c_void_p]
        lua.luaL_loadstring.argtypes=[ctypes.c_void_p,ctypes.c_char_p]
        lua.luaL_loadstring.restype=ctypes.c_int
        lua.lua_pcallk.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_longlong,ctypes.c_void_p]
        lua.lua_pcallk.restype=ctypes.c_int
        lua.lua_tolstring.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p]
        lua.lua_tolstring.restype=ctypes.c_char_p
        lua.lua_close.argtypes=[ctypes.c_void_p]
        source=(MODULE/'addon/ForeverSubclass/ForeverSubclassTalents.lua').read_text()
        script='''
CreateFrame=function() return {RegisterEvent=function() end,SetScript=function() end} end
local parse,getState,visible=assert(load([====[
'''+source+'''
return parse,function() return state end,visibleSpells
]====]))()
local function snapshot(filter,freepick)
 parse('STATE 1 '..filter..' 1 2 8 10000')
 if freepick then parse('MODE FREEPICK 1') end
 parse('CLASS 1 20 100 1000');parse('CLASS 5 20 0 1000');parse('CLASS 8 20 0 1000')
 parse('SPELL 2050 2050 1 1 30 0');parse('SPELL 116 116 4 1 25 0');parse('END')
end
snapshot(5,true)
assert(getState().freepick and #visible(getState())==2)
snapshot(8,true)
assert(getState().primary==1 and getState().xpTarget==1)
assert(getState().spells[2050].selected and getState().spells[116].selected)
assert(#visible(getState())==2)
snapshot(0,true) -- Clearing only the filter also preserves the purchased loadout.
assert(#visible(getState())==2)
snapshot(5,false) -- The opt-in mode must not leak across later legacy snapshots.
assert(not getState().freepick)
parse('STATE 2 5 2 1 8 10000');parse('MODE FREEPICK 1');parse('CLASS 2 20 0 1000')
parse('SPELL 2050 2050 1 1 30 0')
parse('CUSTOM 1463 10 0 1 2 2 0 36 0')
parse('CUSTOM 278016 20 0 1 2 2 768 36 0');parse('END')
local current=getState()
assert(#visible(current,'abilities')==1 and #visible(current,'custom')==2)
assert(current.spells[1463].custom and current.spells[1463].classesMet)
assert(not current.spells[1463].implemented)
assert(not current.spells[278016].classesMet)
parse('STATE 1 5 1 2 8 10000');parse('MODE FREEPICK 1');parse('CLASS 1 20 0 1000')
parse('CUSTOM 278016 20 0 1 2 2 768 770 0');parse('END')
assert(getState().spells[278016].classesMet)
assert(#visible(getState(),'abilities')==0 and #visible(getState(),'custom')==1)
'''
        state=lua.luaL_newstate()
        try:
            lua.luaL_openlibs(state)
            result=lua.luaL_loadstring(state,script.encode())
            if not result:
                result=lua.lua_pcallk(state,0,0,0,0,None)
            if result:
                self.fail(lua.lua_tolstring(state,-1,None).decode())
        finally:
            lua.lua_close(state)
