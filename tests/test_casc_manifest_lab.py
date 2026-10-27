import csv
import hashlib
import importlib.util
import io
import struct
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "manifest_lab", Path(__file__).parents[1] / "scripts/casc-manifest-lab.py")
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


def fixture(count=2):
    """Entirely synthetic metadata: no client files or extracted game data."""
    path, cft, vfs = b"", b"", b""
    est = b"b:{*=n}\0"
    for i in range(count):
        name = f"file-{i}".encode()
        content = f"synthetic payload {i}".encode()
        blte = b"BLTE\0\0\0\0N" + content
        path += bytes([len(name)]) + name + b"\xff" + struct.pack(">I", len(vfs))
        vfs += b"\x01" + struct.pack(">II", 0, len(content)) + bytes([len(cft)])
        cft += hashlib.md5(blte).digest()[:9] + struct.pack(">I", len(blte))
        cft += b"\0" + struct.pack(">I", len(content)) + hashlib.md5(content).digest() + b"\0"
    path = b"\xff" + struct.pack(">I", 0x80000000 | (len(path)+4)) + path
    po, eo = 46, 46 + len(path)
    co, vo = eo + len(est), eo + len(est) + len(cft)
    header = struct.pack(">4s4B7IH2I", b"TVFS", 1, 46, 9, 9, 7,
                         po, len(path), vo, len(vfs), co, len(cft), 1, eo, len(est))
    return header + path + est + cft + vfs


class ManifestLabTests(unittest.TestCase):
    def test_append_preserves_old_bytes_and_resolves_own_payload(self):
        original = fixture()
        payload = b"our own text"
        candidate, blte = lab.append_lab_leaf(original, "new-file", payload)
        before, after = lab.parse_tvfs(original), lab.parse_tvfs(candidate)
        self.assertEqual(len(after["leaves"]), 3)
        for name, value in before["leaves"].items():
            self.assertEqual(after["leaves"][name], value)
        # Beyond semantic comparisons, old table bodies must remain byte-for-byte.
        for name in ("cft", "vfs", "est"):
            self.assertTrue(after["tables"][name].startswith(before["tables"][name]))
        self.assertTrue(after["tables"]["path"][5:].startswith(before["tables"]["path"][5:]))
        span = after["leaves"]["new-file"][0]
        self.assertEqual(blte[:9], b"BLTE\0\0\0\0N")
        self.assertEqual(blte[9:], payload)
        self.assertEqual(span["ckey"], hashlib.md5(payload).hexdigest())
        self.assertEqual(span["ekey_prefix"], hashlib.md5(blte).hexdigest()[:18])
        self.assertEqual(span["bytes"], len(payload))
        self.assertEqual(span["encoded_bytes"], len(blte))

    def test_reject_duplicate_or_non_leaf_paths(self):
        for name in ("file-0", "", "a/b", "a\\b", "a:b", "a\0b", "x"*255):
            with self.subTest(name=name), self.assertRaises(ValueError):
                lab.append_lab_leaf(fixture(), name, b"text")

    def test_offset_width_change_fails_instead_of_corrupting_existing_spans(self):
        with self.assertRaisesRegex(ValueError, "CFT offset width"):
            lab.append_lab_leaf(fixture(7), "new", b"text")

    def test_bounds_checks(self):
        for bad in (fixture()[:45], fixture()[:-1]):
            with self.assertRaises(ValueError):
                lab.parse_tvfs(bad)
        bad = bytearray(fixture())
        struct.pack_into(">I", bad, 12, len(bad)+1)  # Path table points outside file.
        with self.assertRaises(ValueError):
            lab.parse_tvfs(bad)
        bad = bytearray(fixture())
        struct.pack_into(">I", bad, 47, 0x80000000)  # Folder length underflows.
        with self.assertRaises(ValueError):
            lab.parse_tvfs(bad)

    def test_unsupported_patch_records_rejected(self):
        bad = bytearray(fixture())
        co = struct.unpack_from(">I", bad, 28)[0]
        bad[co+34] = 1
        with self.assertRaisesRegex(ValueError, "Patched CFT"):
            lab.parse_tvfs(bad)

    def test_root_v2_counts_and_version(self):
        root = b"TSFM" + struct.pack("<5I", 24, 2, 100, 20, 0)
        self.assertEqual(lab.root_header(root)["total_records"], 100)
        for values in ((24, 1, 100, 20, 0), (24, 2, 10, 20, 0)):
            with self.assertRaises(ValueError):
                lab.root_header(b"TSFM" + struct.pack("<5I", *values))

    def test_report_checks_md5_and_partial_read_lengths(self):
        root = b"TSFM" + struct.pack("<5I", 24, 2, 100, 20, 0) + bytes(40)
        vfs = fixture()
        rows = [
            ["root_prefix", "0"*32, "PREFIX_READ_OK", 1000, 64, root.hex(), 0],
            ["vfs_root", hashlib.md5(vfs).hexdigest(), "FULL_READ_OK", len(vfs), len(vfs), vfs.hex(), 0],
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "metadata.tsv"

            def save(escaped=False):
                out = io.StringIO()
                writer = csv.writer(out, delimiter="\t", lineterminator="\n")
                writer.writerow(["label", "ckey", "status", "file_bytes", "read_bytes", "hex", "error"])
                writer.writerows(rows)
                text = out.getvalue()
                path.write_text(text.replace("\t", r"\t").replace("\n", r"\n") if escaped else text)

            save()
            self.assertEqual(lab.read_report(path)["vfs_root"][1], vfs)
            save(escaped=True)
            self.assertEqual(lab.read_report(path)["vfs_root"][1], vfs)
            rows[1][1] = "0"*32
            save()
            with self.assertRaisesRegex(ValueError, "CKey/size"):
                lab.read_report(path)
            rows[1][1] = hashlib.md5(vfs).hexdigest()
            rows[0][4] = 63
            save()
            with self.assertRaises(ValueError):
                lab.read_report(path)


if __name__ == "__main__":
    unittest.main()
