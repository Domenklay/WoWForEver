import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).parents[1]/'scripts'


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,SCRIPTS/file)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


planner=load('client_plan','plan-legion-client.py')
lab=load('plan_lab','build-casc-sandbox.py')


class ClientPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.client=self.root/'client'
        self.client.mkdir()
        (self.client/'.build.info').write_bytes(b'owned fixture build information')
        self.package=self.root/'package'
        self.package.mkdir()
        self.report=self.package/'report.json'
        self.output=self.root/'comparison.json'

    def package_report(self,assets,external=()):
        rows=[]
        with zipfile.ZipFile(self.package/'tile-candidate.zip','w') as archive:
            for fid,body,original in assets:
                path=f'models/{fid}.m2'
                archive.writestr('data/'+path,body)
                rows.append(dict(path=path,bytes=len(body),sha256=hashlib.sha256(body).hexdigest(),
                                 source_sha256=hashlib.sha256(original).hexdigest(),ckey=hashlib.md5(body).hexdigest(),
                                 file_data_ids=[fid],transformation='fixture transformation' if body!=original else None))
            value=dict(format='wowforever-legion-tile-package-v1',errors=[],files=rows,
                       tile={'export_tile':'23_33'},coverage_limits=[],
                       missing_from_export=[dict(file_data_id=fid,catalog_path='unknown') for fid in external],
                       references=[])
            archive.writestr('package-index.json',json.dumps(value))
        value['package_sha256']=planner.sha_file(self.package/'tile-candidate.zip')
        self.report.write_text(json.dumps(value))
        return value

    def row(self,fid,body=None):
        if body is None:
            return dict(file_id=str(fid),status='OPEN_FAILED',bytes='0',sha256='-',tag_mask='-',error='2',
                        ckey='-',locale_flags='-',content_flags='-')
        return dict(file_id=str(fid),status='READ_OK',bytes=str(len(body)),sha256=hashlib.sha256(body).hexdigest(),
                    tag_mask='3fffe3ff',error='0',ckey=hashlib.md5(body).hexdigest(),locale_flags='173f6',content_flags='120a0000')

    def test_distinguishes_reuse_transformation_conflict_missing_and_external(self):
        self.package_report([(10,b'same',b'same'),(11,b'clipped',b'original'),
                             (12,b'donor',b'donor'),(13,b'new',b'new')],[90])
        results={10:self.row(10,b'same'),11:self.row(11,b'original'),12:self.row(12,b'other'),
                 13:self.row(13),90:self.row(90,b'available map texture')}
        with patch.object(planner,'scan',return_value=results):
            result=planner.plan(self.report,self.client,self.output,progress=lambda _:None)
        kinds={r['file_data_id']:r['classification'] for r in result['resources']}
        self.assertEqual(kinds,{10:'identical',11:'source_matches_but_package_transformed',
                                12:'different_content_same_id',13:'not_readable_requires_ROOT_check'})
        self.assertTrue(result['external_dependencies'][0]['available'])
        self.assertFalse(result['external_dependencies'][0]['donor_content_match_verified'])
        self.assertFalse(result['installable'])
        self.assertEqual(sum(row['files'] for row in result['verified_source_profiles']),2)

    def test_changed_archive_or_external_index_is_rejected(self):
        value=self.package_report([(10,b'data',b'data')])
        value['files'][0]['bytes']=99
        self.report.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'packaged index'):
            planner.read_package(self.report)
        with (self.package/'tile-candidate.zip').open('ab') as out:out.write(b'changed')
        with self.assertRaisesRegex(ValueError,'Package SHA'):
            planner.read_package(self.report)

    def test_pinned_casclib_offline_error_is_not_a_size_limit_or_corruption(self):
        self.package_report([(10,b'data',b'data')])
        actual=self.row(10)
        actual.update(status='SIZE_FAILED',error='1007')
        with patch.object(planner,'scan',return_value={10:actual}):
            result=planner.plan(self.report,self.client,self.output,progress=lambda _:None)
        self.assertEqual(result['counts'],{'not_locally_resident':1})

    def test_size_limit_does_not_reuse_a_previous_offline_error(self):
        self.package_report([(10,b'data',b'data')])
        actual=self.row(10)
        actual.update(status='SIZE_LIMIT',bytes=str(65*1024*1024),error='0')
        with patch.object(planner,'scan',return_value={10:actual}):
            result=planner.plan(self.report,self.client,self.output,progress=lambda _:None)
        self.assertEqual(result['counts'],{'size_limit_not_checked':1})

    def test_prior_unused_modi_review_applies_only_to_exact_report(self):
        value=self.package_report([(10,b'data',b'data')],[777])
        # Recreate a valid report/index with the legacy MODI edge.
        value.pop('package_sha256')
        value['references']=[dict(source='world/wmo/brokenisles/dalaran2.wmo',file_data_id=777,kind='MODI')]
        with zipfile.ZipFile(self.package/'tile-candidate.zip','w') as archive:
            archive.writestr('data/models/10.m2',b'data')
            archive.writestr('package-index.json',json.dumps(value))
        value['package_sha256']=planner.sha_file(self.package/'tile-candidate.zip')
        self.report.write_text(json.dumps(value))
        review=self.root/'review.json'
        review.write_text(json.dumps(dict(report_sha256=planner.sha_file(self.report),
                                         package_sha256=value['package_sha256'],unplaced_modi_ids=[777])))
        with patch.object(planner,'REVIEW',review):
            self.assertEqual(planner.read_package(self.report)[2],{})
            self.assertEqual(planner.read_package(self.report)[3],[777])
            self.report.write_text(json.dumps(value,indent=2))
            self.assertEqual(planner.read_package(self.report)[3],[])

    def test_output_inside_client_data_is_refused_before_any_access(self):
        with self.assertRaisesRegex(ValueError,'outside client data'):
            planner.plan(self.report,self.client,self.client/'Data/result.json')
        self.assertFalse((self.client/'Data').exists())

    def test_incomplete_native_output_cannot_create_a_plan(self):
        self.package_report([(10,b'data',b'data')])
        script=self.root/'empty-checker'
        script.write_text('#!/bin/sh\necho "invalid output"\n')
        script.chmod(0o755)
        with self.assertRaisesRegex(ValueError,'required metadata columns'):
            planner.plan(self.report,self.client,self.output,script,progress=lambda _:None)
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(os.environ.get('CASC_SANDBOX_CHECKER'),'Native CascLib checker required')
    def test_native_comparison_preserves_all_client_files(self):
        # A real CascLib scan of owned synthetic bytes, including a missing ID.
        (self.client/'.build.info').unlink()
        self.client.rmdir()
        lab.write_store(self.client)
        self.package_report([(lab.BASE_ID,lab.BASE_TEXT,lab.BASE_TEXT)],[123456])
        before={p.relative_to(self.client):p.read_bytes() for p in self.client.rglob('*') if p.is_file()}
        result=planner.plan(self.report,self.client,self.output,Path(os.environ['CASC_SANDBOX_CHECKER']),progress=lambda _:None)
        self.assertEqual(result['counts'],{'identical':1})
        self.assertFalse(result['external_dependencies'][0]['available'])
        self.assertNotEqual(result['resources'][0]['native']['ckey'],'0'*32)
        self.assertEqual(before,{p.relative_to(self.client):p.read_bytes() for p in self.client.rglob('*') if p.is_file()})

    def test_client_build_change_during_scan_prevents_publishing(self):
        self.package_report([(10,b'data',b'data')])
        def changed(*args,**kwargs):
            (self.client/'.build.info').write_bytes(b'changed selection')
            return {10:self.row(10,b'data')}
        with patch.object(planner,'scan',changed):
            with self.assertRaisesRegex(ValueError,'build selection changed'):
                planner.plan(self.report,self.client,self.output,progress=lambda _:None)
        self.assertFalse(self.output.exists())
