import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).parents[1]/'scripts'
sys.path.insert(0, str(SCRIPTS))
from casc_download import Download, append_download

spec = importlib.util.spec_from_file_location('download_audit', SCRIPTS/'audit-casc-client.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
lab = audit.copy.lab


def fixture(count=10, tags=(), version=1, checksums=0, flags=0):
    header = b'DL'+bytes([version,16,checksums])+struct.pack('>IH', count, len(tags))
    if version >= 2:
        header += bytes([flags])
    if version == 3:
        header += b'\x07abc'
    rows = b''.join(hashlib.md5(f'entry {i}'.encode()).digest()+(123+i).to_bytes(5,'big')+bytes([i%255])
                    +bytes(4*checksums+flags) for i in range(count))
    return header+rows+b''.join(name+b'\0'+kind.to_bytes(2,'big')+bitmap for name,kind,bitmap in tags)


class DownloadTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('CASC_DOWNLOAD_TAG_CHECKER'),'Native tag-mask checker required')
    def test_native_reader_sees_only_explicit_new_memberships_not_old_padding(self):
        for selected in ([],[5,9,20,24,29]):
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as temp:
                store = Path(temp)/'store'
                original = fixture(count=11,tags=[(f'tag-{i}'.encode(),i,b'\xff\xff') for i in range(30)])
                resource = lab.asset(lab.BASE_TEXT)
                raw = append_download(original,[dict(ekey=resource['ekey'],encoded_bytes=len(resource['encoded']),
                                                     priority=0,tag_indices=selected)])
                original_asset = lab.asset
                def tagged_asset(body):
                    return original_asset(raw if body==b'DL\1\x10\0'+bytes(11) else body)
                with patch.object(lab,'asset',side_effect=tagged_asset):
                    lab.write_store(store)
                expected = sum(1<<index for index in selected)
                native = subprocess.run([os.environ['CASC_DOWNLOAD_TAG_CHECKER'],str(store),str(lab.BASE_ID),
                                         format(expected,'x')],capture_output=True)
                self.assertEqual(native.returncode,0,native.stdout+native.stderr)

    def test_append_clears_old_padding_ones_without_changing_old_memberships(self):
        original = fixture(count=3, tags=[(b'Windows',1,b'\xff'),(b'Talebound',16384,b'\x1f')])
        row = dict(ekey=hashlib.md5(b'new').digest(),encoded_bytes=456,priority=0,tag_indices=[])
        updated = Download(append_download(original,[row]))
        self.assertEqual(updated.count,4)
        self.assertEqual(updated.tag_indices(3),[])
        for index in range(3):
            self.assertEqual(updated.tag_indices(index),Download(original).tag_indices(index))
        self.assertEqual([t['member_count'] for t in updated.summary()['tags']], [3,0])
        self.assertEqual([t['unused_bits_value'] for t in updated.summary()['tags']], [0,0])
        self.assertEqual(updated.data[11:11+3*22], original[11:11+3*22])

    def test_append_explicit_tags_across_bitmap_byte_boundary(self):
        original = fixture(count=7, tags=[(b'Windows',1,b'\xff'),(b'ruRU',3,b'\x01')])
        rows = [dict(ekey=hashlib.md5(f'new-{i}'.encode()).digest(),encoded_bytes=456,priority=0,tag_indices=tags)
                for i,tags in enumerate([[],[1]])]
        updated = Download(append_download(original,rows))
        self.assertEqual(updated.tag_indices(7),[])
        self.assertEqual(updated.tag_indices(8),[1])
        self.assertEqual([t['member_count'] for t in updated.summary()['tags']], [7,1])
        self.assertEqual(updated.tags[0]['bitmap'].tobytes(), b'\xfe\0')
        self.assertEqual(updated.tags[1]['bitmap'].tobytes(), b'\0\x80')

    def test_append_refuses_implicit_tags_duplicate_keys_and_unsupported_layout(self):
        original = fixture(count=1,tags=[(b'Windows',1,b'\x80')])
        row = dict(ekey=hashlib.md5(b'new').digest(),encoded_bytes=456,priority=0,tag_indices=[0])
        self.assertEqual(append_download(original,[]),original)
        for bad in ({k:v for k,v in row.items() if k!='tag_indices'},
                    dict(row,tag_indices=[1]),dict(row,tag_indices=[True]),
                    dict(row,tag_indices=[0,0]),dict(row,encoded_bytes=-1),
                    dict(row,priority=256),dict(row,ekey=hashlib.md5(b'entry 0').digest())):
            with self.assertRaises(ValueError):
                append_download(original,[bad])
        with self.assertRaisesRegex(ValueError,'duplicate'):
            append_download(original,[row,row])
        with self.assertRaisesRegex(ValueError,'v1'):
            append_download(fixture(version=2),[row])

    def test_big_endian_types_msb_membership_and_unused_bits(self):
        raw = fixture(tags=[(b'ruRU',0x102,b'\x81\xff'),(b'Windows',1,b'\x40\0')])
        parsed = Download(raw)
        self.assertEqual(parsed.tag_indices(0), [0])
        self.assertEqual(parsed.tag_indices(1), [1])
        self.assertEqual(parsed.tag_indices(7), [0])
        self.assertEqual(parsed.tag_indices(8), [0])
        self.assertEqual(parsed.tag_indices(9), [0])
        summary = parsed.summary()
        self.assertEqual(summary['tags'][0]['type'], 0x102)
        self.assertEqual(summary['tags'][0]['member_count'], 4)
        self.assertEqual(summary['tags'][0]['unused_bits_value'], 63)
        self.assertEqual(summary['tags'][1]['member_count'], 1)
        self.assertFalse(summary['supported_by_lab_updater'])
        self.assertEqual(parsed.data, raw)

    def test_thirty_tags_and_byte_aligned_bitmaps(self):
        tags = [(f'tag-{i}'.encode(),i,b'\x80\x01') for i in range(30)]
        parsed = Download(fixture(count=16,tags=tags))
        self.assertEqual(parsed.tag_indices(15),list(range(30)))
        self.assertEqual([t['member_count'] for t in parsed.summary()['tags']], [2]*30)

    def test_version_two_and_three_checksum_and_flag_offsets(self):
        for version in (2,3):
            parsed = Download(fixture(count=2,tags=[(b'x',7,b'\x40')],version=version,checksums=1,flags=3))
            self.assertEqual(parsed.tag_indices(1),[0])
            self.assertEqual(parsed.summary()['flag_bytes'],3)
            refs = parsed.references({'test':hashlib.md5(b'entry 1').digest()})
            self.assertEqual(refs['test']['matches'][0]['encoded_bytes'],124)
            self.assertEqual(refs['test']['matches'][0]['raw_priority'],1)

    def test_known_reference_matches_and_missing_reference_are_explicit(self):
        parsed = Download(fixture(count=2,tags=[(b'ruRU',0,b'\x40')]))
        refs = parsed.references({'known':hashlib.md5(b'entry 1').digest(),'absent':bytes(16)})
        self.assertEqual(refs['known']['match_count'],1)
        self.assertEqual(refs['known']['matches'][0]['tag_indices'],[0])
        self.assertEqual(refs['absent']['match_count'],0)

    def test_truncation_and_unknown_trailing_data_fail_closed(self):
        raw = fixture(count=2,tags=[(b'x',7,b'\x80')])
        for bad in (raw[:10],raw[:12],raw[:-1],raw+b'unknown',raw+b'\0'*16,
                    fixture(count=0)+b'name-without-zero'):
            with self.assertRaises(ValueError):
                Download(bad)
        with self.assertRaises(ValueError):
            Download(fixture(count=1)).tag_indices(1)

    def test_empty_synthetic_header_padding(self):
        parsed = Download(b'DL\1\x10\0'+bytes(11))
        self.assertEqual(parsed.summary()['padding_bytes'],5)
        self.assertTrue(parsed.summary()['supported_by_lab_updater'])

    def test_download_only_cli_reads_all_tags_and_leaves_store_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);store = root/'store'
            raw = fixture(count=16,tags=[(f'tag-{i}'.encode(),i,b'\x80\x01') for i in range(30)])
            original_asset = lab.asset
            def tagged_asset(body):
                return original_asset(raw if body==b'DL\1\x10\0'+bytes(11) else body)
            with patch.object(lab,'asset',side_effect=tagged_asset):
                lab.write_store(store)
            def hashes():
                return {str(p.relative_to(store)):hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in store.rglob('*') if p.is_file()}
            before = hashes();output = root/'reports/download.json'
            result = subprocess.run([sys.executable,str(SCRIPTS/'audit-casc-client.py'),str(store),
                                     '--download-only','--output',str(output)],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            report = json.loads(output.read_text())
            self.assertTrue(report['audit_passed'])
            self.assertEqual(report['download']['tag_count'],30)
            self.assertTrue(report['download']['tags_parsed'])
            self.assertFalse(report['installation_supported'])
            self.assertEqual(hashes(), before)
            if os.environ.get('CASC_SANDBOX_CHECKER'):
                native = subprocess.run([os.environ['CASC_SANDBOX_CHECKER'],str(store),str(lab.BASE_ID)],capture_output=True)
                self.assertEqual(native.returncode,0,native.stderr)
