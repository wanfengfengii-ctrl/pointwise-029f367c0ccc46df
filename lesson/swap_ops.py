import json
from dataclasses import dataclass, replace

from display.inspection import LinkUnavailable
from lesson.rounds import Conflict, require_request_id, require_round_id
from lesson.seats import apply_swap, issue_authorization, swap_pair


PLANNED = 'planned'
SETTLED = 'swapped'


def pending_result(round_id, request_id):
    return {'status': 'pending', 'round_id': round_id, 'request_id': request_id}


@dataclass(frozen=True)
class SwapRecord:
    request_id: str
    round_id: int
    device_a: str
    device_b: str
    pair: tuple
    revoked: tuple
    state: str

    def response(self):
        return {
            'status': 'swapped',
            'round_id': self.round_id,
            'request_id': self.request_id,
            'bindings': [binding.to_dict() for binding in self.pair],
        }

    def wire_body(self):
        body = {
            'request_id': self.request_id,
            'round_id': self.round_id,
            'device_a': self.device_a,
            'device_b': self.device_b,
            'bindings': [binding.to_dict() for binding in self.pair],
            'revoked': list(self.revoked),
        }
        return body


class SeatSwapOperations:
    def initialize(self, db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS seat_swap_requests (
                request_id TEXT PRIMARY KEY NOT NULL,
                round_id INTEGER NOT NULL REFERENCES rounds (id),
                device_a TEXT NOT NULL,
                device_b TEXT NOT NULL,
                pair TEXT NOT NULL,
                revoked TEXT NOT NULL,
                state TEXT NOT NULL
            )
        ''')

    def _row_to_record(self, row):
        from lesson.seats import Binding
        pair = tuple(Binding(**entry) for entry in json.loads(row['pair']))
        return SwapRecord(
            row['request_id'], row['round_id'], row['device_a'], row['device_b'],
            pair, tuple(json.loads(row['revoked'])), row['state'],
        )

    def get(self, db, request_id):
        row = db.execute(
            'SELECT * FROM seat_swap_requests WHERE request_id = ?', (request_id,),
        ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def plan(self, db, *, request_id, round_id, device_a, device_b, pair, revoked):
        db.execute(
            'INSERT INTO seat_swap_requests '
            '(request_id, round_id, device_a, device_b, pair, revoked, state) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (request_id, round_id, device_a, device_b,
             json.dumps([binding.to_dict() for binding in pair]),
             json.dumps(list(revoked)), PLANNED),
        )
        return self.get(db, request_id)

    def unsettled_for_round(self, db, round_id):
        row = db.execute(
            "SELECT 1 FROM seat_swap_requests WHERE round_id = ? AND state != ? LIMIT 1",
            (round_id, SETTLED),
        ).fetchone()
        return row is not None

    def mark_settled(self, db, request_id):
        db.execute(
            'UPDATE seat_swap_requests SET state = ? WHERE request_id = ?',
            (SETTLED, request_id),
        )


class SeatSwapService:
    def __init__(self, rounds, operations, room):
        self.rounds = rounds
        self.operations = operations
        self.room = room

    def swap_seats(self, db, round_id, request_id, device_a, device_b):
        require_round_id(round_id)
        require_request_id(request_id)
        if not isinstance(device_a, str) or not isinstance(device_b, str):
            raise ValueError('invalid_device')
        with db:
            db.execute('BEGIN IMMEDIATE')
            round_ = self.rounds.get(db, round_id)
            prior = self.operations.get(db, request_id)
            if prior is not None:
                if (prior.round_id, prior.device_a, prior.device_b) != (
                    round_id, device_a, device_b,
                ):
                    raise Conflict('swap_request_changed')
                if prior.state == SETTLED:
                    return prior.response()
                record = prior
            else:
                if not round_.is_open():
                    raise Conflict('round_closed')
                if round_.bindings is None:
                    raise ValueError('invalid_device')
                if self.operations.unsettled_for_round(db, round_id):
                    raise Conflict('swap_pending')
                new_authorizations = {
                    device_a: issue_authorization(),
                    device_b: issue_authorization(),
                }
                pair, revoked = swap_pair(
                    round_.bindings, device_a, device_b, new_authorizations,
                )
                record = self.operations.plan(
                    db, request_id=request_id, round_id=round_id,
                    device_a=device_a, device_b=device_b,
                    pair=pair, revoked=revoked,
                )

        try:
            result = self.room.swap_seats(record.wire_body())
        except LinkUnavailable:
            return pending_result(round_id, request_id)
        if result.get('status') != 'swapped':
            return pending_result(round_id, request_id)

        with db:
            db.execute('BEGIN IMMEDIATE')
            current = self.operations.get(db, request_id)
            if current is None:
                raise KeyError('unknown_swap')
            if current.state != SETTLED:
                round_ = self.rounds.get(db, round_id)
                if round_.bindings is not None:
                    updated = apply_swap(round_.bindings, current.pair)
                    self.rounds.save_bindings(db, replace(round_, bindings=updated))
                self.operations.mark_settled(db, request_id)
        return current.response()
