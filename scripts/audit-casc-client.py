#!/usr/bin/env python3
"""Read-only local manifest audit. Writes only the requested JSON report.

No downloading, key fetching, encrypted-data substitution, or client updates.
The complete ROOT/ENCODING/DOWNLOAD are read locally; raw files are not exported.
"""
import argparse
import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path

from casc_manifest_update import root_groups,Encoding

SPEC=importlib.util.spec_from_file_location("casc_copy",Path(__file__).with_name("update-casc-sandbox.py"))
copy=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(copy)


def audit(path):
    store=copy.Store(path,synthetic_only=False)
    result=dict(format="wowforever-full-manifest-audit-v1",build_key=store.build_key,
                build_name=store.values.get("build-name"),
                client_modified=False,installation_supported=False,
                idx=dict(buckets=16,unique_ekey_prefixes=len(store.entries),offset_bits=store.bits))
    result["idx"]["profiles"]=[dict(bucket=number,generation=entry["version"],
                                    records=len(entry["records"]),layout=entry["layout"],
                                    checksum_modes=entry["checksum_modes"])
                               for number,entry in sorted(store.buckets.items())]
    def configured(name):
        keys=store.values[name].split()
        body=store.read(bytes.fromhex(keys[1]),bytes.fromhex(keys[0]))
        return body
    print("Reading ENCODING and validating all pages...",file=sys.stderr,flush=True)
    encoded=configured("encoding");encoding=Encoding(encoded)
    root_ckey=bytes.fromhex(store.values["root"].split()[0]);root_ekey=None
    ccount=ecount=variants=0
    for key,raw in encoding.rows("c"):
        ccount+=1;variants+=raw[0]
        if key==root_ckey:root_ekey=raw[22:38]
    for _key,_raw in encoding.rows("e"):ecount+=1
    result["encoding"]=dict(bytes=len(encoded),md5=hashlib.md5(encoded).hexdigest(),
                            ckey_pages=encoding.nc,ekey_pages=encoding.ne,
                            ckey_records=ccount,ekey_records=ecount,encoding_variants=variants,
                            ckey_page_bytes=encoding.ckb,ekey_page_bytes=encoding.ekb,
                            all_page_hashes_verified=True)
    if root_ekey is None:raise ValueError("ROOT key absent from ENCODING")
    print("Reading ROOT and checking every group...",file=sys.stderr,flush=True)
    root=store.read(root_ekey,root_ckey);groups=records=named=maximum=0
    targets={957774:[],956360:[],956397:[]};locales=set();profiles={}
    for group in root_groups(root):
        groups+=1;records+=group["count"];named+=group["count"]*group["has_names"]
        locales.add(group["locale"]);current=0
        profile=(group["locale"],*group["content_flags"])
        profiles[profile]=profiles.get(profile,0)+group["count"]
        for index,(delta,) in enumerate(struct.iter_unpack("<I",memoryview(root)[group["ids_offset"]:group["ckeys_offset"]])):
            current+=delta
            if current>0xffffffff:raise ValueError("ROOT FileDataID overflow")
            maximum=max(maximum,current)
            if current in targets:
                offset=group["ckeys_offset"]+index*16
                targets[current].append(dict(locale=group["locale"],ckey=root[offset:offset+16].hex()))
            current+=1
    result["root"]=dict(bytes=len(root),md5=hashlib.md5(root).hexdigest(),version=2,
                        groups=groups,records=records,named_records=named,max_file_data_id=maximum,
                        locale_masks=sorted(locales),target_ids=targets,all_groups_validated=True)
    result["root"]["profiles"]=[dict(locale=key[0],content_flags=list(key[1:]),records=count)
                                   for key,count in sorted(profiles.items())]
    print("Reading TVFS and DOWNLOAD...",file=sys.stderr,flush=True)
    raw_vfs=configured("vfs-root");vfs=copy.tvfs.parse_tvfs(raw_vfs)
    reference=vfs["leaves"].get(".root",[])
    if (len(reference)!=1 or reference[0]["ckey"]!=root_ckey.hex() or
            reference[0]["offset"]!=0 or reference[0]["bytes"]!=len(root)):
        raise ValueError("TVFS root reference mismatch")
    result["tvfs"]=dict(bytes=len(raw_vfs),md5=hashlib.md5(raw_vfs).hexdigest(),
                        top_level_references=len(vfs["leaves"]),legacy_root_reference_matches=True)
    download=configured("download")
    if len(download)<11 or download[:2]!=b"DL" or download[2] not in (1,2,3):
        raise ValueError("Unsupported DOWNLOAD header")
    version=download[2];header_bytes={1:11,2:12,3:16}[version]
    if len(download)<header_bytes:raise ValueError("Truncated DOWNLOAD header")
    keys=download[3];checksums=download[4];count=struct.unpack_from(">I",download,5)[0]
    tags=struct.unpack_from(">H",download,9)[0];flags=download[11] if version>=2 else 0
    entry_bytes=keys+5+1+(4 if checksums else 0)+flags
    if header_bytes+count*entry_bytes>len(download):raise ValueError("Truncated DOWNLOAD entry table")
    result["download"]=dict(bytes=len(download),md5=hashlib.md5(download).hexdigest(),
                            version=version,ekey_bytes=keys,entry_has_checksum=checksums,
                            entry_count=count,tag_count=tags,flag_bytes=flags,
                            tags_parsed=False,
                            supported_by_lab_updater=version==1 and keys==16 and not checksums and not tags)
    result["audit_passed"]=True
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    client=args.client.resolve();output=args.output.resolve()
    protected=(client/"Data").resolve()
    if output==(client/".build.info").resolve() or output==protected or protected in output.parents:
        parser.error("Report must be outside the client's Data and .build.info")
    try:
        result=audit(client)
    except (ValueError,OSError,KeyError,struct.error) as error:
        result=dict(format="wowforever-full-manifest-audit-v1",audit_passed=False,
                    client_modified=False,error=str(error),installation_supported=False)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+"\n")
    print(f"Report: {output}")
    if not result.get("audit_passed"):
        print("Audit stopped: "+result["error"],file=sys.stderr);return 1
    return 0


if __name__=="__main__":raise SystemExit(main())
