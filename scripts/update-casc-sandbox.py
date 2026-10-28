#!/usr/bin/env python3
"""Incrementally update a COPY of an existing synthetic CASC lab.

Only build-casc-sandbox.py fixtures are accepted. Real-client installation is
deliberately unsupported until real manifest variants and WowB.exe are tested.
"""
import argparse
import csv
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

from casc_manifest_update import append_root, extend_encoding, Encoding


def load_script(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+".py"))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


lab=load_script("build-casc-sandbox")
tvfs=load_script("casc-manifest-lab")


def md5(data):
    return hashlib.md5(data).digest()


def read_index(raw,bucket):
    if len(raw)<40:
        raise ValueError("Truncated IDX")
    length,checksum=struct.unpack_from("<II",raw)
    if length!=16 or lab.hashlittle(raw[8:24])!=checksum:
        raise ValueError("IDX header checksum mismatch")
    version,number,extra,sz,off,key,bits,segment=struct.unpack_from("<H6BQ",raw,8)
    if (version,number,extra,sz,off,key)!=(7,bucket,0,4,5,9) or not 1<=bits<40:
        raise ValueError("Unsupported IDX layout")
    count,expected=struct.unpack_from("<II",raw,32)
    records=[]
    checksum_modes=[]
    if count:
        if count%18 or 40+count>len(raw):
            raise ValueError("Invalid IDX block length")
        high=low=blizz=0
        for pos in range(40,40+count,18):
            entry=raw[pos:pos+18];records.append(entry)
            high,low=lab.hashlittle2(entry,high,low)
            blizz=lab.hashlittle(entry,blizz)
        if expected not in (high,blizz):
            raise ValueError("IDX entry block checksum mismatch")
        if expected==high:checksum_modes.append("native-two-seed")
        if expected==blizz:checksum_modes.append("blizzget")
    else:
        if len(raw)<0x8000:
            raise ValueError("Unsupported empty IDX layout")
        for start in range(0x1000,len(raw),512):
            page=raw[start:start+512];pos=0
            while pos+23<=len(page):
                checksum=struct.unpack_from("<I",page,pos)[0]
                if not checksum:
                    if any(page[pos:]):raise ValueError("Nonzero IDX page padding")
                    break
                entry=page[pos+4:pos+22]
                if (lab.hashlittle(page[pos+4:pos+23])|0x80000000)!=checksum:
                    raise ValueError("IDX paged checksum mismatch")
                records.append(entry);pos+=24
    return dict(bits=bits,segment=segment,records=records,
                layout="guarded" if count else "paged",checksum_modes=checksum_modes)


def write_index(number,records,bits,segment):
    header=struct.pack("<H6BQ",7,number,0,4,5,9,bits,segment)
    ordered=sorted(records)
    checksum=0
    for row in ordered:checksum=lab.hashlittle(row,checksum)
    blob=lab.guarded(header,lab.hashlittle(header))+bytes(8)
    blob+=lab.guarded(b"".join(ordered),checksum)
    return blob if ordered else blob.ljust(0x8000,b"\0")


def decode_blte(blob,expected_ekey,expected_ckey=None):
    if len(blob)<9 or blob[:4]!=b"BLTE":raise ValueError("Missing BLTE header")
    header_size=struct.unpack_from(">I",blob,4)[0]
    if md5(blob[:header_size] if header_size else blob)!=expected_ekey:
        raise ValueError("BLTE EKey mismatch")
    if header_size:
        if len(blob)<12 or blob[8]!=15:
            raise ValueError("Invalid BLTE frame table")
        count=int.from_bytes(blob[9:12],"big")
        if not count or header_size!=12+24*count or header_size>len(blob):
            raise ValueError("Invalid BLTE header size")
        frames=[];pos=header_size
        for index in range(count):
            encoded,decoded,digest=struct.unpack_from(">II16s",blob,12+24*index)
            frame=blob[pos:pos+encoded]
            if len(frame)!=encoded or md5(frame)!=digest:
                raise ValueError("BLTE frame checksum mismatch")
            frames.append((frame,decoded));pos+=encoded
        if pos!=len(blob):raise ValueError("Trailing BLTE bytes")
    else:
        frames=[(blob[8:],None)]
    output=bytearray()
    for frame,size in frames:
        if frame[:1]==b"N":body=frame[1:]
        elif frame[:1]==b"Z":
            decoder=zlib.decompressobj()
            body=decoder.decompress(frame[1:],256*1024*1024-len(output)+1)
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise ValueError("Invalid or oversized zlib frame")
        else:raise ValueError("Unsupported BLTE frame codec; no encrypted-data override")
        if size is not None and len(body)!=size:
            raise ValueError("BLTE decoded size mismatch")
        if len(output)+len(body)>256*1024*1024:
            raise ValueError("Decoded metadata exceeds 256 MiB")
        output.extend(body)
    result=bytes(output)
    if expected_ckey is not None and md5(result)!=expected_ckey:
        raise ValueError("Decoded CKey mismatch")
    return result


