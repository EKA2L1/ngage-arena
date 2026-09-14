"""High Seize's native CMM01 commander records."""
from dataclasses import dataclass
import struct


@dataclass(frozen=True)
class Commander:
    metadata: bytes
    skills: bytes
    perks: bytes
    nationality: int
    name: bytes
    description: bytes
    attack: tuple
    defense: tuple
    attack_range: tuple
    movement: tuple
    vision: tuple
    rations: tuple
    ammunition: tuple
    cost: tuple
    income: int
    player: int

    @classmethod
    def decode(cls, data):
        if not 1001 <= len(data) <= 4096 or data[:5] != b'CMM01':
            raise ValueError('Invalid commander record')
        offset = 5

        def take(size):
            nonlocal offset
            if size < 0 or offset + size > len(data):
                raise ValueError('Truncated commander record')
            result = data[offset:offset + size]
            offset += size
            return result

        def unpack(layout):
            return struct.unpack(layout, take(struct.calcsize(layout)))

        def string():
            size, = unpack('<I')
            value = take(size + 1)
            if value[-1] or b'\0' in value[:-1]:
                raise ValueError('Invalid commander string')
            return value[:-1]

        def fixed_vector():
            values = []
            for _ in range(21):
                numerator, fraction = unpack('<iI')
                if fraction != 8:
                    raise ValueError('Unsupported commander fixed-point precision')
                values.append(numerator)
            return tuple(values)

        metadata, skills, perks = take(37), take(37), take(30)
        nationality, = unpack('<i')
        name, description = string(), string()
        attack, defense = fixed_vector(), fixed_vector()
        vectors = [unpack('<21i') for _ in range(6)]
        if take(30) != perks:
            raise ValueError('Inconsistent commander perk arrays')
        income, player = unpack('<ii')
        if offset != len(data):
            raise ValueError('Trailing commander data')
        return cls(metadata, skills, perks, nationality, name, description,
                   attack, defense, *vectors, income, player)
