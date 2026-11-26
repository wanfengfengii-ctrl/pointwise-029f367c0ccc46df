from display.inspection import LinkUnavailable
from tests.support import ClassroomCase


class RevealTests(ClassroomCase):
    def test_v5_scheduled_reveal_has_not_displayed(self):
        round_id = self.open_round()
        self.submit(round_id, '甲', 'first', 'A')
        self.schedule(round_id, 'r1')
        self.assert_pending(self.lookup(round_id, 'reveal', 'r1', 202), round_id, 'r1')
        self.assertEqual(self.screen(round_id)['display_count'], 0)
        second = self.submit(round_id, '乙', 'second', 'B')
        self.assert_receipt(second, category='blind', choice='B', correct=False, points=0)
        shown = self.show(round_id, 'r1', side='room')
        self.assertEqual(shown['frame']['answer'], 'A')
        self.assertEqual(self.screen(round_id)['display_count'], 1)
        self.assertEqual(self.lookup(round_id, 'submission', 'second'), second)

    def test_v6_visible_when_first_reply_is_lost(self):
        round_id = self.open_round()
        first = self.submit(round_id, '甲', 'first', 'A')
        self.schedule(round_id, 'r1')
        self.controls.drop_next_reply('room', '/apply_display', 'r1')
        self.assert_pending(self.show(round_id, 'r1', status=202), round_id, 'r1')
        screen = self.screen(round_id)
        self.assertEqual((screen['status'], screen['display_count'], screen['frame']['answer']),
                         ('shown', 1, 'A'))
        first_display = self.lookup(round_id, 'reveal', 'r1')
        self.assertEqual(self.controls.dropped, [(('room', '/apply_display', 'r1'), first_display)])
        second = self.submit(round_id, '乙', 'second', 'B')
        self.assert_receipt(first, category='blind', choice='A', correct=True, points=3)
        self.assert_receipt(second, category='hinted', choice='B', correct=False, points=0)
        self.reopen()
        self.assertEqual(self.schedule(round_id, 'r1', 200), first_display)
        self.assertEqual(self.show(round_id, 'r1'), first_display)
        self.assertEqual(self.screen(round_id), screen)
        self.assertEqual(self.submit(round_id, '乙', 'second', 'B'), second)
        self.assertEqual(self.lookup(round_id, 'submission', 'first'), first)

    def test_v6_reveal_identity(self):
        edition = self.publish()
        round_id = self.open_round(edition)
        other_round = self.open_round(edition)
        self.schedule(round_id, 'r1')
        shown = self.show(round_id, 'r1')
        self.reopen()
        self.assertEqual(self.schedule(round_id, 'r1', 200), shown)
        self.assertEqual(self.schedule(other_round, 'r1', 409), {'error': 'reveal_request_changed'})
        self.assertEqual(self.schedule(round_id, 'r2', 409), {'error': 'round_has_reveal'})
        self.lookup(other_round, 'reveal', 'r1', 404)
        self.show(other_round, 'r1', side='room', status=404)
        self.assertEqual(self.screen(round_id)['display_count'], 1)
        self.assertEqual(self.screen(other_round)['display_count'], 0)

    def test_v6_delivery_and_display_are_independent(self):
        round_id = self.open_round()
        self.controls.hold_delivery('/internal/reveal', 'r1')
        waiting = self.schedule(round_id, 'r1')
        self.assertEqual(self.lookup(round_id, 'reveal', 'r1', 202), waiting)
        self.show(round_id, 'r1', side='room', status=404)
        self.assertEqual(self.screen(round_id)['display_count'], 0)
        self.reopen()
        self.controls.release_delivery('/internal/reveal', 'r1')
        self.assertEqual(self.schedule(round_id, 'r1'), waiting)
        self.assertEqual(self.screen(round_id)['display_count'], 0)
        shown = self.show(round_id, 'r1', side='room')
        self.assertEqual(self.lookup(round_id, 'reveal', 'r1'), shown)

    def test_cross_commit_recovery_preserves_pre_display_admission(self):
        round_id = self.open_round()
        self.schedule(round_id, 'r1')
        self.controls.drop_next_reply('room', '/internal/decide', 'b1')
        self.assert_pending(self.submit(round_id, '乙', 'b1', 'B', 202), round_id, 'b1')
        self.assertEqual(self.controls.dropped[0][1]['category'], 'blind')
        self.assert_pending(self.lookup(round_id, 'submission', 'b1', 202), round_id, 'b1')
        self.show(round_id, 'r1', side='room')
        self.reopen()
        self.assert_pending(self.lookup(round_id, 'submission', 'b1', 202), round_id, 'b1')
        self.assert_receipt(self.submit(round_id, '乙', 'b1', 'B'),
                            category='blind', choice='B', correct=False, points=0)
        self.assert_receipt(self.submit(round_id, '丙', 'c1', 'A'),
                            category='hinted', choice='A', correct=True, points=3)
        self.assertEqual(self.screen(round_id)['display_count'], 1)

    def test_v6_room_can_recover_without_score_reply(self):
        round_id = self.open_round()
        self.schedule(round_id, 'r1')
        self.controls.drop_next_reply('room', '/apply_display', 'r1')
        with self.assertRaises(LinkUnavailable):
            self.show(round_id, 'r1', side='room')
        self.reopen()
        shown = self.lookup(round_id, 'reveal', 'r1')
        self.assertEqual(shown, self.show(round_id, 'r1', side='room'))
        self.assertEqual(self.screen(round_id)['display_count'], 1)