class Store:
    def __init__(self,path,synthetic_only=True):
        self.path=Path(path).resolve(strict=True)
        marker={}
        if synthetic_only:
            marker=json.loads((self.path/"lab.json").read_text())
            if marker.get("format")!="wowforever-synthetic-casc-v1" or marker.get("synthetic") is not True:
                raise ValueError("Only synthetic CASC labs are supported")
            if any(p.is_symlink() for p in self.path.rglob("*")):
                raise ValueError("Symlinked lab files are unsupported")
        self.marker=marker
        self.info=(self.path/".build.info").read_text()
        self.csv=list(csv.reader(io.StringIO(self.info),delimiter="|"))
        if not self.csv:raise ValueError("Empty .build.info")
        self.headers=self.csv[0]
        if any(row and len(row)!=len(self.headers) for row in self.csv[1:]):
            raise ValueError("Malformed .build.info row")
        names={v.split("!")[0]:i for i,v in enumerate(self.headers)}
        matches=[i for i,r in enumerate(self.csv[1:],1) if r and
                 r[names["Active"]]=="1" and r[names["Product"]]==lab.PRODUCT]
        if len(matches)!=1:raise ValueError("Expected one active lab product")
        self.row=matches[0];self.build_column=names["Build Key"]
        self.build_key=self.csv[self.row][self.build_column]
        if not re.fullmatch("[0-9a-f]{32}",self.build_key):raise ValueError("Invalid build key")
        self.config_path=Path("Data/config")/self.build_key[:2]/self.build_key[2:4]/self.build_key
        config=(self.path/self.config_path).read_bytes()
        if md5(config).hex()!=self.build_key:raise ValueError("Build config hash mismatch")
        self.config=config.decode()
        self.values=dict(line.split(" = ",1) for line in self.config.splitlines() if " = " in line)
        self.buckets={};self.entries={};self.bits=None
        paths={}
        for p in (self.path/"Data/data").glob("*.idx"):
            match=re.fullmatch(r"([0-9a-f]{2})([0-9a-f]{8})\.idx",p.name)
            if match:
                number,version=(int(v,16) for v in match.groups())
                if number<16 and (number not in paths or version>paths[number][0]):
                    paths[number]=(version,p)
        if len(paths)!=16:raise ValueError("All 16 IDX buckets are required")
        for number,(version,p) in paths.items():
            try:parsed=read_index(p.read_bytes(),number)
            except ValueError as error:raise ValueError(f"{p.name}: {error}") from error
            if self.bits is not None and self.bits!=parsed["bits"]:
                raise ValueError("IDX offset widths disagree")
            self.bits=parsed["bits"]
            self.buckets[number]=dict(version=version,**parsed)
            for entry in parsed["records"]:
                if entry[:9] in self.entries and self.entries[entry[:9]]!=entry:
                    raise ValueError("Conflicting local EKey prefixes")
                self.entries[entry[:9]]=entry

    def read(self,ekey,ckey=None):
        entry=self.entries.get(ekey[:9])
        if entry is None:raise ValueError("Metadata not resident in local IDX")
        position=int.from_bytes(entry[9:14],"big")
        segment,offset=position>>self.bits,position&((1<<self.bits)-1)
        size=struct.unpack_from("<I",entry,14)[0]
        if size<39 or size>256*1024*1024:raise ValueError("Metadata size outside lab limits")
        with (self.path/"Data/data"/f"data.{segment:03d}").open("rb") as f:
            f.seek(offset);raw=f.read(size)
        if len(raw)!=size:raise ValueError("Truncated local data record")
        # Archive records have a 30-byte prefix before BLTE.
        return decode_blte(raw[30:],ekey,ckey)


