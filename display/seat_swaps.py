import json

from lesson.rounds import Conflict, require_request_id, require_round_id
from exercise.questions import require_text


class ClassroomSeatSwaps:
    """Classroom-side durable record of seat exchanges and revoked auths."""

    def initialize(self, db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS room_seat_swaps (
                request_id TEXT PRIMARY KEY NOT NULL,
                round_id INTEGER NOT NULL,
                device_a TEXT NOT NULL,
                device_b TEXT NOT NULL,
                payload TEXT NOT NULL
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS authorization_revocations (
                round_id INTEGER NOT NULL,
                authorization TEXT NOT NULL,
                swap_request_id TEXT NOT NULL,
                PRIMARY KEY (round_id, authorization)
            )
        ''')

    def apply_swap(self, db, round_id, request_id, device_a, device_b,
                   bindings=None, revoked=None):
        require_round_id(round_id)
        require_request_id(request_id)
        require_text(device_a, 'invalid_device')
        require_text(device_b, 'invalid_device')
        with db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute(
                'SELECT * FROM room_seat_swaps WHERE request_id = ?', (request_id,),
            ).fetchone()
            if row is not None:
                if (row['round_id'], row['device_a'], row['device_b']) != (
                    round_id, device_a, device_b,
                ):
                    raise Conflict('swap_request_changed')
                return json.loads(row['payload'])
            payload = {
                'status': 'swapped',
                'round_id': round_id,
                'request_id': request_id,
                'bindings': bindings if isinstance(bindings, list) else [],
            }
            db.execute(
                'INSERT INTO room_seat_swaps '
                '(request_id, round_id, device_a, device_b, payload) '
                'VALUES (?, ?, ?, ?, ?)',
                (request_id, round_id, device_a, device_b,
                 json.dumps(payload, ensure_ascii=True)),
            )
            for authorization in revoked or []:
                if isinstance(authorization, str) and authorization:
                    db.execute(
                        'INSERT OR IGNORE INTO authorization_revocations '
                        '(round_id, authorization, swap_request_id) '
                        'VALUES (?, ?, ?)',
                        (round_id, authorization, request_id),
                    )
        return payload

    def is_revoked(self, db, round_id, authorization):
        if not authorization:
            return False
        row = db.execute(
            'SELECT 1 FROM authorization_revocations '
            'WHERE round_id = ? AND authorization = ? LIMIT 1',
            (round_id, authorization),
        ).fetchone()
        return row is not None
