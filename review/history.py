class ReviewHistory:
    def __init__(self, snapshots):
        self.snapshots = snapshots

    def for_round(self, db, round_id):
        snapshot = self.snapshots.by_round(db, round_id)
        return snapshot.to_dict() if snapshot is not None else None

    def replay_close(self, db, round_id, request_id):
        if self.snapshots.request_round(db, request_id) != round_id:
            raise KeyError('unknown_close')
        snapshot = self.snapshots.by_close_request(db, request_id)
        if snapshot is None:
            return {'status': 'pending', 'round_id': round_id, 'request_id': request_id}
        return snapshot.to_dict()
