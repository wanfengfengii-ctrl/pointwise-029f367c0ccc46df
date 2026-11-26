"""Business verification for device seat mode and in-round seat swaps."""
from seat_swap_scene import SeatSwapCase
from submission.http_service import exchange


DEVICE_SEATS = [
    {'device': 'S1', 'student': '甲'},
    {'device': 'S2', 'student': '乙'},
    {'device': 'S3', 'student': '丙'},
]


class DeviceSeatOpenTests(SeatSwapCase):
    def open_device(self, seats=None):
        edition = self.publish()
        return self.call('/open_round', edition_id=edition, question_id='pulses',
                         seats=DEVICE_SEATS if seats is None else seats)

    def test_bindings_in_device_order(self):
        opened = self.open_device()
        self.assertEqual(opened['state'], 'open')
        self.assertEqual(opened['seats'], ['甲', '乙', '丙'])
        bindings = opened['bindings']
        self.assertEqual([b['device'] for b in bindings], ['S1', 'S2', 'S3'])
        self.assertEqual([b['student'] for b in bindings], ['甲', '乙', '丙'])
        auths = [b['authorization'] for b in bindings]
        self.assertTrue(all(isinstance(a, str) and a for a in auths))
        self.assertEqual(len(set(auths)), 3)
        fetched = self.call('/get_round', round_id=opened['round_id'])
        self.assertEqual(fetched['bindings'], bindings)
        self.assertEqual(fetched['seats'], ['甲', '乙', '丙'])

    def test_named_mode_has_no_bindings(self):
        round_id = self.open_round()
        view = self.call('/get_round', round_id=round_id)
        self.assertNotIn('bindings', view)

    def test_duplicate_device_and_student_rejected(self):
        dup_device = [
            {'device': 'S1', 'student': '甲'},
            {'device': 'S1', 'student': '乙'},
        ]
        self.assertEqual(self._open_status(dup_device), 400)
        dup_student = [
            {'device': 'S1', 'student': '甲'},
            {'device': 'S2', 'student': '甲'},
        ]
        self.assertEqual(self._open_status(dup_student), 400)

    def _open_status(self, seats):
        edition = self.publish()
        status, body = exchange(self.runtime.address('score'), '/open_round', {
            'edition_id': edition, 'question_id': 'pulses', 'seats': seats,
        })
        return status

    def test_blank_and_untrimmed_values_rejected(self):
        for bad in ('', ' 甲', '甲 '):
            status = self._open_status([
                {'device': 'S1', 'student': bad},
                {'device': 'S2', 'student': '乙'},
            ])
            self.assertEqual(status, 400)
        status = self._open_status([
            {'device': ' S1', 'student': '甲'},
            {'device': 'S2', 'student': '乙'},
        ])
        self.assertEqual(status, 400)


