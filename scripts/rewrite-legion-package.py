#!/usr/bin/env python3
"""Stage private-ID payloads with typed reference rewriting; never install them."""
import argparse
import hashlib
import importlib.util
import json
import shutil
import struct
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path


def load(filename):
    spec = importlib.util.spec_from_file_location(filename, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


compare = load('plan-legion-client.py')
MAX_FILE = 256 * 1024 * 1024


def reference_slots(path, data):
    """Yield (absolute byte offset, FileDataID, semantic kind), never scan integers.

    MODD contains indexes into MODI, not FileDataIDs; its bytes stay unchanged.
    Unparsed sections stay unchanged and remain explicit coverage limitations.
    """
    suffix = Path(path).suffix.lower()
    if suffix not in {'.m2', '.skel', '.adt', '.wdt', '.wmo', '.wdl', '.tex'}:
        return []
    if suffix in {'.m2', '.skel'} and data[:4] == b'MD20':
        return []
    reverse = suffix in {'.adt', '.wdt', '.wmo', '.wdl', '.tex'}
    blocks = []
    offset = 0
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError('Truncated chunk header: ' + path)
        tag, size = struct.unpack_from('<4sI', data, offset)
        tag = (tag[::-1] if reverse else tag).decode('ascii')
        if size > len(data) - offset - 8:
            raise ValueError('Chunk exceeds bounds: ' + path)
        blocks.append((tag, offset + 8, size))
        offset += 8 + size
    tags = {tag for tag, _, _ in blocks}
    # Auxiliary WDT formats have unrelated schemas (including their MPHD).
    if suffix == '.wdt' and Path(path).stem.lower().endswith(('_lgt', '_occ', '_fogs', '_mpv')):
        return []
    result = []

    def array(start, size, kind, stride=4, field=0):
        if size % stride or field + 4 > stride:
            raise ValueError('Invalid ' + kind + ' reference array: ' + path)
        for pos in range(start + field, start + size, stride):
            fid = struct.unpack_from('<I', data, pos)[0]
            if fid:
                result.append((pos, fid, kind))

    for tag, start, size in blocks:
        if suffix in {'.m2', '.skel'}:
            if tag in {'SFID', 'TXID', 'SKID', 'BFID', 'PFID', 'RPID', 'GPID'}:
                array(start, size, tag)
            elif tag == 'AFID':
                array(start, size, tag, 8, 4)
            elif tag == 'SKPD':
                if size != 16:
                    raise ValueError('Unsupported SKPD layout')
                array(start, size, tag, 16, 8)
        elif suffix == '.tex':
            if tag == 'TXBT' and 'TXFN' not in tags:
                array(start, size, 'TXBT', 12)
        elif suffix == '.wdt':
            if tag == 'MPHD':
                if size != 32:
                    raise ValueError('Unsupported MPHD layout')
                array(start + 4, size - 4, 'MPHD')
            elif tag == 'MAID':
                if size != 4096 * 32:
                    raise ValueError('Unsupported MAID layout')
                for field in range(8):
                    array(start, size, 'MAID' if field < 5 else 'MAID-map-texture', 32, field * 4)
        else:
            if tag in {'GFID', 'MODI', 'MDID', 'MHID'}:
                array(start, size, tag)
            elif tag in {'MDDF', 'MODF', 'MLDD', 'MLMD'}:
                stride, flag, mask = ({'MDDF': (36, 34, 0x40), 'MODF': (64, 56, 8),
                                       'MLDD': (36, 34, 0x40), 'MLMD': (40, 32, 8)})[tag]
                if size % stride:
                    raise ValueError('Invalid placement layout')
                for pos in range(start, start + size, stride):
                    if struct.unpack_from('<H', data, pos + flag)[0] & mask:
                        array(pos, stride, tag, stride)
            elif tag in {'MLDX', 'MLMX'}:
                if size % 28:
                    raise ValueError('Invalid LOD extent layout')
                # Seven floats describe bounds/radius, not FileDataIDs.
            elif tag == 'MSSO' and suffix == '.wdl':
                array(start, size, tag, 48, 8)
            elif tag == 'MOMT' and 'MOTX' not in tags:
                for field in (12, 24, 36):
                    array(start, size, 'MOMT', 64, field)
    return result


def rewrite(path, data, mapping, expected):
    slots = reference_slots(path, data)
    observed = {(fid, kind) for _, fid, kind in slots}
    required = {(fid, 'MODI' if kind == 'MODI-placed-by-MODD' else kind)
                for fid, kind in expected if fid in mapping and kind != 'sidecar'}
    if required - observed:
        raise ValueError(f'Unlocated reference requiring a rewrite in {path}: {sorted(required-observed)[:8]}')
    sidecar = {fid for fid, kind in expected if fid in mapping and kind == 'sidecar'}
    if sidecar - {fid for _, fid, _ in slots}:
        raise ValueError('Sidecar-only private reference lacks a typed location: ' + path)
    body = bytearray(data)
    changes = []
    for offset, fid, kind in slots:
        if fid in mapping:
            new_id = mapping[fid]
            struct.pack_into('<I', body, offset, new_id)
            changes.append(dict(offset=offset, original_file_data_id=fid, target_file_data_id=new_id, kind=kind))
    # Round-trip every slot and every unchanged byte. No size/offset table changes.
    expected_body = bytearray(data)
    for row in changes:
        struct.pack_into('<I', expected_body, row['offset'], row['target_file_data_id'])
    rewritten = bytes(body)
    if rewritten != expected_body or len(rewritten) != len(data):
        raise ValueError('Reference rewrite changed unrelated bytes')
    after = reference_slots(path, rewritten)
    if len(after) != len(slots) or any(b != (pos, mapping.get(fid, fid), kind)
                                      for (pos, fid, kind), b in zip(slots, after)):
        raise ValueError('Rewritten reference round-trip failed: ' + path)
    return rewritten, changes


def prepare(report_path, plan_path, output, progress=print, format_sample=False):
    report_path, plan_path, output = map(lambda p: Path(p).resolve(), (report_path, plan_path, output))
    if (output.exists() or output.is_relative_to(report_path.parent) or
            any(p in {'Data', '_classic_beta_'} for p in output.parts)):
        raise ValueError('Output must be a NEW package directory outside inputs and client trees')
    progress('Verifying candidate ZIP and private-ID plan...')
    report_hash = compare.sha_file(report_path)
    report, requested, external, ignored = compare.read_package(report_path)
    plan_bytes = plan_path.read_bytes()
    plan_hash = hashlib.sha256(plan_bytes).hexdigest()
    plan = json.loads(plan_bytes)
    if plan.get('format') != 'wowforever-legion-private-id-plan-v1' or plan['package_sha256'] != report['package_sha256']:
        raise ValueError('Private-ID plan does not match package')
    rows = {row['original_file_data_id']: row for row in plan['resources']}
    if set(rows) != set(requested) or len(rows) != len(plan['resources']):
        raise ValueError('Incomplete or duplicate private-ID plan')
    mapping = {}
    for fid, row in rows.items():
        if row['path'] != requested[fid]['path'] or row['donor_ckey'] != requested[fid]['ckey']:
            raise ValueError('Plan resource fingerprint mismatch')
        dest = row['target_file_data_id']
        if not isinstance(dest, int) or isinstance(dest, bool) or not 0 < dest <= 0xffffffff:
            raise ValueError('Invalid target FileDataID')
        if dest != fid:
            if not 0x00f00000 <= dest < 0x00ffff00 or dest in requested or dest in external:
                raise ValueError('Invalid private FileDataID allocation')
            mapping[fid] = dest
    if len(set(row['target_file_data_id'] for row in rows.values())) != len(rows):
        raise ValueError('Duplicate target FileDataID')
    if len(mapping) != plan['private_ids']:
        raise ValueError('Private-ID count mismatch')
    refs = defaultdict(set)
    for edge in report['references']:
        if edge['file_data_id'] not in ignored:
            refs[edge['source']].add((edge['file_data_id'], edge['kind']))
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < report['bytes'] + 256*1024*1024:
        raise ValueError('Insufficient free space for delta and 256 MiB reserve')
    stage = Path(tempfile.mkdtemp(prefix=output.name + '.partial-', dir=output.parent))
    files, counts = [], Counter()
    additional = []
    sample = []
    sample_bytes = 0
    try:
        with zipfile.ZipFile(report_path.parent/'tile-candidate.zip') as source, zipfile.ZipFile(
                stage/'private-resources.zip', 'x', zipfile.ZIP_DEFLATED, allowZip64=True) as dest:
            if len(source.namelist()) != len(set(source.namelist())):
                raise ValueError('Duplicate ZIP entries')
            for index, row in enumerate(report['files']):
                member = source.getinfo('data/' + row['path'])
                if member.file_size != row['bytes'] or member.file_size > MAX_FILE:
                    raise ValueError('Resource size mismatch/limit: ' + row['path'])
                data = source.read(member)
                if hashlib.sha256(data).hexdigest() != row['sha256'] or hashlib.md5(data).hexdigest() != row['ckey']:
                    raise ValueError('Resource content mismatch: ' + row['path'])
                for offset, fid, kind in reference_slots(row['path'], data):
                    if kind in {'MLDD', 'MLMD', 'MSSO', 'TXBT'}:
                        additional.append(dict(source=row['path'], offset=offset, file_data_id=fid, kind=kind,
                            role='embedded_texture_key' if kind == 'TXBT' else 'external_placement',
                            target_file_data_id=mapping.get(fid, fid),
                            listed_in_package_or_external_plan=fid in requested or fid in external))
                if format_sample and Path(row['path']).suffix.lower() in {'.tex', '.wdl'}:
                    sample_bytes += len(data)
                    if sample_bytes > 20*1024*1024:
                        raise ValueError('Format sample exceeds 20 MiB budget')
                    sample.append((row['path'], data, row['sha256']))
                rewritten, changes = rewrite(row['path'], data, mapping, refs[row['path']])
                ids = row['file_data_ids']
                private = [fid in mapping for fid in ids]
                if any(private) != all(private) or (changes and not all(private)):
                    raise ValueError('Shared/aliased parent requires a private ID: ' + row['path'])
                payload = 'data/' + row['path'] if all(private) else None
                if payload:
                    dest.writestr(payload, rewritten)
                    if dest.read(payload) != rewritten:
                        raise ValueError('Delta ZIP verification failed')
                counts['private_payload_files' if payload else 'shared_file_candidates'] += 1
                counts['rewritten_files'] += bool(changes)
                counts['rewritten_reference_slots'] += len(changes)
                files.append(dict(path=row['path'],original_file_data_ids=ids,
                                  target_file_data_ids=[mapping.get(fid,fid) for fid in ids],
                                  original_sha256=row['sha256'],sha256=hashlib.sha256(rewritten).hexdigest(),
                                  ckey=hashlib.md5(rewritten).hexdigest(),bytes=len(rewritten),payload=payload,changes=changes))
                if (index+1) % 250 == 0:
                    progress(f'Rewritten and verified {index+1}/{len(report["files"])} files')
            result = dict(format='wowforever-legion-private-resource-stage-v1',
                          source_package_sha256=report['package_sha256'],source_report_sha256=report_hash,source_plan_sha256=plan_hash,
                          target_build_info_sha256=plan['target_build_info_sha256'],tile=report['tile'],
                          counts=dict(counts),files=files,external_dependencies=plan['external_dependencies'],
                          coverage_limits=report['coverage_limits'],ignored_unplaced_modi_ids=ignored,
                          reference_parser_revision=2,additional_typed_references=additional,
                          unresolved_additional_placement_ids=sorted({r['file_data_id'] for r in additional
                              if r['role']=='external_placement' and not r['listed_in_package_or_external_plan']}),
                          client_modified=False,typed_references_rewritten=True,full_dependency_closure_proven=False,
                          root_policy_assigned=False,installable=False,
                          remaining_requirements=['revalidate target ROOT reservations and every reused payload',
                              'resolve opaque dependency sections and native ROOT/tag policies',
                              'client/server Map record and server geometry', 'transactional CASC import and game test'])
            dest.writestr('private-resource-index.json', json.dumps(result, indent=2)+'\n')
        if format_sample:
            sample_index = dict(format='wowforever-legion-aux-format-sample-v1',
                source_package_sha256=report['package_sha256'],
                files=[dict(path=name, bytes=len(body), sha256=digest) for name,body,digest in sample])
            with zipfile.ZipFile(stage/'aux-format-sample.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('sample-index.json', json.dumps(sample_index, indent=2)+'\n')
                for name, body, _ in sample:
                    archive.writestr('data/'+name, body)
                    if archive.read('data/'+name) != body:
                        raise ValueError('Auxiliary sample verification failed')
        result['package_sha256'] = compare.sha_file(stage/'private-resources.zip')
        (stage/'report.json').write_text(json.dumps(result, indent=2)+'\n')
        if compare.sha_file(report_path.parent/'tile-candidate.zip') != report['package_sha256']:
            raise ValueError('Source package changed during rewrite')
        if compare.sha_file(report_path) != report_hash:
            raise ValueError('Package report changed during rewrite')
        if compare.sha_file(plan_path) != result['source_plan_sha256']:
            raise ValueError('Private-ID plan changed during rewrite')
        if output.exists():
            raise FileExistsError(output)
        stage.rename(output)
    except BaseException:
        shutil.rmtree(stage)
        raise
    progress('Private resource package: '+str(output/'private-resources.zip'))
    progress('Report: '+str(output/'report.json'))
    if format_sample:
        progress('Small format sample: '+str(output/'aux-format-sample.zip'))
    progress(f'Unresolved additional placement IDs: {len(result["unresolved_additional_placement_ids"])}')
    progress(f'Private payload files: {counts["private_payload_files"]}; rewritten files: {counts["rewritten_files"]}; installable: false')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-report', type=Path, required=True)
    parser.add_argument('--private-plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--format-sample', action='store_true', help='Also package original TEX/WDL for format review (20 MiB limit)')
    args = parser.parse_args()
    try:
        prepare(args.package_report, args.private_plan, args.output, format_sample=args.format_sample)
    except (ValueError, OSError, KeyError, TypeError, struct.error, UnicodeError, zipfile.BadZipFile) as exc:
        parser.exit(1, f'Private resource staging stopped: {exc}\n')
