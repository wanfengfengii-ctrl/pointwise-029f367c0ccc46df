"""Transport controls and a fixed-roster comparison for the seat swap exercise."""
from copy import deepcopy
import unittest

from submission.http_service import exchange
from tests.support import ClassroomCase, TransportControls


class SceneTransport(TransportControls):
    def __init__(self):
        super().__init__()
        self._captured = {}
        self._reply_statuses = {}

    def before_forward(self, path, body):
        held = super().before_forward(path, body)
        if held:
            key = (path, body['request_id'])
            with self._lock:
                self._captured.setdefault(key, deepcopy(body))
        return held

    def deliver_held(self, runtime, path, request_id):
        with self._lock:
            body = self._captured.pop((path, request_id))
        self.release_delivery(path, request_id)
        return exchange(runtime.address('room'), path, body, runtime.token)

    def drop_reply_with_status(self, side, path, request_id, status):
        with self._lock:
            self._reply_statuses[side, path, request_id] = status

    def before_reply(self, side, path, body, result):
        key = (side, path, body.get('request_id'))
        with self._lock:
            if key in self._reply_statuses and result.get('status') == self._reply_statuses[key]:
                del self._reply_statuses[key]
                self.dropped.append((key, deepcopy(result)))
                return True
        return super().before_reply(side, path, body, result)


class SeatSwapCase(ClassroomCase):
    def start(self):
        if not isinstance(self.controls, SceneTransport):
            self.controls = SceneTransport()
        super().start()


class FixedRosterComparison(SeatSwapCase):
    def test_delayed_delivery_and_lost_reply(self):
        round_id = self.open_round()
        self.call('/play_prompt', round_id=round_id)
        path = '/internal/decide'
        self.controls.drop_reply_with_status('room', path, 'a', 'decided')
        self.controls.hold_delivery(path, 'u')
        self.assert_pending(self.submit(round_id, '甲', 'a', 'A', 202), round_id, 'a')
        self.assert_pending(self.submit(round_id, '乙', 'u', 'B', 202), round_id, 'u')
        dropped_key, dropped_result = self.controls.dropped[0]
        self.assertEqual(dropped_key, ('room', path, 'a'))
        self.assertEqual(dropped_result['category'], 'blind')
        for request_id in ('a', 'u'):
            self.assert_pending(self.lookup(round_id, 'submission', request_id, 202),
                                round_id, request_id)
        self.schedule(round_id, 'show')
        self.show(round_id, 'show', side='room')
        status, delayed = self.controls.deliver_held(self.runtime, path, 'u')
        self.assertEqual((status, delayed['status'], delayed['seat'], delayed['category']),
                         (200, 'decided', '乙', 'hinted'))
        first = self.submit(round_id, '甲', 'a', 'A')
        second = self.submit(round_id, '乙', 'u', 'B')
        self.assert_receipt(first, category='blind', choice='A', correct=True, points=3)
        self.assert_receipt(second, category='hinted', choice='B', correct=False, points=0)
        report = self.close_round(round_id, 'close')
        self.assertEqual([row['receipt'] for row in report['seats']], [first, second, None])
        self.reopen()
        self.assertEqual(self.lookup(round_id, 'close', 'close'), report)


if __name__ == '__main__':
    unittest.main(verbosity=2)
