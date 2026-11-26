from dataclasses import dataclass, replace

from exercise.edition import Edition
from exercise.questions import Question, question_prompt
from lesson.seats import Binding, Seat, freeze_seats


class Conflict(Exception):
    pass


def require_round_id(round_id):
    if type(round_id) is not int or not 0 < round_id < 2**63:
        raise ValueError('invalid_round_id')
    return round_id


def require_request_id(request_id):
    if not isinstance(request_id, str) or not request_id or request_id != request_id.strip():
        raise ValueError('invalid_request_id')
    if len(request_id) > 120:
        raise ValueError('invalid_request_id')
    return request_id


@dataclass(frozen=True)
class Round:
    id: int | None
    edition_id: int
    question: Question
    roster: tuple[Seat, ...]
    played: bool = False
    closed: bool = False
    bindings: tuple[Binding, ...] | None = None

    def is_open(self):
        return not self.closed

    def is_device_mode(self):
        return self.bindings is not None

    def public_view(self):
        if self.bindings is None:
            seats = [seat.name for seat in self.roster]
            bindings = None
        else:
            seats = [binding.student for binding in self.bindings]
            bindings = [binding.to_dict() for binding in self.bindings]
        view = {
            'round_id': self.id,
            'edition_id': self.edition_id,
            'seats': seats,
            'prompt': question_prompt(self.question),
            'played': self.played,
            'state': 'open' if self.is_open() else 'closed',
        }
        if bindings is not None:
            view['bindings'] = bindings
        return view


def freeze_round(edition: Edition, question_id: str, seats: list) -> Round:
    if edition.id is None:
        raise ValueError('unissued_edition')
    roster, bindings = freeze_seats(seats)
    return Round(None, edition.id, edition.get_question(question_id), roster,
                 bindings=bindings)


def mark_prompt_played(round_: Round) -> Round:
    if not round_.is_open():
        raise Conflict('round_closed')
    return replace(round_, played=True)


def mark_round_closed(round_: Round) -> Round:
    if not round_.is_open():
        raise Conflict('round_closed')
    return replace(round_, closed=True)