def rebuild_tvfs(original,root,resources,locale=2,path_transform=None):
    parsed=tvfs.parse_tvfs(original)
    paths=dict(parsed["leaves"]);est=parsed["tables"]["est"]
    cursor=0;offset=None
    for spec in est.split(b"\0")[:-1]:
        if spec==b"b:{*=n}":offset=cursor;break
        cursor+=len(spec)+1
    if offset is None:offset=len(est);est+=b"b:{*=n}\0"
    def span(obj):
        return [dict(offset=0,bytes=len(obj["content"]),ekey_prefix=obj["ekey"][:9].hex(),
                     encoded_bytes=len(obj["encoded"]),content_bytes=len(obj["content"]),
                     ckey=obj["ckey"].hex(),espec_offset=offset)]
    if ".root" not in paths:raise ValueError("Missing TVFS .root reference")
    paths[".root"]=span(root)
    for fid,obj in resources.items():
        name=f"{locale:08X}10000000:{fid:08X}{obj['ckey'].hex().upper()}"
        if name in paths:raise ValueError("Duplicate TVFS resource path")
        paths[name]=span(obj)
    if path_transform is not None:
        transformed={}
        for name,spans in paths.items():
            changed=path_transform(name)
            if changed in transformed:raise ValueError('TVFS transformed path collision')
            transformed[changed]=spans
        paths=transformed
    ew=tvfs.width(len(est));cft=bytearray();offsets=[]
    for name,spans in sorted(paths.items()):
        for s in spans:
            offsets.append(len(cft))
            cft.extend(bytes.fromhex(s["ekey_prefix"])+struct.pack(">I",s["encoded_bytes"]))
            cft.extend(s["espec_offset"].to_bytes(ew,"big"))
            cft.extend(struct.pack(">I",s["content_bytes"])+bytes.fromhex(s["ckey"])+b"\0")
    cw=tvfs.width(len(cft));path=bytearray();vfs=bytearray();index=0
    for name,spans in sorted(paths.items()):
        raw=name.encode("ascii")
        if not 0<len(raw)<255:raise ValueError("Unsupported TVFS path length")
        path.extend(bytes([len(raw)])+raw+b"\xff"+struct.pack(">I",len(vfs)))
        vfs.extend(bytes([len(spans)]))
        for s in spans:
            vfs.extend(struct.pack(">II",s["offset"],s["bytes"])+offsets[index].to_bytes(cw,"big"))
            index+=1
    path=b"\xff"+struct.pack(">I",0x80000000|(len(path)+4))+bytes(path)
    po=46;eo=po+len(path);co=eo+len(est);vo=co+len(cft)
    header=struct.pack(">4s4B7IH2I",b"TVFS",1,46,9,9,7,po,len(path),vo,len(vfs),
                       co,len(cft),max(1,parsed["max_depth"]),eo,len(est))
    result=header+path+est+bytes(cft)+bytes(vfs)
    actual=tvfs.parse_tvfs(result)["leaves"]
    if actual!=paths:raise ValueError("TVFS rebuild changed span fields")
    return result


