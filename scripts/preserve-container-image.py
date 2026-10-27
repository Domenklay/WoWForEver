#!/usr/bin/env python3
"""Preserve a running container's server image locally, including Desktop stores."""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path


def preserve(container, tag):
    def run(*args, check=True):
        return subprocess.run(['docker', *args], check=check, capture_output=True, text=True)

    info = json.loads(run('inspect', container).stdout)[0]
    source = info['Image']
    # A container's .Image digest need not be addressable by `docker image`
    # in Desktop's containerd store after its original tag has been replaced.
    found = run('image', 'inspect', source, check=False)
    tagged = found.returncode == 0 and run('tag', source, tag, check=False).returncode == 0
    if tagged:
        method = 'original-image-tag'
    else:
        # Export does not need the old image metadata, unlike commit, which can
        # also fail when its parent image is no longer addressable. Reconstruct
        # the runtime directives needed by this repository's TrinityCore image.
        # Compose supplies service environment, ports and volumes on rollback.
        config = info['Config']
        if config.get('Entrypoint') != ['/usr/local/bin/entrypoint.sh']:
            raise ValueError('Unexpected server entrypoint; refusing filesystem fallback')
        changes = ['ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                   'ENV LD_LIBRARY_PATH=/opt/trinitycore/lib',
                   'ENTRYPOINT '+json.dumps(config['Entrypoint']),
                   'CMD '+json.dumps(config.get('Cmd') or ['worldserver'])]
        if config.get('WorkingDir'):
            changes.append('WORKDIR '+config['WorkingDir'])
        if config.get('User'):
            changes.append('USER '+config['User'])
        with tempfile.TemporaryDirectory(prefix='forever-server-image-') as temp:
            archive = str(Path(temp)/'rootfs.tar')
            run('export', '--output', archive, container)
            args = ['import']
            for change in changes:
                args.extend(['--change', change])
            run(*args, archive, tag)
        method = 'container-filesystem-export-import'
    saved = json.loads(run('image', 'inspect', tag).stdout)[0]
    return {'container': container, 'container_image_reference': source,
            'rollback_reference': tag, 'saved_image_id': saved['Id'], 'method': method,
            'volumes_included': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container', required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--backup', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = preserve(args.container, args.tag)
    except subprocess.CalledProcessError as exc:
        parser.exit(1, 'Cannot preserve previous server; services have not been stopped.\n'+(exc.stderr or str(exc))+'\n')
    args.backup.mkdir(parents=True, exist_ok=True)
    (args.backup/'image-preservation.json').write_text(json.dumps(report, indent=2)+'\n')
    # Use the verified unique tag: a manifest/config digest can itself be
    # unaddressable in the Desktop image store that caused the original error.
    (args.backup/'old-image.txt').write_text(report['rollback_reference']+'\n')
    print('Previous server preserved:', report['rollback_reference'], '('+report['method']+')')
