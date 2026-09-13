import json
from pathlib import Path
import tempfile
import unittest

import yaml

from arena.ashen_setup import configure, HOSTS
from arena.setup import restore


class AshenSetupTests(unittest.TestCase):
    def test_configuration_is_reversible_and_preserves_other_games(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            game = data / 'drives/e/system/apps/6r21/6R21.APP'
            game.parent.mkdir(parents=True)
            game.write_bytes(b'original game executable')
            snap = data / 'drives/e/system/libs/SC_LIB.DLL'
            snap.parent.mkdir(parents=True)
            snap.write_bytes(b'original shared SNAP library')
            config = data / 'config.yml'
            original = b'# preserve on restore\nvolume: 37\nhosts:\n  arena.cng.n-gage.com: 192.0.2.3\n  ARENA.N-GAGE.COM.: 192.0.2.4\n'
            config.write_bytes(original)
            backup = configure(data, ' Private.Example. ')
            self.assertIsNone(configure(data, 'private.example'))
            settings = yaml.safe_load(config.read_text())
            self.assertEqual(settings['volume'], 37)
            self.assertEqual(settings['hosts'], {
                'arena.cng.n-gage.com': '192.0.2.3',
                'arena.n-gage.com': 'private.example',
                'im01.ashen.torus.sf.yav4.com': 'private.example',
            })
            self.assertEqual(json.loads((backup / 'manifest.json').read_text())['files'], {'config.yml': True})
            self.assertEqual(game.read_bytes(), b'original game executable')
            self.assertEqual(snap.read_bytes(), b'original shared SNAP library')
            restore(backup)
            self.assertEqual(config.read_bytes(), original)

    def test_configuration_does_not_require_an_installed_game(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            config = data / 'config.yml'
            config.write_text('volume: 40\n')
            configure(data, '2001:db8::1')
            self.assertEqual(yaml.safe_load(config.read_text())['hosts'], dict.fromkeys(HOSTS, '2001:db8::1'))
            self.assertFalse((data / 'drives').exists())

    def test_invalid_address_leaves_configuration_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            config = data / 'config.yml'
            config.write_text('volume: 40\n')
            with self.assertRaises(ValueError):
                configure(data, 'https://private.example:8192')
            self.assertEqual(config.read_text(), 'volume: 40\n')
            self.assertFalse((data / 'arena-backups').exists())

    def test_invalid_settings_leave_configuration_untouched(self):
        for original in ['[]\n', 'hosts: []\n']:
            with self.subTest(config=original), tempfile.TemporaryDirectory() as directory:
                data = Path(directory)
                config = data / 'config.yml'
                config.write_text(original)
                with self.assertRaises(ValueError):
                    configure(data)
                self.assertEqual(config.read_text(), original)
                self.assertFalse((data / 'arena-backups').exists())
