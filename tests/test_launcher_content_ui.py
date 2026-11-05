from pathlib import Path
import shutil
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
class LauncherContentUiTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_package_flow_uses_selected_client_and_blocks_experimental_content(self):
        subprocess.run(['node',str(ROOT/'tests/fixtures/launcher-content-ui.js'),str(ROOT)],check=True,capture_output=True,text=True)
