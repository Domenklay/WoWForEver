#!/usr/bin/env python3
"""Create a NEW, synthetic offline CASC laboratory. Never edits a game client.

The header-span checksum adapts CascLib code, Copyright (c) 2014 Ladislav Zezula.
Its MIT notice is in tools/legion-casc-probe/CASCLIB-LICENSE.txt.
Binary layouts follow the Forever core's CascLib readers. Jenkins lookup3 is
Bob Jenkins' public-domain algorithm. This is not an installer or a CASC updater.
"""
import argparse
import csv
import hashlib
import io
import json
import shutil
import struct
import subprocess
from pathlib import Path

PRODUCT = "wow_classic_beta"
BASE_ID = 0x00FFFFF0
NEW_ID = BASE_ID + 1
BASE_TEXT = b"WoWForEver synthetic baseline resource.\n"
NEW_TEXT = b"WoWForEver synthetic added resource.\n"
MASK = 0xFFFFFFFF


def rot(x, k):
    return ((x << k) | (x >> (32-k))) & MASK


def hashlittle2(data, seed=0, low=0):
    """lookup3 pair (pc, pb), including the unaligned byte path."""
    a = b = c = (0xDEADBEEF + len(data) + seed) & MASK
    c = (c+low)&MASK
    pos = 0
    while len(data)-pos > 12:
        x, y, z = struct.unpack_from("<3I", data, pos)
        a, b, c = (a+x)&MASK, (b+y)&MASK, (c+z)&MASK
        a = ((a-c)&MASK) ^ rot(c, 4); c = (c+b)&MASK
        b = ((b-a)&MASK) ^ rot(a, 6); a = (a+c)&MASK
        c = ((c-b)&MASK) ^ rot(b, 8); b = (b+a)&MASK
        a = ((a-c)&MASK) ^ rot(c,16); c = (c+b)&MASK
        b = ((b-a)&MASK) ^ rot(a,19); a = (a+c)&MASK
        c = ((c-b)&MASK) ^ rot(b, 4); b = (b+a)&MASK
        pos += 12
    tail = data[pos:]
    if not tail:
        return c,b
    a = (a+int.from_bytes(tail[:4], "little"))&MASK
    b = (b+int.from_bytes(tail[4:8], "little"))&MASK
    c = (c+int.from_bytes(tail[8:12], "little"))&MASK
    c = ((c ^ b)-rot(b,14))&MASK
    a = ((a ^ c)-rot(c,11))&MASK
    b = ((b ^ a)-rot(a,25))&MASK
    c = ((c ^ b)-rot(b,16))&MASK
    a = ((a ^ c)-rot(c, 4))&MASK
    b = ((b ^ a)-rot(a,14))&MASK
    return ((c ^ b)-rot(b,24))&MASK,b


def hashlittle(data, seed=0):
    return hashlittle2(data,seed)[0]


def asset(content):
    # One checksummed BLTE frame: deliberately exercise strict frame validation.
    frame = b"N" + content
    header = b"BLTE" + struct.pack(">I", 36) + b"\x0f\0\0\1"
    header += struct.pack(">II", len(frame), len(content)) + hashlib.md5(frame).digest()
    encoded = header + frame
    return dict(content=content, encoded=encoded, ckey=hashlib.md5(content).digest(),
                ekey=hashlib.md5(header).digest())


def make_root(records):
    """ROOT TSFM, actual header version=2, 17-byte (58221) group header."""
    records = sorted(records.items())
    if not records or any(not 0 < i <= MASK for i, _ in records):
        raise ValueError("Expected nonempty positive FileDataIDs")
    header = b"TSFM" + struct.pack("<5I", 24, 2, len(records), 0, 0)
    # No name hashes, enUS locale. FileID deltas are relative to previous ID+1.
    group = struct.pack("<4IB", len(records), 2, 0x10000000, 0, 0)
    previous = 0
    for file_id, _ in records:
        group += struct.pack("<I", file_id-previous)
        previous = file_id+1
    return header + group + b"".join(obj["ckey"] for _, obj in records)


def make_tvfs(root, records):
    """Tiny top-level directory: .root plus WoW generic file references.

    Default Forever CascLib reparses generic WoW names through legacy ROOT.
    This deliberately exercises that fallback, not a TVFS-only reader build.
    """
    entries = [(".root", root)] + [
        (f"0000000210000000:{i:08X}{obj['ckey'].hex().upper()}", obj)
        for i, obj in sorted(records.items())]
    est = b"b:{*=n}\0"
    path = vfs = cft = b""
    for name, obj in entries:
        raw = name.encode("ascii")
        path += bytes([len(raw)]) + raw + b"\xff" + struct.pack(">I", len(vfs))
        vfs += b"\1" + struct.pack(">II", 0, len(obj["content"])) + bytes([len(cft)])
        cft += obj["ekey"][:9] + struct.pack(">I", len(obj["encoded"])) + b"\0"
        cft += struct.pack(">I", len(obj["content"])) + obj["ckey"] + b"\0"
    path = b"\xff" + struct.pack(">I", 0x80000000 | (len(path)+4)) + path
    po, eo = 46, 46+len(path)
    co, vo = eo+len(est), eo+len(est)+len(cft)
    header = struct.pack(">4s4B7IH2I", b"TVFS", 1, 46, 9, 9, 7,
                         po, len(path), vo, len(vfs), co, len(cft), 1, eo, len(est))
    return header + path + est + cft + vfs


