"""Conservative transforms for decoded ROOT v2 and ENCODING v1 manifests.

Existing entries are validated and preserved. These functions do not open or
write a game installation. Binary layouts follow the Forever CascLib readers.
"""
import hashlib
import struct


def root_groups(data):
    if len(data)<24 or data[:4]!=b"TSFM":
        raise ValueError("Expected TSFM ROOT")
    size,version,total,named,_ = struct.unpack_from("<5I",data,4)
    if size!=24 or version!=2 or named>total:
        raise ValueError("Unsupported ROOT header")
    pos,seen,names = size,0,0
    while pos<len(data):
        start=pos
        if pos+17>len(data):
            raise ValueError("Truncated ROOT group")
        count,locale,f1,f2,f3 = struct.unpack_from("<4IB",data,pos)
        pos+=17
        flags=f1|f2|(f3<<17)
        has_names=not flags&0x10000000
        end=pos+count*(20+8*has_names)
        if end>len(data):
            raise ValueError("Truncated ROOT records")
        yield dict(start=start,end=end,count=count,locale=locale,flags=flags,
                   content_flags=[f1,f2,f3],
                   ids_offset=pos,ckeys_offset=pos+count*4,has_names=has_names)
        pos=end;seen+=count;names+=count*has_names
    if (seen,names)!=(total,named):
        raise ValueError("ROOT header counters disagree with groups")


def append_root(data,records,locale=2):
    """Add one hashless group; preserve every old group byte-for-byte."""
    if not records or not 0<locale<=0xffffffff:
        raise ValueError("Expected new records and a valid locale mask")
    for fid,key in records.items():
        if not 0<fid<=0xffffffff or len(key)!=16:
            raise ValueError("Invalid ROOT FileDataID or CKey")
    requested=set(records)
    for group in root_groups(data):
        current=0
        for (delta,) in struct.iter_unpack("<I",memoryview(data)[group["ids_offset"]:group["ckeys_offset"]]):
            current+=delta
            if current>0xffffffff:
                raise ValueError("ROOT FileDataID overflow")
            if current in requested:
                raise ValueError(f"ROOT FileDataID conflict: {current}")
            current+=1
    count=len(records)
    total=struct.unpack_from("<I",data,12)[0]
    if total+count>0xffffffff:
        raise ValueError("ROOT record counter overflow")
    block=struct.pack("<4IB",count,locale,0x10000000,0,0)
    previous=0
    for fid in sorted(records):
        block+=struct.pack("<I",fid-previous);previous=fid+1
    block+=b"".join(records[fid] for fid in sorted(records))
    header=bytearray(data[:24]);struct.pack_into("<I",header,12,total+count)
    result=bytes(header)+data[24:]+block
    list(root_groups(result))
    return result


class Encoding:
    """Validated streaming entry views over all CKey/EKey pages, including variants."""
    def __init__(self,data):
        if len(data)<22 or data[:5]!=b"EN\1\x10\x10":
            raise ValueError("Unsupported ENCODING header")
        self.data=data
        self.ckb,self.ekb,self.nc,self.ne=struct.unpack_from(">HHII",data,5)
        self.ckb*=1024;self.ekb*=1024
        if not self.ckb or not self.ekb or data[17]!=0:
            raise ValueError("Unsupported ENCODING page sizes or flags")
        spec_len=struct.unpack_from(">I",data,18)[0]
        self.spec=data[22:22+spec_len]
        if len(self.spec)!=spec_len or not self.spec.endswith(b"\0"):
            raise ValueError("Truncated ESpec table")
        self.spec_count=len(self.spec[:-1].split(b"\0"))
        self.cindex=22+spec_len
        self.cpages=self.cindex+self.nc*32
        self.eindex=self.cpages+self.nc*self.ckb
        self.epages=self.eindex+self.ne*32
        self.end=self.epages+self.ne*self.ekb
        if self.end>len(data):
            raise ValueError("Truncated ENCODING page tables")
        self.trailing=data[self.end:]

    def rows(self,kind):
        if kind not in ("c","e"):
            raise ValueError("Unknown ENCODING table")
        count,index,start,size=(self.nc,self.cindex,self.cpages,self.ckb) if kind=="c" else (self.ne,self.eindex,self.epages,self.ekb)
        previous=None
        for number in range(count):
            page=memoryview(self.data)[start+number*size:start+(number+1)*size]
            first,digest=struct.unpack_from("16s16s",self.data,index+number*32)
            if hashlib.md5(page).digest()!=digest:
                raise ValueError(f"ENCODING {kind} page checksum mismatch")
            pos=0;found=False
            while pos<len(page):
                if kind=="c":
                    n=page[pos]
                    if not n:
                        if any(page[pos:]):raise ValueError("Nonzero CKey page padding")
                        break
                    length=22+n*16;offset=6
                else:
                    if not any(page[pos:pos+16]):
                        tail=bytes(page[pos:])
                        eof=(number==count-1 and len(tail)>=20 and
                             tail[:20]==bytes(16)+b"\xff"*4 and not any(tail[20:]))
                        if any(tail) and not eof:raise ValueError("Invalid EKey page terminator")
                        break
                    length=25;offset=0
                if pos+length>len(page):
                    raise ValueError("Truncated ENCODING entry")
                raw=bytes(page[pos:pos+length]);key=raw[offset:offset+16]
                if not found and key!=first:
                    raise ValueError("ENCODING first-key index mismatch")
                if previous is not None and key<=previous:
                    raise ValueError("ENCODING keys are not strictly sorted")
                if kind=="e" and int.from_bytes(raw[16:20],"big")>=self.spec_count:
                    raise ValueError("ENCODING ESpec index out of range")
                previous=key;found=True
                yield key,raw
                pos+=length
            if not found:
                raise ValueError("Empty ENCODING indexed page")


