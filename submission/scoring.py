from dataclasses import dataclass

from exercise.questions import Question


@dataclass(frozen=True)
class Score:
    correct: bool
    points: int


def score_choice(question: Question, choice: str) -> Score:
    if not question.has_option(choice):
        raise ValueError('invalid_choice')
    correct = choice == question.answer
    return Score(correct, question.points if correct else 0)
