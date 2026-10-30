import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'scripts/check-subclass-ready.py'
spec = importlib.util.spec_from_file_location('freepick_readiness', HELPER)
readiness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(readiness)

BASE = 'ForeverSubclass ready: 50 supported spell ranks\nTrinityCore test (worldserver-daemon) ready...\n'
FREEPICK = 'ForeverSubclass Freepick ability prototype enabled: 8 AE\n'
AVAILABLE = 'Freepick custom Mana Shield: available (native aura 1463 and both script bindings required)\n'
UNAVAILABLE = 'Freepick custom Mana Shield: unavailable (native aura 1463 and both script bindings required)\n'

DOCKER = '''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
a=sys.argv[1:]
with open(os.environ['MOCK_CALLS'],'a') as f:f.write(json.dumps(a)+'\\n')
mode=os.environ.get('MOCK_MODE','freepick')
if a[:2]==['compose','ps']:
 print('test-world' if '-q' in a else 'worldserver\\nmysql\\nbnetserver\\nweb')
elif a and a[0]=='inspect':
 field=a[a.index('--format')+1]
 if 'StartedAt' in field:print('2026-10-30T00:00:00Z')
 elif 'Labels' in field:print('0.4.2-freepick-custom.1')
 else:print('sha256:test')
elif a[:2]==['compose','logs']:
 print(Path(os.environ['MOCK_LOGS']).read_text())
elif a[:2]==['compose','exec']:
 q=a[-1]
 if 'information_schema.tables' in q:
  missing=os.environ.get('MOCK_MISSING_TABLE','')
  print(0 if missing and missing in q else 1)
 elif 'spell_id=-1463' in q:print(os.environ.get('MOCK_SHIELD_BINDINGS','2'))
 elif 'spell_script_names' in q:print(20)
 elif 'chr_classes_x_power_types' in q or 'hotfix_data' in q:print(2 if mode=='legacy' else 0)
 else:raise SystemExit('unexpected SQL request')
else:raise SystemExit('unexpected docker request')
'''


class FreepickRuntimeTests(unittest.TestCase):
    def test_ready_requires_world_module_mode_and_custom_shield(self):
        self.assertEqual(readiness.assess(AVAILABLE + FREEPICK + BASE, 'freepick')[0], 0)
        self.assertEqual(readiness.assess(AVAILABLE + FREEPICK, 'freepick')[0], 1)
        self.assertEqual(readiness.assess(AVAILABLE + FREEPICK + 'worldserver-daemon ready', 'freepick')[0], 1)
        self.assertEqual(readiness.assess(AVAILABLE + FREEPICK + BASE.replace('ready...', 'not ready'), 'freepick')[0], 1)

    def test_missing_or_unavailable_shield_is_not_a_successful_install(self):
        for marker in ('', UNAVAILABLE, AVAILABLE + UNAVAILABLE):
            with self.subTest(marker=marker):
                self.assertEqual(readiness.assess(marker + FREEPICK + BASE, 'freepick')[0], 2)
        self.assertEqual(readiness.assess(UNAVAILABLE + AVAILABLE + FREEPICK + BASE, 'freepick')[0], 0)

    def test_mode_override_is_rejected_in_both_directions(self):
        self.assertEqual(readiness.assess(BASE, 'freepick')[0], 2)
        self.assertEqual(readiness.assess(AVAILABLE + FREEPICK + BASE, 'legacy')[0], 2)
        self.assertEqual(readiness.assess(BASE, 'legacy')[0], 0)

    def test_cli_preserves_status_and_does_not_echo_raw_logs(self):
        result = subprocess.run([sys.executable, str(HELPER), '--mode', 'freepick'],
                                input='private fixture data\n' + FREEPICK + BASE,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('readiness was not reported', result.stdout)
        self.assertNotIn('private fixture data', result.stdout + result.stderr)

    def doctor(self, logs, mode='freepick', **settings):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / 'scripts'
            scripts.mkdir()
            for name in ('subclass-doctor.sh', 'check-subclass-ready.py'):
                (scripts / name).write_bytes((ROOT / 'scripts' / name).read_bytes())
            (root / '.env').write_text('SUBCLASS_ENABLED=1\nSUBCLASS_FREEPICK=' + ('1' if mode == 'freepick' else '0') + '\n')
            executable = root / 'docker'
            executable.write_text(DOCKER)
            executable.chmod(0o755)
            log_file = root / 'logs'
            log_file.write_text(logs)
            calls = root / 'calls'
            environment = os.environ.copy()
            environment.update(PATH=str(root) + os.pathsep + environment['PATH'],
                               MOCK_MODE=mode, MOCK_LOGS=str(log_file), MOCK_CALLS=str(calls), **settings)
            result = subprocess.run(['bash', str(scripts / 'subclass-doctor.sh')],
                                    env=environment, text=True, capture_output=True)
            return result, [json.loads(line) for line in calls.read_text().splitlines()]

    def test_doctor_accepts_freepick_without_the_removed_mage_experiment(self):
        result, calls = self.doctor(AVAILABLE + FREEPICK + BASE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('RESULT: Freepick, custom Mana Shield', result.stdout)
        self.assertIn('experimental Mage native-power rows are absent', result.stdout)
        self.assertTrue(any('forever_character_freepick_resources' in call[-1] for call in calls))
        log_calls = [call for call in calls if call[:2] == ['compose', 'logs']]
        self.assertTrue(log_calls)
        self.assertTrue(all('--since' in call and '2026-10-30T00:00:00Z' in call for call in log_calls))

    def test_doctor_rejects_missing_shield_binding_even_if_logs_report_ready(self):
        result, _ = self.doctor(AVAILABLE + FREEPICK + BASE, MOCK_SHIELD_BINDINGS='1')
        self.assertEqual(result.returncode, 1)
        self.assertIn('script bindings: 1 (expected 2)', result.stdout)

    def test_doctor_rejects_missing_freepick_schema(self):
        result, _ = self.doctor(AVAILABLE + FREEPICK + BASE, MOCK_MISSING_TABLE='forever_character_freepick_resources')
        self.assertEqual(result.returncode, 1)
        self.assertIn('forever_character_freepick_resources missing', result.stdout)

    def test_doctor_rejects_runtime_unavailability(self):
        result, _ = self.doctor(UNAVAILABLE + FREEPICK + BASE)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Mana Shield is unavailable', result.stdout)

    def test_doctor_preserves_legacy_native_power_checks(self):
        result, _ = self.doctor(BASE, mode='legacy')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Mage native Rage/Energy DB2 rows = 2', result.stdout)
        self.assertIn('RESULT: staged Mage', result.stdout)