class SeatSwapFlowTests(SeatSwapCase):
    def open_device_round(self):
        edition = self.publish()
        opened = self.call('/open_round', edition_id=edition,
                           question_id='pulses', seats=DEVICE_SEATS)
        self.round_id = opened['round_id']
        self.bindings = {b['device']: b for b in opened['bindings']}
        return opened

    def auth(self, device):
        return self.bindings[device]['authorization']

    def device_submit(self, request_id, device, authorization, choice, status=200):
        return self.call('/submit', status=status, round_id=self.round_id,
                         request_id=request_id, device=device,
                         authorization=authorization, choice=choice)

    def swap(self, request_id='swap-1', status=200, a='S1', b='S2'):
        return self.call('/swap_seats', status=status, round_id=self.round_id,
                         request_id=request_id, device_a=a, device_b=b)

    def test_swap_rotates_two_authorizations_only(self):
        self.open_device_round()
        old_s1, old_s2, old_s3 = (self.auth('S1'), self.auth('S2'), self.auth('S3'))
        result = self.swap()
        self.assertEqual(result['status'], 'swapped')
        self.assertEqual(result['round_id'], self.round_id)
        self.assertEqual(result['request_id'], 'swap-1')
        pair = result['bindings']
        self.assertEqual([b['device'] for b in pair], ['S1', 'S2'])
        self.assertEqual([b['student'] for b in pair], ['乙', '甲'])
        new_auth = {b['device']: b['authorization'] for b in pair}
        self.assertNotEqual(new_auth['S1'], old_s1)
        self.assertNotEqual(new_auth['S2'], old_s2)
        view = self.call('/get_round', round_id=self.round_id)
        current = {b['device']: b for b in view['bindings']}
        self.assertEqual(current['S1']['student'], '乙')
        self.assertEqual(current['S2']['student'], '甲')
        self.assertEqual(current['S3']['student'], '丙')
        self.assertEqual(current['S3']['authorization'], old_s3)
        self.assertEqual(current['S1']['authorization'], new_auth['S1'])
        # Same number replays the identical result.
        self.assertEqual(self.swap(), result)
        # Changed parameters conflict.
        self.swap(status=409, b='S3')

    def test_invalid_swap_pair(self):
        self.open_device_round()
        self.swap(status=400, a='S1', b='S1')
        self.swap(status=400, a='S1', b='S9')

    def test_new_swap_after_close_conflicts_but_replay_remains(self):
        self.open_device_round()
        result = self.swap()
        self.close_round(self.round_id, 'close')
        self.swap(status=409, request_id='swap-2')
        self.assertEqual(self.swap(request_id='swap-1'), result)

    def test_main_scene_late_order_rejected_and_review_order(self):
        self.open_device_round()
        rid = self.round_id
        self.call('/play_prompt', round_id=rid)
        old_s1, old_s2 = self.auth('S1'), self.auth('S2')

        self.controls.drop_reply_with_status('room', '/internal/decide', 'a', 'decided')
        self.controls.hold_delivery('/internal/decide', 'u')

        waiting_a = self.device_submit('a', 'S1', old_s1, 'A', 202)
        self.assert_pending(waiting_a, rid, 'a')
        waiting_u = self.device_submit('u', 'S2', old_s2, 'B', 202)
        self.assert_pending(waiting_u, rid, 'u')
        for request_id in ('a', 'u'):
            self.assert_pending(
                self.lookup(rid, 'submission', request_id, 202), rid, request_id,
            )

        swapped = self.swap()
        new_auth = {b['device']: b['authorization'] for b in swapped['bindings']}

        self.schedule(rid, 'show')
        self.show(rid, 'show')

        second = self.device_submit('b', 'S1', new_auth['S1'], 'B')
        self.assert_receipt(second, category='hinted', choice='B',
                            correct=False, points=0)
        self.assertEqual(second['seat'], '乙')
        self.assertEqual(second['device'], 'S1')

        status, delayed = self.controls.deliver_held(self.runtime, '/internal/decide', 'u')
        self.assertEqual(status, 409)
        self.assertEqual(self.device_submit('u', 'S2', old_s2, 'B', 409),
                         {'error': 'authorization_revoked'})

        first = self.device_submit('a', 'S1', old_s1, 'A')
        self.assert_receipt(first, category='blind', choice='A', correct=True, points=3)
        self.assertEqual(first['seat'], '甲')
        self.assertEqual(first['device'], 'S1')
        self.assertEqual(self.lookup(rid, 'submission', 'a'), first)

        report = self.close_round(rid, 'close')
        self.assertEqual([row['device'] for row in report['seats']],
                         ['S1', 'S2', 'S3'])
        self.assertEqual([row['seat'] for row in report['seats']],
                         ['乙', '甲', '丙'])
        self.assertEqual([row['receipt'] for row in report['seats']],
                         [second, first, None])
        jia_row = report['seats'][1]
        self.assertEqual(jia_row['device'], 'S2')
        self.assertEqual(jia_row['receipt']['device'], 'S1')
        self.assertEqual(report['seats'][2]['status'], 'missing')
        self.assertIsNone(report['seats'][2]['choice'])
        self.assertEqual(report['totals'], {
            'blind': {'count': 1, 'points': 3, 'correct': 1},
            'hinted': {'count': 1, 'points': 0, 'correct': 0},
        })

        self.reopen()
        self.assertEqual(self.lookup(rid, 'close', 'close'), report)
        self.assertEqual(self.close_round(rid, 'close'), report)

    def test_release_old_order_before_new_submission(self):
        self.open_device_round()
        rid = self.round_id
        old_s2 = self.auth('S2')
        self.controls.hold_delivery('/internal/decide', 'u')
        self.device_submit('u', 'S2', old_s2, 'B', 202)
        swapped = self.swap()
        new_s1 = next(b['authorization'] for b in swapped['bindings']
                      if b['device'] == 'S1')

        status, _ = self.controls.deliver_held(self.runtime, '/internal/decide', 'u')
        self.assertEqual(status, 409)
        self.device_submit('u', 'S2', old_s2, 'B', 409)

        self.schedule(rid, 'show')
        self.show(rid, 'show')
        fresh = self.device_submit('b', 'S1', new_s1, 'B')
        self.assertEqual(fresh['status'], 'accepted')
        self.assertEqual(fresh['seat'], '乙')

    def test_pending_swap_keeps_old_bindings_blocks_close_then_recovers(self):
        self.open_device_round()
        rid = self.round_id
        old = {device: self.auth(device) for device in ('S1', 'S2', 'S3')}

        first = self.device_submit('a', 'S1', old['S1'], 'A')
        self.assert_receipt(first, category='blind', choice='A', correct=True, points=3)

        self.controls.drop_reply_with_status(
            'room', '/internal/swap_seats', 'swap-1', 'swapped',
        )
        waiting = self.swap(status=202)
        self.assert_pending(waiting, rid, 'swap-1')

        pending_view = self.call('/get_round', round_id=rid)
        pending_auth = {b['device']: b['authorization'] for b in pending_view['bindings']}
        self.assertEqual(pending_auth, old)

        third = self.device_submit('c', 'S3', old['S3'], 'A')
        self.assert_receipt(third, category='blind', choice='A', correct=True, points=3)

        close_waiting = self.close_round(rid, 'close', 202)
        self.assert_pending(close_waiting, rid, 'close')

        self.reopen()
        done = self.swap()
        self.assertEqual([b['student'] for b in done['bindings']], ['乙', '甲'])
        # Replaying the same swap number is stable and only swaps once.
        self.assertEqual(self.swap(), done)
        self.swap(status=409, b='S3')
        # Original first receipt replays unchanged.
        self.assertEqual(self.lookup(rid, 'submission', 'a'), first)

        report = self.close_round(rid, 'close')
        self.assertEqual([row['seat'] for row in report['seats']], ['乙', '甲', '丙'])
        self.assertEqual([row['receipt'] for row in report['seats']],
                         [None, first, third])
        self.reopen()
        self.assertEqual(self.lookup(rid, 'close', 'close'), report)

    def test_wrong_authorization_is_conflict_and_does_not_reserve(self):
        self.open_device_round()
        rid = self.round_id
        bogus = self.device_submit('x', 'S1', 'not-an-auth', 'A', 409)
        self.assertEqual(bogus, {'error': 'authorization_revoked'})
        # The legitimate authorization can still submit.
        receipt = self.device_submit('ok', 'S1', self.auth('S1'), 'A')
        self.assertEqual(receipt['status'], 'accepted')

    def test_held_swap_delivery_then_deliver_and_resume(self):
        self.open_device_round()
        rid = self.round_id
        self.controls.hold_delivery('/internal/swap_seats', 'swap-1')
        waiting = self.swap(status=202)
        self.assert_pending(waiting, rid, 'swap-1')
        # Old confirmed bindings still readable while the swap is held.
        self.assertEqual(
            [b['student'] for b in self.call('/get_round', round_id=rid)['bindings']],
            ['甲', '乙', '丙'],
        )
        status, room_result = self.controls.deliver_held(
            self.runtime, '/internal/swap_seats', 'swap-1',
        )
        self.assertEqual(status, 200)
        self.assertEqual(room_result['status'], 'swapped')
        # Same number resumes; room replay makes the score side apply once.
        done = self.swap()
        self.assertEqual([b['student'] for b in done['bindings']], ['乙', '甲'])
        self.assertEqual(self.swap(), done)

    def test_held_new_authorization_paper_blocks_close(self):
        self.open_device_round()
        rid = self.round_id
        swapped = self.swap()
        new_s1 = next(b['authorization'] for b in swapped['bindings']
                      if b['device'] == 'S1')
        self.controls.hold_delivery('/internal/decide', 'b')
        self.device_submit('b', 'S1', new_s1, 'A', 202)
        self.close_round(rid, 'close', 202)
        status, decided = self.controls.deliver_held(
            self.runtime, '/internal/decide', 'b',
        )
        self.assertEqual((status, decided['status'], decided['category']),
                         (200, 'decided', 'blind'))
        receipt = self.device_submit('b', 'S1', new_s1, 'A')
        self.assert_receipt(receipt, category='blind', choice='A',
                            correct=True, points=3)
        report = self.close_round(rid, 'close')
        self.assertEqual(report['seats'][0]['receipt'], receipt)

    def test_close_settles_without_score_repost_of_room_rejected_order(self):
        # Mirrors the spec sequence literally: u is only released to the room
        # (where the stale authorization is rejected); score never re-posts u.
        self.open_device_round()
        rid = self.round_id
        old_s1, old_s2 = self.auth('S1'), self.auth('S2')
        self.controls.drop_reply_with_status('room', '/internal/decide', 'a', 'decided')
        self.controls.hold_delivery('/internal/decide', 'u')
        self.device_submit('a', 'S1', old_s1, 'A', 202)
        self.device_submit('u', 'S2', old_s2, 'B', 202)
        swapped = self.swap()
        new_s1 = next(b['authorization'] for b in swapped['bindings']
                      if b['device'] == 'S1')
        self.schedule(rid, 'show')
        self.show(rid, 'show')
        second = self.device_submit('b', 'S1', new_s1, 'B')
        status, _ = self.controls.deliver_held(self.runtime, '/internal/decide', 'u')
        self.assertEqual(status, 409)
        first = self.device_submit('a', 'S1', old_s1, 'A')
        report = self.close_round(rid, 'close')
        self.assertEqual([row['receipt'] for row in report['seats']],
                         [second, first, None])

    def test_lost_acceptance_reply_recovers_after_reopen(self):
        self.open_device_round()
        rid = self.round_id
        old_s1 = self.auth('S1')
        self.controls.drop_reply_with_status('room', '/internal/decide', 'a', 'decided')
        self.device_submit('a', 'S1', old_s1, 'A', 202)
        self.reopen()
        receipt = self.device_submit('a', 'S1', old_s1, 'A')
        self.assert_receipt(receipt, category='blind', choice='A', correct=True, points=3)
        self.assertEqual((receipt['seat'], receipt['device']), ('甲', 'S1'))
        self.assertEqual(self.lookup(rid, 'submission', 'a'), receipt)

    def test_score_side_swap_reply_loss_still_replays(self):
        from display.inspection import LinkUnavailable
        self.open_device_round()
        self.controls.drop_reply_with_status('score', '/swap_seats', 'swap-9', 'swapped')
        with self.assertRaises(LinkUnavailable):
            self.swap('swap-9')
        # Score committed the swap before its own reply was lost.
        self.assertEqual(
            [b['student'] for b in self.call('/get_round', round_id=self.round_id)['bindings']],
            ['乙', '甲', '丙'],
        )
        done = self.swap('swap-9')
        self.assertEqual([b['student'] for b in done['bindings']], ['乙', '甲'])
        self.assertEqual(self.swap('swap-9'), done)

    def test_consecutive_swaps_rotate_again_and_keep_devices(self):
        self.open_device_round()
        first = self.swap('swap-1')
        new_s2 = next(b['authorization'] for b in first['bindings']
                      if b['device'] == 'S2')
        second = self.swap('swap-2', a='S2', b='S3')
        self.assertEqual([b['device'] for b in second['bindings']], ['S2', 'S3'])
        self.assertEqual([b['student'] for b in second['bindings']], ['丙', '甲'])
        view = self.call('/get_round', round_id=self.round_id)
        current = {b['device']: b for b in view['bindings']}
        self.assertEqual([current[d]['student'] for d in ('S1', 'S2', 'S3')],
                         ['乙', '丙', '甲'])
        # The authorization issued by the first swap for S2 is now superseded.
        self.device_submit('old', 'S2', new_s2, 'A', 409)
        self.assertTrue(current['S2']['authorization'] != new_s2)
