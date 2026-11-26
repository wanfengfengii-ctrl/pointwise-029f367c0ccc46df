from dataclasses import dataclass

from submission.scoring import Score


CATEGORIES = ('blind', 'hinted')


@dataclass(frozen=True)
class Receipt:
    request_id: str
    round_id: int
    seat: str
    choice: str
    score: Score
    category: str
    reveal_request_id: str | None

    def to_dict(self):
        return {
            'status': 'accepted',
            'request_id': self.request_id,
            'round_id': self.round_id,
            'seat': self.seat,
            'choice': self.choice,
            'correct': self.score.correct,
            'points': self.score.points,
            'category': self.category,
            'reveal_request_id': self.reveal_request_id,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            data['request_id'], data['round_id'], data['seat'], data['choice'],
            Score(data['correct'], data['points']), data['category'],
            data['reveal_request_id'],
        )


def make_receipt(request, score: Score, category: str, reveal_request_id: str | None):
    if category not in CATEGORIES or (category == 'hinted') != (reveal_request_id is not None):
        raise ValueError('invalid_admission_evidence')
    return Receipt(
        request.request_id, request.round_id, request.seat, request.choice,
        score, category, reveal_request_id,
    )
