from dataclasses import dataclass

from exercise.audio import AudioSegment


def require_text(value, error):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(error)
    return value


@dataclass(frozen=True)
class Option:
    id: str
    label: str

    def to_dict(self):
        return {'id': self.id, 'label': self.label}


@dataclass(frozen=True)
class Question:
    id: str
    prompt: str
    audio: AudioSegment
    options: tuple[Option, ...]
    answer: str
    points: int

    def has_option(self, choice):
        return any(option.id == choice for option in self.options)

    def to_record(self):
        return {
            'id': self.id,
            'prompt': self.prompt,
            'audio': self.audio.to_dict(),
            'options': [option.to_dict() for option in self.options],
            'answer': self.answer,
            'points': self.points,
        }

    @classmethod
    def from_record(cls, record):
        return cls(
            record['id'], record['prompt'], AudioSegment.from_dict(record['audio']),
            tuple(Option(**option) for option in record['options']),
            record['answer'], record['points'],
        )


def validate_question(draft: dict, audio: AudioSegment) -> Question:
    question_id = require_text(draft.get('id'), 'invalid_question_id')
    prompt = require_text(draft.get('prompt'), 'invalid_prompt')
    options = draft.get('options')
    if not isinstance(options, list) or not options:
        raise ValueError('invalid_options')
    checked = []
    seen = set()
    for option in options:
        if not isinstance(option, dict):
            raise ValueError('invalid_options')
        option_id = require_text(option.get('id'), 'invalid_option_id')
        label = require_text(option.get('label'), 'invalid_option_label')
        if option_id in seen:
            raise ValueError('duplicate_option')
        checked.append(Option(option_id, label))
        seen.add(option_id)
    answer = require_text(draft.get('answer'), 'invalid_answer_key')
    if answer not in seen:
        raise ValueError('invalid_answer_key')
    points = draft.get('points')
    if type(points) is not int or points < 0:
        raise ValueError('invalid_points')
    return Question(question_id, prompt, audio, tuple(checked), answer, points)


def question_prompt(question: Question) -> dict:
    return {
        'question_id': question.id,
        'prompt': question.prompt,
        'audio_ref': question.audio.reference,
        'options': [option.to_dict() for option in question.options],
    }
