#!/usr/bin/env python3
"""Test activation/rollback SQL in an explicit disposable, owned MySQL container."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


def check(container,source,scripts):
    sys.path.insert(0,str(scripts))
    from legion_activation import MAP_COLUMNS,apply_sql,rollback_sql
    def sql(text):
        return subprocess.run(['docker','exec','-i',container,'mysql','--default-character-set=utf8mb4','-uroot','-N','-B'],
                              input=text,text=True,capture_output=True,check=True).stdout.strip()
    if sql('SHOW DATABASES LIKE "hotfixes";'):
        raise ValueError('Use a disposable EMPTY test database container')
    base=(source/'sql/base/dev/hotfixes_database.sql').read_text()
    tables=[]
    for name in ('map','map_locale','hotfix_data'):
        match=re.search(r'CREATE TABLE `'+name+r'` \(.*?\) ENGINE=.*?;',base,re.S)
        if not match:raise ValueError('Test schema not found')
        tables.append(match.group())
    sql('CREATE DATABASE hotfixes; USE hotfixes;\n'+'\n'.join(tables))
    if 'OceanLiquidTypeID' not in sql('SHOW COLUMNS FROM hotfixes.`map`;'):
        sql('ALTER TABLE hotfixes.`map` ADD OceanLiquidTypeID int NOT NULL DEFAULT 0;')
    sql('''CREATE DATABASE characters;
CREATE TABLE characters.characters (guid bigint PRIMARY KEY,map int,position_x float,position_y float,
position_z float,orientation float,zone int,instance_id int);
CREATE TABLE characters.character_homebind (guid bigint PRIMARY KEY,mapId int,zoneId int,
posX float,posY float,posZ float,orientation float);
INSERT INTO characters.characters VALUES (1,0,10,20,30,0,12,0),(2,1220,1,2,3,0,0,0),(3,1220,1,2,3,0,0,0);
INSERT INTO characters.character_homebind VALUES (2,1,42,111,222,333,1);
INSERT INTO hotfixes.`map` (ID,Directory,VerifiedBuild) VALUES (0,'owned-control',0);
INSERT INTO hotfixes.hotfix_data VALUES (10,1,999,7,1,0);
''')
    values={x:0 for x in MAP_COLUMNS}
    values.update(ID=1220,Directory='ForeverDalaran',MapName="owned ' SQL fixture",WdtFileDataID=15730590,
                  ParentMapID=-1,CosmeticParentMapID=-1,MinimapIconScale=1.0)
    sql(apply_sql(values,3179597154,11))
    if sql('SELECT WdtFileDataID FROM hotfixes.`map` WHERE ID=1220 AND (VerifiedBuild>0)=0;')!='15730590':
        raise ValueError('Custom Map loader predicate did not select the inserted row')
    if sql('SELECT Status FROM hotfixes.hotfix_data WHERE Id=11;')!='1':raise ValueError('Hotfix not advertised')
    if 'Даларан' not in sql("SELECT MapName_lang FROM hotfixes.map_locale WHERE ID=1220 AND locale='ruRU' AND VerifiedBuild=0;"):
        raise ValueError('Russian locale name is missing')
    sql(rollback_sql(3179597154,11))
    if sql('SELECT COUNT(*) FROM hotfixes.`map` WHERE ID=1220;')!='0':raise ValueError('Map row was not removed')
    if sql('SELECT COUNT(*) FROM hotfixes.map_locale WHERE ID=1220;')!='0':raise ValueError('Locale row was not removed')
    if sql('SELECT guid,map,position_x,position_y,position_z FROM characters.characters WHERE guid=1;')!='1\t0\t10\t20\t30':
        raise ValueError('Existing world character was changed')
    if sql('SELECT guid,map,position_x,position_y,position_z FROM characters.characters WHERE guid=2;')!='2\t1\t111\t222\t333':
        raise ValueError('Experimental character was not returned home')
    if sql('SELECT map FROM characters.characters WHERE guid=3;')!='0':raise ValueError('Fallback rescue failed')
    if sql('SELECT Status FROM hotfixes.hotfix_data WHERE RecordId=1220 ORDER BY Id DESC LIMIT 1;')!='2':
        raise ValueError('Client removal hotfix was not emitted')
    if sql('SELECT COUNT(*) FROM hotfixes.hotfix_data WHERE Id=10;')!='1':raise ValueError('Other hotfix removed')
    return dict(mysql_apply_and_rollback_verified=True,custom_loader_predicate_verified=True,
                unrelated_characters_and_hotfixes_preserved=True,experimental_characters_rescued=True,
                removal_hotfix_created=True,client_runtime_verified=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container',required=True);parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--scripts',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(check(args.container,args.source,args.scripts),indent=2))
