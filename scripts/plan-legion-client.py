#!/usr/bin/env python3
"""Verify a prepared tile package and compare its resources to a local client.

Read-only client scan, no network or installation. OPEN_FAILED never proves an
ID is free in all ROOT variants. Conflicts are reported, never overwritten.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import signal
import subprocess
import tempfile
import threading
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

REVIEW = Path(__file__).parents[1]/'content/donors/legion-735/full-tile-package-review.json'
REQUIRED = {'file_id','status','bytes','sha256','tag_mask','error','ckey','locale_flags','content_flags'}


def sha_file(path):
    value = hashlib.sha256()
    with path.open('rb') as incoming:
        for block in iter(lambda: incoming.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def safe_name(value):
    if (not isinstance(value, str) or not value or '\\' in value or ':' in value or
            PurePosixPath(value).is_absolute() or '..' in PurePosixPath(value).parts):
        raise ValueError('Invalid resource path in report')


def read_package(report_path):
    report = json.loads(report_path.read_text())
    if report.get('format') != 'wowforever-legion-tile-package-v1' or report.get('errors'):
        raise ValueError('Expected a tile package report without structural errors')
    archive_path = report_path.parent/'tile-candidate.zip'
    if sha_file(archive_path) != report['package_sha256']:
        raise ValueError('Package SHA-256 differs from report')
    with zipfile.ZipFile(archive_path) as archive:
        member = archive.getinfo('package-index.json')
        if member.file_size > 32*1024*1024:
            raise ValueError('Oversized package index')
        inner = json.loads(archive.read(member))
        if inner != {key:value for key,value in report.items() if key != 'package_sha256'}:
            raise ValueError('External report differs from the packaged index')
    requested = {}
    paths = set()
    for row in report['files']:
        safe_name(row['path'])
        if row['path'] in paths:
            raise ValueError('Duplicate resource path')
        paths.add(row['path'])
        if not isinstance(row['bytes'],int) or isinstance(row['bytes'],bool) or row['bytes'] < 0:
            raise ValueError('Invalid resource size')
        for key, length in (('sha256',64),('source_sha256',64),('ckey',32)):
            if not re.fullmatch('[0-9a-f]{'+str(length)+'}', row[key]):
                raise ValueError('Invalid resource hash')
        if not row['file_data_ids']:
            raise ValueError('Resource lacks a FileDataID: '+row['path'])
        for fid in row['file_data_ids']:
            if not isinstance(fid,int) or isinstance(fid,bool) or not 0 < fid <= 0xffffffff:
                raise ValueError('Invalid resource FileDataID')
            if fid in requested and requested[fid]['sha256'] != row['sha256']:
                raise ValueError('Conflicting package contents for one FileDataID')
            requested[fid] = row
    ignored = set()
    if REVIEW.exists():
        review = json.loads(REVIEW.read_text())
        # Accept the earlier overinclusive MODI graph only for this exact
        # reviewed report; never apply those omissions to arbitrary packages.
        if review.get('report_sha256') == sha_file(report_path) and review.get('package_sha256') == report['package_sha256']:
            ignored = set(review['unplaced_modi_ids'])
            for fid in ignored:
                links = [r for r in report['references'] if r['file_data_id'] == fid]
                if not links or any(r['kind'] != 'MODI' or r['source'] != 'world/wmo/brokenisles/dalaran2.wmo' for r in links):
                    raise ValueError('Reviewed MODI correction does not match references')
    external = {row['file_data_id']:row for row in report['missing_from_export'] if row['file_data_id'] not in ignored}
    if any(not isinstance(fid,int) or isinstance(fid,bool) or not 0 < fid <= 0xffffffff for fid in external):
        raise ValueError('Invalid external dependency ID')
    if set(external) & set(requested):
        raise ValueError('Report calls a packaged FileDataID missing')
    return report, requested, external, sorted(ignored)


def scan(checker, client, ids, progress=print, timeout=1800):
    ids = sorted(ids)
    expected_ids = set(ids)
    timed_out = threading.Event()
    with tempfile.TemporaryFile(mode='w+t') as errors:
        process = subprocess.Popen([str(checker.resolve()),str(client),*map(str,ids)],
                                   stdout=subprocess.PIPE,stderr=errors,text=True,start_new_session=True)
        def stop():
            timed_out.set()
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        timer = threading.Timer(timeout, stop)
        timer.daemon = True
        timer.start()
        rows = {}
        try:
            reader = csv.DictReader(process.stdout, delimiter='\t')
            if not reader.fieldnames or not REQUIRED <= set(reader.fieldnames):
                raise ValueError('Native checker did not return the required metadata columns')
            for row in reader:
                fid = int(row['file_id'])
                if fid not in expected_ids or fid in rows or None in row:
                    raise ValueError('Unexpected or duplicate native result')
                if row['status'] not in {'READ_OK','OPEN_FAILED','READ_FAILED','SIZE_FAILED','SIZE_LIMIT','INFO_FAILED'}:
                    raise ValueError('Unknown native result status')
                int(row['bytes']);int(row['error'])
                if row['status'] == 'READ_OK':
                    if not re.fullmatch('[0-9a-f]{64}',row['sha256']) or not re.fullmatch('[0-9a-f]{32}',row['ckey']):
                        raise ValueError('Invalid native fingerprint')
                    for key in ('tag_mask','locale_flags','content_flags'):
                        int(row[key],16)
                rows[fid] = row
                if len(rows) % 250 == 0:
                    progress(f'Compared {len(rows)}/{len(ids)} FileDataIDs')
            code = process.wait(timeout=10)
            if timed_out.is_set():
                raise ValueError('Native scan timed out; client remains unchanged')
            if code not in (0,1) or set(rows) != expected_ids:
                raise ValueError('Native scan failed or returned incomplete results')
            return rows
        except BaseException as exc:
            if process.poll() is None:
                stop()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL)
                    process.wait()
            if isinstance(exc,ValueError):
                errors.seek(0)
                raise ValueError(str(exc)+'\n'+errors.read()[-8192:]) from exc
            raise
        finally:
            timer.cancel()
            process.stdout.close()


def classify(report, requested, external, ignored, results):
    entries = []
    counts = Counter()
    profiles = Counter()
    for fid,row in sorted(requested.items()):
        actual = results[fid]
        if actual['status'] == 'READ_OK':
            if int(actual['bytes']) == row['bytes'] and actual['sha256'] == row['sha256']:
                kind = 'identical'
                if actual['ckey'] != '0'*32 and actual['ckey'] != row['ckey']:
                    kind = 'inconsistent_native_ckey'
            elif row['transformation'] and actual['sha256'] == row['source_sha256']:
                kind = 'source_matches_but_package_transformed'
            else:
                kind = 'different_content_same_id'
        elif actual['status'] == 'SIZE_LIMIT':
            kind = 'size_limit_not_checked'
        elif actual['status'] in {'SIZE_FAILED','READ_FAILED'} and actual['error'] == '1007':
            kind = 'not_locally_resident'
        elif actual['status'] == 'OPEN_FAILED':
            kind = 'not_readable_requires_ROOT_check'
        else:
            kind = 'read_error'
        counts[kind] += 1
        if kind in {'identical','source_matches_but_package_transformed'}:
            profiles[(Path(row['path']).suffix.lower(),actual['locale_flags'],actual['content_flags'],actual['tag_mask'])] += 1
        entries.append(dict(file_data_id=fid,path=row['path'],classification=kind,
                            package_sha256=row['sha256'],package_ckey=row['ckey'],native=actual))
    dependencies = []
    for fid,row in sorted(external.items()):
        actual = results[fid]
        dependencies.append(dict(file_data_id=fid,catalog_path=row['catalog_path'],native=actual,
                                 available=actual['status']=='READ_OK',donor_content_match_verified=False))
    return dict(format='wowforever-legion-client-comparison-v1',package_sha256=report['package_sha256'],
                tile=report['tile'],counts=dict(counts),resources=entries,external_dependencies=dependencies,
                ignored_unplaced_legacy_MODI_ids=ignored,
                verified_source_profiles=[dict(extension=k[0],locale_flags=k[1],content_flags=k[2],tag_mask=k[3],files=v)
                                          for k,v in sorted(profiles.items())],
                client_modified=False,installable=False,coverage_limits=report['coverage_limits'],
                note='A failed local open does not prove an ID is unreserved in ROOT. Different contents and transformed WDT need an explicit remap/override plan. Native profiles cover only fingerprint-matched files. Map records and server geometry are not installed.')


def plan(report_path, client, output, checker=None, progress=print):
    client = Path(client).resolve(strict=True)
    output = Path(output).resolve()
    if (output.exists() or output == client/'.build.info' or output.is_relative_to(client/'Data') or
            output.is_relative_to(client/'_classic_beta_')):
        raise ValueError('Use a new report path outside client data and executable trees')
    report_path = Path(report_path).resolve(strict=True)
    build_info_sha256 = sha_file(client/'.build.info')
    checker = Path(checker or Path(__file__).with_name('check-client-casc.sh'))
    progress('Checking the existing ZIP and report without repackaging...')
    report, requested, external, ignored = read_package(report_path)
    progress(f"Comparing {len(requested)} packaged IDs and {len(external)} external dependencies; original client is read-only...")
    results = scan(checker,client,set(requested)|set(external),progress)
    if sha_file(client/'.build.info') != build_info_sha256:
        raise ValueError('Client build selection changed during comparison; no plan published')
    result = classify(report,requested,external,ignored,results)
    result['client_build_info_sha256'] = build_info_sha256
    result['source_report_sha256'] = sha_file(report_path)
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as outgoing:
        json.dump(result,outgoing,indent=2)
        outgoing.write('\n')
    progress(json.dumps(result['counts'],ensure_ascii=False))
    progress('Client comparison report: '+str(output))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    parser.add_argument('--client',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    try:
        plan(args.report,args.client,args.output)
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError,zipfile.BadZipFile) as error:
        parser.exit(1,f'Client comparison stopped: {error}\n')
    except KeyboardInterrupt:
        parser.exit(130,'Client comparison interrupted; no client files were changed.\n')
