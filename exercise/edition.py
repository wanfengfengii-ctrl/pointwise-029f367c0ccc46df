from dataclasses import dataclass
from pathlib import Path

from exercise.audio import read_audio_segment
from exercise.questions import Question, require_text, validate_question


@dataclass(frozen=True)
class Edition:
    id: int | None
    book: str
    questions: tuple[Question, ...]

    def get_question(self, question_id: str) -> Question:
        require_text(question_id, 'invalid_question_id')
        for question in self.questions:
            if question.id == question_id:
                return question
        raise KeyError('unknown_question')


def prepare_edition(audio_dir: Path, book: str, drafts: list) -> Edition:
    require_text(book, 'invalid_book')
    if not isinstance(drafts, list) or not drafts:
        raise ValueError('empty_edition')
    questions = []
    audio_by_ref = {}
    seen = set()
    for draft in drafts:
        if not isinstance(draft, dict):
            raise ValueError('invalid_question')
        ref = require_text(draft.get('audio'), 'invalid_audio_reference')
        if ref not in audio_by_ref:
            audio_by_ref[ref] = read_audio_segment(audio_dir, ref)
        question = validate_question(draft, audio_by_ref[ref])
        if question.id in seen:
            raise ValueError('duplicate_question')
        questions.append(question)
        seen.add(question.id)
    return Edition(None, book, tuple(questions))
