import csv
import hashlib
import importlib.util
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

SCRIPTS=Path(__file__).parents[1]/"scripts"
sys.path.insert(0,str(SCRIPTS))
from casc_manifest_update import append_root,root_groups,Encoding,extend_encoding,pack_pages

spec=importlib.util.spec_from_file_location("copy_lab",SCRIPTS/"update-casc-sandbox.py")
copy=importlib.util.module_from_spec(spec);spec.loader.exec_module(copy)
spec=importlib.util.spec_from_file_location("audit_lab",SCRIPTS/"audit-casc-client.py")
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
lab=copy.lab


def snapshot(path):
    return {str(p.relative_to(path)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.rglob("*") if p.is_file()}


def package(folder,build_key,count=1,start=lab.NEW_ID):
    folder.mkdir()
    rows=[]
    for index in range(count):
        body=f"independently added resource {index}".encode()
        name=f"resource-{index}.txt";(folder/name).write_bytes(body)
        rows.append(dict(file_data_id=start+index,path=name,sha256=hashlib.sha256(body).hexdigest()))
    path=folder/"package.json"
    path.write_text(json.dumps(dict(format="wowforever-casc-resource-package-v1",
                                   base_build_key=build_key,resources=rows)))
    return path


class ManifestTransformTests(unittest.TestCase):
    def test_append_preserves_named_and_localized_root_groups(self):
        # One named enUS group and one hashless ruRU group for the same old ID.
        key=hashlib.md5(b"old").digest()
        header=b"TSFM"+struct.pack("<5I",24,2,2,1,0)
        named=struct.pack("<4IBI",1,2,0,0,0,100)+key+struct.pack("<Q",12345)
        localized=struct.pack("<4IBI",1,256,0x80,0x12000000,4,100)+key
        original=header+named+localized
        updated=append_root(original,{200:hashlib.md5(b"new").digest()},locale=256)
        self.assertEqual(updated[24:len(original)],original[24:])
        self.assertEqual(struct.unpack_from("<II",updated,12),(3,1))
        self.assertEqual([g["locale"] for g in root_groups(updated)],[2,256,256])
        with self.assertRaisesRegex(ValueError,"conflict"):
            append_root(original,{100:key})

    def test_root_truncation_and_bad_counters_rejected(self):
        original=lab.make_root({100:lab.asset(b"old")})
        for bad in (original[:-1],original[:30]):
            with self.assertRaises(ValueError):list(root_groups(bad))
        bad=bytearray(original);struct.pack_into("<I",bad,12,99)
        with self.assertRaisesRegex(ValueError,"counters"):append_root(bad,{200:bytes(16)})

    def test_multi_page_encoding_preserves_all_old_rows(self):
        old=lab.asset(b"old")
        original=lab.make_encoding([old])
        additions=[lab.asset(f"new {i}".encode()) for i in range(70)]
        updated=extend_encoding(original,additions)
        before,after=Encoding(original),Encoding(updated)
        self.assertGreater(after.nc,1);self.assertGreater(after.ne,1)
        for kind in ("c","e"):
            preserved=dict(before.rows(kind));actual=dict(after.rows(kind))
            self.assertEqual(len(actual),71)
            for key,raw in preserved.items():self.assertEqual(actual[key],raw)
        # Last EKey page carries the zero-key/FFFFFFFF terminator used by TACT.
        last=updated[after.epages+(after.ne-1)*after.ekb:after.end]
        self.assertIn(bytes(16)+b"\xff"*4,last)

    def test_encoding_variants_and_existing_espec_indices_survive(self):
        obj=lab.asset(b"old");base=Encoding(lab.make_encoding([obj]))
        ck,raw=next(base.rows("c"))
        alternate=hashlib.md5(b"another encoding").digest()
        raw=b"\2"+raw[1:]+alternate
        ci,cp,nc=pack_pages([(ck,raw)],base.ckb)
        old_ekey=next(base.rows("e"))
        other=(alternate,alternate+bytes(4)+(100).to_bytes(5,"big"))
        ei,ep,ne=pack_pages(sorted([old_ekey,other]),base.ekb)
        header=bytearray(base.data[:22]);struct.pack_into(">II",header,9,nc,ne)
        original=bytes(header)+base.spec+ci+cp+ei+ep+b"b:{*=n}"
        updated=extend_encoding(original,[lab.asset(b"new")])
        self.assertEqual(dict(Encoding(updated).rows("c"))[ck],raw)
        self.assertEqual(dict(Encoding(updated).rows("e"))[old_ekey[0]],old_ekey[1])

    def test_encoding_bad_page_hash_and_conflicting_key_rejected(self):
        obj=lab.asset(b"old");original=lab.make_encoding([obj]);base=Encoding(original)
        bad=bytearray(original);bad[base.cpages+30]^=1
        with self.assertRaisesRegex(ValueError,"checksum"):
            extend_encoding(bad,[lab.asset(b"new")])
        conflicting=dict(lab.asset(b"different"));conflicting["ckey"]=obj["ckey"]
        with self.assertRaisesRegex(ValueError,"conflict"):
            extend_encoding(original,[conflicting])

    def test_blte_checks_encoded_hash_frame_hash_and_zlib_body(self):
        obj=lab.asset(b"payload")
        self.assertEqual(copy.decode_blte(obj["encoded"],obj["ekey"],obj["ckey"]),b"payload")
        bad=obj["encoded"][:-1]+bytes([obj["encoded"][-1]^1])
        with self.assertRaisesRegex(ValueError,"frame checksum"):
            copy.decode_blte(bad,obj["ekey"],obj["ckey"])
        body=b"compressed metadata"*100
        encoded=b"BLTE\0\0\0\0Z"+zlib.compress(body)
        self.assertEqual(copy.decode_blte(encoded,hashlib.md5(encoded).digest(),hashlib.md5(body).digest()),body)
        with self.assertRaisesRegex(ValueError,"EKey"):
            copy.decode_blte(encoded,bytes(16))

    def test_idx_accepts_both_native_and_blizzget_hash_chains(self):
        records=[hashlib.md5(bytes([i])).digest()[:9]+bytes(5)+struct.pack("<I",100) for i in range(3)]
        blob=copy.write_index(0,records,30,1<<30)
        self.assertEqual(copy.read_index(blob,0)["records"],sorted(records))
        high=low=0
        for record in sorted(records):high,low=lab.hashlittle2(record,high,low)
        native=bytearray(blob);struct.pack_into("<I",native,36,high)
        self.assertEqual(copy.read_index(native,0)["records"],sorted(records))
        native[-1]^=1
        with self.assertRaisesRegex(ValueError,"checksum"):
            copy.read_index(native,0)

    def test_paged_idx_record_checksum(self):
        entry=hashlib.md5(b"entry").digest()[:9]+bytes(5)+struct.pack("<I",100)
        blob=bytearray(copy.write_index(0,[],30,1<<30))
        struct.pack_into("<I",blob,0x1000,lab.hashlittle(entry+b"\0")|0x80000000)
        blob[0x1004:0x1004+18]=entry
        self.assertEqual(copy.read_index(blob,0)["records"],[entry])
        blob[0x1004]^=1
        with self.assertRaisesRegex(ValueError,"checksum"):
            copy.read_index(blob,0)


class IncrementalCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/"source"
        self.marker=lab.write_store(self.source)
        self.package=package(self.root/"package",self.marker["build_key"])

    def test_update_existing_copy_keeps_old_files_and_adds_a_new_segment(self):
        before=snapshot(self.source);destination=self.root/"updated"
        result=copy.update(self.source,self.package,destination)
        self.assertEqual(snapshot(self.source),before)
        for path,digest in before.items():
            if path not in ("lab.json",".build.info"):
                self.assertEqual(hashlib.sha256((destination/path).read_bytes()).hexdigest(),digest)
        self.assertTrue((destination/"Data/data/data.001").exists())
        self.assertEqual(set(result["resources"]),{str(lab.BASE_ID),str(lab.NEW_ID)})
        # Validate complete newly written metadata, not just generator objects.
        audit_result=audit.audit(destination)
        self.assertTrue(audit_result["audit_passed"])
        self.assertEqual(audit_result["root"]["records"],2)

    def test_wrong_source_build_and_old_id_leave_no_destination(self):
        before=snapshot(self.source)
        spec=json.loads(self.package.read_text());spec["base_build_key"]="0"*32
        self.package.write_text(json.dumps(spec))
        with self.assertRaisesRegex(ValueError,"build mismatch"):
            copy.update(self.source,self.package,self.root/"wrong")
        spec["base_build_key"]=self.marker["build_key"];spec["resources"][0]["file_data_id"]=lab.BASE_ID
        self.package.write_text(json.dumps(spec))
        with self.assertRaisesRegex(ValueError,"conflict"):
            copy.update(self.source,self.package,self.root/"wrong")
        self.assertFalse((self.root/"wrong").exists());self.assertEqual(snapshot(self.source),before)

    def test_refuse_existing_output_and_package_escape(self):
        destination=self.root/"exists";destination.mkdir();(destination/"keep").write_text("keep")
        with self.assertRaises(FileExistsError):copy.update(self.source,self.package,destination)
        self.assertEqual((destination/"keep").read_text(),"keep")
        spec=json.loads(self.package.read_text());spec["resources"][0]["path"]="../secret"
        self.package.write_text(json.dumps(spec))
        with self.assertRaisesRegex(ValueError,"resource path"):
            copy.update(self.source,self.package,self.root/"escape")
        self.assertFalse((self.root/"escape").exists())

    def test_corrupt_package_or_metadata_rejected_before_copy(self):
        (self.package.parent/"resource-0.txt").write_text("tampered")
        with self.assertRaisesRegex(ValueError,"SHA-256"):
            copy.update(self.source,self.package,self.root/"bad")
        self.assertFalse((self.root/"bad").exists())

    def test_real_client_marker_is_not_accepted_by_writer(self):
        (self.source/"lab.json").write_text(json.dumps(dict(synthetic=False)))
        with self.assertRaisesRegex(ValueError,"synthetic"):
            copy.update(self.source,self.package,self.root/"bad")

    @unittest.skipUnless(os.environ.get("CASC_SANDBOX_CHECKER"),"Real CascLib checker required")
    def test_native_large_incremental_package_and_second_update(self):
        self.package=package(self.root/"many",self.marker["build_key"],70,lab.BASE_ID+100)
        # Source buckets use Blizzard's two-seed checksum chain, independently
        # accepted by the real reader before the updater touches the copy.
        for path in (self.source/"Data/data").glob("*.idx"):
            number=int(path.name[:2],16)
            records=copy.read_index(path.read_bytes(),number)["records"]
            if records:
                high=low=0
                for raw in records:high,low=lab.hashlittle2(raw,high,low)
                raw=bytearray(path.read_bytes());struct.pack_into("<I",raw,36,high)
                path.write_bytes(raw)
        native=__import__("subprocess").run([os.environ["CASC_SANDBOX_CHECKER"],str(self.source),str(lab.BASE_ID)],capture_output=True)
        self.assertEqual(native.returncode,0,native.stderr)
        before=snapshot(self.source);destination=self.root/"large"
        result=copy.update(self.source,self.package,destination,os.environ["CASC_SANDBOX_CHECKER"])
        self.assertEqual(result["native_verified_resources"],71)
        self.assertEqual(snapshot(self.source),before)
        second=package(self.root/"second",result["build_key"],1,lab.BASE_ID+200)
        before=snapshot(destination)
        again=copy.update(destination,second,self.root/"again",os.environ["CASC_SANDBOX_CHECKER"])
        self.assertEqual(again["native_verified_resources"],72)
        self.assertEqual(again["new_segment"],2)
        self.assertEqual(again["reused_existing_encodings"],1)
        self.assertEqual(snapshot(destination),before)

    def test_failed_native_check_leaves_no_output_or_staging(self):
        before=snapshot(self.source)
        with self.assertRaisesRegex(ValueError,"Native storage"):
            copy.update(self.source,self.package,self.root/"bad",checker="/bin/false")
        self.assertFalse((self.root/"bad").exists())
        self.assertFalse(list(self.root.glob(".casc-update-*")))
        self.assertEqual(snapshot(self.source),before)

    def test_readonly_audit_cli_protects_client_and_writes_only_report(self):
        import subprocess
        info=self.source/".build.info";info.write_text(info.read_text()+"\n")
        before=snapshot(self.source)
        output=self.root/"report.json"
        run=subprocess.run([sys.executable,str(SCRIPTS/"audit-casc-client.py"),str(self.source),"--output",str(output)],capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertTrue(json.loads(output.read_text())["audit_passed"])
        self.assertEqual(snapshot(self.source),before)
        for path in (self.source/".build.info",self.source/"Data/report.json"):
            run=subprocess.run([sys.executable,str(SCRIPTS/"audit-casc-client.py"),str(self.source),"--output",str(path)],capture_output=True)
            self.assertEqual(run.returncode,2)
        self.assertEqual(snapshot(self.source),before)


if __name__=="__main__":unittest.main()
