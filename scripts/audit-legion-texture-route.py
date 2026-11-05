#!/usr/bin/env python3
"""Read-only comparison of the original/private texture's ROOT and TVFS routes.

Outputs metadata only. Missing variant coverage is a hypothesis, not proof of
the game engine's selected variant or the reason for a green texture.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile

from casc_manifest_update import Encoding
from legion_reports import default_root


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


canary = load('repair-legion-tvfs-entry.py')
root_audit = load('audit-legion-root-types.py')
install = canary.install
ORIGINAL_ID = 123086
PRIVATE_ID = 15728640


def variant_coverage(original, private):
    def identity(row):
        return row['locale'], tuple(row['raw_flags']), row['ckey']
    actual = {identity(row) for row in private}
    return [row for row in original if identity(row) not in actual]


def child_routes(data, original_id=ORIGINAL_ID, private_id=PRIVATE_ID):
    parsed = canary.storelib.tvfs.parse_tvfs(data, raw_paths=True)
    leaves = parsed['leaves']
    original_prefix = f'{original_id:08X}'
    private_prefix = f'{private_id:08X}'
    pairs = []
    for name, offset in leaves.items():
        if len(name) != 40 or not name.upper().startswith(original_prefix):
            continue
        # Preserve the actual filename case used in the native directory.
        target = private_prefix + name[8:]
        pairs.append(dict(ckey=name[8:].lower(), original_path=name, private_path=target,
                          original_vfs_offset=offset, private_vfs_offset=leaves.get(target),
                          same_vfs_row=leaves.get(target) == offset))
    positions = {'path': 12, 'vfs': 20, 'cft': 28, 'est': 38}
    tables = {name: dict(zip(('offset', 'bytes'), struct.unpack_from('>II', data, pos)))
              for name, pos in positions.items()}
    return dict(table_layout=tables, pairs=pairs)


def audit(client, output, progress=print):
    client, _ = install.canary.copy_identity(client)
    folder, journal = install.operation(client)
    before_info = (client/'.build.info').read_bytes()
    before_metadata = install.container.metadata(client/'Data/data')
    if journal['phase'] != 'verified' or install.canary.sha(before_info) != journal['after_info_sha256']:
        raise ValueError('Active verified operation does not match this client')
    if not journal.get('tvfs_entry_canary'):
        raise ValueError('Expected the installed one-texture TVFS experiment')
    if (journal.get('tvfs_canary_original_id'), journal.get('tvfs_canary_new_id')) != (ORIGINAL_ID, PRIVATE_ID):
        raise ValueError('Unexpected texture experiment IDs')
    output = Path(output).resolve()
    repo = Path(__file__).resolve().parents[1]
    if output.exists() or output.is_relative_to(client) or output.is_relative_to(repo):
        raise ValueError('Choose a NEW report outside the client and Git repository')
    progress('Reading active ROOT and texture directories; no client files are changed...')
    store = canary.storelib.Store(client, synthetic_only=False)
    ck, ek = store.values['encoding'].split()[:2]
    encoding = Encoding(store.read(bytes.fromhex(ek), bytes.fromhex(ck)))
    root = root_audit.read_content(store, encoding, store.values['root'].split()[0])
    observed = root_audit.profiles(root, {ORIGINAL_ID, PRIVATE_ID})
    original = observed.get(ORIGINAL_ID, [])
    private = observed.get(PRIVATE_ID, [])
    if not original or not private:
        raise ValueError('Original/private ID missing from active ROOT')
    top = canary.storelib.tvfs.parse_tvfs(canary.configured(store, 'vfs-root'))
    directories = []
    for row in journal['tvfs_canary_directories']:
        name, key = row['directory'], row['build_config_key']
        data = canary.configured(store, key)
        ck, ek = store.values[key].split()[:2]
        spans = top['leaves'].get(name, [])
        expected_reference = len(spans) == 1 and all((
            spans[0]['ckey'] == ck, spans[0]['ekey_prefix'] == ek[:18],
            spans[0]['offset'] == 0, spans[0]['bytes'] == len(data)))
        directories.append(dict(directory=name, build_config_key=key,
                                top_level_reference_matches=expected_reference,
                                **child_routes(data, ORIGINAL_ID, PRIVATE_ID)))
    payloads = []
    for ckey in sorted({row['ckey'] for row in original + private}):
        try:
            data = root_audit.read_content(store, encoding, ckey)
            payloads.append(dict(ckey=ckey, status='READ_OK', bytes=len(data),
                                 sha256=hashlib.sha256(data).hexdigest(),
                                 texture_signature=data[:4].decode('ascii', errors='replace')))
        except (OSError, ValueError, KeyError) as error:
            payloads.append(dict(ckey=ckey, status='NOT_READABLE_BY_LOCAL_AUDITOR', error=str(error)))
    if (client/'.build.info').read_bytes() != before_info or install.container.metadata(client/'Data/data') != before_metadata:
        raise ValueError('Client changed while reading; close game and launcher and retry')
    result = dict(format='wowforever-texture-route-audit-v1', operation=folder.name,
                  build_info_sha256=install.canary.sha(before_info),
                  active_is_tvfs_layout_canary=bool(journal.get('tvfs_layout_canary')),
                  original_file_data_id=ORIGINAL_ID, private_file_data_id=PRIVATE_ID,
                  original_root_profiles=original, private_root_profiles=private,
                  native_profiles_missing_from_private_root=variant_coverage(original, private),
                  directories=directories, payloads=payloads,
                  client_modified=False, server_modified=False,
                  engine_selected_variant_known=False, green_texture_cause_proven=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    progress('Texture route report: ' + str(output))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('client', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        output = args.output or default_root(args.client)/(
            'Dalaran-texture-route-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '.json')
        token = hashlib.sha256(str(args.client.resolve()).casefold().encode()).hexdigest()
        with (Path(tempfile.gettempdir())/('wowforever-casc-edit-' + token + '.lock')).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            audit(args.client, output)
    except (OSError, ValueError, KeyError, TypeError, struct.error) as error:
        parser.exit(1, 'Texture route audit stopped: ' + str(error) + '\n')
