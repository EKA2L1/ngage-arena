import unittest

from arena.hosts import host_target


class HostTargetTests(unittest.TestCase):
    def test_addresses_and_domains(self):
        for value, expected in [(' Private.Example. ', 'private.example'), ('localhost', 'localhost'),
                                ('127.0.0.1', '127.0.0.1'), ('2001:DB8::1', '2001:db8::1')]:
            with self.subTest(value=value):
                self.assertEqual(host_target(value), expected)

    def test_invalid_targets(self):
        for value in ['', 'https://private.example', 'private.example:8192', 'private..example',
                      '[::1]', '1.2.3.999', 'a' * 64 + '.example', 'a' * 254]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                host_target(value)
