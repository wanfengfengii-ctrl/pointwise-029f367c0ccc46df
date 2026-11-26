import base64
from contextlib import ExitStack
import io
import json
from pathlib import Path
import shutil
import tempfile
from threading import Lock
import unittest
import wave
import zlib

from submission.http_service import SAMPLES, build_runtime, exchange


class TransportControls:
    def __init__(self):
        self._lock = Lock()
        self._held = set()
        self._drops = set()
        self.dropped = []

    def hold_delivery(self, path, request_id):
        with self._lock:
            self._held.add((path, request_id))

    def release_delivery(self, path, request_id):
        with self._lock:
            self._held.remove((path, request_id))

    def drop_next_reply(self, side, path, request_id):
        with self._lock:
            self._drops.add((side, path, request_id))

    def before_forward(self, path, body):
        with self._lock:
            return (path, body.get('request_id')) in self._held

    def before_reply(self, side, path, body, result):
        if result.get('status') not in ('accepted', 'decided', 'shown'):
            return False
        key = (side, path, body.get('request_id'))
        with self._lock:
            if key not in self._drops:
                return False
            self._drops.remove(key)
            self.dropped.append((key, result))
            return True


def write_clip(path, frames):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as audio:
        audio.setparams((1, 1, 8000, 0, 'NONE', 'not compressed'))
        audio.writeframes(frames)
    path.write_bytes(base64.b64encode(zlib.compress(buffer.getvalue())) + b'\n')


class ClassroomCase(unittest.TestCase):
    def setUp(self):
        self.workspace = ExitStack()
        self.addCleanup(self.workspace.close)
        root = Path(self.workspace.enter_context(tempfile.TemporaryDirectory(prefix='songlan-test-')))
        self.audio_dir = root / 'audio'
        self.audio_dir.mkdir()
        shutil.copyfile(SAMPLES / 'two-pulses.wav.z64', self.audio_dir / 'two-pulses.wav.z64')
        self.data_dir = root / 'data'
        self.controls = TransportControls()
        self.running = ExitStack()
        self.addCleanup(self.running.close)
        self.start()

    def start(self):
        self.runtime = self.running.enter_context(build_runtime(
            self.data_dir, self.audio_dir,
            before_forward=self.controls.before_forward, before_reply=self.controls.before_reply,
        ))

    def reopen(self):
        self.running.close()
        self.start()

    def call(self, path, *, side='score', status=200, **body):
        received_status, result = exchange(self.runtime.address(side), path, body)
        self.assertEqual(received_status, status, (path, body, result))
        return result

    def draft(self, *, answer='A', points=3):
        draft = json.loads((SAMPLES / 'daily.json').read_text(encoding='utf-8'))
        draft['questions'][0].update(answer=answer, points=points)
        return draft

    def publish(self, **changes):
        return self.call('/publish', **self.draft(**changes))['edition_id']

    def open_round(self, edition=None, seats=None):
        edition = self.publish() if edition is None else edition
        seats = ['甲', '乙', '丙'] if seats is None else seats
        return self.call('/open_round', edition_id=edition, question_id='pulses', seats=seats)['round_id']

    def submit(self, round_id, seat, request_id, choice, status=200):
        return self.call('/submit', status=status, round_id=round_id, seat=seat,
                         request_id=request_id, choice=choice)

    def lookup(self, round_id, kind, request_id, status=200):
        return self.call('/lookup', status=status, round_id=round_id, kind=kind, request_id=request_id)

    def schedule(self, round_id, request_id, status=202):
        return self.call('/reveal', status=status, round_id=round_id, request_id=request_id)

    def show(self, round_id, request_id, *, side='score', status=200):
        return self.call('/apply_display', side=side, status=status,
                         round_id=round_id, request_id=request_id)

    def screen(self, round_id):
        return self.call('/current_display', side='room', round_id=round_id)

    def close_round(self, round_id, request_id, status=200):
        return self.call('/close_round', status=status, round_id=round_id, request_id=request_id)

    def assert_receipt(self, receipt, *, category, choice, correct, points):
        self.assertEqual(receipt['status'], 'accepted')
        self.assertEqual((receipt['category'], receipt['choice'], receipt['correct'], receipt['points']),
                         (category, choice, correct, points))

    def assert_pending(self, result, round_id, request_id):
        self.assertEqual(result, {'status': 'pending', 'round_id': round_id, 'request_id': request_id})
