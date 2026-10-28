#!/usr/bin/env python3
"""Recompile two tool entry points against the existing core build, no server build."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT=Path(__file__).resolve().parent


def replace_once(text,old,new):
    if text.count(old)!=1:
        raise ValueError('Pinned extractor anchor missing or ambiguous: '+old.strip())
    return text.replace(old,new,1)


def patch_source(text,target):
    if target not in {'mapextractor','vmap4extractor'}:raise ValueError('Unsupported extractor target')
    entry='ReadMapDBC' if target=='mapextractor' else 'ReadMapTable'
    body='''    if (auto request = WoWForeverGeometry::RequestFromEnvironment())
    {
        map_ids.clear();
        MapEntry map;
        map.Id = request->MapId;
        map.WdtFileDataId = int32(request->WdtId);
        map.Name = "ForeverDalaran geometry probe";
        map.Directory = "ForeverDalaran";
'''
    if target=='vmap4extractor':body+='        map.ParentMapID = -1;\n'
    body+='''        map_ids.push_back(std::move(map));
        printf("Explicit geometry map: %u, WDT: %u\\n", request->MapId, request->WdtId);
        return;
    }
'''
    text=replace_once(text,'void '+entry+'()\n{\n','void '+entry+'()\n{\n'+body)
    if target=='vmap4extractor':
        text=replace_once(text,'    ExtractGameobjectModels();','    if (!WoWForeverGeometry::RequestFromEnvironment())\n        ExtractGameobjectModels();')
    return text


def compile_flags(path):
    values={}
    for line in path.read_text().splitlines():
        if ' = ' in line and not line.startswith('#'):
            key,value=line.split(' = ',1);values[key]=shlex.split(value)
    return values.get('CXX_DEFINES',[])+values.get('CXX_INCLUDES',[])+values.get('CXX_FLAGS',[])


def link_command(path,target,output,replacement,all_objects=False):
    command=shlex.split(path.read_text())
    if command.count('-o')!=1:raise ValueError('Unsupported cached linker command')
    at=command.index('-o');command[at+1]=str(output)
    count=0;result=[]
    for arg in command:
        match=(arg.endswith('.o') if all_objects else arg.endswith('/'+target+'.cpp.o'))
        if match:
            if not count:result.append(str(replacement))
            count+=1
        else:result.append(arg)
    if not count or (not all_objects and count!=1):
        raise ValueError('Cached tool object was not found exactly once')
    return result


def build(source,cache,output,progress=print):
    source,cache,output=(Path(p).resolve() for p in (source,cache,output))
    if output.exists():raise ValueError('Use a NEW tool output directory')
    profile=json.loads((ROOT/'source-profile.json').read_text())
    revision=subprocess.run(['git','-c',f'safe.directory={source}','-C',str(source),'rev-parse','HEAD'],
                            capture_output=True,text=True,check=True).stdout.strip()
    if revision!=profile['core_revision']:raise ValueError('Cached core revision differs from pinned geometry profile')
    for relative,digest in profile['files'].items():
        if hashlib.sha256((source/relative).read_bytes()).hexdigest()!=digest:
            raise ValueError('Extractor source differs from pinned revision: '+relative)
    compiler=None
    for line in (cache/'CMakeCache.txt').read_text().splitlines():
        if line.startswith('CMAKE_CXX_COMPILER:FILEPATH='):compiler=line.split('=',1)[1]
    if not compiler:raise ValueError('Cached C++ compiler not found')
    output.mkdir(parents=True)
    for target,relative,file in [('mapextractor','map_extractor','System'),('vmap4extractor','vmap4_extractor','vmapexport')]:
        original=source/'src/tools'/relative/(file+'.cpp')
        directory=cache/'src/tools'/relative
        make=directory/f'CMakeFiles/{target}.dir'
        patched=output/(file+'.cpp');patched.write_text(patch_source(original.read_text(),target))
        obj=output/(file+'.o')
        flags=compile_flags(make/'flags.make')
        progress('Compiling '+target+' entry point...')
        subprocess.run([compiler,*flags,'-I',str(original.parent),'-include',str(ROOT/'request.h'),'-c',str(patched),'-o',str(obj)],check=True)
        subprocess.run(link_command(make/'link.txt',file,output/target,obj),cwd=directory,check=True)
    directory=cache/'src/tools/vmap4_assembler'
    make=directory/'CMakeFiles/vmap4assembler.dir'
    obj=output/'check-height.o'
    progress('Compiling the server VMAP height probe...')
    subprocess.run([compiler,*compile_flags(make/'flags.make'),'-c',str(ROOT/'check-height.cpp'),'-o',str(obj)],check=True)
    subprocess.run(link_command(make/'link.txt','',output/'check-height',obj,all_objects=True),cwd=directory,check=True)
    original_link=shlex.split((make/'link.txt').read_text())
    assembler=(directory/original_link[original_link.index('-o')+1]).resolve()
    if not assembler.is_file():raise ValueError('Cached vmap4assembler missing (TOOLS=1 required)')
    return assembler


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path('/src/TrinityCore'))
    parser.add_argument('--build',type=Path,default=Path('/src/TrinityCore/build'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        print('Assembler:',build(args.source,args.build,args.output))
    except (ValueError,OSError,subprocess.CalledProcessError) as error:
        parser.exit(1,str(error)+'\n')
