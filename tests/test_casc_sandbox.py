import hashlib
import csv
import io
import importlib.util
import os
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "casc_sandbox",Path(__file__).parents[1]/"scripts/build-casc-sandbox.py")
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


class CascSandboxTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('CASC_SANDBOX_CHECKER'), 'Native CascLib checker required')
    def test_native_streaming_hash_reads_resource_larger_than_one_mib(self):
        payload = (b'owned streaming fixture\0'+bytes(range(256)))*7000
        self.assertGreater(len(payload), 1024*1024)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'client'
            with patch.object(lab, 'BASE_TEXT', payload):
                lab.write_store(root)
            result = subprocess.run([os.environ['CASC_SANDBOX_CHECKER'],str(root),str(lab.BASE_ID)],
                                    capture_output=True,text=True,check=True,timeout=30)
            row = next(csv.DictReader(io.StringIO(result.stdout),delimiter='\t'))
            self.assertEqual(row['status'], 'READ_OK')
            self.assertEqual(int(row['bytes']), len(payload))
            self.assertEqual(row['sha256'], hashlib.sha256(payload).hexdigest())

    def test_lookup3_vectors(self):
        for text, expected in ((b"",0xDEADBEEF),(b"a",0x58D68708),
                               (b"abc",0x0E397631),(bytes(range(32)),0x21362CFE)):
            self.assertEqual(lab.hashlittle(text),expected)

    def test_blte_has_real_frame_checksum(self):
        obj = lab.asset(b"own synthetic bytes")
        self.assertEqual(obj["encoded"][:4],b"BLTE")
        self.assertEqual(struct.unpack_from(">I",obj["encoded"],4)[0],36)
        self.assertEqual(obj["ekey"],hashlib.md5(obj["encoded"][:36]).digest())
        self.assertEqual(obj["encoded"][20:36],hashlib.md5(obj["encoded"][36:]).digest())
        corrupted = obj["encoded"][36:-1] + bytes([obj["encoded"][-1]^1])
        self.assertNotEqual(obj["encoded"][20:36],hashlib.md5(corrupted).digest())

    def test_root_v2_supports_file_id_gaps(self):
        root = lab.make_root({100:lab.asset(b"a"),200:lab.asset(b"b")})
        self.assertEqual(struct.unpack_from("<5I",root,4),(24,2,2,0,0))
        self.assertEqual(struct.unpack_from("<4IB",root,24),(2,2,0x10000000,0,0))
        self.assertEqual(struct.unpack_from("<2I",root,41),(100,99))
        self.assertEqual(root[49:],hashlib.md5(b"a").digest()+hashlib.md5(b"b").digest())

    def test_existing_directory_and_files_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"client"
            path.mkdir()
            sentinel = path/"Data"
            sentinel.write_bytes(b"leave intact")
            with self.assertRaises(FileExistsError):
                lab.write_store(path,added=True)
            self.assertEqual(sentinel.read_bytes(),b"leave intact")
            self.assertEqual(list(path.iterdir()),[sentinel])

    def test_all_index_buckets_and_config_hashes_present(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/"lab"
            report = lab.write_store(root,added=True)
            indices = list((root/"Data/data").glob("*.idx"))
            self.assertEqual(len(indices),16)
            for index in indices:
                raw = index.read_bytes()
                length,checksum = struct.unpack_from("<II",raw)
                self.assertEqual(length,16)
                self.assertEqual(checksum,lab.hashlittle(raw[8:24]))
                self.assertEqual(raw[10],int(index.name[:2],16))
            for config in (root/"Data/config").glob("*/*/*"):
                self.assertEqual(config.name,hashlib.md5(config.read_bytes()).hexdigest())
            self.assertEqual(report["resources"][str(lab.BASE_ID)]["sha256"],hashlib.sha256(lab.BASE_TEXT).hexdigest())
            with self.assertRaises(FileExistsError):
                lab.write_store(root,added=True)

    @unittest.skipUnless(os.environ.get("CASC_SANDBOX_CHECKER"),
                         "Compile tools/legion-casc-probe/check-storage.cpp with real CascLib first")
    def test_native_full_storage_and_failure_controls(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            lab.write_store(folder/"baseline")
            lab.write_store(folder/"candidate",added=True)
            result = lab.verify_stores(os.environ["CASC_SANDBOX_CHECKER"],folder)
            self.assertTrue(result["all_passed"])
            self.assertEqual(len(result["cases"]),4)
            self.assertFalse(result["client_compatibility_verified"])

    @unittest.skipUnless(os.environ.get("CASC_CONTENT_KEY_PROBE"),
                         "Compile tools/legion-casc-probe/probe.cpp with real CascLib first")
    def test_native_content_key_lookup_and_invalid_keys(self):
        binary = os.environ["CASC_CONTENT_KEY_PROBE"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/"candidate"
            report = lab.write_store(root,added=True)
            records = list(report["resources"].values())
            keys = [r["ckey"] for r in records]
            result = subprocess.run([binary,str(root),lab.PRODUCT,"--content-keys",*keys],
                                    capture_output=True,text=True,check=True,timeout=30)
            rows = list(csv.DictReader(io.StringIO(result.stdout),delimiter="\t"))
            self.assertEqual(len(rows),2)
            for row,expected in zip(rows,records):
                self.assertEqual(row["status"],"READ_OK")
                self.assertEqual(row["label"],expected["ckey"])
                self.assertEqual(row["sha256"],expected["sha256"])
            result = subprocess.run([binary,str(root),lab.PRODUCT,"--content-keys","0"*32],
                                    capture_output=True,text=True,check=True,timeout=30)
            self.assertEqual(next(csv.DictReader(io.StringIO(result.stdout),delimiter="\t"))["status"],"OPEN_FAILED")
            for args in (["--content-keys"],["--content-keys","bad"]):
                result = subprocess.run([binary,str(root),lab.PRODUCT,*args],capture_output=True,timeout=30)
                self.assertEqual(result.returncode,2)

    @unittest.skipUnless(os.environ.get('CASC_SANDBOX_CHECKER'), 'Native CascLib checker required')
    def test_locale_specific_read_avoids_offline_variant_and_reports_failed_ckey(self):
        original_root = lab.make_root
        def localized(records):
            first = bytearray(original_root({lab.BASE_ID:records[lab.BASE_ID]}))
            struct.pack_into('<I',first,12,2)
            second = (struct.pack('<4IB',1,0x2000,0x10000000,0,0)+
                      struct.pack('<I',lab.BASE_ID)+records[lab.NEW_ID]['ckey'])
            return bytes(first)+second
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'client'
            with patch.object(lab,'make_root',localized):
                lab.write_store(root,added=True)
            base=lab.asset(lab.BASE_TEXT)
            path=root/'Data/data'/f'{lab.bucket(base["ekey"]):02x}00000001.idx'
            data=path.read_bytes();length=struct.unpack_from('<I',data,32)[0]
            entries=[data[pos:pos+18] for pos in range(40,40+length,18)
                     if data[pos:pos+9]!=base['ekey'][:9]]
            checksum=0
            for entry in entries:checksum=lab.hashlittle(entry,checksum)
            result=data[:32]+lab.guarded(b''.join(entries),checksum)
            path.write_bytes(result if entries else result.ljust(0x8000,b'\0'))
            snapshot={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
            for locale,status,code in [('enUS','SIZE_FAILED',1),('ruRU','READ_OK',0)]:
                process=subprocess.run([os.environ['CASC_SANDBOX_CHECKER'],str(root),str(lab.BASE_ID)],
                    env=dict(os.environ,CASC_CHECK_LOCALE=locale),text=True,capture_output=True,timeout=30)
                self.assertEqual(process.returncode,code,process.stderr)
                row=next(csv.DictReader(io.StringIO(process.stdout),delimiter='\t'))
                self.assertEqual(row['status'],status)
                if locale=='enUS':
                    self.assertEqual(row['error'],'1007')
                    self.assertEqual(row['ckey'],base['ckey'].hex())
                else:
                    self.assertEqual(row['sha256'],hashlib.sha256(lab.NEW_TEXT).hexdigest())
            self.assertEqual(snapshot,{p:p.read_bytes() for p in snapshot})


if __name__ == "__main__":
    unittest.main()
