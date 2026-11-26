from dataclasses import dataclass
import secrets

from exercise.questions import require_text


@dataclass(frozen=True)
class Seat:
    name: str
    position: int


@dataclass(frozen=True)
class Binding:
    device: str
    student: str
    authorization: str

    def to_dict(self):
        return {
            'device': self.device,
            'student': self.student,
            'authorization': self.authorization,
        }


def issue_authorization():
    return secrets.token_hex(24)


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


def freeze_bindings(entries: list) -> tuple[Binding, ...]:
    if not isinstance(entries, list) or not entries:
        raise ValueError('empty_roster')
    bindings = []
    seen_devices = set()
    seen_students = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('invalid_seat')
        device = require_text(entry.get('device'), 'invalid_device')
        student = require_text(entry.get('student'), 'invalid_seat')
        if device in seen_devices:
            raise ValueError('duplicate_device')
        if student in seen_students:
            raise ValueError('duplicate_seat')
        bindings.append(Binding(device, student, issue_authorization()))
        seen_devices.add(device)
        seen_students.add(student)
    return tuple(bindings)


def freeze_seats(seats):
    """Return (roster, bindings); bindings is None in named-list mode."""
    if not isinstance(seats, list) or not seats:
        raise ValueError('empty_roster')
    if all(isinstance(entry, str) for entry in seats):
        return freeze_roster(seats), None
    if all(isinstance(entry, dict) for entry in seats):
        bindings = freeze_bindings(seats)
        roster = tuple(Seat(binding.student, index)
                       for index, binding in enumerate(bindings, start=1))
        return roster, bindings
    raise ValueError('invalid_seat')


def require_seat(roster: tuple[Seat, ...], name: str) -> Seat:
    for seat in roster:
        if seat.name == name:
            return seat
    raise ValueError('invalid_seat')


def require_device(bindings: tuple[Binding, ...], device: str) -> Binding:
    require_text(device, 'invalid_device')
    for binding in bindings:
        if binding.device == device:
            return binding
    raise ValueError('invalid_device')


def binding_authorizations(bindings: tuple[Binding, ...] | None):
    if bindings is None:
        return None
    return {binding.authorization for binding in bindings}


def swap_pair(bindings: tuple[Binding, ...], device_a: str, device_b: str,
              new_authorizations: dict):
    """Validate a swap pair and build the two new bindings in device order."""
    if device_a == device_b:
        raise ValueError('same_device')
    positions = {binding.device: index for index, binding in enumerate(bindings)}
    first = require_device(bindings, device_a)
    second = require_device(bindings, device_b)
    old = tuple(sorted((first, second), key=lambda binding: positions[binding.device]))
    missing = [binding.device for binding in old
               if not isinstance(new_authorizations.get(binding.device), str)
               or not new_authorizations[binding.device]]
    if missing:
        raise ValueError('invalid_authorization')
    swapped = (
        Binding(old[0].device, old[1].student, new_authorizations[old[0].device]),
        Binding(old[1].device, old[0].student, new_authorizations[old[1].device]),
    )
    revoked = [binding.authorization for binding in old]
    return swapped, revoked


def apply_swap(bindings: tuple[Binding, ...], pair: tuple[Binding, ...]) -> tuple[Binding, ...]:
    replacements = {binding.device: binding for binding in pair}
    return tuple(replacements.get(binding.device, binding) for binding in bindings)
