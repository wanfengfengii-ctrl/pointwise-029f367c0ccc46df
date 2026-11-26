from exercise.questions import question_prompt
from lesson.rounds import mark_prompt_played


class PromptPlayback:
    def __init__(self, rounds):
        self.rounds = rounds

    def play(self, db, round_id):
        with db:
            db.execute('BEGIN IMMEDIATE')
            round_ = mark_prompt_played(self.rounds.get(db, round_id))
            played = {
                'status': 'played',
                'round_id': round_id,
                'edition_id': round_.edition_id,
                'prompt': question_prompt(round_.question),
                'audio': round_.question.audio.to_dict(),
            }
            self.rounds.save_playback(db, round_)
        return played

    def read_prompt(self, db, round_id):
        round_ = self.rounds.get(db, round_id)
        return {'round_id': round_id, 'prompt': question_prompt(round_.question)}
