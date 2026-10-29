import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

spec=importlib.util.spec_from_file_location('mpq_export',Path(__file__).parents[1]/'scripts/extract-ascension-dbc.py')
export=importlib.util.module_from_spec(spec);spec.loader.exec_module(export)

class Reader:
    def __init__(self): self.closed=[]
    def open(self,path): return path.name
    def close(self,handle): self.closed.append(handle)
    def read(self,handle,member):
        if member.endswith('Spell.dbc'): return b'WDBC'+b'\0'*16+(b'custom' if 'patch' in handle else b'base')
        return None

class MPQExportTests(unittest.TestCase):
    def test_variants_manifest_dedup_and_client_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'Client Data';data.mkdir()
            for name in ['common.MPQ','duplicate.mpq','patch-A.MPQ']: (data/name).write_bytes(b'archive')
            reader=Reader();out=root/'export.zip';report=export.extract(data,out,reader)
            self.assertEqual(len(reader.closed),3)
            with zipfile.ZipFile(out) as z:
                self.assertEqual(len(z.namelist()),3)
                manifest=json.loads(z.read('manifest.json'));self.assertEqual(len(manifest['tables']),3)
                self.assertEqual(len({r['sha256'] for r in report['tables']}),2)
            self.assertTrue(all(p.read_bytes()==b'archive' for p in data.iterdir()))
            with self.assertRaises(FileExistsError):export.extract(data,out,reader)
            with self.assertRaises(ValueError):export.extract(data,data/'export.zip',reader)

    def test_partial_patch_is_reported_and_handle_closed(self):
        class Partial(Reader):
            def read(self,handle,member): return b'PTCH'+b'\0'*20 if member.endswith('Spell.dbc') else None
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'Data';data.mkdir();(data/'patch.mpq').touch();reader=Partial()
            report=export.extract(data,root/'export.zip',reader)
            self.assertFalse(report['tables']);self.assertEqual(len(report['errors']),1);self.assertEqual(reader.closed,['patch.mpq'])

    def test_target_archive_only_and_split_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'Data';data.mkdir()
            for name in ['common.MPQ','patch-T.MPQ']:(data/name).touch()
            report=export.extract(data,root/'tables.zip',Reader(),'PATCH-T.MPQ',('Spell',))
            self.assertEqual(report['archives'],['patch-T.MPQ'])
            self.assertEqual(len(report['tables']),1)
            original=(root/'tables.zip').read_bytes()
            parts=export.split_export(root/'tables.zip',64)
            self.assertEqual(b''.join(p.read_bytes() for p in parts),original)
            with self.assertRaises(FileExistsError):export.split_export(root/'tables.zip',64)

    def test_storm_reads_large_table_in_bounded_chunks(self):
        import ctypes as C
        class Library:
            def __init__(self):self.pos=0;self.calls=[];self.closed=False
            def SFileOpenFileEx(self,a,b,c,p):p._obj.value=1;return True
            def SFileGetFileSize(self,h,high):high._obj.value=0;return len(payload)
            def SFileReadFile(self,h,target,count,got,unused):
                self.calls.append(count);C.memmove(target,payload[self.pos:self.pos+count],count)
                self.pos+=count;got._obj.value=count;return True
            def SFileCloseFile(self,h):self.closed=True
        payload=b'WDBC'+b'0'*(2*1024*1024+7)
        reader=export.Storm.__new__(export.Storm);reader.lib=Library();reader.max_size=len(payload)
        with reader.read(None,'DBFilesClient\\Spell.dbc') as content:
            self.assertEqual(content.read(),payload)
        self.assertTrue(reader.lib.closed)
        self.assertLessEqual(max(reader.lib.calls),1024*1024)
        reader.lib=Library();reader.max_size=128
        with self.assertRaises(RuntimeError):reader.read(None,'DBFilesClient\\Spell.dbc')
        self.assertTrue(reader.lib.closed)
