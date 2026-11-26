import base64
import io
import wave

from tests.support import ClassroomCase, write_clip


class MaterialsTests(ClassroomCase):
    def test_v1_edition_binding(self):
        first = self.publish()
        old = self.open_round(first)
        second = self.publish(answer='B', points=5)
        new = self.open_round(second)
        self.assertNotEqual(first, second)
        self.assertEqual(self.call('/get_round', round_id=old)['edition_id'], first)
        self.assertEqual(self.call('/get_round', round_id=new)['edition_id'], second)
        self.assert_receipt(self.submit(old, '甲', 'old-a', 'A'),
                            category='blind', choice='A', correct=True, points=3)
        self.assert_receipt(self.submit(new, '甲', 'new-a', 'A'),
                            category='blind', choice='A', correct=False, points=0)

    def test_v1_archive_reopen(self):
        first = self.publish()
        old = self.open_round(first)
        original = self.call('/play_prompt', round_id=old)['audio']
        source = self.audio_dir / 'two-pulses.wav.z64'
        replacement_frames = bytes([128, 160, 128, 96]) * 100
        write_clip(source, replacement_frames)
        second = self.publish(answer='B', points=7)
        new = self.open_round(second)
        source.unlink()
        self.reopen()
        self.assertTrue(self.call('/get_round', round_id=old)['played'])
        self.assertEqual(self.call('/play_prompt', round_id=old)['audio'], original)
        updated = self.call('/play_prompt', round_id=new)['audio']
        self.assertNotEqual(updated['wav_base64'], original['wav_base64'])
        with wave.open(io.BytesIO(base64.b64decode(updated['wav_base64'])), 'rb') as audio:
            self.assertEqual(audio.readframes(400), replacement_frames)
        self.assert_receipt(self.submit(old, '甲', 'archive-a', 'A'),
                            category='blind', choice='A', correct=True, points=3)
        self.assert_receipt(self.submit(new, '甲', 'archive-b', 'B'),
                            category='blind', choice='B', correct=True, points=7)
        self.schedule(old, 'archive-display')
        self.assertEqual(self.show(old, 'archive-display')['frame']['answer'], 'A')
        self.assertEqual(self.close_round(old, 'archive-close')['edition_id'], first)

    def test_v1_round_guards(self):
        edition = self.publish()
        for edition_id, question_id, seats, status, error in (
            (edition + 1, 'pulses', ['甲'], 404, 'unknown_edition'),
            (edition, 'absent', ['甲'], 404, 'unknown_question'),
            (edition, 'pulses', [], 400, 'empty_roster'),
            (edition, 'pulses', ['甲', '甲'], 400, 'duplicate_seat'),
            (edition, 'pulses', ['甲', ' '], 400, 'invalid_seat'),
        ):
            with self.subTest(error=error):
                result = self.call('/open_round', status=status, edition_id=edition_id,
                                   question_id=question_id, seats=seats)
                self.assertEqual(result, {'error': error})
        self.call('/get_round', status=404, round_id=1)
        self.call('/play_prompt', status=404, round_id=1)
        self.open_round(edition)

    def test_v1_prompt_playback(self):
        draft = self.draft()
        proof = self.call('/proof', **draft)
        self.assertEqual(proof['questions'][0]['answer'], 'A')
        self.call('/open_round', status=404, edition_id=1, question_id='pulses', seats=['甲'])
        round_id = self.open_round(seats=['乙', '甲'])
        opened = self.call('/get_round', round_id=round_id)
        self.assertFalse(opened['played'])
        self.assertEqual(opened['seats'], ['乙', '甲'])
        played = self.call('/play_prompt', round_id=round_id)
        read = self.call('/read_prompt', round_id=round_id)
        prompt = {'question_id': 'pulses', 'prompt': '短音响了几次？',
                  'audio_ref': 'two-pulses.wav.z64',
                  'options': [{'id': 'A', 'label': '两次'}, {'id': 'B', 'label': '一次'}]}
        self.assertEqual(opened['prompt'], prompt)
        self.assertEqual(played['prompt'], prompt)
        self.assertEqual(read['prompt'], prompt)
        with wave.open(io.BytesIO(base64.b64decode(played['audio']['wav_base64'])), 'rb') as audio:
            self.assertEqual((audio.getframerate(), audio.getnframes()), (8000, 2080))
            frames = audio.readframes(2080)
        self.assertNotEqual(set(frames[:800]), {128})
        self.assertEqual(set(frames[800:1280]), {128})
        self.assertNotEqual(set(frames[1280:]), {128})
        self.assertTrue(self.call('/get_round', round_id=round_id)['played'])

    def test_v2_answer_must_belong_to_new_question(self):
        issued = self.publish()
        invalid = self.draft()
        invalid['questions'][0]['options'] = [{'id': 'B', 'label': '一次'}, {'id': 'C', 'label': '三次'}]
        self.assertEqual(self.call('/publish', status=400, **invalid), {'error': 'invalid_answer_key'})
        self.call('/open_round', status=404, edition_id=issued + 1, question_id='pulses', seats=['甲'])
        round_id = self.open_round(issued)
        self.assert_receipt(self.submit(round_id, '甲', 'prior-a', 'A'),
                            category='blind', choice='A', correct=True, points=3)

    def test_v2_invalid_materials(self):
        issued = self.publish()
        cases = [
            ({'audio': 'missing.wav.z64'}, 'invalid_audio'),
            ({'audio': '../two-pulses.wav.z64'}, 'invalid_audio_reference'),
            ({'options': []}, 'invalid_options'),
            ({'options': [{'id': 'A', 'label': '甲'}, {'id': 'A', 'label': '乙'}]}, 'duplicate_option'),
            ({'points': -1}, 'invalid_points'),
            ({'points': True}, 'invalid_points'),
            ({'points': 1.5}, 'invalid_points'),
        ]
        for changes, error in cases:
            with self.subTest(changes=changes):
                draft = self.draft()
                invalid = {**draft['questions'][0], **changes, 'id': 'second-question'}
                draft['questions'].append(invalid)
                self.assertEqual(self.call('/publish', status=400, **draft), {'error': error})
        broken = self.audio_dir / 'broken.wav.z64'
        broken.write_text('AAAA\n', encoding='ascii')
        draft = self.draft()
        draft['questions'][0]['audio'] = broken.name
        self.assertEqual(self.call('/publish', status=400, **draft), {'error': 'invalid_audio'})
        self.call('/open_round', status=404, edition_id=issued + 1, question_id='pulses', seats=['甲'])
        self.open_round(issued)
