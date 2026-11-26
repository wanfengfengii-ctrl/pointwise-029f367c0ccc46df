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
    device: str | None = None
    authorization: str | None = None

    def identity(self):
        return {
            'request_id': self.request_id,
            'round_id': self.round_id,
            'seat': self.seat,
            'choice': self.choice,
        }

    def same_parameters(self, round_id, choice, seat, device, authorization):
        if self.round_id != round_id or self.choice != choice:
            return False
        if self.device is not None or device is not None:
            return self.device == device and self.authorization == authorization
        return self.seat == seat

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
                device TEXT,
                authorization TEXT
            )
        ''')
        columns = {row[1] for row in db.execute('PRAGMA table_info(submissions)')}
        if 'device' not in columns:
            db.execute('ALTER TABLE submissions ADD COLUMN device TEXT')
        if 'authorization' not in columns:
            db.execute('ALTER TABLE submissions ADD COLUMN authorization TEXT')

    def get_request(self, db, request_id):
        row = db.execute(
            'SELECT * FROM submissions WHERE request_id = ?', (request_id,),
        ).fetchone()
        if row is None:
            return None
        keys = row.keys()
        receipt = Receipt.from_dict(json.loads(row['receipt'])) if row['receipt'] else None
        device = row['device'] if 'device' in keys else None
        authorization = row['authorization'] if 'authorization' in keys else None
        return SubmissionRequest(
            row['request_id'], row['round_id'], row['seat'], row['choice'],
            receipt, device, authorization,
        )

    def register(self, db, request: SubmissionRequest):
        db.execute(
            'INSERT INTO submissions '
            '(request_id, round_id, seat, choice, device, authorization) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (request.request_id, request.round_id, request.seat, request.choice,
             request.device, request.authorization),
        )

    def seat_request(self, db, round_id, seat, valid_authorizations=None):
        """Return an active unresolved reservation for the student's seat.

        Rows created under an authorization that a settled swap has revoked
        are superseded and no longer reserve the student's first paper.
        """
        rows = db.execute(
            'SELECT request_id, authorization, receipt FROM submissions '
            'WHERE round_id = ? AND seat = ?',
            (round_id, seat),
        ).fetchall()
        for row in rows:
            if row['receipt'] is not None:
                continue
            authorization = row['authorization'] if 'authorization' in row.keys() else None
            if valid_authorizations is None:
                return row['request_id']
            if authorization in valid_authorizations:
                return row['request_id']
        return None

    def find_receipt_for_seat(self, db, round_id, seat):
        row = db.execute(
            'SELECT receipt FROM submissions '
            'WHERE round_id = ? AND seat = ? AND receipt IS NOT NULL LIMIT 1',
            (round_id, seat),
        ).fetchone()
        if row is None or not row['receipt']:
            return None
        return Receipt.from_dict(json.loads(row['receipt']))

    def complete(self, db, receipt: Receipt):
        updated = db.execute(
            'UPDATE submissions SET receipt = ? WHERE request_id = ? AND receipt IS NULL',
            (json.dumps(receipt.to_dict()), receipt.request_id),
        )
        if updated.rowcount != 1:
            raise Conflict('submission_already_finalized')

    def pending_for_round(self, db, round_id, valid_authorizations=None):
        rows = db.execute(
            'SELECT authorization FROM submissions WHERE round_id = ? AND receipt IS NULL',
            (round_id,),
        ).fetchall()
        for row in rows:
            if valid_authorizations is None:
                return True
            authorization = row['authorization'] if 'authorization' in row.keys() else None
            if authorization in valid_authorizations:
                return True
        return False

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
