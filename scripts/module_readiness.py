"""Read current-process module evidence, including flushed Server.log output."""
import json
import re
import time

# Only selected, non-secret config keys and module lines leave the container.
# Server.log is trusted only in truncate mode and after this process started.
PROBE = r'''
import collections,datetime,json,re,sys
from pathlib import Path
config = Path(sys.argv[1])
started = datetime.datetime.fromisoformat(sys.argv[2].replace('Z','+00:00')).timestamp()
values = {}
if config.is_file():
    for line in config.read_text(errors='replace').splitlines():
        match = re.match(r'^\s*([^#;=\s]+)\s*=\s*(.*?)\s*$',line)
        if match: values[match[1]] = match[2]
keys = ('ForeverAdvancement.Enable','ForeverEncyclopedia.Enable','Logger.scripts')
settings = {k:values.get(k) for k in keys}
base = values.get('LogsDir','').strip('"')
path = Path(base) / 'Server.log' if base else Path('Server.log')
if not path.is_absolute():
    try: cwd = Path('/proc/1/cwd').resolve()
    except OSError: cwd = Path.cwd()
    path = cwd / path
appender = [v.strip() for v in values.get('Appender.Server','').split(',')]
status = 'missing'; lines = collections.deque(maxlen=256)
if len(appender) >= 5 and appender[3] == 'Server.log' and appender[4] == 'w':
    if path.is_file():
        if path.stat().st_mtime < started - 1: status = 'older-than-current-process'
        else:
            status = 'current-process-file'
            with path.open(errors='replace') as stream:
                for line in stream:
                    if re.search(r'Forever(?:Advancement|Encyclopedia|Scaling|DungeonFinder)',line): lines.append(line.rstrip()[:1024])
else: status = 'not-truncate-mode'
print(json.dumps(dict(settings=settings,serverLogStatus=status,lines=list(lines))))
'''


def redact(state, text):
    for value in sorted((str(v) for v in state.get('credentials', {}).values() if v), key=len, reverse=True):
        text = text.replace(value, '[REDACTED]')
    text = re.sub(r'(?i)((?:password|passwd|secret|token)\s*[=:]\s*)[^\s,;]+', r'\1[REDACTED]', text)
    return re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)


def snapshot(clean, state, item, *, allow_stopped=False):
    if not item or (not item['State']['Running'] and not allow_stopped):
        raise RuntimeError('The current worldserver is no longer running')
    result = dict(container=item['Id'], startedAt=item['State']['StartedAt'],
                  image=item['Config'].get('Image'), running=item['State']['Running'],
                  exitCode=item['State'].get('ExitCode'), settings={}, serverLogStatus='unavailable', lines=[])
    console = clean.run(['docker','logs','--since',item['State']['StartedAt'],'--tail','5000',item['Id']],
                        capture=True, merge_log_streams=True)
    result['lines'] = [line[:1024] for line in console.splitlines()
                       if re.search(r'Forever(?:Advancement|Encyclopedia|Scaling|DungeonFinder)',line)][-256:]
    try:
        if not item['State']['Running']: raise RuntimeError('Cannot exec a stopped container')
        raw = clean.compose(state,'exec','-T','worldserver','python3','-c',PROBE,
                            '/opt/trinitycore/etc/worldserver.conf',item['State']['StartedAt'],capture=True)
        file_report = json.loads(raw)
        result.update(settings=file_report['settings'],serverLogStatus=file_report['serverLogStatus'])
        result['lines'] = list(dict.fromkeys(result['lines'] + file_report['lines']))[-256:]
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        result['fileProbeError'] = type(error).__name__
    result['lines'] = [redact(state, line) for line in result['lines']]
    return result


def wait(clean, state, patterns, timeout=180):
    deadline = time.monotonic() + timeout
    clean.wait_world(state, timeout)
    first = None; report = None
    while True:
        item = clean.container(state,'worldserver')
        if not item or not item['State']['Running']: raise RuntimeError('Worldserver stopped during module readiness check')
        identity = (item['Id'],item['State']['StartedAt'])
        if first is None: first = identity
        if identity != first: raise RuntimeError('Worldserver restarted during module readiness check')
        report = snapshot(clean,state,item)
        text = '\n'.join(report['lines'])
        # A read must never combine evidence from two different processes.
        after = clean.container(state,'worldserver')
        if not after or not after['State']['Running'] or (after['Id'],after['State']['StartedAt']) != first:
            raise RuntimeError('Worldserver changed during startup evidence collection')
        missing = [p for p in patterns if p not in text]
        if not missing: return report
        failure = [line for line in report['lines'] if 'schema missing' in line or 'script registration missing' in line]
        disabled = [k for k,v in report['settings'].items() if k.endswith('.Enable') and v is not None and v.strip('"').lower() in ('0','false','no','off')]
        if failure or disabled or time.monotonic() >= deadline:
            detail = '\n'.join(failure or report['lines'][-16:])
            raise RuntimeError('Module startup is incomplete. Missing: ' + '; '.join(missing)
                               + ('; disabled: ' + ','.join(disabled) if disabled else '')
                               + '; file log: ' + report['serverLogStatus'] + ('\n' + detail if detail else ''))
        time.sleep(min(2,max(0,deadline-time.monotonic())))
