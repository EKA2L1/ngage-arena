import gzip
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import yaml

from arena.setup import configure, enable_arena, restore


class SetupTests(unittest.TestCase):
    def test_setup_is_idempotent_and_restore_preserves_original_files(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            config = data / 'config.yml'
            original = b'# original formatting\nvolume: 37\nhosts:\n  Example.Org: 192.0.2.1\n  ARENA.CNG.N-GAGE.COM.: 192.0.2.2\n'
            config.write_bytes(original)
            game = data / 'drives/e/system/apps/tombraider/GSBAPP.APP'
            game.parent.mkdir(parents=True)
            game.write_bytes(b'retail launcher')
            commdb = data / 'drives/c/system/data/Cdbv2.dat'
            commdb.parent.mkdir(parents=True)
            commdb.write_bytes(b'original database')
            with patch('arena.setup.enable_arena',lambda value:b'enabled launcher'):
                backup = configure(data,'127.0.0.1')
                self.assertIsNone(configure(data,'127.0.0.1'))
            settings = yaml.safe_load(config.read_text())
            self.assertEqual(settings['volume'],37)
            self.assertEqual(settings['hosts'],{'Example.Org':'192.0.2.1','arena.cng.n-gage.com':'127.0.0.1','discovery.cng.n-gage.com':'127.0.0.1'})
            commdb.write_bytes(b'modified by billing module')
            restore(backup)
            self.assertEqual(config.read_bytes(),original)
            self.assertEqual(game.read_bytes(),b'retail launcher')
            self.assertEqual(commdb.read_bytes(),b'original database')
            self.assertFalse((data/'drives/e/game.id').exists())
            self.assertFalse((data/'drives/c/system/libs/abtesrv.dll').exists())

    def test_unknown_launcher_is_not_patched(self):
        data = b'wrapper' + gzip.compress(b'unknown executable') + struct.pack('<I',7)
        with self.assertRaisesRegex(ValueError,'Unknown'):
            enable_arena(data)

    def test_restore_rejects_paths_outside_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory)/'arena-backups/one'
            backup.mkdir(parents=True)
            (backup/'manifest.json').write_text(json.dumps({'files':{'../outside':False}}))
            with self.assertRaisesRegex(ValueError,'Invalid backup path'):
                restore(backup)
