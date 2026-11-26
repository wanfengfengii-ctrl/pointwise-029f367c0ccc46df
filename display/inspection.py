from lesson.rounds import require_request_id, require_round_id


class LinkUnavailable(Exception):
    pass


class DisplayInspection:
    def __init__(self, jobs, outcomes):
        self.jobs = jobs
        self.outcomes = outcomes

    def lookup_reveal(self, db, round_id, request_id):
        require_round_id(round_id)
        require_request_id(request_id)
        job = self.jobs.get_request(db, request_id)
        if job is None or job.frame.round_id != round_id:
            raise KeyError('unknown_reveal')
        visible = self.outcomes.get_visible(db, round_id)
        if visible is not None and visible.request_id == request_id:
            return visible.to_dict()
        return {'status': 'pending', 'round_id': round_id, 'request_id': request_id}

    def current_display(self, db, round_id):
        require_round_id(round_id)
        visible = self.outcomes.get_visible(db, round_id)
        if visible is None:
            return {'status': 'not_shown', 'round_id': round_id, 'display_count': 0, 'frame': None}
        return {
            'status': 'shown', 'round_id': round_id, 'display_count': 1,
            'frame': visible.frame.to_dict(),
        }

    def round_reveal_status(self, db, round_id):
        require_round_id(round_id)
        job = self.jobs.for_round(db, round_id)
        if job is None:
            return {'status': 'none', 'round_id': round_id}
        return self.lookup_reveal(db, round_id, job.request_id)
