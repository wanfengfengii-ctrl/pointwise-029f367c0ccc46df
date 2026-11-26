from dataclasses import replace
import json
import sqlite3

from lesson.rounds import Round, require_round_id
from lesson.seats import Binding, freeze_roster


class RoundStore:
    def __init__(self, catalog):
        self.catalog = catalog

    def initialize(self, db: sqlite3.Connection):
        db.execute('''
            CREATE TABLE IF NOT EXISTS rounds (
                id INTEGER PRIMARY KEY,
                edition_id INTEGER NOT NULL REFERENCES editions (id),
                question_id TEXT NOT NULL,
                roster TEXT NOT NULL,
                played INTEGER NOT NULL DEFAULT 0 CHECK (played IN (0, 1)),
                closed INTEGER NOT NULL DEFAULT 0 CHECK (closed IN (0, 1)),
                bindings TEXT
            )
        ''')
        columns = {row[1] for row in db.execute('PRAGMA table_info(rounds)')}
        if 'bindings' not in columns:
            db.execute('ALTER TABLE rounds ADD COLUMN bindings TEXT')

    def add(self, db, round_: Round) -> Round:
        cursor = db.execute(
            'INSERT INTO rounds (edition_id, question_id, roster, bindings) '
            'VALUES (?, ?, ?, ?)',
            (round_.edition_id, round_.question.id,
             json.dumps([seat.name for seat in round_.roster]),
             json.dumps([binding.to_dict() for binding in round_.bindings])
             if round_.bindings is not None else None),
        )
        return replace(round_, id=cursor.lastrowid)

    def get(self, db, round_id) -> Round:
        require_round_id(round_id)
        row = db.execute('SELECT * FROM rounds WHERE id = ?', (round_id,)).fetchone()
        if row is None:
            raise KeyError('unknown_round')
        edition = self.catalog.get(db, row['edition_id'])
        raw_bindings = row['bindings'] if 'bindings' in row.keys() else None
        bindings = None
        if raw_bindings:
            bindings = tuple(
                Binding(entry['device'], entry['student'], entry['authorization'])
                for entry in json.loads(raw_bindings)
            )
        return Round(
            round_id, edition.id, edition.get_question(row['question_id']),
            freeze_roster(json.loads(row['roster'])), bool(row['played']),
            bool(row['closed']), bindings,
        )

    def save_playback(self, db, round_: Round):
        db.execute('UPDATE rounds SET played = ? WHERE id = ?', (round_.played, round_.id))

    def save_closure(self, db, round_: Round):
        db.execute('UPDATE rounds SET closed = ? WHERE id = ?', (round_.closed, round_.id))

    def save_bindings(self, db, round_: Round):
        db.execute('UPDATE rounds SET bindings = ? WHERE id = ?', (
            json.dumps([binding.to_dict() for binding in round_.bindings])
            if round_.bindings is not None else None,
            round_.id,
        ))
