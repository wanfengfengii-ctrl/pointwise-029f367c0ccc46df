from dataclasses import dataclass, replace

from exercise.edition import Edition
from exercise.questions import Question, question_prompt, require_text
from lesson.seats import Seat, freeze_roster


class Conflict(Exception):
    pass


def require_round_id(round_id):
    if type(round_id) is not int or not 0 < round_id < 2**63:
        raise ValueError('invalid_round_id')
    return round_id


def require_request_id(request_id):
    require_text(request_id, 'invalid_request_id')
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

    def is_open(self):
        return not self.closed

    def public_view(self):
        return {
            'round_id': self.id,
            'edition_id': self.edition_id,
            'seats': [seat.name for seat in self.roster],
            'prompt': question_prompt(self.question),
            'played': self.played,
            'state': 'open' if self.is_open() else 'closed',
        }


def freeze_round(edition: Edition, question_id: str, names: list) -> Round:
    if edition.id is None:
        raise ValueError('unissued_edition')
    return Round(None, edition.id, edition.get_question(question_id), freeze_roster(names))


def mark_prompt_played(round_: Round) -> Round:
    if not round_.is_open():
        raise Conflict('round_closed')
    return replace(round_, played=True)


def mark_round_closed(round_: Round) -> Round:
    if not round_.is_open():
        raise Conflict('round_closed')
    return replace(round_, closed=True)
