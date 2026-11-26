from display.inspection import LinkUnavailable
from lesson.rounds import Conflict, require_request_id, require_round_id
from submission.operations import SubmissionRequest


class SubmissionService:
    def __init__(self, operations, admission, room, reveal_relay, history):
        self.operations = operations
        self.admission = admission
        self.room = room
        self.reveal_relay = reveal_relay
        self.history = history

    def submit(self, db, round_id, seat, request_id, choice):
        require_round_id(round_id)
        require_request_id(request_id)
        incoming = SubmissionRequest(request_id, round_id, seat, choice)
        with db:
            db.execute('BEGIN IMMEDIATE')
            request = self.operations.get_request(db, request_id)
            if request is None:
                self.admission.check_submission(db, incoming)
                self.operations.register(db, incoming)
                request = incoming
            elif request.identity() != incoming.identity():
                raise Conflict('submission_request_changed')
            if request.receipt is not None:
                return request.receipt.to_dict()

        try:
            decision = self.room.decide_submission(request.identity())
        except LinkUnavailable:
            # Another retry of this same request may have completed while we waited.
            return self.lookup(db, round_id, 'submission', request_id)
        return self.admission.finalize_submission(db, request_id, decision)

    def lookup(self, db, round_id, kind, request_id):
        require_round_id(round_id)
        require_request_id(request_id)
        if kind == 'reveal':
            return self.reveal_relay.lookup(db, round_id, request_id)
        if kind == 'close':
            return self.history.replay_close(db, round_id, request_id)
        if kind != 'submission':
            raise ValueError('invalid_operation_kind')
        request = self.operations.get_request(db, request_id)
        if request is None or request.round_id != round_id:
            raise KeyError('unknown_submission')
        if request.receipt is None:
            return request.pending()
        return request.receipt.to_dict()
