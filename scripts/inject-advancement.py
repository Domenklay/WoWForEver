#!/usr/bin/env python3
"""Register the new advancement server; remove the obsolete generated subclass adapter."""
import argparse
from pathlib import Path
import re
import shutil


def inject(core,module=None):
    core=Path(core).resolve();module=Path(module or Path(__file__).parents[1]/'mods/forever-advancement').resolve()
    loader=core/'src/server/scripts/Custom/custom_script_loader.cpp'
    text=loader.read_text()
    text=text.replace('void AddSC_forever_subclass();\n','').replace('    AddSC_forever_subclass();\n','')
    declaration='void AddSC_forever_advancement();'
    if declaration not in text:
        text,count=re.subn(r'(^void AddCustomScripts\(\)\s*\{)',declaration+'\n\n'+r'\1'+'\n    AddSC_forever_advancement();',text,count=1,flags=re.M)
        if count!=1:raise ValueError('Unknown Custom loader layout')
    if text.count('    AddSC_forever_advancement();')!=1:raise ValueError('Inconsistent advancement registration')
    target=loader.parent/'ForeverAdvancement'
    if target.is_symlink() or (loader.parent/'ForeverSubclass').is_symlink():raise ValueError('Symlinked module path')
    target.mkdir(exist_ok=True)
    for name in ['ForeverAdvancement.cpp','AscensionCatalog.h']:shutil.copy2(module/'server'/name,target/name)
    legacy=loader.parent/'ForeverSubclass'
    if legacy.exists():shutil.rmtree(legacy)
    manager=core/'src/server/game/Globals/ObjectMgr.h'
    if manager.exists():
        original=manager.read_text()
        signature='        void RegisterForeverAdvancementBinding(uint32 spellId, uint32 scriptId)'
        if signature not in original:
            anchor='        SpellScriptsBounds GetSpellScriptsBounds(uint32 spellId);'
            if original.count(anchor)!=1:raise ValueError('Unknown ObjectMgr binding layout')
            original=original.replace(anchor,anchor+"\n"+signature+"\n        {\n            auto bounds = _spellScriptsStore.equal_range(spellId);\n            for (auto it = bounds.first; it != bounds.second; ++it)\n                if (it->second.first == scriptId) { it->second.second = true; return; }\n            _spellScriptsStore.emplace(spellId, std::make_pair(scriptId, true));\n        }\n")
            manager.write_text(original)
    loader.write_text(text)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('core',type=Path);parser.add_argument('--module',type=Path)
    args=parser.parse_args();inject(args.core,args.module)
