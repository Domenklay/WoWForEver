"""Execute the real probe with a CASC API double that only resolves FileDataIDs."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
HEADER=r'''
#pragma once
#include <cstdint>
#include <cstring>
using DWORD=unsigned;using ULONGLONG=unsigned long long;using HANDLE=void*;
constexpr DWORD CASC_LOCALE_RURU=0x2000,CASC_OPEN_BY_NAME=0,CASC_OPEN_BY_FILEID=3,CASC_STRICT_DATA_CHECK=0x10000;
#define CASC_FILE_DATA_ID(x) reinterpret_cast<void const*>(static_cast<uintptr_t>(x))
struct CASC_OPEN_STORAGE_ARGS { unsigned Size;char const* szLocalPath;char const* szCodeName;DWORD dwLocaleMask; };
inline bool CascOpenStorageEx(void*,CASC_OPEN_STORAGE_ARGS*,bool,HANDLE* s){*s=(void*)1;return true;}
inline unsigned GetCascError(){return 2;}
inline bool CascOpenFile(HANDLE,void const* key,DWORD,DWORD flags,HANDLE* f){
 if((flags&3)!=CASC_OPEN_BY_FILEID)return false;
 auto id=reinterpret_cast<uintptr_t>(key);
 if(id!=775971&&id!=782779&&id!=828395)return false;
 *f=(void*)id;return true;
}
inline bool CascGetFileSize64(HANDLE,ULONGLONG* n){*n=4;return true;}
inline bool CascReadFile(HANDLE,void* b,DWORD want,DWORD* got){std::memcpy(b,"WDT!",want);*got=want;return true;}
inline bool CascCloseFile(HANDLE){return true;}
inline bool CascCloseStorage(HANDLE){return true;}
'''

class OutlandFileIdTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('g++'),'g++ required')
    def test_failed_name_control_does_not_block_fileid_reads(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'CascLib.h').write_text(HEADER)
            exe=root/'probe'
            subprocess.run(['g++','-std=c++20','-O1','-I',str(root),str(ROOT/'tools/terrain-335/check-client-paths.cpp'),'-lcrypto','-o',str(exe)],check=True,capture_output=True)
            result=subprocess.run([str(exe),'owned-storage'],check=True,capture_output=True,text=True)
            report=json.loads(result.stdout)
            self.assertFalse(report['negative_name_lookup_proves_absence'])
            named=[f for f in report['files'] if f['open_by']=='name']
            self.assertTrue(named)
            self.assertTrue(all(f['status']=='OPEN_FAILED' for f in named))
            ids={f['file_id']:f for f in report['files'] if f['open_by']=='file_id'}
            for id in (775971,782779,828395):
                self.assertEqual(ids[id]['status'],'READ_OK')
                self.assertEqual(ids[id]['bytes_read'],4)
                self.assertEqual(ids[id]['sha256'],hashlib.sha256(b'WDT!').hexdigest())
            for id in (828853,828914,829190,829655):
                self.assertEqual(ids[id]['status'],'OPEN_FAILED')