def pack_pages(rows,size,ekey_eof=False):
    index=bytearray();pages=bytearray();page=bytearray();first=None
    reserve=20 if ekey_eof else 0
    def flush(final=False):
        nonlocal page,first
        if not page:return
        marker=(bytes(16)+b"\xff"*4) if final and ekey_eof else b""
        block=(bytes(page)+marker).ljust(size,b"\0")
        index.extend(first+hashlib.md5(block).digest());pages.extend(block)
        page=bytearray();first=None
    for key,raw in rows:
        if len(raw)>size-reserve:
            raise ValueError("ENCODING record exceeds page capacity")
        if len(page)+len(raw)>size-reserve:flush()
        if first is None:first=key
        page.extend(raw)
    flush(final=True)
    return bytes(index),bytes(pages),len(index)//32


def merge_rows(old,new,kind,allow_variants=False):
    additions=iter(sorted(new.items()));pending=next(additions,None)
    for key,raw in old:
        while pending and pending[0]<key:
            yield pending;pending=next(additions,None)
        if pending and pending[0]==key:
            proposed=pending[1]
            if kind=="c":
                # A reused CKey must already contain this exact encoding and size.
                matches=(raw[1:6]==proposed[1:6] and proposed[22:38] in
                         [raw[i:i+16] for i in range(22,len(raw),16)])
            else:
                matches=raw==proposed
            if not matches and allow_variants:
                if kind=="c" and raw[1:6]==proposed[1:6]:
                    if raw[0]>=255:
                        raise ValueError("ENCODING variant count exhausted")
                    # Prefer the verified, fully local N frame, retain every old variant.
                    raw=bytes([raw[0]+1])+raw[1:22]+proposed[22:38]+raw[22:]
                    matches=True
                elif kind=="e" and raw[20:25]==proposed[20:25]:
                    # Same EKey and encoded length: preserve its established ESpec.
                    matches=True
            if not matches:
                raise ValueError(f"ENCODING {kind} key conflict")
            pending=next(additions,None)
        yield key,raw
    while pending:
        yield pending;pending=next(additions,None)


def extend_encoding(data,objects,allow_variants=False):
    source=Encoding(data)
    if source.trailing and not source.trailing.startswith(b"b:"):
        raise ValueError("Unsupported ENCODING trailing data")
    spec=source.spec
    strings=spec[:-1].split(b"\0")
    if b"b:{*=n}" in strings:
        spec_index=strings.index(b"b:{*=n}")
    else:
        spec_index=len(strings);spec+=b"b:{*=n}\0"
    crows={};erows={}
    for obj in objects:
        ck,ek=obj["ckey"],obj["ekey"]
        if allow_variants:
            if hashlib.md5(obj["content"]).digest()!=ck:
                raise ValueError("ENCODING content fingerprint conflict")
            # Variant insertion currently accepts only independently verified
            # single-frame N encodings, never an arbitrary supplied EKey.
            frame=b"N"+obj["content"]
            header=(b"BLTE"+struct.pack(">I",36)+b"\x0f\0\0\1"+
                    struct.pack(">II",len(frame),len(obj["content"]))+hashlib.md5(frame).digest())
            if obj["encoded"]!=header+frame or ek!=hashlib.md5(header).digest():
                raise ValueError("ENCODING variant must be a valid single N frame")
        c= b"\1"+len(obj["content"]).to_bytes(5,"big")+ck+ek
        e= ek+spec_index.to_bytes(4,"big")+len(obj["encoded"]).to_bytes(5,"big")
        if (ck in crows and crows[ck]!=c) or (ek in erows and erows[ek]!=e):
            raise ValueError("Conflicting package encodings")
        crows[ck]=c;erows[ek]=e
    ci,cp,nc=pack_pages(merge_rows(source.rows("c"),crows,"c",allow_variants),source.ckb)
    ei,ep,ne=pack_pages(merge_rows(source.rows("e"),erows,"e",allow_variants),source.ekb,ekey_eof=True)
    header=bytearray(data[:22]);struct.pack_into(">II",header,9,nc,ne)
    struct.pack_into(">I",header,18,len(spec))
    # Caller stores the new ENCODING in a single N frame. Its self-ESpec must
    # describe that new encoding, rather than retain old per-block byte lengths.
    return bytes(header)+spec+ci+cp+ei+ep+b"b:{*=n}"
