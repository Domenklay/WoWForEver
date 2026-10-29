#!/usr/bin/env python3
"""Decode 3.3.5 Spell.dbc into a private porting workspace, without activating spells."""
import argparse
import hashlib
import json
import mmap
from pathlib import Path
import re
import shutil
import struct
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
CLASSES={'Warrior','Paladin','Hunter','Rogue','Priest','Shaman','Mage','Warlock','Druid'}

class SpellDBC:
    def __init__(self, data):
        self.data=data
        if len(data)<20:raise ValueError('Truncated DBC header')
        magic,self.count,fields,self.size,self.string_size=struct.unpack_from('<4s4I',data)
        if (magic,fields,self.size)!=(b'WDBC',234,936):raise ValueError('Expected WDBC Spell layout 234 fields / 936 bytes')
        self.string_start=20+self.count*self.size
        if self.string_start+self.string_size!=len(data):raise ValueError('DBC size does not match header')
        self.index={}
        for i in range(self.count):
            pos=20+i*self.size;spell=struct.unpack_from('<I',data,pos)[0]
            if spell in self.index:raise ValueError('Duplicate spell ID')
            self.index[spell]=pos

    def text(self, offset):
        if not 0<=offset<self.string_size:raise ValueError('Invalid string offset')
        start=self.string_start+offset;end=self.data.find(b'\0',start,self.string_start+self.string_size)
        if end<0:raise ValueError('Unterminated DBC string')
        return self.data[start:end].decode('utf-8',errors='replace')

    def spell(self, spell):
        pos=self.index.get(spell)
        if pos is None:return None
        words=struct.unpack_from('<234I',self.data,pos)
        signed=lambda i:struct.unpack_from('<i',self.data,pos+4*i)[0]
        real=lambda i:struct.unpack_from('<f',self.data,pos+4*i)[0]
        row={'id':spell,'names':[self.text(v) for v in words[136:152]],
             'descriptions':[self.text(v) for v in words[170:186]],
             'aura_descriptions':[self.text(v) for v in words[187:203]],
             'attributes':list(words[4:12]),'family':words[208],'family_flags':list(words[209:212]),
             'school_mask':words[225],'level':words[39],'base_level':words[38],
             'power_type':signed(41),'cost':words[42],'cost_pct':words[204],
             'cost_per_level':words[43],'cost_per_second':words[44],
             'duration_id':words[40],'cast_time_id':words[28],'range_id':words[46],
             'cooldown_ms':words[29],'category_cooldown_ms':words[30],
             'proc_flags':words[34],'proc_chance':words[35],'proc_charges':words[36],
             'stance_mask':words[12],'excluded_stance_mask':words[14],
             'visual_ids':list(words[131:133]),'icon_id':words[133],
             'caster_aura':words[24],'target_aura':words[25],
             'excluded_caster_aura':words[26],'excluded_target_aura':words[27],
             'effects':[], 'raw_words':list(words)}
        for i in range(3):
            if not words[71+i]:continue
            row['effects'].append({'index':i,'effect':words[71+i],'aura':words[95+i],
                'base_points':signed(80+i),'die_sides':signed(74+i),'points_per_level':real(77+i),
                'value_multiplier':real(101+i),'bonus_multiplier':real(229+i),
                'damage_multiplier':real(216+i),'misc':signed(110+i),'misc_b':signed(113+i),
                'target_a':words[86+i],'target_b':words[89+i],'radius_id':words[92+i],
                'trigger_spell':words[116+i],'period_ms':words[98+i],
                'class_mask':list(words[122+i*3:125+i*3])})
        return row


def prepare(dbc, requested):
    pending=set(requested);rows={};missing=set()
    while pending:
        spell=pending.pop()
        if spell in rows or spell in missing:continue
        row=dbc.spell(spell)
        if row is None:missing.add(spell);continue
        rows[spell]=row
        refs={row[k] for k in ['caster_aura','target_aura','excluded_caster_aura','excluded_target_aura']}
        refs.update(e['trigger_spell'] for e in row['effects'])
        for text in row['descriptions']:
            refs.update(int(v) for v in re.findall(r'@s:(\d+)',text))
        pending.update(refs-{0}-rows.keys()-missing)
    return rows,sorted(missing)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--spell',type=int,action='append',default=[])
    args=parser.parse_args();output=args.output.resolve()
    if output==ROOT or ROOT in output.parents:parser.error('Use an output folder outside the Git repository')
    catalog=json.loads((ROOT/'mods/forever-advancement/catalog/CharacterAdvancementData.json').read_text())
    ranks=json.loads((ROOT/'mods/forever-advancement/catalog/SpellRankData.json').read_text())
    entries=[r for r in catalog if r.get('Class') in CLASSES and r.get('Type') in ('Ability','Talent')]
    requested={v for r in entries for v in r.get('Spells',[])}|set(args.spell)
    first=set(requested);requested.update(r['spellId'] for r in ranks if r['firstSpellId'] in first)
    with zipfile.ZipFile(args.archive) as archive:
        candidates=[n for n in archive.namelist() if n.endswith('/Spell.dbc')]
        if len(candidates)!=1:parser.error('Provide an export with exactly one Spell.dbc version')
        if archive.getinfo(candidates[0]).file_size>1024**3:parser.error('Spell.dbc exceeds 1 GiB')
        with tempfile.TemporaryFile() as staged:
            with archive.open(candidates[0]) as source:shutil.copyfileobj(source,staged,1024*1024)
            staged.flush()
            with mmap.mmap(staged.fileno(),0,access=mmap.ACCESS_READ) as data:
                dbc=SpellDBC(data);rows,missing=prepare(dbc,requested)
                summary={'source_sha256':hashlib.sha256(data).hexdigest(),'source_records':dbc.count,
                    'requested':len(requested),'decoded_with_dependencies':len(rows),'missing':missing,
                    'catalog_entries_with_all_direct_spells':sum(bool(r.get('Spells')) and all(v in dbc.index for v in r['Spells']) for r in entries),
                    'catalog_entries':len(entries),'activated':0}
                output.mkdir(parents=True,exist_ok=False)
                for spell,row in sorted(rows.items()):(output/f'{spell}.json').write_text(json.dumps(row,ensure_ascii=False,indent=2))
                (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
                print(json.dumps({k:v for k,v in summary.items() if k!='missing'},ensure_ascii=False))
                for spell in args.spell:
                    if spell in rows:print(spell,rows[spell]['names'][0],rows[spell]['effects'])
    return 0

if __name__=='__main__':raise SystemExit(main())
