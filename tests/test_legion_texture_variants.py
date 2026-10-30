"""Single-ID ROOT variant canary: owned metadata, native reads and rollback."""
import copy
import importlib.util
import os
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from casc_manifest_update import root_groups
from casc_texture_variants import mirror_alternate, profiles

spec = importlib.util.spec_from_file_location('variant_canary', ROOT/'scripts/repair-legion-tvfs-entry.py')
canary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(canary)


def group(fid, flag, key, locale=0x173f6, type_flag=0x12000000, kind=4):
    return struct.pack('<4IBI', 1, locale, flag, type_flag, kind, fid) + key


class RootVariantTests(unittest.TestCase):
    def test_append_preserves_every_old_group_and_exact_native_profile(self):
        old, new = 123086, 15728640
        raw = b'TSFM' + struct.pack('<5I',24,2,4,0,0)
        raw += group(old,1,b'b'*16) + group(old,0,b'a'*16) + group(new,0,b'a'*16) + group(777,0,b'c'*16)
        result, added = mirror_alternate(raw,old,new)
        self.assertEqual(result[24:len(raw)],raw[24:])
        self.assertEqual(struct.unpack_from('<I',result,12)[0],5)
        self.assertEqual(result[:12],raw[:12])
        self.assertEqual(result[16:24],raw[16:24])
        before = profiles(raw,{old,new,777})
        after = profiles(result,{old,new,777})
        self.assertEqual(after[old],before[old])
        self.assertEqual(after[777],before[777])
        self.assertEqual(after[new],before[new]+[added])
        self.assertEqual(added['raw_flags'],[1,0x12000000,4])
        with self.assertRaisesRegex(ValueError,'exactly the matching'):
            mirror_alternate(result,old,new)

    def test_unrelated_private_payload_or_variant_type_is_rejected(self):
        header = b'TSFM' + struct.pack('<5I',24,2,3,0,0)
        for baseline, alternate in [(b'c'*16,group(123086,1,b'b'*16)),
                                    (b'a'*16,group(123086,1,b'b'*16,kind=5))]:
            raw = header + group(123086,0,b'a'*16) + alternate + group(15728640,0,baseline)
            with self.assertRaises(ValueError):mirror_alternate(raw,123086,15728640)

    @unittest.skipUnless(os.environ.get('CASC_SANDBOX_CHECKER'),'Native CascLib checker required')
    def test_native_install_unresident_alternate_preserves_reads_and_exact_rollback(self):
        from test_legion_resource_install import ResourceBatchTests
        f = ResourceBatchTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.apply()
        install, lib = canary.install, canary.storelib
        client = f.client
        folder, parent = install.operation(client)
        old = install.canary.lab.BASE_ID
        new = f.rows[1]['target_file_data_ids'][0]
        store = lib.Store(client,synthetic_only=False)
        audit = install.load('audit-legion-root-types.py')
        original_root = audit.read_content(store,audit.Encoding(canary.configured(store,'encoding')),store.values['root'].split()[0])
        groups = []
        base_key = bytes.fromhex(f.rows[1]['ckey'])
        for row in root_groups(original_root):
            self.assertFalse(row['has_names'])
            fid = 0
            for i,(delta,) in enumerate(struct.iter_unpack('<I',original_root[row['ids_offset']:row['ckeys_offset']])):
                fid += delta
                ck = original_root[row['ckeys_offset']+16*i:row['ckeys_offset']+16*(i+1)]
                flags, locale = row['content_flags'], row['locale']
                if fid in {old,new}:flags,locale = [0,0x12000000,4],0x173f6
                groups.append(struct.pack('<4IBI',1,locale,*flags,fid)+ck)
                fid += 1
        alternate = install.canary.lab.asset(b'owned alternate texture not resident locally')
        groups.append(group(old,1,alternate['ckey']))
        header = bytearray(original_root[:24])
        struct.pack_into('<I',header,12,len(groups))
        root = install.canary.lab.asset(bytes(header)+b''.join(groups))
        top = lib.tvfs.parse_tvfs(canary.configured(store,'vfs-root'))
        leaves = copy.deepcopy(top['leaves'])
        leaves.pop(next(k for k in leaves if ':'+f'{new:08X}' in k))
        root_est, leaves['.root'] = canary.add_span(top['tables']['est'],root)
        children, directory_rows = [],[]
        # Reuse the resident base variant, while retaining a second ENCODING
        # entry whose BLTE is deliberately absent from local IDX.
        base_obj = install.canary.lab.asset(f.bodies['owned/private-same.txt'])
        for index,obj in enumerate([base_obj,alternate],2):
            est, spans = canary.add_span(b'',obj)
            paths = {f'{old:08X}'+obj['ckey'].hex().upper():spans}
            native = lib.encode_tvfs(paths,est)
            mirrored,_ = canary.mirror_child(native,old,new)
            child = install.canary.lab.asset(lib.tvfs.repack_tvfs_like(mirrored,native))
            children.append(child)
            name = f'000173F6{index-2:08X}'
            root_est,leaves[name] = canary.add_span(root_est,child)
            key = f'vfs-{index}'
            store.values[key] = child['ckey'].hex()+' '+child['ekey'].hex()
            store.values[key+'-size'] = f'{len(child["content"])} {len(child["encoded"])}'
            store.config += '\n'+key+' = '+store.values[key]+'\n'+key+'-size = '+store.values[key+'-size']+'\n'
            directory_rows.append(dict(directory=name,build_config_key=key,source_config_key=key,mirrored=[]))
        vfs = install.canary.lab.asset(lib.encode_tvfs(leaves,root_est))
        encoding = install.canary.lab.asset(install.canary.extend_encoding(canary.configured(store,'encoding'),
            [root,vfs,*children,alternate],allow_variants=True))
        config = install.canary.resource_configuration(store,dict(root=root,vfs=vfs,encoded=encoding,
            download=install.canary.lab.asset(canary.configured(store,'download'))))
        meta = install.container.metadata(client/'Data/data')
        prologues = {}
        for path in (client/'Data/data').glob('data.[0-9][0-9][0-9]'):
            with path.open('rb') as stream:prologues[int(path.name[5:])] = stream.read(480)
        files, shared = install.plan_segment(meta,prologues,[root,vfs,encoding,*children])
        for name,body in files.items():(client/'Data/data'/name).write_bytes(body)
        (client/'Data/data/shmem').write_bytes(shared)
        path = client/config['path']
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(config['body'])
        (client/'.build.info').write_bytes(config['build_info'])
        parent.update(root_types_repaired=True,tvfs_entry_canary=True,tvfs_layout_canary=True,
            tvfs_canary_original_id=old,tvfs_canary_new_id=new,tvfs_canary_directories=directory_rows,
            root_type_profiles={str(new):dict(locale=0x173f6,raw_flags=[0,0x12000000,4],ckey=base_key.hex())},
            after_info_sha256=install.canary.sha(config['build_info']))
        install.canary.checkpoint(folder/'operation.json',parent)
        before, source = f.snapshot(client),f.snapshot(f.fixture.source)
        checker = os.environ['CASC_SANDBOX_CHECKER']
        kwargs = dict(progress=lambda _:None,old_id=old,new_id=new,root_variant=True)
        with patch.object(install,'verify',side_effect=ValueError('variant readback failure')):
            with self.assertRaisesRegex(ValueError,'variant readback failure'):canary.apply(client,checker,**kwargs)
        self.assertEqual(before,f.snapshot(client))
        self.assertEqual(install.operation(client)[0],folder)
        result = canary.apply(client,checker,**kwargs)
        self.assertTrue(result['root_variant_only'])
        self.assertFalse(result['root_unchanged'])
        self.assertEqual(result['root_variant_added']['ckey'],alternate['ckey'].hex())
        current = lib.Store(client,synthetic_only=False)
        installed_root = audit.read_content(current,audit.Encoding(canary.configured(current,'encoding')),current.values['root'].split()[0])
        self.assertEqual(len(profiles(installed_root,{new})[new]),2)
        self.assertNotIn(alternate['ekey'][:9],current.entries)
        self.assertEqual(source,f.snapshot(f.fixture.source))
        for p,body in before.items():
            if str(p).startswith('Data/data/data.'):
                self.assertEqual((client/p).read_bytes(),body)
        canary.rollback(client)
        self.assertEqual(install.operation(client)[0],folder)
        self.assertEqual(before,f.snapshot(client))
