from lesson.rounds import freeze_round


class ClassroomService:
    def __init__(self, catalog, rounds):
        self.catalog = catalog
        self.rounds = rounds

    def open_round(self, db, edition_id, question_id, seats):
        edition = self.catalog.get(db, edition_id)
        round_ = freeze_round(edition, question_id, seats)
        with db:
            saved = self.rounds.add(db, round_)
        return saved.public_view()

    def get_round(self, db, round_id):
        return self.rounds.get(db, round_id).public_view()
