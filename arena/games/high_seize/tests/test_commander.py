import struct
import unittest

from arena.games.high_seize.commander import Commander
from arena.games.high_seize.tests.fixtures import commander_wire


class CommanderTests(unittest.TestCase):
    def test_native_header_and_variable_strings(self):
        for control in (-1, 0, 1, 2, 3):
            for name, description in ((b'A', b''), (b'Long commander name', b'5200'),
                                      (b'Andr\xe9', b'Localized description')):
                wire = commander_wire(name, description, control)
                result = Commander.decode(wire)
                self.assertEqual(len(wire), 1001 + len(name) + len(description))
                self.assertEqual(struct.unpack_from('<i', result.metadata)[0], control)
                self.assertEqual((result.name, result.description), (name, description))
                self.assertEqual((result.nationality, result.player), (4, 1))
                self.assertEqual(result.attack, (0,) * 21)
                self.assertEqual(result.defense, (0,) * 21)

    def test_native_arrays_have_distinct_order_and_signed_values(self):
        wire = bytearray(commander_wire(b'A', b''))
        wire[42:79] = bytes(range(37))
        perks = bytes(range(30))
        wire[79:109] = perks
        position = 124
        for row in range(2):
            for index in range(21):
                struct.pack_into('<iI', wire, position, row * 50 + index - 10, 8)
                position += 8
        for row in range(6):
            struct.pack_into('<21i', wire, position, *(row * 100 + i - 10 for i in range(21)))
            position += 84
        wire[position:position + 30] = perks
        struct.pack_into('<ii', wire, position + 30, -15, 2)
        result = Commander.decode(wire)
        self.assertEqual(result.skills, bytes(range(37)))
        self.assertEqual(result.perks, perks)
        self.assertEqual(result.attack, tuple(range(-10, 11)))
        self.assertEqual(result.defense, tuple(range(40, 61)))
        for row, values in enumerate((result.attack_range, result.movement, result.vision,
                                      result.rations, result.ammunition, result.cost)):
            self.assertEqual(values, tuple(range(row * 100 - 10, row * 100 + 11)))
        self.assertEqual((result.income, result.player), (-15, 2))

    def test_truncation_trailing_bytes_and_string_bounds(self):
        original = commander_wire()
        cases = [original[:size] for size in (0, 5, 999, 1001, len(original) - 1)]
        cases += [original + b'\0', b'WRONG' + original[5:],
                  commander_wire(b'a\0b'), original + bytes(4096)]
        for offset, value in ((113, 0xffffffff), (113, 500), (113, 0)):
            wire = bytearray(original)
            struct.pack_into('<I', wire, offset, value)
            cases.append(wire)
        wire = bytearray(original)
        wire[117 + len(b'Captain')] = 1
        cases.append(wire)
        for index, wire in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(ValueError):
                Commander.decode(wire)

    def test_fixed_precision_and_repeated_perks_must_be_consistent(self):
        wire = bytearray(commander_wire(b'A', b''))
        struct.pack_into('<I', wire, 128, 7)
        with self.assertRaises(ValueError):
            Commander.decode(wire)
        wire = bytearray(commander_wire())
        wire[-38] = 1
        with self.assertRaises(ValueError):
            Commander.decode(wire)
