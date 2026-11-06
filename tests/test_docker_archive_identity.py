import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from docker_archive_identity import verify_image_ids

OCI_INDEX = 'application/vnd.oci.image.index.v1+json'
OCI_MANIFEST = 'application/vnd.oci.image.manifest.v1+json'
OCI_CONFIG = 'application/vnd.oci.image.config.v1+json'


class SavedImage:
    def __init__(self):
        self.files = {}
        self.config = self.put({'architecture':'amd64','os':'linux','config':{'Cmd':['server']}}, OCI_CONFIG)
        self.image = self.put({'schemaVersion':2,'mediaType':OCI_MANIFEST,
                               'config':self.config,'layers':[]}, OCI_MANIFEST)
        self.attestation_config = self.put({'architecture':'unknown','os':'unknown'}, OCI_CONFIG)
        self.attestation = self.put({'schemaVersion':2,'mediaType':OCI_MANIFEST,
                                     'config':self.attestation_config,'layers':[]}, OCI_MANIFEST)
        self.index = self.put({'schemaVersion':2,'mediaType':OCI_INDEX,
                               'manifests':[self.image,self.attestation]}, OCI_INDEX)

    def put(self, content, media):
        body = json.dumps(content, separators=(',',':')).encode()
        digest = 'sha256:' + hashlib.sha256(body).hexdigest()
        self.files['blobs/sha256/' + digest[7:]] = body
        return {'mediaType':media,'digest':digest,'size':len(body)}

    def write(self, path, roots=None, compatibility=None):
        files = dict(self.files)
        files['manifest.json'] = json.dumps(compatibility or [
            {'Config':'blobs/sha256/' + self.config['digest'][7:], 'Layers':[]}]).encode()
        if roots is not None:
            files['index.json'] = json.dumps({'schemaVersion':2,'manifests':roots}).encode()
        with tarfile.open(path, 'w') as archive:
            for name, body in files.items():
                item = tarfile.TarInfo(name)
                item.size = len(body)
                archive.addfile(item, io.BytesIO(body))


class DockerArchiveIdentityTests(unittest.TestCase):
    def test_classic_config_digest_and_containerd_single_manifest_and_index_ids(self):
        for kind in ('classic', 'manifest', 'index'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                saved = SavedImage()
                roots = None if kind == 'classic' else [saved.image if kind == 'manifest' else saved.index]
                saved.write(Path(temp) / 'images.tar', roots)
                expected = saved.config['digest'] if kind == 'classic' else roots[0]['digest']
                result = verify_image_ids(Path(temp) / 'images.tar', {expected})
                self.assertEqual(result['verified_ids'], [expected])

    def test_user_case_four_distinct_roots_one_manifest_three_indices(self):
        with tempfile.TemporaryDirectory() as temp:
            saved = SavedImage()
            roots, configs = [], []
            for index in range(4):
                config = saved.put({'architecture':'amd64','os':'linux','config':{'id':index}}, OCI_CONFIG)
                manifest = saved.put({'schemaVersion':2,'mediaType':OCI_MANIFEST,
                                      'config':config,'layers':[]}, OCI_MANIFEST)
                root = manifest if index == 0 else saved.put({'schemaVersion':2,'mediaType':OCI_INDEX,
                                      'manifests':[manifest,saved.attestation]}, OCI_INDEX)
                roots.append(root)
                configs.append({'Config':'blobs/sha256/' + config['digest'][7:], 'Layers':[]})
            saved.write(Path(temp) / 'images.tar', roots, configs)
            result = verify_image_ids(Path(temp) / 'images.tar', {root['digest'] for root in roots})
            self.assertEqual(result['format'], 'oci-root')
            self.assertEqual(len(result['config_ids']), 4)

    def test_index_digest_strings_alone_cannot_pass_without_verified_root_bytes(self):
        for broken in ('missing_root', 'changed_root', 'changed_config', 'unrelated_root', 'wrong_size'):
            with self.subTest(broken=broken), tempfile.TemporaryDirectory() as temp:
                saved = SavedImage()
                root = dict(saved.index)
                name = 'blobs/sha256/' + root['digest'][7:]
                if broken == 'missing_root':
                    del saved.files[name]
                elif broken == 'changed_root':
                    saved.files[name] = b' ' * len(saved.files[name])
                elif broken == 'changed_config':
                    name = 'blobs/sha256/' + saved.config['digest'][7:]
                    saved.files[name] = b' ' * len(saved.files[name])
                elif broken == 'unrelated_root':
                    root = saved.attestation
                else:
                    root['size'] += 1
                saved.write(Path(temp) / 'images.tar', [root])
                with self.assertRaises((ValueError, KeyError)):
                    verify_image_ids(Path(temp) / 'images.tar', {root['digest']})

    def test_extra_root_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            saved = SavedImage()
            saved.write(Path(temp) / 'images.tar', [saved.index,saved.image])
            with self.assertRaisesRegex(ValueError, 'root identities differ'):
                verify_image_ids(Path(temp) / 'images.tar', {saved.index['digest']})

    def test_available_platform_can_verify_with_an_unavailable_other_platform(self):
        with tempfile.TemporaryDirectory() as temp:
            saved = SavedImage()
            absent = {'mediaType':OCI_MANIFEST, 'digest':'sha256:' + '0'*64, 'size':123}
            root = saved.put({'schemaVersion':2,'mediaType':OCI_INDEX,
                              'manifests':[saved.image,absent]}, OCI_INDEX)
            saved.write(Path(temp) / 'images.tar', [root])
            self.assertEqual(verify_image_ids(Path(temp) / 'images.tar', {root['digest']})['format'], 'oci-root')

    def test_missing_runnable_layer_cannot_verify(self):
        with tempfile.TemporaryDirectory() as temp:
            saved = SavedImage()
            absent = {'mediaType':'application/vnd.oci.image.layer.v1.tar',
                      'digest':'sha256:' + '0'*64, 'size':123}
            root = saved.put({'schemaVersion':2,'mediaType':OCI_MANIFEST,
                              'config':saved.config,'layers':[absent]}, OCI_MANIFEST)
            saved.write(Path(temp) / 'images.tar', [root])
            with self.assertRaises(KeyError):
                verify_image_ids(Path(temp) / 'images.tar', {root['digest']})
