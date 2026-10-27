#!/usr/bin/env python3
"""Inspect an offline metadata report; experiment on a TVFS copy, never install it.

Layout reference: Forever CascLib CascRootFile_TVFS.cpp / CascRootFile_WoW.cpp.
Only the observed TVFS v1, flags=7, unpatched CFT entries are supported.
"""
import argparse
import csv
import hashlib
import io
import json
import struct
from pathlib import Path


def width(size):
    return max(1, (size.bit_length() + 7) // 8)


def root_header(data):
    if len(data) < 24 or data[:4] != b"TSFM":
        raise ValueError("Expected modern ROOT header")
    size, version, total, named, reserved = struct.unpack_from("<5I", data, 4)
    if size != 24 or version != 2 or named > total:
        raise ValueError("Unsupported ROOT header")
    return dict(header_bytes=size, version=version, total_records=total,
                named_records=named, reserved=reserved)


def parse_tvfs(data):
    if len(data) < 46:
        raise ValueError("Truncated TVFS header")
    sig, ver, hs, ek, pk, flags, po, ps, vo, vs, co, cs, depth, eo, es = \
        struct.unpack_from(">4s4B7IH2I", data)
    if (sig, ver, hs, ek, pk, flags) != (b"TVFS", 1, 46, 9, 9, 7):
        raise ValueError("Unsupported TVFS layout")
    ranges = sorted((off, off + size) for off, size in
                    [(po, ps), (vo, vs), (co, cs), (eo, es)])
    end = hs
    for start, stop in ranges:
        if start < end or stop > len(data):
            raise ValueError("TVFS tables overlap or exceed file")
        end = stop
    tables = dict(path=data[po:po+ps], vfs=data[vo:vo+vs],
                  cft=data[co:co+cs], est=data[eo:eo+es])
    pt, vt, ct = tables["path"], tables["vfs"], tables["cft"]
    cw, ew = width(cs), width(es)
    leaves = {}

    def take(pos, n, limit):
        if pos < 0 or pos + n > limit:
            raise ValueError("Truncated TVFS entry")
        return pos + n

    def spans(offset):
        take(offset, 1, len(vt))
        count = vt[offset]
        if not 1 <= count <= 224:
            raise ValueError("Unsupported TVFS span count")
        pos = offset + 1
        result = []
        for _ in range(count):
            stop = take(pos, 8 + cw, len(vt))
            file_offset, size = struct.unpack_from(">II", vt, pos)
            cft_offset = int.from_bytes(vt[pos+8:stop], "big")
            # EKey, encoded size, EST offset, content size, CKey, patch count.
            cstop = take(cft_offset, 9 + 4 + ew + 4 + 16 + 1, len(ct))
            raw = ct[cft_offset:cstop]
            if raw[-1] != 0:
                raise ValueError("Patched CFT records are not supported")
            est_offset = int.from_bytes(raw[13:13+ew], "big")
            if est_offset >= es or b"\0" not in tables["est"][est_offset:]:
                raise ValueError("Invalid encoding specifier offset")
            content_size = int.from_bytes(raw[13+ew:17+ew], "big")
            if file_offset + size > content_size:
                raise ValueError("Span exceeds referenced content")
            result.append(dict(offset=file_offset, bytes=size,
                               ekey_prefix=raw[:9].hex(),
                               encoded_bytes=int.from_bytes(raw[9:13], "big"),
                               content_bytes=content_size,
                               espec_offset=est_offset,
                               ckey=raw[17+ew:33+ew].hex()))
            pos = stop
        return result

    def walk(pos, limit, prefix="", level=0):
        if level > 64:
            raise ValueError("TVFS nesting limit exceeded")
        saved = prefix
        while pos < limit:
            pre = pt[pos] == 0
            pos += int(pre)
            take(pos, 1, limit)
            fragment = ""
            if pt[pos] != 255:
                length = pt[pos]
                pos += 1
                stop = take(pos, length, limit)
                fragment = pt[pos:stop].decode("ascii")
                pos = stop
            post = pos < limit and pt[pos] == 0
            pos += int(post)
            path = prefix + ("/" if pre else "") + fragment + ("/" if post else "")
            if pos < limit and pt[pos] == 255:
                take(pos, 5, limit)
                value = int.from_bytes(pt[pos+1:pos+5], "big")
                pos += 5
                if value & 0x80000000:
                    length = value & 0x7fffffff
                    if length < 4:
                        raise ValueError("Invalid folder length")
                    stop = take(pos, length - 4, limit)
                    walk(pos, stop, path, level+1)
                    pos = stop
                else:
                    if path in leaves:
                        raise ValueError("Duplicate TVFS path")
                    leaves[path] = spans(value)
                prefix = saved
            else:
                prefix = path + ("" if post else "/")

    walk(0, len(pt))
    return dict(tables=tables, leaves=leaves, max_depth=depth,
                flags=flags, file_bytes=len(data))


def append_lab_leaf(data, name, payload):
    """Append a standalone top-level file in a COPY. Not a client patch builder."""
    parsed = parse_tvfs(data)
    encoded_name = name.encode("ascii")
    if (not encoded_name or len(encoded_name) > 254 or
            any(c in name for c in "/\\:\0") or name in parsed["leaves"]):
        raise ValueError("Expected a new top-level filename")
    tables = parsed["tables"]
    pt, vt, ct, est = (tables[k] for k in ("path", "vfs", "cft", "est"))
    if pt[:1] != b"\xff" or int.from_bytes(pt[1:5], "big") != (0x80000000 | (len(pt)-1)):
        raise ValueError("Expected one enclosing root folder")
    # Uncompressed BLTE, with no chunk table. This adds our own text, not game data.
    blte = b"BLTE\0\0\0\0N" + payload
    ckey, ekey = hashlib.md5(payload).digest(), hashlib.md5(blte).digest()
    # Keep original table offset widths; crossing a width boundary needs a full rebuild.
    extra = ekey[:9] + struct.pack(">I", len(blte)) + bytes(width(len(est)))
    extra += struct.pack(">I", len(payload)) + ckey + b"\0"
    if width(len(ct)+len(extra)) != width(len(ct)):
        raise ValueError("CFT offset width change is not supported")
    if est[:1] == b"\0":
        raise ValueError("Missing encoding specifier")
    # BLTE is uncompressed: add a matching spec instead of claiming zlib encoding.
    spec = b"b:{*=n}\0"
    new_est = est + spec
    if width(len(new_est)) != width(len(est)):
        raise ValueError("EST offset width change is not supported")
    extra = extra[:13] + len(est).to_bytes(width(len(est)), "big") + extra[13+width(len(est)):]
    span = b"\x01" + struct.pack(">II", 0, len(payload)) + len(ct).to_bytes(width(len(ct)), "big")
    leaf = bytes([len(encoded_name)]) + encoded_name + b"\xff" + struct.pack(">I", len(vt))
    new_pt = b"\xff" + struct.pack(">I", 0x80000000 | (len(pt)-1+len(leaf))) + pt[5:] + leaf
    new_ct, new_vt = ct + extra, vt + span
    po = 46
    eo = po + len(new_pt)
    co = eo + len(new_est)
    vo = co + len(new_ct)
    header = struct.pack(">4s4B7IH2I", b"TVFS", 1, 46, 9, 9, 7,
                         po, len(new_pt), vo, len(new_vt), co, len(new_ct),
                         parsed["max_depth"], eo, len(new_est))
    candidate = header + new_pt + new_est + new_ct + new_vt
    check = parse_tvfs(candidate)
    if {k: v for k, v in check["leaves"].items() if k != name} != parsed["leaves"]:
        raise ValueError("Existing references changed")
    return candidate, blte


def read_report(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    # Some pasted uploads represent tabs/newlines as literal escape sequences.
    if "\t" not in text:
        text = text.replace(r"\t", "\t").replace(r"\n", "\n")
    rows = list(csv.DictReader(io.StringIO(text), delimiter="\t"))
    if len(rows) != 2 or {r["label"] for r in rows} != {"root_prefix", "vfs_root"}:
        raise ValueError("Expected two distinct metadata rows")
    result = {}
    for row in rows:
        blob = bytes.fromhex(row["hex"])
        full = row["label"] == "vfs_root"
        expected = "FULL_READ_OK" if full else "PREFIX_READ_OK"
        if row["status"] != expected or row["error"] != "0" or len(blob) != int(row["read_bytes"]):
            raise ValueError("Incomplete metadata report")
        if full:
            if len(blob) != int(row["file_bytes"]) or hashlib.md5(blob).hexdigest() != row["ckey"].lower():
                raise ValueError("TVFS CKey/size mismatch")
        elif len(blob) != min(64, int(row["file_bytes"])):
            raise ValueError("Incomplete ROOT prefix")
        result[row["label"]] = (row, blob)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("report", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--experiment-dir", type=Path)
    args = ap.parse_args()
    rows = read_report(args.report)
    root_row, root_bytes = rows["root_prefix"]
    _, vfs_bytes = rows["vfs_root"]
    parsed = parse_tvfs(vfs_bytes)
    root_refs = parsed["leaves"].get(".root", [])
    if len(root_refs) != 1 or root_refs[0]["ckey"] != root_row["ckey"] or root_refs[0]["bytes"] != int(root_row["file_bytes"]):
        raise ValueError("TVFS .root does not match reported legacy ROOT")
    report = dict(format="wowforever-manifest-lab-v1", root=root_header(root_bytes),
                  root_file_bytes=int(root_row["file_bytes"]),
                  root_full_integrity_verified=False,
                  tvfs=dict(file_bytes=len(vfs_bytes), md5_verified=True,
                            version=1, flags=parsed["flags"],
                            max_depth=parsed["max_depth"],
                            top_level_references=len(parsed["leaves"]),
                            legacy_root_reference_matches=True),
                  client_installation_supported=False)
    if args.experiment_dir:
        payload = b"WoWForEver offline TVFS experiment; not a client patch.\n"
        candidate, blte = append_lab_leaf(vfs_bytes, ".wowforever-lab", payload)
        # A new directory prevents overwriting an earlier experiment or client files.
        args.experiment_dir.mkdir(parents=True, exist_ok=False)
        (args.experiment_dir / "candidate-tvfs.decoded").write_bytes(candidate)
        (args.experiment_dir / "lab-payload.blte").write_bytes(blte)
        report["experiment"] = dict(original_references_preserved=len(parsed["leaves"]),
                                     candidate_references=len(parse_tvfs(candidate)["leaves"]),
                                     candidate_bytes=len(candidate),
                                     installed=False,
                                     limitation="Standalone TVFS copy only; no ROOT, encoding, local IDX, build config, or WowB.exe validation")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