def make_encoding(objects):
    objects = sorted(objects, key=lambda obj: obj["ckey"])
    spec = b"b:{*=n}\0"
    cpage = b"".join(b"\1" + len(obj["content"]).to_bytes(5,"big") + obj["ckey"] + obj["ekey"]
                     for obj in objects)
    eobjects = sorted(objects, key=lambda obj: obj["ekey"])
    epage = b"".join(obj["ekey"] + bytes(4) + len(obj["encoded"]).to_bytes(5,"big")
                     for obj in eobjects)
    if len(cpage)>1000 or len(epage)>1000:
        raise ValueError("Synthetic single-page encoding limit exceeded")
    cpage, epage = cpage.ljust(1024,b"\0"), epage.ljust(1024,b"\0")
    header = b"EN\1\x10\x10" + struct.pack(">HHII",1,1,1,1) + b"\0" + struct.pack(">I",len(spec))
    return (header + spec + objects[0]["ckey"] + hashlib.md5(cpage).digest() + cpage +
            eobjects[0]["ekey"] + hashlib.md5(epage).digest() + epage)


def bucket(key):
    value = 0
    for byte in key[:9]:
        value ^= byte
    return (value ^ (value >> 4)) & 15


def guarded(data, checksum):
    return struct.pack("<II",len(data),checksum) + data


def storage_record(obj, offset, flags=0):
    length = 30 + len(obj["encoded"])
    head = obj["ekey"][::-1] + struct.pack("<IH",length,flags)
    head += struct.pack("<I",hashlittle(head,0x3D6BE971))
    # Agent header-span checksum, from CascLib VerifyHeaderSpan (not a bypass).
    constants = [0x049396B8,0x72A82A9B,0xEE626CCA,0x9917754F,
                 0x15DE40B1,0xF5A8A9B6,0x421EAC7E,0xA9D55C9A,
                 0x317FD40C,0x04FAF80D,0x3D6BE971,0x52933CFD,
                 0x27F64B7D,0xC6F5C11B,0xD5757E3A,0x6C388745]
    position = offset+30
    encoded_offset = (position ^ constants[position&15]).to_bytes(4,"little")
    hashed = bytearray(4)
    for i, byte in enumerate(head):
        hashed[i&3] ^= byte
    checksum = bytes(hashed[(26+j)&3] ^ encoded_offset[(26+j)&3] for j in range(4))
    return head + checksum + obj["encoded"]


