from dataclasses import dataclass
import json

from lesson.rounds import Conflict
from submission.receipts import Receipt


@dataclass(frozen=True)
class SubmissionRequest:
    request_id: str
    round_id: int
    seat: str
    choice: str
    receipt: Receipt | None = None

    def identity(self):
        return {
            'request_id': self.request_id,
            'round_id': self.round_id,
            'seat': self.seat,
            'choice': self.choice,
        }

    def pending(self):
        return {'status': 'pending', 'round_id': self.round_id, 'request_id': self.request_id}


class SubmissionOperations:
    def initialize(self, db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS submissions (
                request_id TEXT PRIMARY KEY NOT NULL,
                round_id INTEGER NOT NULL REFERENCES rounds (id),
                seat TEXT NOT NULL,
                choice TEXT NOT NULL,
                receipt TEXT,
                UNIQUE (round_id, seat)
            )
        ''')

    def get_request(self, db, request_id):
        row = db.execute(
            'SELECT * FROM submissions WHERE request_id = ?', (request_id,),
        ).fetchone()
        if row is None:
            return None
        receipt = Receipt.from_dict(json.loads(row['receipt'])) if row['receipt'] else None
        return SubmissionRequest(row['request_id'], row['round_id'], row['seat'], row['choice'], receipt)

    def register(self, db, request: SubmissionRequest):
        db.execute(
            'INSERT INTO submissions (request_id, round_id, seat, choice) VALUES (?, ?, ?, ?)',
            (request.request_id, request.round_id, request.seat, request.choice),
        )

    def seat_request(self, db, round_id, seat):
        row = db.execute(
            'SELECT request_id FROM submissions WHERE round_id = ? AND seat = ?',
            (round_id, seat),
        ).fetchone()
        return row['request_id'] if row else None

    def find_receipt_for_seat(self, db, round_id, seat):
        request_id = self.seat_request(db, round_id, seat)
        return self.get_request(db, request_id).receipt if request_id is not None else None

    def complete(self, db, receipt: Receipt):
        updated = db.execute(
            'UPDATE submissions SET receipt = ? WHERE request_id = ? AND receipt IS NULL',
            (json.dumps(receipt.to_dict()), receipt.request_id),
        )
        if updated.rowcount != 1:
            raise Conflict('submission_already_finalized')

    def pending_for_round(self, db, round_id):
        return db.execute(
            'SELECT 1 FROM submissions WHERE round_id = ? AND receipt IS NULL LIMIT 1',
            (round_id,),
        ).fetchone() is not None

    def receipts_for_round(self, db, round_id):
        rows = db.execute(
            'SELECT receipt FROM submissions WHERE round_id = ? AND receipt IS NOT NULL',
            (round_id,),
        )
        return tuple(Receipt.from_dict(json.loads(row['receipt'])) for row in rows)


class RevealDispatchStore:
    def initialize(self, db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS reveal_dispatch (
                round_id INTEGER PRIMARY KEY REFERENCES rounds (id),
                request_id TEXT UNIQUE NOT NULL,
                phase TEXT NOT NULL
            )
        ''')

    def for_round(self, db, round_id):
        row = db.execute(
            'SELECT request_id FROM reveal_dispatch WHERE round_id = ?', (round_id,),
        ).fetchone()
        return row['request_id'] if row else None

    def require(self, db, round_id, request_id):
        row = db.execute(
            'SELECT round_id FROM reveal_dispatch WHERE request_id = ?', (request_id,),
        ).fetchone()
        if row is None or row['round_id'] != round_id:
            raise KeyError('unknown_reveal')

    def register(self, db, round_id, request_id):
        row = db.execute(
            'SELECT round_id FROM reveal_dispatch WHERE request_id = ?', (request_id,),
        ).fetchone()
        if row is not None:
            if row['round_id'] != round_id:
                raise Conflict('reveal_request_changed')
            return
        if self.for_round(db, round_id) is not None:
            raise Conflict('round_has_reveal')
        db.execute(
            'INSERT INTO reveal_dispatch (round_id, request_id, phase) VALUES (?, ?, ?)',
            (round_id, request_id, 'queued'),
        )

    def note(self, db, request_id, phase):
        db.execute('UPDATE reveal_dispatch SET phase = ? WHERE request_id = ?', (phase, request_id))
