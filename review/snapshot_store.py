from dataclasses import dataclass
import json

from lesson.rounds import Conflict
from review.breakdown import CategoryTotals
from review.roster_results import SeatResult


@dataclass(frozen=True)
class ReviewSnapshot:
    round_id: int
    request_id: str
    edition_id: int
    question_id: str
    seats: tuple[SeatResult, ...]
    totals: dict[str, CategoryTotals]

    def to_dict(self):
        return {
            'status': 'closed',
            'round_id': self.round_id,
            'request_id': self.request_id,
            'edition_id': self.edition_id,
            'question_id': self.question_id,
            'seats': [seat.to_dict() for seat in self.seats],
            'totals': {category: total.to_dict() for category, total in self.totals.items()},
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            data['round_id'], data['request_id'], data['edition_id'], data['question_id'],
            tuple(SeatResult.from_dict(row) for row in data['seats']),
            {category: CategoryTotals(**total) for category, total in data['totals'].items()},
        )


class ReviewSnapshotStore:
    def initialize(self, db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS close_requests (
                request_id TEXT PRIMARY KEY NOT NULL,
                round_id INTEGER UNIQUE NOT NULL REFERENCES rounds (id)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS review_snapshots (
                round_id INTEGER PRIMARY KEY REFERENCES rounds (id),
                request_id TEXT UNIQUE NOT NULL REFERENCES close_requests (request_id),
                payload TEXT NOT NULL
            )
        ''')

    def bind_close_request(self, db, round_id, request_id):
        prior_round = self.request_round(db, request_id)
        if prior_round is not None:
            if prior_round != round_id:
                raise Conflict('close_request_changed')
            return
        prior = db.execute(
            'SELECT request_id FROM close_requests WHERE round_id = ?', (round_id,),
        ).fetchone()
        if prior is not None:
            raise Conflict('round_has_close_request')
        db.execute(
            'INSERT INTO close_requests (request_id, round_id) VALUES (?, ?)', (request_id, round_id),
        )

    def request_round(self, db, request_id):
        row = db.execute(
            'SELECT round_id FROM close_requests WHERE request_id = ?', (request_id,),
        ).fetchone()
        return row['round_id'] if row else None

    def save(self, db, snapshot: ReviewSnapshot):
        db.execute(
            'INSERT INTO review_snapshots (round_id, request_id, payload) VALUES (?, ?, ?)',
            (snapshot.round_id, snapshot.request_id, json.dumps(snapshot.to_dict())),
        )

    def by_round(self, db, round_id):
        row = db.execute(
            'SELECT payload FROM review_snapshots WHERE round_id = ?', (round_id,),
        ).fetchone()
        return ReviewSnapshot.from_dict(json.loads(row['payload'])) if row else None

    def by_close_request(self, db, request_id):
        row = db.execute(
            'SELECT payload FROM review_snapshots WHERE request_id = ?', (request_id,),
        ).fetchone()
        return ReviewSnapshot.from_dict(json.loads(row['payload'])) if row else None
