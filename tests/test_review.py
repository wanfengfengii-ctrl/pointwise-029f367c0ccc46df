from tests.support import ClassroomCase


class ReviewTests(ClassroomCase):
    def test_v7_review_replays_fixed_order_and_totals(self):
        round_id = self.open_round()
        first = self.submit(round_id, '甲', 'a1', 'A')
        self.schedule(round_id, 'r1')
        self.show(round_id, 'r1')
        second = self.submit(round_id, '乙', 'b1', 'B')
        report = self.close_round(round_id, 'close')
        self.assertEqual(report['status'], 'closed')
        self.assertEqual([row['seat'] for row in report['seats']], ['甲', '乙', '丙'])
        self.assertEqual([row['answer'] for row in report['seats']], ['A', 'A', 'A'])
        self.assertEqual([row['receipt'] for row in report['seats']], [first, second, None])
        self.assertEqual(report['seats'][2]['status'], 'missing')
        self.assertIsNone(report['seats'][2]['choice'])
        self.assertIsNone(report['seats'][2]['points'])
        self.assertEqual(report['totals'], {
            'blind': {'count': 1, 'points': 3, 'correct': 1},
            'hinted': {'count': 1, 'points': 0, 'correct': 0},
        })
        self.reopen()
        self.assertEqual(self.lookup(round_id, 'close', 'close'), report)
        self.assertEqual(self.close_round(round_id, 'close'), report)

    def test_v7_closed_submission(self):
        edition = self.publish()
        round_id = self.open_round(edition)
        other_round = self.open_round(edition)
        receipt = self.submit(round_id, '甲', 'a1', 'A')
        report = self.close_round(round_id, 'close')
        self.assertEqual(self.call('/get_round', round_id=round_id)['state'], 'closed')
        self.assertEqual(self.submit(round_id, '乙', 'b1', 'A', 409), {'error': 'round_closed'})
        self.lookup(round_id, 'submission', 'b1', 404)
        self.assertEqual(self.submit(round_id, '甲', 'a1', 'A'), receipt)
        self.assertEqual(self.lookup(round_id, 'submission', 'a1'), receipt)
        self.assertEqual(self.schedule(round_id, 'r1', 409), {'error': 'round_closed'})
        self.assertEqual(self.close_round(other_round, 'close', 409), {'error': 'close_request_changed'})
        self.lookup(other_round, 'close', 'close', 404)
        self.assertEqual(self.lookup(round_id, 'close', 'close'), report)

    def test_v7_zero_point_and_missing(self):
        round_id = self.open_round(self.publish(points=0), seats=['乙', '丙', '甲'])
        self.submit(round_id, '甲', 'a1', 'A')
        self.schedule(round_id, 'r1')
        self.show(round_id, 'r1')
        self.submit(round_id, '乙', 'b1', 'B')
        report = self.close_round(round_id, 'close')
        expected = [('乙', 'B', 0, False), ('丙', None, None, None), ('甲', 'A', 0, True)]
        actual = [(row['seat'], row['choice'], row['points'], row['correct']) for row in report['seats']]
        self.assertEqual(actual, expected)
        self.assertEqual(report['totals'], {
            'blind': {'count': 1, 'points': 0, 'correct': 1},
            'hinted': {'count': 1, 'points': 0, 'correct': 0},
        })
        self.reopen()
        self.assertEqual(self.lookup(round_id, 'close', 'close'), report)

    def test_v8_pending_submission(self):
        round_id = self.open_round()
        self.controls.hold_delivery('/internal/decide', 'a1')
        self.submit(round_id, '甲', 'a1', 'A', 202)
        waiting = self.close_round(round_id, 'close', 202)
        self.assert_pending(waiting, round_id, 'close')
        self.assertEqual(self.lookup(round_id, 'close', 'close', 202), waiting)
        self.assertEqual(self.call('/get_round', round_id=round_id)['state'], 'open')
        self.reopen()
        self.assertEqual(self.lookup(round_id, 'close', 'close', 202), waiting)
        self.controls.release_delivery('/internal/decide', 'a1')
        receipt = self.submit(round_id, '甲', 'a1', 'A')
        report = self.close_round(round_id, 'close')
        self.assertEqual(report['seats'][0]['receipt'], receipt)
        self.assertEqual(report['totals']['hinted'], {'count': 0, 'points': 0, 'correct': 0})
        self.assertEqual(self.close_round(round_id, 'close'), report)

    def test_v8_pending_reveal(self):
        round_id = self.open_round()
        first = self.submit(round_id, '甲', 'a1', 'A')
        self.schedule(round_id, 'r1')
        waiting = self.close_round(round_id, 'close', 202)
        self.assert_pending(waiting, round_id, 'close')
        self.assertEqual(self.lookup(round_id, 'close', 'close', 202), waiting)
        self.assertEqual(self.screen(round_id)['display_count'], 0)
        self.assertEqual(self.call('/get_round', round_id=round_id)['state'], 'open')
        self.controls.drop_next_reply('room', '/apply_display', 'r1')
        self.assert_pending(self.show(round_id, 'r1', status=202), round_id, 'r1')
        report = self.close_round(round_id, 'close')
        self.assertEqual(report['seats'][0]['receipt'], first)
        self.assertEqual(report['totals']['blind'], {'count': 1, 'points': 3, 'correct': 1})
        self.assertEqual(self.lookup(round_id, 'close', 'close'), report)
        self.assertEqual(self.close_round(round_id, 'close'), report)

    def test_v8_close_waits_for_undelivered_reveal(self):
        round_id = self.open_round()
        self.controls.hold_delivery('/internal/reveal', 'r1')
        self.schedule(round_id, 'r1')
        self.assert_pending(self.close_round(round_id, 'close', 202), round_id, 'close')
        self.controls.release_delivery('/internal/reveal', 'r1')
        self.schedule(round_id, 'r1')
        self.show(round_id, 'r1', side='room')
        report = self.close_round(round_id, 'close')
        self.assertEqual(report['totals'], {
            'blind': {'count': 0, 'points': 0, 'correct': 0},
            'hinted': {'count': 0, 'points': 0, 'correct': 0},
        })
