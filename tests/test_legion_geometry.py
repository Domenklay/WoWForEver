"""Tool-only overrides, staged file validation, and client mount protection."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO=Path(__file__).parents[1]
sys.path.insert(0,str(REPO/'scripts'))


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


builder=load('geometry_build_test',REPO/'tools/legion-geometry/build-tools.py')
geo=load('geometry_extract_test',REPO/'scripts/extract-legion-geometry.py')


def write_staged_files(root):
    maps=root/'maps';maps.mkdir(exist_ok=True)
    head=struct.pack('<4s10I',b'MAPS',10,70532,44,8,52,16,0,0,0,0)
    (maps/'1220_33_23.map').write_bytes(head+b'AREA'+struct.pack('<HH',1,0)+b'MHGT'+struct.pack('<Iff',1,-98,-98))
    bits=bytearray(b'0'*4096);bits[4095-2135]=ord('1')
    (maps/'1220.tilelist').write_bytes(b'MAPS'+struct.pack('<II',10,70532)+bits)
    vmaps=root/'vmaps/1220';vmaps.mkdir(parents=True,exist_ok=True)
    for name in ('1220.vmtree','1220_33_23.vmtile'):(vmaps/name).write_bytes(b'VMAP_4.Eowned shape')
    (root/'vmaps/owned.vmo').write_bytes(b'VMAP_4.Eowned model')


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)

    def test_patch_is_tools_only_preserves_stock_fallback_and_skips_global_objects(self):
        source='void ReadMapDBC()\n{\n    original_map_table();\n}\n'
        output=builder.patch_source(source,'mapextractor')
        self.assertIn('RequestFromEnvironment()',output)
        self.assertIn('return;\n    }\n    original_map_table();',output)
        source='void ReadMapTable()\n{\n    original_map_table();\n}\n    ExtractGameobjectModels();\n'
        output=builder.patch_source(source,'vmap4extractor')
        self.assertIn('map.ParentMapID = -1;',output)
        self.assertIn('if (!WoWForeverGeometry::RequestFromEnvironment())\n        ExtractGameobjectModels();',output)
        with self.assertRaises(ValueError):builder.patch_source(source+source,'vmap4extractor')

    def test_compile_and_link_commands_keep_quoted_arguments_without_shell(self):
        flags=self.home/'flags.make'
        flags.write_text('CXX_DEFINES = -DVALUE=\\"plain\\"\nCXX_INCLUDES = -I"/own path"\nCXX_FLAGS = -O2 -std=c++20\n')
        self.assertIn('-I/own path',builder.compile_flags(flags))
        path=self.home/'link.txt';path.write_text('c++ CMakeFiles/tool.dir/System.cpp.o "own lib.a" -o old-tool -Wl,-rpath,/old')
        command=builder.link_command(path,'System',self.home/'new',self.home/'new.o')
        self.assertEqual(command[1],str(self.home/'new.o'));self.assertIn('own lib.a',command)
        self.assertEqual(command[command.index('-o')+1],str(self.home/'new'))
        with self.assertRaises(ValueError):builder.link_command(path,'Missing',self.home/'new',self.home/'new.o')

    @unittest.skipUnless(shutil.which('g++'),'C++ compiler required')
    def test_native_override_parser_rejects_partial_or_out_of_range_requests(self):
        cpp=self.home/'own.cpp'
        cpp.write_text('#include "request.h"\n#include <iostream>\nint main(){try{auto r=WoWForeverGeometry::RequestFromEnvironment();if(r)std::cout<<r->MapId<<":"<<r->WdtId;else std::cout<<"none";return 0;}catch(...){return 2;}}')
        binary=self.home/'parser'
        subprocess.run(['g++','-std=c++20','-I',str(REPO/'tools/legion-geometry'),str(cpp),'-o',str(binary)],check=True,capture_output=True)
        clean={k:v for k,v in os.environ.items() if k not in {'WOWFOREVER_GEOMETRY_MAP_ID','WOWFOREVER_GEOMETRY_WDT_ID'}}
        for mid,wdt,code in [(None,None,0),('1220','15730590',0),('1220',None,2),('0','15730590',2),
                             ('65536','15730590',2),('1220','775971',2),('1220','16776960',2),('1;cmd','15730590',2)]:
            env=dict(clean)
            if mid is not None:env['WOWFOREVER_GEOMETRY_MAP_ID']=mid
            if wdt is not None:env['WOWFOREVER_GEOMETRY_WDT_ID']=wdt
            process=subprocess.run([str(binary)],env=env,capture_output=True,text=True)
            self.assertEqual(process.returncode,code,(mid,wdt,process.stderr))
            if code==0:self.assertEqual(process.stdout,'none' if mid is None else '1220:15730590')

    def test_inventory_checks_native_axis_order_bounds_and_exact_tile_selection(self):
        write_staged_files(self.home)
        rows,errors=geo.inventory(self.home,1220,33,23)
        self.assertFalse(errors);self.assertEqual(len(rows),5)
        p=self.home/'maps/1220_33_23.map';p.rename(p.with_name('1220_23_33.map'))
        _,errors=geo.inventory(self.home,1220,33,23)
        self.assertTrue(any('Missing' in x for x in errors));self.assertTrue(any('extra terrain' in x for x in errors))
        p.with_name('1220_23_33.map').rename(p)
        data=bytearray(p.read_bytes());struct.pack_into('<I',data,20,999999);p.write_bytes(data)
        _,errors=geo.inventory(self.home,1220,33,23)
        self.assertIn('Terrain section outside file bounds',errors)
        path=self.home/'maps/1220.tilelist';data=bytearray(path.read_bytes());data[-1]=ord('1');path.write_bytes(data)
        _,errors=geo.inventory(self.home,1220,33,23)
        self.assertTrue(any('tile list' in x for x in errors))

    def test_report_fingerprints_and_active_build_are_bound_to_installed_batch(self):
        client=self.home/'client';client.mkdir();(client/'.build.info').write_bytes(b'own build')
        wdt=15730590;row=dict(path='own.wdt',target_file_data_ids=[wdt],payload='data/own.wdt',sha256='a'*64,ckey='b'*32)
        resource=dict(format='wowforever-legion-private-resource-stage-v1',package_sha256='c'*64,
                      tile=dict(world_tile_x=33,world_tile_y=23,raw_maid_index=2135,declared_map_id=1220),files=[row])
        rp=self.home/'resource.json';rp.write_text(json.dumps(resource));sha=hashlib.sha256(rp.read_bytes()).hexdigest()
        table=dict(format='wowforever-legion-map-record-candidate-v1',map_id=1220,directory='ForeverDalaran',
                   wdt_file_data_id=wdt,source_resource_report_sha256=sha,resource_package_sha256='c'*64)
        mp=self.home/'map.json';mp.write_text(json.dumps(table))
        journal=dict(phase='verified',map_record_installed=False,after_info_sha256=hashlib.sha256(b'own build').hexdigest(),
                     source_report_sha256=sha,source_package_sha256='c'*64,expected_after={str(wdt):dict(sha256='a'*64,ckey='b'*32)})
        with patch.object(geo.install.canary,'copy_identity',return_value=(client,{})),patch.object(geo.install,'operation',return_value=(self.home/'operation',journal)):
            self.assertEqual(geo.inputs(client,rp,mp)[3]['map_id'],1220)
            table['wdt_file_data_id']=775971;mp.write_text(json.dumps(table))
            with self.assertRaises(ValueError):geo.inputs(client,rp,mp)
            (client/'.build.info').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'build changed'):geo.inputs(client,rp,mp)

    def test_readonly_mounts_and_staged_output_never_deploy_to_server(self):
        client=self.home/'client';(client/'Data/data').mkdir(parents=True)
        (client/'.build.info').write_bytes(b'own build');(client/'Data/data/shmem').write_bytes(b'own metadata')
        expected=dict(bytes=4,sha256='a'*64,ckey='b'*32)
        journal=dict(expected_after={'15730590':expected},locale='ruRU',source_report_sha256='c'*64,operation='own-operation')
        resource=dict(tile=dict(world_tile_x=33,world_tile_y=23))
        table=dict(map_id=1220,wdt_file_data_id=15730590)
        before={p:p.read_bytes() for p in client.rglob('*') if p.is_file()};output=self.home/'geometry'
        def fake_process(command,**kwargs):
            self.assertIn('--read-only',command);self.assertIn('none',command)
            self.assertIn(f'type=bind,src={client},dst=/wow,readonly',command)
            self.assertFalse(any('docker-compose' in str(x) for x in command))
            write_staged_files(output)
            (output/'height-probe.json').write_text(json.dumps(dict(load_success=True,city_collision_samples=1,player_spawn_verified=False)))
            return SimpleNamespace(stdout=iter(['owned extraction\n']),wait=lambda **kw:0,terminate=lambda:None)
        native={15730590:dict(status='READ_OK',bytes='4',sha256='a'*64,ckey='b'*32)}
        with patch.object(geo,'inputs',return_value=(client,journal,resource,table)),\
             patch.object(geo.install,'scan',return_value=native),patch.object(geo.subprocess,'run',return_value=SimpleNamespace(returncode=0)),\
             patch.object(geo.subprocess,'Popen',side_effect=fake_process):
            result=geo.extract(client,'unused','unused',output,progress=lambda _:None)
        self.assertTrue(result['geometry_probe_passed']);self.assertFalse(result['server_modified'])
        self.assertFalse(result['client_map_enabled']);self.assertFalse(result['player_spawn_verified'])
        self.assertEqual(before,{p:p.read_bytes() for p in before})
