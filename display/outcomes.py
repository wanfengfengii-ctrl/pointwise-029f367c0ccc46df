from dataclasses import dataclass
import json

from display.screen import AnswerFrame
from exercise.questions import require_text
from lesson.rounds import Conflict, require_request_id, require_round_id


@dataclass(frozen=True)
class DisplayOutcome:
    request_id: str
    frame: AnswerFrame

    def to_dict(self):
        return {
            'status': 'shown',
            'round_id': self.frame.round_id,
            'request_id': self.request_id,
            'frame': self.frame.to_dict(),
        }


class DisplayOutcomes:
    def initialize(self, db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS visible_frames (
                round_id INTEGER PRIMARY KEY,
                request_id TEXT UNIQUE NOT NULL REFERENCES reveal_jobs (request_id),
                frame TEXT NOT NULL
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS admission_decisions (
                request_id TEXT PRIMARY KEY NOT NULL,
                round_id INTEGER NOT NULL,
                seat TEXT NOT NULL,
                choice TEXT NOT NULL,
                reveal_request_id TEXT REFERENCES visible_frames (request_id),
                UNIQUE (round_id, seat)
            )
        ''')

    def record_visible(self, db, outcome: DisplayOutcome):
        db.execute(
            'INSERT INTO visible_frames (round_id, request_id, frame) VALUES (?, ?, ?)',
            (outcome.frame.round_id, outcome.request_id, json.dumps(outcome.frame.to_dict())),
        )

    def get_visible(self, db, round_id) -> DisplayOutcome | None:
        row = db.execute(
            'SELECT request_id, frame FROM visible_frames WHERE round_id = ?', (round_id,),
        ).fetchone()
        if row is None:
            return None
        return DisplayOutcome(row['request_id'], AnswerFrame(**json.loads(row['frame'])))

    def decide_submission(self, db, round_id, request_id, seat, choice):
        require_round_id(round_id)
        require_request_id(request_id)
        require_text(seat, 'invalid_seat')
        require_text(choice, 'invalid_choice')
        with db:
            # A decision and an actual display both take the classroom write transaction.
            db.execute('BEGIN IMMEDIATE')
            row = db.execute(
                'SELECT * FROM admission_decisions WHERE request_id = ?', (request_id,),
            ).fetchone()
            if row is not None:
                if (row['round_id'], row['seat'], row['choice']) != (round_id, seat, choice):
                    raise Conflict('submission_request_changed')
                reveal_request_id = row['reveal_request_id']
            else:
                occupied = db.execute(
                    'SELECT 1 FROM admission_decisions WHERE round_id = ? AND seat = ?',
                    (round_id, seat),
                ).fetchone()
                if occupied is not None:
                    raise Conflict('seat_already_decided')
                visible = self.get_visible(db, round_id)
                reveal_request_id = visible.request_id if visible is not None else None
                db.execute('''
                    INSERT INTO admission_decisions
                        (request_id, round_id, seat, choice, reveal_request_id)
                    VALUES (?, ?, ?, ?, ?)
                ''', (request_id, round_id, seat, choice, reveal_request_id))
        return {
            'status': 'decided',
            'round_id': round_id,
            'request_id': request_id,
            'seat': seat,
            'choice': choice,
            'category': 'blind' if reveal_request_id is None else 'hinted',
            'reveal_request_id': reveal_request_id,
        }
