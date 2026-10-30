import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ManaShieldCoreTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('g++') and shutil.which('git'), 'g++ and git required')
    def test_native_mana_shield_can_prevent_double_payment_and_preserve_nested_hooks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'src/server/game/Spells/SpellScript.cpp'
            source.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / 'tests/fixtures/aura-script-hooks.cpp', source)
            subprocess.run(['git', 'apply', str(ROOT / 'docker/patches/0006-mana-shield-default-action.patch')],
                           cwd=root, check=True, capture_output=True)
            binary = root / 'check-hooks'
            subprocess.run(['g++', '-std=c++17', '-O2', str(source), '-o', str(binary)],
                           check=True, capture_output=True)
            subprocess.run([str(binary)], check=True, capture_output=True)
