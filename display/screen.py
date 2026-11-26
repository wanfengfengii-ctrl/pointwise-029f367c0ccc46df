from dataclasses import dataclass

from lesson.rounds import Round


@dataclass(frozen=True)
class AnswerFrame:
    round_id: int
    edition_id: int
    question_id: str
    answer: str
    label: str

    def to_dict(self):
        return {
            'round_id': self.round_id,
            'edition_id': self.edition_id,
            'question_id': self.question_id,
            'answer': self.answer,
            'label': self.label,
        }


def build_answer_frame(round_: Round) -> AnswerFrame:
    question = round_.question
    option = next(option for option in question.options if option.id == question.answer)
    return AnswerFrame(round_.id, round_.edition_id, question.id, option.id, option.label)
