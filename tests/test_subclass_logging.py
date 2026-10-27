import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'subclass_logging', Path(__file__).parents[1]/'scripts/subclass-log-config.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class SubclassLoggingTests(unittest.TestCase):
    def test_enable_and_restore_preserve_unrelated_and_later_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);config = root/'worldserver.conf';backup = root/'backup'
            config.write_text('#Logger.scripts=5,Console\nRate.XP.Kill=2\nLogger.scripts = 5,Console\n')
            helper.enable(config, backup)
            self.assertIn('Logger.scripts = 3,Console Server\n', config.read_text())
            self.assertNotIn('\nLogger.scripts = 5,Console', config.read_text())
            with config.open('a') as stream:
                stream.write('Rate.Drop.Money=3\n')
            helper.restore(backup)
            self.assertIn('Logger.scripts = 5,Console\n', config.read_text())
            self.assertIn('Rate.Drop.Money=3\n', config.read_text())
            self.assertIn('#Logger.scripts=5,Console\nRate.XP.Kill=2\n', config.read_text())

    def test_missing_override_is_removed_on_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);config = root/'overrides/worldserver.conf';backup = root/'backup'
            helper.enable(config, backup)
            self.assertTrue(config.exists())
            helper.restore(backup)
            self.assertFalse(config.exists())

    def test_existing_backup_refused_and_new_unrelated_override_kept(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);config = root/'worldserver.conf';backup = root/'backup'
            helper.enable(config, backup)
            with self.assertRaises(FileExistsError):
                helper.enable(config, backup)
            with config.open('a') as stream:
                stream.write('Rate.XP.Kill=2\n')
            helper.restore(backup)
            self.assertEqual(config.read_text(), 'Rate.XP.Kill=2\n')
