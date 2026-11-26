from display.inspection import LinkUnavailable
from lesson.rounds import mark_round_closed, require_request_id, require_round_id
from lesson.seats import binding_authorizations
from review.breakdown import summarize_results
from review.roster_results import build_roster_results
from review.snapshot_store import ReviewSnapshot


class ReviewService:
    def __init__(self, rounds, operations, dispatch, room, snapshots, history, swaps=None):
        self.rounds = rounds
        self.operations = operations
        self.dispatch = dispatch
        self.room = room
        self.snapshots = snapshots
        self.history = history
        self.swaps = swaps

    def _unsettled(self, db, round_id, round_):
        if self.swaps is not None and self.swaps.unsettled_for_round(db, round_id):
            return True
        valid_authorizations = binding_authorizations(round_.bindings)
        return self.operations.pending_for_round(db, round_id, valid_authorizations)

    def close_round(self, db, round_id, request_id):
        require_round_id(round_id)
        require_request_id(request_id)
        pending = {'status': 'pending', 'round_id': round_id, 'request_id': request_id}
        with db:
            db.execute('BEGIN IMMEDIATE')
            round_ = self.rounds.get(db, round_id)
            self.snapshots.bind_close_request(db, round_id, request_id)
            existing = self.history.for_round(db, round_id)
            if existing is not None:
                return existing
            if self._unsettled(db, round_id, round_):
                return pending
            observed_reveal = self.dispatch.for_round(db, round_id)

        if observed_reveal is not None:
            try:
                evidence = self.room.round_reveal_status(round_id)
            except LinkUnavailable:
                return pending
            if evidence['status'] != 'shown' or evidence.get('request_id') != observed_reveal:
                return pending

        with db:
            db.execute('BEGIN IMMEDIATE')
            existing = self.history.for_round(db, round_id)
            if existing is not None:
                return existing
            round_ = self.rounds.get(db, round_id)
            if (self.dispatch.for_round(db, round_id) != observed_reveal
                    or self._unsettled(db, round_id, round_)):
                return pending
            rows = build_roster_results(round_, self.operations.receipts_for_round(db, round_id))
            snapshot = ReviewSnapshot(
                round_id, request_id, round_.edition_id, round_.question.id,
                rows, summarize_results(rows),
            )
            self.snapshots.save(db, snapshot)
            self.rounds.save_closure(db, mark_round_closed(round_))
        return snapshot.to_dict()
