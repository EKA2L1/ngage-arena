import tempfile
import unittest
import shutil
import subprocess
import yaml
from pathlib import Path

from arena.ngage2_setup import configure
from arena.setup import restore


class Nage2SetupTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('openssl'), 'openssl is needed for a temporary public certificate')
    def test_host_tls_setup_copies_only_public_trust_and_can_be_restored(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)
            config = data/'config.yml'
            config.write_text('hosts: {}\n')
            naf = data/'drives/c/private/2000106c/config.xml'
            naf.parent.mkdir(parents=True)
            naf.write_text('<nafSetting name="WebServicesHostname" value="new.arena.n-gage.com"/>')
            cert, key = data/'public.pem', data/'private.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-noenc',
                            '-keyout', str(key), '-out', str(cert), '-days', '1', '-subj', '/CN=arena.test'],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            original_config, original_naf = config.read_bytes(), naf.read_bytes()
            with self.assertRaises(ValueError):
                configure(data, [], tls_ca=key)
            self.assertEqual(config.read_bytes(), original_config)
            self.assertFalse((data/'arena-backups').exists())
            backup = configure(data, [], tls_ca=cert)
            settings = yaml.safe_load(config.read_text())
            self.assertIs(settings['host-tls'], True)
            copied = data/settings['tls-ca-file']
            self.assertEqual(copied.read_bytes(), cert.read_bytes())
            self.assertIsNone(configure(data, [], tls_ca=cert))
            restore(backup)
            self.assertEqual(config.read_bytes(), original_config)
            self.assertEqual(naf.read_bytes(), original_naf)
            self.assertFalse(copied.exists())

    def test_configuration_is_idempotent_and_restore_preserves_originals(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)
            config = data/'config.yml'
            original = b'hosts: {Existing.Example.: 127.0.0.2}\ncpu: dynarmic\n'
            config.write_bytes(original)
            naf = data/'drives/c/private/2000106c/config.xml'
            naf.parent.mkdir(parents=True)
            xml = b'<nafSetting name="Version" value="2.50"allowOverride="true"/>\r\n<nafSetting name="WebServicesHostname" value="new.arena.n-gage.com"/>\r\n'
            naf.write_bytes(xml)
            backup = configure(data, ['2000afbc'])
            self.assertIn(b'new.arena.n-gage.com:8194', naf.read_bytes())
            configured = config.read_bytes()
            self.assertIsNone(configure(data, ['2000afbc']))
            self.assertEqual(config.read_bytes(), configured)
            restore(backup)
            self.assertEqual(config.read_bytes(), original)
            self.assertEqual(naf.read_bytes(), xml)

    def test_reset_only_removes_selected_rom_login_and_can_be_undone(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)
            (data/'config.yml').write_text('hosts: {}\n')
            naf = data/'drives/c/private/2000106c/config.xml'
            naf.parent.mkdir(parents=True)
            naf.write_text('<nafSetting name="WebServicesHostname" value="new.arena.n-gage.com"/>')
            files = [data/'drives/c/private/10202be9/persists'/rom/name
                     for rom, name in [('rm-409', '20001077.cre'), ('rm-707', '20001077.cre'),
                                       ('rm-409', '2000afbc.cre')]]
            for path in files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'preserved local settings')
            backup = configure(data, [], reset_login='rm-409')
            self.assertFalse(files[0].exists())
            self.assertTrue(all(path.exists() for path in files[1:]))
            restore(backup)
            self.assertTrue(all(path.read_bytes() == b'preserved local settings' for path in files))
            with self.assertRaises(ValueError):
                configure(data, [], reset_login='../rm-409')