def write_store(destination, added=False):
    destination = Path(destination)
    # Never mutate or merge with an existing directory, even a failed earlier lab.
    destination.mkdir(parents=True, exist_ok=False)
    data = destination / "Data/data"
    data.mkdir(parents=True)
    records = {BASE_ID: asset(BASE_TEXT)}
    if added:
        records[NEW_ID] = asset(NEW_TEXT)
    root = asset(make_root(records))
    tvfs = asset(make_tvfs(root, records))
    # Empty version-1 DOWNLOAD; padding satisfies the reader's full header struct.
    download = asset(b"DL\1\x10\0" + bytes(11))
    objects = list(records.values()) + [root,tvfs,download]
    encoding = asset(make_encoding(objects))
    objects.append(encoding)
    segment = b""
    groups = {}
    for obj in objects:
        offset = len(segment)
        stored = storage_record(obj,offset)
        segment += stored
        entry = obj["ekey"][:9] + offset.to_bytes(5,"big") + struct.pack("<I",len(stored))
        groups.setdefault(bucket(obj["ekey"]),[]).append(entry)
    (data / "data.000").write_bytes(segment)
    for number in range(16):
        entries = groups.get(number,[])
        header = struct.pack("<H6BQ",7,number,0,4,5,9,30,1<<30)
        entries = sorted(entries)
        checksum = 0
        for entry in entries:
            checksum = hashlittle(entry,checksum)
        index = guarded(header,hashlittle(header)) + bytes(8)
        index += guarded(b"".join(entries),checksum)
        if not entries:
            # Empty paged IDX. CascLib stops its bucket scan at the first missing
            # file, and its contiguous-block form requires at least one entry.
            index = index.ljust(0x8000,b"\0")
        (data / f"{number:02x}00000001.idx").write_bytes(index)
    config = ("# Synthetic offline CASC lab; not a game installation\n"
              "build-name = WOW-70532-WoWForEver-LAB\n"
              f"build-uid = {PRODUCT}\n"
              f"root = {root['ckey'].hex()}\n"
              f"encoding = {encoding['ckey'].hex()} {encoding['ekey'].hex()}\n"
              f"encoding-size = {len(encoding['content'])} {len(encoding['encoded'])}\n"
              f"download = {download['ckey'].hex()} {download['ekey'].hex()}\n"
              f"download-size = {len(download['content'])} {len(download['encoded'])}\n"
              f"vfs-root = {tvfs['ckey'].hex()} {tvfs['ekey'].hex()}\n"
              f"vfs-root-size = {len(tvfs['content'])} {len(tvfs['encoded'])}\n"
              f"vfs-1 = {tvfs['ckey'].hex()} {tvfs['ekey'].hex()}\n"
              f"vfs-1-size = {len(tvfs['content'])} {len(tvfs['encoded'])}\n").encode()
    build_key = hashlib.md5(config).hexdigest()
    config_path = destination / "Data/config" / build_key[:2] / build_key[2:4] / build_key
    config_path.parent.mkdir(parents=True)
    config_path.write_bytes(config)
    cdn = b"# Offline synthetic CDN configuration; no remote sources\narchives = " + hashlib.md5(segment).hexdigest().encode() + b"\n"
    cdn_key = hashlib.md5(cdn).hexdigest()
    cdn_path = destination / "Data/config" / cdn_key[:2] / cdn_key[2:4] / cdn_key
    cdn_path.parent.mkdir(parents=True,exist_ok=True)
    cdn_path.write_bytes(cdn)
    (destination / ".build.info").write_text(
        "Branch!STRING:0|Active!DEC:1|Build Key!HEX:16|CDN Key!HEX:16|Tags!STRING:0|Version!STRING:0|Product!STRING:0\n"
        f"lab|1|{build_key}|{cdn_key}|Windows x86_64 enUS text?|1.60.1.70532|{PRODUCT}\n")
    report = dict(format="wowforever-synthetic-casc-v1", synthetic=True,
                  game_client_modified=False, product=PRODUCT, build_key=build_key,
                  objects=len(objects), data_bytes=len(segment), index_files=16,
                  nonempty_index_files=len(groups),
                  root_version=2, tvfs=True, encoding=True,
                  resources={str(i):dict(bytes=len(obj["content"]),
                                         sha256=hashlib.sha256(obj["content"]).hexdigest(),
                                         ckey=obj["ckey"].hex(),ekey=obj["ekey"].hex())
                             for i,obj in records.items()})
    (destination / "lab.json").write_text(json.dumps(report,indent=2)+"\n")
    return report


def verify_stores(checker, directory):
    """Four independent outcomes, using real CascLib rather than a mocked reader."""
    checker = str(Path(checker).resolve(strict=True))
    directory = Path(directory)
    for name, original in (("data-only","baseline"),("damaged-frame","candidate")):
        target = directory / name
        shutil.copytree(directory/original,target)
        data = target / "Data/data/data.000"
        content = data.read_bytes()
        if name == "data-only":
            content += storage_record(asset(NEW_TEXT),len(content))
        else:
            offset = content.index(NEW_TEXT)
            content = content[:offset] + bytes([content[offset]^1]) + content[offset+1:]
        data.write_bytes(content)
    result = dict(format="wowforever-synthetic-casc-verification-v1",cases={},
                  synthetic_only=True, client_compatibility_verified=False)
    for name, expected in (("baseline","OPEN_FAILED"),("candidate","READ_OK"),
                           ("data-only","OPEN_FAILED"),("damaged-frame","READ_FAILED")):
        run = subprocess.run([checker,str(directory/name),str(BASE_ID),str(NEW_ID)],
                             capture_output=True,text=True,timeout=30)
        rows = list(csv.DictReader(io.StringIO(run.stdout),delimiter="\t"))
        # Store evidence even on a failed test; do not turn a storage-open failure into a pass.
        (directory/f"{name}.stderr.log").write_text(run.stderr)
        result["cases"][name] = dict(exit_code=run.returncode,results=rows)
        expected_exit = 0 if expected == "READ_OK" else 1
        if (run.returncode != expected_exit or len(rows)!=2 or
                "ROOT (reparsed)" not in run.stderr or
                rows[0]["file_id"]!=str(BASE_ID) or rows[0]["status"]!="READ_OK" or
                rows[0]["bytes"]!=str(len(BASE_TEXT)) or
                rows[0]["sha256"]!=hashlib.sha256(BASE_TEXT).hexdigest() or
                rows[1]["file_id"]!=str(NEW_ID) or rows[1]["status"]!=expected):
            raise RuntimeError(f"Unexpected native result in {name}: {run.stdout} {run.stderr}")
        if expected == "READ_OK" and (rows[1]["sha256"]!=hashlib.sha256(NEW_TEXT).hexdigest()
                                      or rows[1]["bytes"]!=str(len(NEW_TEXT))):
            raise RuntimeError("Added resource hash/size mismatch")
    result["all_passed"] = True
    (directory/"verification.json").write_text(json.dumps(result,indent=2)+"\n")
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--checker",type=Path,help="Optional compiled check-storage executable")
    args = ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    result = dict(baseline=write_store(args.output/"baseline"),
                  candidate=write_store(args.output/"candidate",added=True))
    if args.checker:
        result["verification"] = verify_stores(args.checker,args.output)
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
