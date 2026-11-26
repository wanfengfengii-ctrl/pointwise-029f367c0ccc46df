from display.jobs import RevealJob
from display.outcomes import DisplayOutcome
from display.screen import AnswerFrame
from lesson.rounds import Conflict, require_request_id, require_round_id


class RevelationService:
    def __init__(self, jobs, outcomes, inspection):
        self.jobs = jobs
        self.outcomes = outcomes
        self.inspection = inspection

    def reveal(self, db, round_id, request_id, frame):
        require_round_id(round_id)
        require_request_id(request_id)
        answer_frame = AnswerFrame(**frame)
        if answer_frame.round_id != round_id:
            raise ValueError('frame_from_wrong_round')
        with db:
            db.execute('BEGIN IMMEDIATE')
            job = self.jobs.get_request(db, request_id)
            if job is not None:
                if job.frame != answer_frame:
                    raise Conflict('reveal_request_changed')
            else:
                if (self.outcomes.get_visible(db, round_id) is not None
                        or self.jobs.pending_for_round(db, round_id)):
                    raise Conflict('round_has_reveal')
                self.jobs.schedule(db, RevealJob(request_id, answer_frame))
            return self.inspection.lookup_reveal(db, round_id, request_id)

    def apply_display(self, db, round_id, request_id):
        require_round_id(round_id)
        require_request_id(request_id)
        with db:
            db.execute('BEGIN IMMEDIATE')
            job = self.jobs.get_request(db, request_id)
            if job is None or job.frame.round_id != round_id:
                raise KeyError('unknown_reveal')
            visible = self.outcomes.get_visible(db, round_id)
            if visible is not None:
                if visible.request_id != request_id:
                    raise Conflict('round_has_reveal')
                return visible.to_dict()
            outcome = DisplayOutcome(request_id, job.frame)
            self.outcomes.record_visible(db, outcome)
            self.jobs.finish(db, request_id)
        return outcome.to_dict()
