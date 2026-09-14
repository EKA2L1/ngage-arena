"""Owned unit attributes and the unmodified two-unit combat calculation.

World legality, commanders, abilities and map effects must be resolved separately.
This module is not yet used to adjudicate live matches.
"""
from dataclasses import dataclass
import re
import struct


_TOKEN = re.compile(r'\s+|#[^\r\n]*|"[^"\r\n]*"|[{}|]|[^\s{}|"#]+')
_DECIMAL = re.compile(r'-?\d+(?:\.\d+)?\Z', re.ASCII)
UNIT_COUNT = 21
INDIRECT_MASK = 0x61c0
UNIT_NAMES = (
    'Swordsman', 'Pistoleer', 'Musketeer', 'Scout', 'Cavalry-Light', 'Cavalry-Heavy',
    'Mortar', 'Cannon', 'Scorch-Cannon', 'Wagon', 'Rowing-boat', 'Sloop',
    'Transport-Heavy', 'Galley', 'H.I.D.S.U.', 'Mothership', 'Man-o-war',
    'Cannon-Tower', 'Rowing-boat-Swordsman', 'Rowing-boat-Pistoleer',
    'Rowing-boat-Musketeer',
)


def parse_attributes(data):
    """Parse named blocks and pipe-delimited lists, retaining scalar spelling."""
    if len(data) > 1024 * 1024:
        raise ValueError('Attribute file is too large')
    try:
        text = data.decode('ascii')
    except UnicodeDecodeError as error:
        raise ValueError('Attributes must be ASCII') from error
    tokens, end = [], 0
    for match in _TOKEN.finditer(text):
        if match.start() != end:
            raise ValueError('Invalid attribute token')
        token = match.group()
        if not token.isspace() and not token.startswith('#'):
            tokens.append(token)
        end = match.end()
    if end != len(text):
        raise ValueError('Invalid attribute token')
    index = 0

    def take():
        nonlocal index
        if index == len(tokens):
            raise ValueError('Truncated attributes')
        token = tokens[index]
        index += 1
        return token

    def scalar(token):
        if token in ('{', '}', '|'):
            raise ValueError('Expected an attribute name or value')
        return token[1:-1] if token.startswith('"') else token

    def block(depth, nested):
        if depth > 8:
            raise ValueError('Attributes are nested too deeply')
        result = {}
        while index < len(tokens):
            token = take()
            if token == '}':
                if nested:
                    return result
                raise ValueError('Unexpected closing brace')
            name = scalar(token)
            if name in result:
                raise ValueError(f'Duplicate attribute: {name}')
            token = take()
            if token != '{':
                value = scalar(token)
            elif index < len(tokens) and tokens[index] == '|':
                take()
                values = []
                while True:
                    token = take()
                    if token == '}':
                        break
                    values.append(scalar(token))
                    if take() != '|':
                        raise ValueError('Expected list delimiter')
                value = tuple(values)
            else:
                value = block(depth + 1, True)
            result[name] = value
        if nested:
            raise ValueError('Unclosed attribute block')
        return result

    return block(0, False)


def _f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def fixed_decimal(token):
    """Return the native decimal reader's signed Q8 numerator."""
    if not isinstance(token, str) or not _DECIMAL.fullmatch(token) or len(token) > 32:
        raise ValueError('Invalid fixed-point decimal')
    negative = token.startswith('-')
    integer, _, digits = token.lstrip('-').partition('.')
    if int(integer) > 32767:
        raise ValueError('Fixed-point decimal is out of range')
    fraction, place = 0.0, _f32(0.1)
    # The native reader accumulates decimal digits with single-precision rounding.
    for digit in digits:
        fraction = _f32(fraction + _f32(int(digit) * place))
        place = _f32(place * _f32(0.1))
    value = _f32(_f32(int(integer)) + fraction)
    return int(_f32((-value if negative else value) * 256.0))


@dataclass(frozen=True)
class UnitAttributes:
    type_id: int
    name: str
    unit_class: str
    cost: int
    vision: int
    movement: int
    rations: int
    ammunition: int
    ration_consumption: int
    ammunition_consumption: int
    min_range: int
    max_range: int
    blast_radius: int
    loading_capacity: int
    movement_mask: int
    attack_mask: int
    supply_mask: int
    production_mask: int
    loading_mask: int
    capture_mask: int
    counterattack: bool
    attack: tuple
    defense: tuple