def extend_download(original,objects):
    # Restrict this first storage updater to the lab's tagless, checksumless v1.
    if len(original)<16 or original[:5]!=b"DL\1\x10\0" or original[9:11]!=b"\0\0":
        raise ValueError("Unsupported DOWNLOAD variant; real-client profile needs an audit")
    count=struct.unpack_from(">I",original,5)[0];end=11+count*22
    if end>len(original):raise ValueError("Truncated DOWNLOAD records")
    old=original[11:end];known={old[i:i+16] for i in range(0,len(old),22)}
    added=b""
    for obj in objects:
        if obj["ekey"] not in known:
            added+=obj["ekey"]+len(obj["encoded"]).to_bytes(5,"big")+b"\0"
            known.add(obj["ekey"])
    header=bytearray(original[:11]);struct.pack_into(">I",header,5,count+len(added)//22)
    return bytes(header)+old+added+original[end:]


def update(source,package,destination,checker=None):
    store=Store(source);package=Path(package).resolve(strict=True)
    destination=Path(destination).resolve()
    if destination.exists():raise FileExistsError(destination)
    if destination==store.path or store.path in destination.parents:
        raise ValueError("Destination must be outside source lab")
    spec=json.loads(package.read_text())
    if spec.get("format")!="wowforever-casc-resource-package-v1" or spec.get("base_build_key")!=store.build_key:
        raise ValueError("Package format or source build mismatch")
    resources={};total=0
    items=spec.get("resources")
    if not isinstance(items,list) or not 1<=len(items)<=100:
        raise ValueError("Expected 1..100 resources")
    for row in items:
        fid=row["file_data_id"]
        if type(fid) is not int or not 0<fid<=0xffffffff or fid in resources:
            raise ValueError("Invalid/duplicate package FileDataID")
        rel=Path(row["path"])
        if rel.is_absolute() or ".." in rel.parts:raise ValueError("Invalid resource path")
        path=(package.parent/rel).resolve(strict=True)
        if not path.is_relative_to(package.parent):raise ValueError("Resource path escapes package")
        if path.stat().st_size>64*1024*1024:raise ValueError("Resource exceeds 64 MiB")
        content=path.read_bytes();total+=len(content)
        if total>128*1024*1024:raise ValueError("Package exceeds 128 MiB lab limit")
        if hashlib.sha256(content).hexdigest()!=row["sha256"]:raise ValueError("Package SHA-256 mismatch")
        resources[fid]=lab.asset(content)
    if not resources or len(resources)>100:raise ValueError("Expected 1..100 resources")
    def configured(name):
        keys=store.values[name].split()
        return store.read(bytes.fromhex(keys[1]),bytes.fromhex(keys[0]))
    encoding_bytes=configured("encoding");encoding=Encoding(encoding_bytes)
    root_ckey=bytes.fromhex(store.values["root"].split()[0]);root_ekey=None
    # Exhaust the iterator to validate every original CKey page before copying.
    for key,raw in encoding.rows("c"):
        if key==root_ckey:root_ekey=raw[22:38]
    if root_ekey is None:raise ValueError("ROOT CKey missing from ENCODING")
    old_root=store.read(root_ekey,root_ckey)
    old_vfs=configured("vfs-root")
    references=tvfs.parse_tvfs(old_vfs)["leaves"].get(".root",[])
    if (len(references)!=1 or references[0]["ckey"]!=root_ckey.hex() or
            references[0]["offset"]!=0 or references[0]["bytes"]!=len(old_root)):
        raise ValueError("TVFS .root disagrees with source build")
    root=lab.asset(append_root(old_root,
                               {fid:obj["ckey"] for fid,obj in resources.items()}))
    vfs=lab.asset(rebuild_tvfs(old_vfs,root,resources))
    additions=list(resources.values())+[root,vfs]
    download=lab.asset(extend_download(configured("download"),additions))
    additions.append(download)
    encoded=lab.asset(extend_encoding(encoding_bytes,additions));additions.append(encoded)
    segment_numbers=[int(p.name[5:]) for p in (store.path/"Data/data").glob("data.*")
                     if re.fullmatch(r"data\.\d{3}",p.name)]
    segment=max(segment_numbers)+1
    if segment>999 or segment>=(1<<(40-store.bits)):raise ValueError("No free data segment number")
    body=bytearray();new_entries={};new_encodings={};reused=0
    for obj in additions:
        key=obj["ekey"][:9]
        if key in store.entries:
            # A matching 9-byte index prefix is insufficient. Verify full EKey,
            # frame hashes, decoded CKey and bytes before reusing existing data.
            if store.read(obj["ekey"],obj["ckey"])!=obj["content"]:
                raise ValueError("Existing EKey prefix conflict")
            reused+=1
            continue
        if key in new_encodings:
            if new_encodings[key]!=obj["encoded"]:raise ValueError("Package EKey prefix conflict")
            continue
        new_encodings[key]=obj["encoded"]
        offset=len(body);raw=lab.storage_record(obj,offset);body.extend(raw)
        position=(segment<<store.bits)|offset
        new_entries[key]=key+position.to_bytes(5,"big")+struct.pack("<I",len(raw))
    if len(body)>(1<<store.bits):raise ValueError("New segment exceeds IDX offset capacity")
    values=dict(store.values)
    for name,obj in (("root",root),("encoding",encoded),("download",download),("vfs-root",vfs),("vfs-1",vfs)):
        values[name]=obj["ckey"].hex()+(" "+obj["ekey"].hex() if name!="root" else "")
        if name!="root":values[name+"-size"]=f"{len(obj['content'])} {len(obj['encoded'])}"
    config="\n".join(line.split(" = ",1)[0]+" = "+values[line.split(" = ",1)[0]]
                       if " = " in line else line for line in store.config.splitlines())+"\n"
    build_key=md5(config.encode()).hex()
    report=dict(format="wowforever-synthetic-casc-v1",synthetic=True,game_client_modified=False,
                source_build_key=store.build_key,build_key=build_key,product=lab.PRODUCT,
                resources=dict(store.marker["resources"]),new_segment=segment,
                reused_existing_encodings=reused,
                updater="incremental copy; old data segments unchanged")
    for fid,obj in resources.items():
        report["resources"][str(fid)]=dict(bytes=len(obj["content"]),sha256=hashlib.sha256(obj["content"]).hexdigest(),
                                           ckey=obj["ckey"].hex(),ekey=obj["ekey"].hex())
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".casc-update-",dir=destination.parent) as temp:
        stage=Path(temp)/"store";shutil.copytree(store.path,stage)
        # Do not carry an earlier candidate's verification claim into a new copy.
        (stage/"update-report.json").unlink(missing_ok=True)
        (stage/"Data/data"/f"data.{segment:03d}").write_bytes(body)
        for number,bucket in store.buckets.items():
            extra=[v for k,v in new_entries.items() if lab.bucket(k)==number]
            if not extra:continue
            if bucket["version"]>=0xffffffff:raise ValueError("IDX generation overflow")
            filename=f"{number:02x}{bucket['version']+1:08x}.idx"
            (stage/"Data/data"/filename).write_bytes(write_index(number,bucket["records"]+extra,store.bits,bucket["segment"]))
        target=stage/"Data/config"/build_key[:2]/build_key[2:4]/build_key
        target.parent.mkdir(parents=True,exist_ok=True);target.write_text(config)
        store.csv[store.row][store.build_column]=build_key
        info=io.StringIO();writer=csv.writer(info,delimiter="|",lineterminator="\n");writer.writerows(store.csv)
        (stage/".build.info").write_text(info.getvalue())
        (stage/"lab.json").write_text(json.dumps(report,indent=2)+"\n")
        if checker:
            result=subprocess.run([str(Path(checker).resolve()),str(stage),*report["resources"]],
                                  capture_output=True,text=True,timeout=30)
            rows=list(csv.DictReader(io.StringIO(result.stdout),delimiter="\t"))
            if (result.returncode or len(rows)!=len(report["resources"]) or
                    {row["file_id"] for row in rows}!=set(report["resources"])):
                raise ValueError("Native storage verification failed: "+result.stderr)
            for row in rows:
                expected=report["resources"][row["file_id"]]
                if row["status"]!="READ_OK" or row["sha256"]!=expected["sha256"] or int(row["bytes"])!=expected["bytes"]:
                    raise ValueError("Native resource verification mismatch")
            report["native_verified_resources"]=len(rows)
            (stage/"update-report.json").write_text(json.dumps(report,indent=2)+"\n")
        if destination.exists():raise FileExistsError(destination)
        os.rename(stage,destination)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--package",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--checker",type=Path)
    args=parser.parse_args()
    print(json.dumps(update(args.source,args.package,args.output,args.checker),indent=2))


if __name__=="__main__":main()
