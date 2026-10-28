import ctypes
import ctypes.util
import json
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class FreepickWindowTests(unittest.TestCase):
    def test_slash_opens_lazy_native_ui_or_standalone_and_preserves_commands(self):
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
        fixture=(ROOT/'tests/fixtures/freepick-open.lua').read_text()
        for native in (False,True):
            with self.subTest(native=native):
                state=lua.luaL_newstate()
                try:
                    lua.luaL_openlibs(state)
                    code='nativeUI='+str(native).lower()+'\naddonDir='+json.dumps(str(ROOT/'mods/forever-subclass/addon/ForeverSubclass'))+'\n'+fixture
                    status=lua.luaL_loadstring(state,code.encode())
                    if not status:status=lua.lua_pcallk(state,0,0,0,0,None)
                    if status:self.fail(lua.lua_tolstring(state,-1,None).decode())
                finally:
                    lua.lua_close(state)