def read_units(data):
    attributes = parse_attributes(data)
    attack = attributes.pop('AttackValues', None)
    defense = attributes.pop('DefenseValues', None)
    if (len(attributes) != UNIT_COUNT or not isinstance(attack, dict)
            or not isinstance(defense, dict)):
        raise ValueError('Expected 21 unit definitions and both combat tables')
    units = {}

    def number(fields, key, maximum=65535):
        value = fields.get(key)
        if not isinstance(value, str):
            raise ValueError(f'Missing numeric unit attribute: {key}')
        try:
            result = int(value, 16 if value.startswith('0x') else 10)
        except ValueError as error:
            raise ValueError(f'Invalid numeric unit attribute: {key}') from error
        if not 0 <= result <= maximum:
            raise ValueError(f'Unit attribute is out of range: {key}')
        return result

    names = set()
    for fields in attributes.values():
        if not isinstance(fields, dict):
            raise ValueError('Expected a unit attribute block')
        name = fields.get('internalName')
        unit_class = fields.get('class')
        if (name not in UNIT_NAMES or not isinstance(unit_class, str)
                or name in names):
            raise ValueError('Invalid or duplicate unit name')
        names.add(name)
        # The native name registry supplies combat IDs; the editor identification is unused.
        type_id = UNIT_NAMES.index(name) + 1

        def row(table):
            values = table.get(name)
            if not isinstance(values, tuple) or len(values) != UNIT_COUNT:
                raise ValueError(f'Expected 21 combat values for {name}')
            values = tuple(fixed_decimal(value) for value in values)
            if any(value < 0 or value > 256 for value in values):
                raise ValueError('Base combat coefficient is out of range')
            return values

        counterattack = fields.get('isAbleToCounterAttack')
        if counterattack not in ('true', 'false'):
            raise ValueError('Invalid counterattack flag')
        units[type_id] = UnitAttributes(
            type_id=type_id, name=name, unit_class=unit_class,
            cost=number(fields, 'cost'), vision=number(fields, 'vision'),
            movement=number(fields, 'maxMovementPoints'), rations=number(fields, 'maxRations'),
            ammunition=number(fields, 'maxAmmunition'),
            ration_consumption=number(fields, 'rationConsumeRate'),
            ammunition_consumption=number(fields, 'ammunitionConsumeRate'),
            min_range=number(fields, 'minAttackRange'), max_range=number(fields, 'maxAttackRange'),
            blast_radius=number(fields, 'attackBlastRadius'),
            loading_capacity=number(fields, 'loadingCapacity'),
            movement_mask=number(fields, 'movementMask', 0xffffffff),
            attack_mask=number(fields, 'attackCapability', 0xffffffff),
            supply_mask=number(fields, 'supplyCapability', 0xffffffff),
            production_mask=number(fields, 'productionCapability', 0xffffffff),
            loading_mask=number(fields, 'loadingCapability', 0xffffffff),
            capture_mask=number(fields, 'captureCapability', 0xffffffff),
            counterattack=counterattack == 'true', attack=row(attack), defense=row(defense))
    if set(attack) != names or set(defense) != names:
        raise ValueError('Combat tables contain unknown unit names')
    return tuple(units[index] for index in range(1, UNIT_COUNT + 1))


def strength(coefficient, hp, bonus=0):
    """Ceil a Q8 coefficient scaled by HP, plus an integer tile bonus."""
    return -(-(coefficient * hp + bonus * 256) // 256)


def damage(attack, defense):
    fraction = _f32(_f32(attack) / 100.0)
    return max(1, int(_f32(fraction * _f32(200 - defense))))


@dataclass(frozen=True)
class CombatUnit:
    attributes: UnitAttributes
    hp: int
    ammunition: int
    x: int
    y: int
    attack_bonus: int = 0
    defense_bonus: int = 0


@dataclass(frozen=True)
class Exchange:
    attacker_hp: int
    defender_hp: int
    attacker_ammunition: int
    defender_ammunition: int
    counterattack: bool
    attacker_lost_cost: int
    defender_lost_cost: int


def base_exchange(attacker, defender):
    """Calculate combat without commander/ability modifiers or world mutation.

    The caller must validate turn, ownership, initial attack range and action state.
    Native intermediate HP and ammunition may be negative after subtraction.
    """
    for unit in (attacker, defender):
        if not 1 <= unit.hp <= 100 or not 0 <= unit.ammunition <= 65535:
            raise ValueError('Invalid living unit state')
    a, d = attacker.attributes, defender.attributes
    if not a.attack_mask & (1 << (d.type_id - 1)) or not attacker.ammunition:
        return None

    def hit(source, target, hp):
        source_type, target_type = source.attributes, target.attributes
        bonus = 0 if INDIRECT_MASK & (1 << (source_type.type_id - 1)) else source.attack_bonus
        attack = strength(source_type.attack[target_type.type_id - 1], hp, bonus)
        defense = strength(target_type.defense[source_type.type_id - 1], target.hp,
                           target.defense_bonus)
        return damage(attack, defense)

    a_hp, d_hp = attacker.hp, defender.hp - hit(attacker, defender, attacker.hp)
    a_ammo = attacker.ammunition - a.ammunition_consumption
    d_ammo = defender.ammunition
    distance = abs(attacker.x - defender.x) + abs(attacker.y - defender.y)
    counter = (d_hp > 0 and d.min_range <= distance <= d.max_range
               and bool(d.attack_mask & (1 << (a.type_id - 1)))
               and d_ammo > 0 and d.counterattack)
    if counter:
        a_hp -= hit(defender, attacker, d_hp)
        d_ammo -= d.ammunition_consumption
    return Exchange(a_hp, d_hp, a_ammo, d_ammo, counter,
                    a.cost if a_hp <= 0 else 0, d.cost if d_hp <= 0 else 0)
