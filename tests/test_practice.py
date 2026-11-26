from display.inspection import LinkUnavailable
from tests.support import ClassroomCase


class PracticeTests(ClassroomCase):
    def test_v3_first_and_hinted_receipts(self):
        round_id = self.open_round()
        first = self.submit(round_id, '甲', 'a1', 'A')
        self.schedule(round_id, 'r1')
        self.show(round_id, 'r1')
        second = self.submit(round_id, '乙', 'b1', 'B')
        self.assert_receipt(first, category='blind', choice='A', correct=True, points=3)
        self.assert_receipt(second, category='hinted', choice='B', correct=False, points=0)
        self.assertIsNone(first['reveal_request_id'])
        self.assertEqual(second['reveal_request_id'], 'r1')
        self.assertEqual(self.lookup(round_id, 'submission', 'a1'), first)
        self.assertEqual(self.lookup(round_id, 'submission', 'b1'), second)

    def test_v3_hinted_correct(self):
        round_id = self.open_round()
        self.schedule(round_id, 'r1')
        self.show(round_id, 'r1')
        receipt = self.submit(round_id, '乙', 'b1', 'A')
        self.assert_receipt(receipt, category='hinted', choice='A', correct=True, points=3)
        self.assertEqual(self.lookup(round_id, 'submission', 'b1'), receipt)

    def test_v3_second_seat_submission(self):
        round_id = self.open_round()
        receipt = self.submit(round_id, '甲', 'first', 'A')
        error = self.submit(round_id, '甲', 'second', 'B', 409)
        self.assertEqual(error, {'error': 'seat_already_submitted'})
        self.lookup(round_id, 'submission', 'second', 404)
        self.assertEqual(self.lookup(round_id, 'submission', 'first'), receipt)
        review = self.close_round(round_id, 'close')
        self.assertEqual(review['totals']['blind'], {'count': 1, 'points': 3, 'correct': 1})

    def test_v4_rejects_outside_roster(self):
        edition = self.publish()
        other = self.open_round(edition, seats=['丁'])
        self.submit(other, '丁', 'valid-d', 'A')
        round_id = self.open_round(edition)
        self.assertEqual(self.submit(round_id, '丁', 'not-on-roster', 'A', 400),
                         {'error': 'invalid_seat'})
        self.lookup(round_id, 'submission', 'not-on-roster', 404)
        review = self.close_round(round_id, 'close')
        self.assertEqual([row['status'] for row in review['seats']], ['missing'] * 3)
        self.assertEqual(review['totals']['blind'], {'count': 0, 'points': 0, 'correct': 0})

    def test_v4_invalid_option_has_no_receipt(self):
        round_id = self.open_round()
        self.assertEqual(self.submit(round_id, '乙', 'invalid', 'Z', 400), {'error': 'invalid_choice'})
        self.lookup(round_id, 'submission', 'invalid', 404)
        self.assert_receipt(self.submit(round_id, '乙', 'valid', 'A'),
                            category='blind', choice='A', correct=True, points=3)

    def test_v6_request_identity_after_grade_reply_loss(self):
        edition = self.publish()
        round_id = self.open_round(edition)
        other_round = self.open_round(edition)
        self.controls.drop_next_reply('score', '/submit', 'first')
        with self.assertRaises(LinkUnavailable):
            self.submit(round_id, '甲', 'first', 'A')
        original = self.lookup(round_id, 'submission', 'first')
        self.assertEqual(self.controls.dropped, [(('score', '/submit', 'first'), original)])
        self.schedule(round_id, 'r1')
        self.show(round_id, 'r1')
        self.reopen()
        self.assertEqual(self.submit(round_id, '甲', 'first', 'A'), original)
        self.assert_receipt(original, category='blind', choice='A', correct=True, points=3)
        self.assertEqual(self.submit(round_id, '甲', 'first', 'B', 409),
                         {'error': 'submission_request_changed'})
        self.assertEqual(self.submit(other_round, '甲', 'first', 'A', 409),
                         {'error': 'submission_request_changed'})
        self.lookup(other_round, 'submission', 'first', 404)

    def test_v6_pending_original_and_independent_round(self):
        edition = self.publish()
        round_id = self.open_round(edition)
        other_round = self.open_round(edition)
        self.controls.hold_delivery('/internal/decide', 'pending-a')
        waiting = self.submit(round_id, '甲', 'pending-a', 'A', 202)
        self.assert_pending(waiting, round_id, 'pending-a')
        self.assertEqual(self.lookup(round_id, 'submission', 'pending-a', 202), waiting)
        self.assertEqual(self.submit(round_id, '甲', 'pending-a', 'B', 409),
                         {'error': 'submission_request_changed'})
        self.assertEqual(self.submit(round_id, '甲', 'new-a', 'B', 409), {'error': 'seat_pending'})
        self.assert_receipt(self.submit(other_round, '甲', 'other-a', 'A'),
                            category='blind', choice='A', correct=True, points=3)
        self.reopen()
        self.assertEqual(self.lookup(round_id, 'submission', 'pending-a', 202), waiting)
        self.controls.release_delivery('/internal/decide', 'pending-a')
        receipt = self.submit(round_id, '甲', 'pending-a', 'A')
        self.assert_receipt(receipt, category='blind', choice='A', correct=True, points=3)
        self.assertEqual(self.lookup(round_id, 'submission', 'pending-a'), receipt)
