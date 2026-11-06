"""Verify image identity in classic Docker-save and containerd OCI archives.

Classic image IDs identify config bytes. Containerd image IDs identify an image
manifest or image index instead (moby daemon/containerd/image_inspect.go). Never
substitute config digests for those roots or accept unverified index strings.
"""
import hashlib
import json
from pathlib import PurePosixPath
import re
import tarfile

INDEX_TYPES = {'application/vnd.oci.image.index.v1+json',
               'application/vnd.docker.distribution.manifest.list.v2+json'}
MANIFEST_TYPES = {'application/vnd.oci.image.manifest.v1+json',
                  'application/vnd.docker.distribution.manifest.v2+json'}
CONFIG_TYPES = {'application/vnd.oci.image.config.v1+json',
                'application/vnd.docker.container.image.v1+json'}
LIMIT = 8 * 1024 * 1024


def sha(body):
    return 'sha256:' + hashlib.sha256(body).hexdigest()


def member(archive, name):
    if not isinstance(name, str) or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts:
        raise ValueError('Unsafe Docker archive member')
    item = archive.getmember(name)
    if not item.isfile():
        raise ValueError('Docker archive metadata/blob is not a regular file')
    return item


def body(archive, name):
    item = member(archive, name)
    if item.size > LIMIT:
        raise ValueError('Docker image metadata exceeds the size limit')
    result = archive.extractfile(item).read(LIMIT + 1)
    if len(result) != item.size:
        raise ValueError('Truncated Docker image metadata')
    return result


def blob(archive, descriptor, metadata=True):
    digest = descriptor.get('digest', '')
    size = descriptor.get('size')
    if (not re.fullmatch('sha256:[0-9a-f]{64}', digest)
            or type(size) is not int or size < 0):
        raise ValueError('Invalid OCI blob descriptor')
    name = 'blobs/sha256/' + digest[7:]
    item = member(archive, name)
    if item.size != size:
        raise ValueError('OCI blob size differs from its descriptor')
    if not metadata:
        return None
    data = body(archive, name)
    if sha(data) != digest:
        raise ValueError('OCI metadata blob digest mismatch')
    return json.loads(data)


def verify_image_ids(path, expected):
    expected = set(expected)
    if not expected or any(not re.fullmatch('sha256:[0-9a-f]{64}', v) for v in expected):
        raise ValueError('Invalid saved image identities')
    with tarfile.open(path, 'r:') as archive:
        names = [v.name for v in archive.getmembers()]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate Docker archive members')
        entries = json.loads(body(archive, 'manifest.json'))
        if not isinstance(entries, list) or not entries or len(entries) > 4096:
            raise ValueError('Invalid Docker compatibility manifest')
        configs = {sha(body(archive, entry['Config'])) for entry in entries}
        if configs == expected:
            return {'format': 'docker-config', 'verified_ids': sorted(expected)}
        try:
            index = json.loads(body(archive, 'index.json'))
        except KeyError:
            raise ValueError('Exported Docker image identities differ') from None
        roots = index.get('manifests', [])
        if (index.get('schemaVersion') != 2 or not isinstance(roots, list)
                or len(roots) > 4096 or {v.get('digest') for v in roots} != expected):
            raise ValueError('Exported OCI root identities differ')
        cache, visiting = {}, set()

        def descend(descriptor, depth=0, optional=False):
            digest = descriptor.get('digest')
            media = descriptor.get('mediaType')
            if depth > 8 or len(cache) > 4096 or digest in visiting:
                raise ValueError('Invalid OCI image descriptor graph')
            if media not in INDEX_TYPES | MANIFEST_TYPES:
                raise ValueError('Unsupported OCI image descriptor type')
            try:
                content = blob(archive, descriptor)
            except KeyError:
                # Docker/containerd can save only locally available platforms of
                # an index. The root must still reach the exported runnable config.
                if optional:
                    return set()
                raise ValueError('Missing OCI root metadata') from None
            if content.get('schemaVersion') != 2 or content.get('mediaType', media) != media:
                raise ValueError('OCI metadata type/schema mismatch')
            key = (digest, media)
            if key in cache:
                return cache[key]
            visiting.add(digest)
            result = set()
            if media in INDEX_TYPES:
                children = content.get('manifests', [])
                if not isinstance(children, list) or len(children) > 4096:
                    raise ValueError('Invalid OCI platform list')
                for child in children:
                    result.update(descend(child, depth + 1, optional=True))
            else:
                config = content.get('config', {})
                if config.get('mediaType') not in CONFIG_TYPES:
                    raise ValueError('Invalid OCI config type')
                if config.get('digest') not in configs:
                    # Attestations and unavailable other platforms are not entries
                    # in Docker's runnable compatibility manifest. Their manifest
                    # hash was checked above; they cannot establish image identity.
                    visiting.remove(digest)
                    cache[key] = result
                    return result
                blob(archive, config)
                layers = content.get('layers', [])
                if not isinstance(layers, list) or len(layers) > 4096:
                    raise ValueError('Invalid OCI layer list')
                for layer in layers:
                    blob(archive, layer, metadata=False)
                result.add(config['digest'])
            visiting.remove(digest)
            cache[key] = result
            return result

        linked = set()
        for root in roots:
            found = descend(root)
            if not found:
                raise ValueError('OCI root does not reach an exported runnable image config')
            linked.update(found)
        if linked != configs:
            raise ValueError('Docker compatibility configs differ from verified OCI roots')
        return {'format': 'oci-root', 'verified_ids': sorted(expected), 'config_ids': sorted(configs)}
