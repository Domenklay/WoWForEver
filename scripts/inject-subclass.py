#!/usr/bin/env python3
"""Copy the adapter into a TrinityCore source checkout before CMake collects scripts."""
import argparse
import re
import shutil
from pathlib import Path


def inject(core, module):
    core=Path(core).resolve();module=Path(module).resolve()
    loader=core/'src/server/scripts/Custom/custom_script_loader.cpp'
    text=loader.read_text()
    declaration='void AddSC_forever_subclass();'
    if declaration not in text:
        pattern=r'(^void AddCustomScripts\(\)\s*\{)'
        if len(re.findall(pattern,text,re.M))!=1:
            raise ValueError('Custom loader layout is not recognized')
        text=re.sub(pattern,declaration+'\n\n'+r'\1'+'\n    AddSC_forever_subclass();',text,count=1,flags=re.M)
    elif text.count('    AddSC_forever_subclass();')!=1:
        raise ValueError('Inconsistent subclass loader registration')
    target=loader.parent/'ForeverSubclass';target.mkdir(exist_ok=True)
    (target/'forever_subclass').mkdir(exist_ok=True)
    shutil.copy2(module/'server/ForeverSubclass.cpp',target/'ForeverSubclass.cpp')
    shutil.copy2(module/'vendor/src/SubclassSystem.cpp',target/'SubclassSystem.cpp')
    shutil.copy2(module/'vendor/include/forever_subclass/SubclassSystem.hpp',target/'forever_subclass/SubclassSystem.hpp')
    loader.write_text(text)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('core',type=Path)
    parser.add_argument('--module',type=Path,default=Path(__file__).resolve().parents[1]/'mods/forever-subclass')
    args=parser.parse_args();inject(args.core,args.module)
