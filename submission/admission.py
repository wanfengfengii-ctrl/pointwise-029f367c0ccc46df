from lesson.rounds import Conflict
from lesson.seats import binding_authorizations, require_device, require_seat
from submission.receipts import make_receipt
from submission.scoring import score_choice


class AdmissionService:
    def __init__(self, rounds, operations):
        self.rounds = rounds
        self.operations = operations

    def resolve_new(self, db, round_id, *, seat, device, authorization):
        """Resolve a new submission's formal student seat for the round mode."""
        round_ = self.rounds.get(db, round_id)
        if round_.bindings is None:
            require_seat(round_.roster, seat)
            return round_, seat
        binding = require_device(round_.bindings, device)
        if not isinstance(authorization, str) or not authorization:
            raise ValueError('invalid_authorization')
        if authorization != binding.authorization:
            # A swap has rotated this device's authorization.
            raise Conflict('authorization_revoked')
        return round_, binding.student

    def check_submission(self, db, request):
        round_ = self.rounds.get(db, request.round_id)
        if not round_.is_open():
            raise Conflict('round_closed')
        require_seat(round_.roster, request.seat)
        if not round_.question.has_option(request.choice):
            raise ValueError('invalid_choice')
        valid_authorizations = binding_authorizations(round_.bindings)
        receipt = self.operations.find_receipt_for_seat(db, request.round_id, request.seat)
        if receipt is not None:
            raise Conflict('seat_already_submitted')
        reserved = self.operations.seat_request(
            db, request.round_id, request.seat, valid_authorizations,
        )
        if reserved is not None and reserved != request.request_id:
            raise Conflict('seat_pending')
        return round_

    def finalize_submission(self, db, request_id, decision):
        with db:
            db.execute('BEGIN IMMEDIATE')
            request = self.operations.get_request(db, request_id)
            if request is None:
                raise KeyError('unknown_submission')
            if request.receipt is not None:
                return request.receipt.to_dict()
            if decision.get('status') != 'decided' or any(
                decision.get(field) != value for field, value in request.identity().items()
            ):
                return request.pending()
            round_ = self.check_submission(db, request)
            receipt = make_receipt(
                request, score_choice(round_.question, request.choice),
                decision['category'], decision['reveal_request_id'],
            )
            self.operations.complete(db, receipt)
        return receipt.to_dict()
