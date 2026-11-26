from dataclasses import dataclass

from lesson.rounds import Round
from submission.receipts import Receipt


@dataclass(frozen=True)
class SeatResult:
    name: str
    position: int
    answer: str
    receipt: Receipt | None

    def to_dict(self):
        receipt = self.receipt
        return {
            'seat': self.name,
            'position': self.position,
            'answer': self.answer,
            'status': 'submitted' if receipt is not None else 'missing',
            'choice': receipt.choice if receipt is not None else None,
            'points': receipt.score.points if receipt is not None else None,
            'correct': receipt.score.correct if receipt is not None else None,
            'category': receipt.category if receipt is not None else None,
            'request_id': receipt.request_id if receipt is not None else None,
            'receipt': receipt.to_dict() if receipt is not None else None,
        }

    @classmethod
    def from_dict(cls, data):
        receipt = Receipt.from_dict(data['receipt']) if data['receipt'] is not None else None
        return cls(data['seat'], data['position'], data['answer'], receipt)


def build_roster_results(round_: Round, receipts: tuple[Receipt, ...]) -> tuple[SeatResult, ...]:
    by_seat = {receipt.seat: receipt for receipt in receipts}
    return tuple(
        SeatResult(seat.name, seat.position, round_.question.answer, by_seat.get(seat.name))
        for seat in round_.roster
    )
