from dataclasses import dataclass


@dataclass(frozen=True)
class Seat:
    name: str
    position: int


def freeze_roster(names: list) -> tuple[Seat, ...]:
    if not isinstance(names, list) or not names:
        raise ValueError('empty_roster')
    roster = []
    seen = set()
    for position, name in enumerate(names, start=1):
        if not isinstance(name, str) or not name or name != name.strip():
            raise ValueError('invalid_seat')
        if name in seen:
            raise ValueError('duplicate_seat')
        roster.append(Seat(name, position))
        seen.add(name)
    return tuple(roster)


def require_seat(roster: tuple[Seat, ...], name: str) -> Seat:
    for seat in roster:
        if seat.name == name:
            return seat
    raise ValueError('invalid_seat')
