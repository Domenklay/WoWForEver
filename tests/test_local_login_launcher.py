from pathlib import Path
import re
import unittest

ROOT = Path(__file__).parents[1]


class LocalLauncherSourceTests(unittest.TestCase):
    def test_client_key_profile_matches_existing_rust_launcher(self):
        rust = (ROOT / 'app/src-tauri/src/patcher/mod.rs').read_text()
        csharp = (ROOT / 'tools/local-login/LocalKey.cs').read_text()
        source_keys = re.findall(r'"([0-9A-F]{64})"', rust.split('const EXPECTED_FLAGS')[0])
        helper_keys = re.findall(r'"([0-9A-F]{64})"', csharp.split('static readonly byte[][]')[0])
        self.assertEqual(len(source_keys), 12)
        self.assertEqual(helper_keys, source_keys)

    def test_default_server_key_matches_existing_launcher(self):
        config = (ROOT / 'app/src-tauri/src/config.rs').read_text()
        ps = (ROOT / 'tools/local-login/Start-LocalForever.ps1').read_text()
        public_key = re.search(r'STOCK_PUBLIC_KEY: &str = "([0-9A-F]{64})"', config)[1]
        self.assertIn(public_key, ps)


if __name__ == '__main__':
    unittest.main()
