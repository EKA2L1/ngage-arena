from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

import yaml

from arena.highseize_setup import configure
from arena.setup import restore

XML = '''<amr app_id="NgageFramework" version="2.01.054">
<servers WebServicesProtocol="http://" WebServicesHostname="arena.n-gage.com"
 JabberFQDN="im.hs.redlynx.sf.yav4.com" GameServerFQDN="bs01.hs.redlynx.sf.yav4.com"
 UpdateURL="http://arena.n-gage.com/n-gage/servlets/update"
 UploadURL="http://arena.n-gage.com/n-gage/servlets/upload?mode=native"
 DownloadURL="http://arena.n-gage.com/n-gage/servlets/download"/>
<module name="CAFMLLOGIN.DLL" checksum="unchanged"/>
</amr>'''


class HighSeizeSetupTests(unittest.TestCase):
    def prepare(self, root, xml=XML, settings='volume: 37\nhosts:\n  arena.cng.n-gage.com: 192.0.2.3\n'):
        data = Path(root)
        source = data / 'drives/e/System/Libs/Framework/ARENA.AMR'
        source.parent.mkdir(parents=True)
        source.write_text(xml)
        config = data / 'config.yml'
        config.write_text(settings)
        return data, source, config

    def test_reversible_configuration_preserves_binaries_and_database(self):
        with tempfile.TemporaryDirectory() as root:
            data, source, config = self.prepare(root)
            originals = {source: source.read_bytes(), config: config.read_bytes()}
            binary = source.parent / 'FMKERNEL.DLL'
            binary.write_bytes(b'original game library')
            database = data / 'drives/c/system/data/Cdbv2.dat'
            database.parent.mkdir(parents=True)
            database.write_bytes(b'original native access points')
            backup = configure(data, ' Private.Example. ')
            self.assertIsNone(configure(data, 'private.example'))
            servers = ET.fromstring(source.read_text()).find('servers')
            self.assertEqual(servers.get('WebServicesHostname'), 'arena.n-gage.com:8193')
            self.assertEqual(servers.get('UploadURL'), 'http://arena.n-gage.com:8193/n-gage/servlets/upload?mode=native')
            self.assertEqual(servers.get('JabberFQDN'), 'im.hs.redlynx.sf.yav4.com')
            self.assertIn('<module name="CAFMLLOGIN.DLL" checksum="unchanged"/>', source.read_text())
            settings = yaml.safe_load(config.read_text())
            self.assertEqual(settings['volume'], 37)
            self.assertEqual(settings['hosts']['arena.cng.n-gage.com'], '192.0.2.3')
            self.assertEqual(settings['hosts']['arena.n-gage.com'], 'private.example')
            self.assertEqual(binary.read_bytes(), b'original game library')
            self.assertEqual(database.read_bytes(), b'original native access points')
            restore(backup)
            for path, original in originals.items():
                self.assertEqual(path.read_bytes(), original)

    def test_default_http_port_and_ipv6_target(self):
        with tempfile.TemporaryDirectory() as root:
            data, source, config = self.prepare(root)
            configure(data, '2001:db8::1', 80)
            self.assertEqual(source.read_text(), XML)
            self.assertEqual(yaml.safe_load(config.read_text())['hosts']['arena.n-gage.com'], '2001:db8::1')
            self.assertIsNone(configure(data, '2001:db8::1', 80))

    def test_rejects_invalid_inputs_before_mutation(self):
        for xml, settings, host, port in [
            ('<amr', '{}', '127.0.0.1', 8193),
            (XML.replace('NgageFramework', 'AnotherApp'), '{}', '127.0.0.1', 8193),
            (XML, 'hosts: []', '127.0.0.1', 8193),
            (XML, '{}', 'https://private.example', 8193),
            (XML, '{}', '127.0.0.1', 0),
        ]:
            with self.subTest(xml=xml, settings=settings, host=host, port=port), tempfile.TemporaryDirectory() as root:
                data, source, config = self.prepare(root, xml, settings)
                with self.assertRaises(ValueError):
                    configure(data, host, port)
                self.assertEqual(source.read_text(), xml)
                self.assertEqual(config.read_text(), settings)
                self.assertFalse((data / 'arena-backups').exists())

    def test_missing_framework_does_not_modify_config(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root)
            config = data / 'config.yml'
            config.write_text('{}')
            with self.assertRaises(ValueError):
                configure(data)
            self.assertEqual(config.read_text(), '{}')
