from exercise.edition import prepare_edition
from exercise.questions import question_prompt


class PublicationService:
    def __init__(self, audio_dir, catalog):
        self.audio_dir = audio_dir
        self.catalog = catalog

    def proof(self, book, questions):
        edition = prepare_edition(self.audio_dir, book, questions)
        proofs = []
        for question in edition.questions:
            audio = question.audio
            proofs.append({
                **question_prompt(question),
                'answer': question.answer,
                'points': question.points,
                'audio': {'sample_rate': audio.sample_rate, 'frame_count': audio.frame_count},
            })
        return {'status': 'valid', 'book': edition.book, 'questions': proofs}

    def publish(self, db, book, questions):
        edition = prepare_edition(self.audio_dir, book, questions)
        with db:
            issued = self.catalog.append(db, edition)
        return {'status': 'published', 'edition_id': issued.id, 'book': issued.book}
