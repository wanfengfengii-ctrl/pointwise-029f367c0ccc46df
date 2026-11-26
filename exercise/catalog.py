from dataclasses import replace
import json
import sqlite3

from exercise.edition import Edition
from exercise.questions import Question


class EditionCatalog:
    def initialize(self, db: sqlite3.Connection):
        db.execute('''
            CREATE TABLE IF NOT EXISTS editions (
                id INTEGER PRIMARY KEY,
                book TEXT NOT NULL,
                questions TEXT NOT NULL
            )
        ''')

    def append(self, db: sqlite3.Connection, edition: Edition) -> Edition:
        if edition.id is not None:
            raise ValueError('edition_already_issued')
        payload = json.dumps([question.to_record() for question in edition.questions])
        cursor = db.execute(
            'INSERT INTO editions (book, questions) VALUES (?, ?)',
            (edition.book, payload),
        )
        return replace(edition, id=cursor.lastrowid)

    def get(self, db: sqlite3.Connection, edition_id: int) -> Edition:
        if type(edition_id) is not int or not 0 < edition_id < 2**63:
            raise ValueError('invalid_edition_id')
        row = db.execute(
            'SELECT book, questions FROM editions WHERE id = ?', (edition_id,),
        ).fetchone()
        if row is None:
            raise KeyError('unknown_edition')
        questions = tuple(Question.from_record(data) for data in json.loads(row['questions']))
        return Edition(edition_id, row['book'], questions)
