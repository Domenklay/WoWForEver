#!/usr/bin/env python3
"""Build unmodified pinned GridMap with dead-code elimination and cached common libs.

Run in a prepared core build environment containing compile_commands.json and
static dependencies. This does not build/start a worldserver or access a client.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess


def build(source,cache,output):
    source,cache,output=[Path(p).resolve() for p in (source,cache,output)]
    root=Path(__file__).resolve().parent
    profile=json.loads((root/'source-profile.json').read_text())
    for path,digest in profile['files'].items():
        if hashlib.sha256((source/path).read_bytes()).hexdigest()!=digest:
            raise ValueError('Core source differs from pinned profile: '+path)
    if output.exists():raise FileExistsError('Use a new output directory')
    output.mkdir(parents=True)
    rows=json.loads((cache/'compile_commands.json').read_text())
    row=next(r for r in rows if Path(r['file'])==source/'src/server/game/Maps/GridMap.cpp')
    args=shlex.split(row['command']);flags=[];i=1
    while i<len(args):
        if args[i] in ('-o','-c'):i+=2;continue
        flags.append(args[i]);i+=1
    flags+=['-ffunction-sections','-fdata-sections']
    for path,name in [(Path(row['file']),'GridMap'),(root/'check-gridmap.cpp','probe')]:
        subprocess.run([args[0],*flags,'-c',str(path),'-o',str(output/(name+'.o'))],cwd=row['directory'],check=True)
    libs=[cache/'src/common/libcommon.a',cache/'dep/argon2/libargon2.a',
          '-lboost_filesystem','-lboost_program_options','-lboost_regex','-lboost_locale','-lboost_chrono',
          '-lboost_thread','-lboost_atomic',cache/'dep/fmt/libfmt.a',cache/'dep/g3dlite/libg3dlib.a',
          '-lz',cache/'dep/SFMT/libsfmt.a',cache/'bin/Release/lib/libopenssl_ed25519.so',
          '-lssl','-lcrypto','-lpthread','-ldl']
    subprocess.run([args[0],'-Wl,--gc-sections',str(output/'probe.o'),str(output/'GridMap.o'),
                    *map(str,libs),'-Wl,-rpath,'+str(cache/'bin/Release/lib'),'-o',str(output/'check-gridmap')],check=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--build',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();build(a.source,a.build,a.output)
