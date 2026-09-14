from dataclasses import replace
import unittest

from arena.games.high_seize.rules import (CombatUnit, Exchange, UNIT_NAMES, base_exchange,
                                  damage, fixed_decimal, parse_attributes, read_units, strength)


def synthetic_attributes():
    fields = '''
    identification 13 class DIRECT_COMBAT_UNIT cost 10 vision 2
    maxMovementPoints 4 maxRations 12 maxAmmunition 8 rationConsumeRate 1
    ammunitionConsumeRate 1 minAttackRange 1 maxAttackRange 1 attackBlastRadius 0
    loadingCapacity 0 movementMask 0x319ec attackCapability 0x1fffff
    supplyCapability 0 productionCapability 0 loadingCapability 0 captureCapability 0
    isAbleToCounterAttack true
    '''
    blocks = [f'Unit{i} {{ internalName "{name}" {fields} }}'
              for i, name in reversed(list(enumerate(UNIT_NAMES)))]
    for table, coefficient in (('AttackValues', '0.45'), ('DefenseValues', '0.70')):
        values = '| ' + ' | '.join([coefficient] * 21) + ' |'
        rows = [f'"{name}" {{ {values} }}' for name in reversed(UNIT_NAMES)]
        blocks.append(table + ' { ' + ' '.join(rows) + ' }')
    return '\n'.join(blocks).encode()


class AttributeTests(unittest.TestCase):
    def test_nested_blocks_lists_comments_and_quoted_names(self):
        self.assertEqual(parse_attributes(b'''# ignored { | "
            outer { "a # name" "quoted value" raw 0x20
                    child { list { | 0.45 | -0.5 | } empty { | } } }
            flag true # tail
        '''), {'outer': {'a # name': 'quoted value', 'raw': '0x20',
                        'child': {'list': ('0.45', '-0.5'), 'empty': ()}}, 'flag': 'true'})

    def test_truncated_duplicate_and_malformed_attributes(self):
        for data in (b'a', b'a {', b'a { b 1', b'}', b'a 1 a 2', b'a { b 1 b 2 }',
                     b'a { | 1 2 | }', b'a { | 1 |', b'a { | | }', b'a "bad',
                     b'a "bad\nquote"', b'a { } |', b'\xff', b'x { ' * 10 + b'} ' * 10):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_attributes(data)

    def test_names_define_native_ids_despite_order_and_repeated_editor_ids(self):
        units = read_units(synthetic_attributes())
        self.assertEqual([unit.type_id for unit in units], list(range(1, 22)))
        self.assertEqual(units[10].name, 'Rowing-boat')
        self.assertEqual(units[13].name, 'Galley')
        self.assertEqual(units[18].name, 'Rowing-boat-Swordsman')
        self.assertEqual((units[0].cost, units[0].movement, units[0].ammunition,
                          units[0].movement_mask, units[0].counterattack),
                         (10, 4, 8, 0x319ec, True))
        self.assertEqual(units[0].attack, (115,) * 21)
        self.assertEqual(units[0].defense, (179,) * 21)

    def test_missing_unknown_duplicate_names_and_bad_table_width(self):
        data = synthetic_attributes()
        cases = [data.replace(b'AttackValues', b'OtherValues'),
                 data.replace(b'"Swordsman"', b'"Unknown"', 1),
                 data.replace(b'"Pistoleer"', b'"Swordsman"', 1),
                 data.replace(b'| 0.45 |', b'|', 1),
                 data.replace(b'| 0.45 |', b'| 0.45 | 0.45 |', 1),
                 data.replace(b'0.45', b'-0.45', 1),
                 data.replace(b'0.45', b'1.45', 1),
                 data.replace(b'0.45', b'NaN', 1),
                 data.replace(b'maxRations 12', b'maxRations -1', 1),
                 data.replace(b'cost 10', b'cost 65536', 1),
                 data.replace(b'cost 10', b'cost unknown', 1),
                 data.replace(b'cost 10', b'', 1),
                 data.replace(b'isAbleToCounterAttack true', b'isAbleToCounterAttack 1', 1)]
        for index, malformed in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(ValueError):
                read_units(malformed)

    def test_native_fixed_decimal_vectors(self):
        for token, value in (('0', 0), ('1', 256), ('0.45', 115), ('0.32', 81),
                             ('0.001', 0), ('0.535', 136), ('-0.7', -179),
                             ('0.00390625', 1), ('0.99609375', 255), ('1.999999', 511)):
            with self.subTest(token=token):
                self.assertEqual(fixed_decimal(token), value)
        for token in ('NaN', 'inf', '1e2', '', '.1', '1.', ' 1', '32768', '--1', '١'):
            with self.subTest(token=token), self.assertRaises(ValueError):
                fixed_decimal(token)

    def test_single_precision_damage_boundary_and_minimum(self):
        self.assertEqual(strength(81, 100, 5), 37)
        self.assertEqual(strength(115, 1), 1)
        self.assertEqual(strength(115, 100, 10), 55)
        self.assertEqual(damage(37, 55), 53)
        self.assertEqual(damage(29, 100), 29)
        self.assertEqual(damage(0, 0), 1)
        self.assertEqual(damage(50, 250), 1)


class ExchangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.units = read_units(synthetic_attributes())

    def unit(self, type_id=1, hp=100, ammunition=8, x=0, y=0, attack_bonus=5, defense_bonus=10):
        return CombatUnit(self.units[type_id - 1], hp, ammunition, x, y,
                          attack_bonus, defense_bonus)

    def test_counterattack_uses_remaining_defender_hp(self):
        result = base_exchange(self.unit(), self.unit(x=1))
        self.assertEqual(result, Exchange(73, 40, 7, 7, True, 0, 0))

    def test_recovered_sword_mortar_checkpoint(self):
        attack = list(self.units[0].attack)
        attack[6] = 81
        a = replace(self.unit(ammunition=1), attributes=replace(
            self.units[0], attack=tuple(attack), ammunition_consumption=0))
        d = replace(self.unit(7, ammunition=6, x=1), attributes=replace(
            self.units[6], defense=(115,) * 21, min_range=2, max_range=4))
        self.assertEqual(base_exchange(a, d), Exchange(100, 47, 1, 6, False, 0, 0))

    def test_counterattack_range_ammunition_mask_and_flag(self):
        a, d = self.unit(), self.unit(x=1)
        cases = [replace(d, ammunition=0), replace(d, x=2),
                 replace(d, attributes=replace(d.attributes, min_range=2, max_range=4)),
                 replace(d, attributes=replace(d.attributes, attack_mask=0)),
                 replace(d, attributes=replace(d.attributes, counterattack=False))]
        for defender in cases:
            with self.subTest(defender=defender):
                result = base_exchange(a, defender)
                self.assertEqual((result.attacker_hp, result.defender_hp, result.counterattack),
                                 (100, 40, False))

    def test_manhattan_counter_range_is_inclusive(self):
        d = replace(self.unit(x=1, y=2), attributes=replace(
            self.units[0], min_range=3, max_range=3))
        self.assertTrue(base_exchange(self.unit(), d).counterattack)
        self.assertFalse(base_exchange(self.unit(), replace(d, y=3)).counterattack)

    def test_indirect_attack_ignores_attack_tile_bonus(self):
        a = self.unit(7)
        d = self.unit(x=3)
        first = base_exchange(a, d)
        self.assertEqual(first, base_exchange(replace(a, attack_bonus=90), d))
        self.assertEqual(first.defender_hp, 46)

    def test_death_cost_and_no_counter_after_defender_dies(self):
        a, d = self.unit(), self.unit(hp=1, x=1)
        result = base_exchange(a, d)
        self.assertLess(result.defender_hp, 0)
        self.assertEqual((result.counterattack, result.attacker_lost_cost, result.defender_lost_cost),
                         (False, 0, 10))
        result = base_exchange(replace(a, hp=1), replace(d, hp=100))
        self.assertLessEqual(result.attacker_hp, 0)
        self.assertEqual((result.counterattack, result.attacker_lost_cost, result.defender_lost_cost),
                         (True, 10, 0))

    def test_rejected_attack_and_native_subtraction_without_clamping(self):
        a, d = self.unit(), self.unit(x=1)
        self.assertIsNone(base_exchange(replace(a, ammunition=0), d))
        self.assertIsNone(base_exchange(replace(a, attributes=replace(a.attributes, attack_mask=0)), d))
        a = replace(a, ammunition=1, attributes=replace(a.attributes, ammunition_consumption=3))
        self.assertEqual(base_exchange(a, d).attacker_ammunition, -2)

    def test_dead_or_invalid_unit_state_is_rejected(self):
        for fields in ({'hp': 0}, {'hp': 101}, {'ammunition': -1}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                base_exchange(replace(self.unit(), **fields), self.unit(x=1))
