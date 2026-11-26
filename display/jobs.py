from dataclasses import dataclass
import json

from display.screen import AnswerFrame
from lesson.rounds import Conflict


@dataclass(frozen=True)
class RevealJob:
    request_id: str
    frame: AnswerFrame
    finished: bool = False


class RevealJobs:
    def initialize(self, db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS reveal_jobs (
                request_id TEXT PRIMARY KEY NOT NULL,
                round_id INTEGER UNIQUE NOT NULL,
                frame TEXT NOT NULL,
                finished INTEGER NOT NULL DEFAULT 0 CHECK (finished IN (0, 1))
            )
        ''')

    @staticmethod
    def _job(row):
        if row is None:
            return None
        return RevealJob(
            row['request_id'], AnswerFrame(**json.loads(row['frame'])), bool(row['finished']),
        )

    def get_request(self, db, request_id):
        row = db.execute('SELECT * FROM reveal_jobs WHERE request_id = ?', (request_id,)).fetchone()
        return self._job(row)

    def for_round(self, db, round_id):
        row = db.execute('SELECT * FROM reveal_jobs WHERE round_id = ?', (round_id,)).fetchone()
        return self._job(row)

    def schedule(self, db, job: RevealJob):
        db.execute(
            'INSERT INTO reveal_jobs (request_id, round_id, frame) VALUES (?, ?, ?)',
            (job.request_id, job.frame.round_id, json.dumps(job.frame.to_dict())),
        )

    def pending_for_round(self, db, round_id):
        job = self.for_round(db, round_id)
        return job is not None and not job.finished

    def finish(self, db, request_id):
        updated = db.execute(
            'UPDATE reveal_jobs SET finished = 1 WHERE request_id = ? AND finished = 0',
            (request_id,),
        )
        if updated.rowcount != 1:
            raise Conflict('reveal_not_pending')
