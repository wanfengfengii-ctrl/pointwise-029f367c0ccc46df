import argparse
from contextlib import closing
from functools import partial
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from inspect import signature
import json
from pathlib import Path
import secrets
import socket
import sqlite3
import tempfile
from threading import Event, Thread
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from display.inspection import DisplayInspection, LinkUnavailable
from display.jobs import RevealJobs
from display.outcomes import DisplayOutcomes
from display.reveal import RevelationService
from display.screen import build_answer_frame
from display.seat_swaps import ClassroomSeatSwaps
from exercise.catalog import EditionCatalog
from exercise.publication import PublicationService
from lesson.classroom import ClassroomService
from lesson.prompt_playback import PromptPlayback
from lesson.round_store import RoundStore
from lesson.rounds import Conflict, require_request_id, require_round_id
from lesson.swap_ops import SeatSwapOperations, SeatSwapService
from review.finalize import ReviewService
from review.history import ReviewHistory
from review.snapshot_store import ReviewSnapshotStore
from submission.admission import AdmissionService
from submission.intake import SubmissionService
from submission.operations import RevealDispatchStore, SubmissionOperations


SAMPLES = Path(__file__).resolve().parents[1] / 'samples'


def exchange(address, path, body, token=None):
    headers = {'Content-Type': 'application/json'}
    if token is not None:
        headers['X-Classroom-Token'] = token
    request = Request(
        address + path, json.dumps(body).encode('utf-8'), headers=headers, method='POST',
    )
    opener = build_opener(ProxyHandler({}))
    try:
        try:
            reply = opener.open(request, timeout=4)
        except HTTPError as error:
            reply = error
        with reply:
            return reply.code, json.loads(reply.read())
    except (OSError, HTTPException) as error:
        raise LinkUnavailable('classroom_transport_unavailable') from error


class ClassroomLink:
    def __init__(self, address, token, before_forward):
        self.address = address
        self.token = token
        self.before_forward = before_forward

    def call(self, path, body):
        if self.before_forward is not None and self.before_forward(path, body):
            raise LinkUnavailable('classroom_delivery_deferred')
        status, result = exchange(self.address, path, body, self.token)
        if status == 404:
            raise KeyError(result['error'])
        if status == 409:
            raise Conflict(result['error'])
        if status == 400:
            raise ValueError(result['error'])
        if status not in (200, 202):
            raise LinkUnavailable('classroom_reply_unavailable')
        return result

    def decide_submission(self, identity, device=None, authorization=None):
        body = dict(identity)
        if device is not None:
            body['device'] = device
        if authorization is not None:
            body['authorization'] = authorization
        return self.call('/internal/decide', body)

    def swap_seats(self, body):
        return self.call('/internal/swap_seats', body)

    def round_reveal_status(self, round_id):
        return self.call('/internal/reveal_status', {'round_id': round_id})


def pending(round_id, request_id):
    return {'status': 'pending', 'round_id': round_id, 'request_id': request_id}


class RevealRelay:
    def __init__(self, rounds, dispatch, room):
        self.rounds = rounds
        self.dispatch = dispatch
        self.room = room

    def _forward(self, db, path, body, stage):
        request_id = body['request_id']
        with db:
            self.dispatch.note(db, request_id, stage + '_sent')
        try:
            result = self.room.call(path, body)
        except LinkUnavailable:
            with db:
                self.dispatch.note(db, request_id, stage + '_unconfirmed')
            return pending(body['round_id'], request_id)
        with db:
            self.dispatch.note(db, request_id, stage + '_answered')
        return result

    def reveal(self, db, round_id, request_id):
        require_request_id(request_id)
        with db:
            db.execute('BEGIN IMMEDIATE')
            round_ = self.rounds.get(db, round_id)
            if not round_.is_open() and self.dispatch.for_round(db, round_id) != request_id:
                raise Conflict('round_closed')
            self.dispatch.register(db, round_id, request_id)
            frame = build_answer_frame(round_)
        return self._forward(db, '/internal/reveal', {
            'round_id': round_id, 'request_id': request_id, 'frame': frame.to_dict(),
        }, 'schedule')

    def apply_display(self, db, round_id, request_id):
        require_round_id(round_id)
        require_request_id(request_id)
        self.dispatch.require(db, round_id, request_id)
        try:
            return self._forward(db, '/apply_display', {
                'round_id': round_id, 'request_id': request_id,
            }, 'display')
        except KeyError:
            return pending(round_id, request_id)

    def lookup(self, db, round_id, request_id):
        self.dispatch.require(db, round_id, request_id)
        try:
            return self.room.call('/internal/lookup_reveal', {
                'round_id': round_id, 'request_id': request_id,
            })
        except (LinkUnavailable, KeyError):
            return pending(round_id, request_id)


class LocalHttpHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _body(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 65536:
                raise ValueError
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError
            return body
        except (ValueError, UnicodeError, RecursionError) as error:
            raise ValueError('invalid_json_body') from error

    def _send(self, status, body):
        data = json.dumps(body, ensure_ascii=True).encode('utf-8')
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def do_POST(self):
        runtime = self.server.runtime
        side = self.server.side
        path = self.path
        route = runtime.routes[side].get(path)
        if route is None or (path.startswith('/internal/')
                             and self.headers.get('X-Classroom-Token') != runtime.token):
            self._send(404, {'error': 'unknown_route'})
            return
        try:
            body = self._body()
            with closing(runtime.connect(side)) as db:
                args = () if path == '/proof' else (db,)
                try:
                    signature(route).bind(*args, **body)
                except TypeError as error:
                    raise ValueError('invalid_arguments') from error
                result = route(*args, **body)
        except ValueError as error:
            self._send(400, {'error': str(error)})
            return
        except Conflict as error:
            self._send(409, {'error': str(error)})
            return
        except KeyError as error:
            self._send(404, {'error': error.args[0]})
            return
        except LinkUnavailable as error:
            self._send(503, {'error': str(error)})
            return
        if runtime.before_reply is not None and runtime.before_reply(side, path, body, result):
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            return
        self._send(202 if result.get('status') == 'pending' else 200, result)


class ServiceRuntime:
    def __init__(self, data_dir, audio_dir, score_port, room_port, before_forward, before_reply):
        data_dir.mkdir(parents=True, exist_ok=True)
        self.databases = {
            'score': data_dir / 'grades.sqlite3', 'room': data_dir / 'classroom.sqlite3',
        }
        self.token = secrets.token_hex(24)
        self.before_reply = before_reply
        self.servers = {}
        self.threads = []

        catalog = EditionCatalog()
        rounds = RoundStore(catalog)
        operations = SubmissionOperations()
        swap_operations = SeatSwapOperations()
        dispatch = RevealDispatchStore()
        snapshots = ReviewSnapshotStore()
        jobs = RevealJobs()
        outcomes = DisplayOutcomes()
        room_swaps = ClassroomSeatSwaps()
        self._initialize('score', (catalog, rounds, operations, swap_operations,
                                   dispatch, snapshots))
        self._initialize('room', (jobs, outcomes, room_swaps))

        try:
            for side, port in (('score', score_port), ('room', room_port)):
                server = ThreadingHTTPServer(('127.0.0.1', port), LocalHttpHandler)
                server.runtime = self
                server.side = side
                self.servers[side] = server
        except OSError:
            for server in self.servers.values():
                server.server_close()
            raise

        room = ClassroomLink(self.address('room'), self.token, before_forward)
        publication = PublicationService(audio_dir, catalog)
        classroom = ClassroomService(catalog, rounds)
        playback = PromptPlayback(rounds)
        inspection = DisplayInspection(jobs, outcomes)
        revelation = RevelationService(jobs, outcomes, inspection)
        relay = RevealRelay(rounds, dispatch, room)
        admission = AdmissionService(rounds, operations)
        history = ReviewHistory(snapshots)
        intake = SubmissionService(operations, admission, room, relay, history)
        seat_swaps = SeatSwapService(rounds, swap_operations, room)
        review = ReviewService(rounds, operations, dispatch, room, snapshots, history,
                               swap_operations)
        self.routes = {
            'score': {
                '/proof': publication.proof,
                '/publish': publication.publish,
                '/open_round': classroom.open_round,
                '/get_round': classroom.get_round,
                '/read_prompt': playback.read_prompt,
                '/play_prompt': playback.play,
                '/submit': intake.submit,
                '/swap_seats': seat_swaps.swap_seats,
                '/lookup': intake.lookup,
                '/reveal': relay.reveal,
                '/apply_display': relay.apply_display,
                '/close_round': review.close_round,
            },
            'room': {
                '/apply_display': revelation.apply_display,
                '/current_display': inspection.current_display,
                '/internal/reveal': revelation.reveal,
                '/internal/lookup_reveal': inspection.lookup_reveal,
                '/internal/reveal_status': inspection.round_reveal_status,
                '/internal/decide': outcomes.decide_submission,
                '/internal/swap_seats': room_swaps.apply_swap,
            },
        }

    def connect(self, side):
        db = sqlite3.connect(self.databases[side], timeout=4)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        return db

    def _initialize(self, side, stores):
        with closing(self.connect(side)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            for store in stores:
                store.initialize(db)

    def address(self, side):
        host, port = self.servers[side].server_address
        return f'http://{host}:{port}'

    def __enter__(self):
        for server in self.servers.values():
            loop = partial(server.serve_forever, poll_interval=0.05)
            thread = Thread(target=loop, daemon=True)
            thread.start()
            self.threads.append((server, thread))
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        for server, _ in self.threads:
            server.shutdown()
        for server, thread in self.threads:
            thread.join()
            server.server_close()


def build_runtime(data_dir, audio_dir=SAMPLES, *, score_port=0, room_port=0,
                  before_forward=None, before_reply=None):
    return ServiceRuntime(
        Path(data_dir), Path(audio_dir), score_port, room_port, before_forward, before_reply,
    )


def serve_local(data_dir, audio_dir, score_port, room_port):
    with build_runtime(data_dir, audio_dir, score_port=score_port, room_port=room_port) as runtime:
        print(json.dumps({side: runtime.address(side) for side in ('score', 'room')}), flush=True)
        try:
            Event().wait()
        except KeyboardInterrupt:
            return


def run_demo():
    with tempfile.TemporaryDirectory(prefix='songlan-demo-') as directory:
        with build_runtime(directory) as runtime:
            def score(path, status=200, **body):
                code, data = exchange(runtime.address('score'), path, body)
                if code != status:
                    raise RuntimeError(f'{path}: expected HTTP {status}, got {code}: {data}')
                return data

            draft = json.loads((SAMPLES / 'daily.json').read_text(encoding='utf-8'))
            edition = score('/publish', **draft)['edition_id']
            round_id = score('/open_round', edition_id=edition, question_id='pulses',
                             seats=['甲', '乙', '丙'])['round_id']
            played = score('/play_prompt', round_id=round_id)
            first = score('/submit', round_id=round_id, seat='甲', request_id='a1', choice='A')
            score('/reveal', 202, round_id=round_id, request_id='r1')
            shown = score('/apply_display', round_id=round_id, request_id='r1')
            second = score('/submit', round_id=round_id, seat='乙', request_id='b1', choice='B')
            review = score('/close_round', round_id=round_id, request_id='close-1')
        with build_runtime(directory) as runtime:
            status, replay = exchange(runtime.address('score'), '/lookup', {
                'round_id': round_id, 'kind': 'close', 'request_id': 'close-1',
            })
            if status != 200 or replay != review:
                raise RuntimeError('复盘复领不一致')

        actual = [[entry['category'], entry['choice'], entry['points'], entry['correct']]
                  for entry in (first, second)]
        expected = [['blind', 'A', 3, True], ['hinted', 'B', 0, False]]
        downstream_expected = {
            'seats': [['甲', 'A', 3], ['乙', 'B', 0], ['丙', None, None]],
            'totals': {
                'blind': {'count': 1, 'points': 3, 'correct': 1},
                'hinted': {'count': 1, 'points': 0, 'correct': 0},
            },
        }
        downstream_actual = {
            'seats': [[entry['seat'], entry['choice'], entry['points']] for entry in replay['seats']],
            'totals': replay['totals'],
        }
        if (actual != expected or downstream_actual != downstream_expected
                or shown['frame']['answer'] != 'A' or played['audio']['frame_count'] != 2080):
            raise RuntimeError(f'样例核对失败: {actual}, {downstream_actual}')
        evidence = {
            'case_id': 'v7',
            'input': {'question': 'pulses', 'answer': 'A', 'points': 3, 'editions': [edition],
                      'events': ['play', '甲:A', 'display', '乙:B', 'close', 'reopen']},
            'expected': expected,
            'actual': actual,
            'downstream_expected': downstream_expected,
            'downstream_actual': downstream_actual,
            'code_paths': ['submission/scoring.py', 'display/reveal.py',
                           'review/roster_results.py', 'review/breakdown.py', 'review/snapshot_store.py'],
            'oracle': '按样例答案键手算甲乙两卷并逐类求和，丙按固定名单单列。',
        }
        print('POINTWISE_SCENARIO ' + json.dumps(evidence, ensure_ascii=False))
    run_seat_swap_demo()


def run_seat_swap_demo():
    """Reproduce SEAT_SWAPS.md main scene: lost acceptance reply, held old
    order, swap, late rejection and replay of the review by close number."""
    from copy import deepcopy
    from threading import Lock

    with tempfile.TemporaryDirectory(prefix='songlan-swap-') as directory:
        lock = Lock()
        held = {('/internal/decide', 'u')}
        captured = {}
        drops = {('room', '/internal/decide', 'a'): 'decided'}

        def before_forward(path, body):
            key = (path, body.get('request_id'))
            with lock:
                if key in held:
                    captured[key] = deepcopy(body)
                    return True
            return False

        def before_reply(side, path, body, result):
            key = (side, path, body.get('request_id'))
            with lock:
                wanted = drops.get(key)
                if wanted is not None and result.get('status') == wanted:
                    del drops[key]
                    return True
            return False

        with build_runtime(directory, before_forward=before_forward,
                           before_reply=before_reply) as runtime:
            def call(path, status=200, side='score', token=False, **body):
                code, data = exchange(
                    runtime.address(side), path, body,
                    runtime.token if token else None,
                )
                if code != status:
                    raise RuntimeError(
                        f'{side}{path}: expected HTTP {status}, got {code}: {data}',
                    )
                return data

            draft = json.loads((SAMPLES / 'daily.json').read_text(encoding='utf-8'))
            edition = call('/publish', **draft)['edition_id']
            opened = call('/open_round', edition_id=edition, question_id='pulses', seats=[
                {'device': 'S1', 'student': '甲'},
                {'device': 'S2', 'student': '乙'},
                {'device': 'S3', 'student': '丙'},
            ])
            rid = opened['round_id']
            auth = {b['device']: b['authorization'] for b in opened['bindings']}
            call('/play_prompt', round_id=rid)

            waiting_a = call('/submit', 202, round_id=rid, request_id='a',
                             device='S1', authorization=auth['S1'], choice='A')
            waiting_u = call('/submit', 202, round_id=rid, request_id='u',
                             device='S2', authorization=auth['S2'], choice='B')
            swapped = call('/swap_seats', round_id=rid, request_id='swap-1',
                           device_a='S1', device_b='S2')
            new_auth = {b['device']: b['authorization'] for b in swapped['bindings']}

            call('/reveal', 202, round_id=rid, request_id='show')
            call('/apply_display', round_id=rid, request_id='show')

            second = call('/submit', round_id=rid, request_id='b', device='S1',
                          authorization=new_auth['S1'], choice='B')

            held_body = captured.pop(('/internal/decide', 'u'))
            with lock:
                held.discard(('/internal/decide', 'u'))
            late_status, late_body = exchange(
                runtime.address('room'), '/internal/decide', held_body, runtime.token,
            )
            score_late_status, score_late_body = exchange(
                runtime.address('score'), '/submit', {
                    'round_id': rid, 'request_id': 'u', 'device': 'S2',
                    'authorization': auth['S2'], 'choice': 'B',
                },
            )
            first = call('/submit', round_id=rid, request_id='a', device='S1',
                         authorization=auth['S1'], choice='A')
            review = call('/close_round', round_id=rid, request_id='close-swap')

        with build_runtime(directory) as runtime:
            replay_status, replay = exchange(runtime.address('score'), '/lookup', {
                'round_id': rid, 'kind': 'close', 'request_id': 'close-swap',
            })
        if replay_status != 200 or replay != review:
            raise RuntimeError('调位复盘按原关轮号复领不一致')

        order = [(row['device'], row['seat']) for row in replay['seats']]
        checks = {
            'waiting_a': waiting_a,
            'waiting_u': waiting_u,
            'swap_status': swapped['status'],
            'order': order,
            'a_receipt': [first['category'], first['points'], first['device']],
            'b_receipt': [second['category'], second['points'], second['device']],
            'late_room_http': late_status,
            'late_room_error': late_body.get('error'),
            'late_score_http': score_late_status,
            'late_score_error': score_late_body.get('error'),
            'replay_close_matches': replay == review,
            'jia_close_device': replay['seats'][1]['device'],
            'jia_receipt_device': replay['seats'][1]['receipt']['device'],
        }
        expected_order = [['S1', '乙'], ['S2', '甲'], ['S3', '丙']]
        if (order != [tuple(x) for x in expected_order]
                or checks['a_receipt'] != ['blind', 3, 'S1']
                or checks['b_receipt'] != ['hinted', 0, 'S1']
                or late_status != 409 or score_late_status != 409
                or not checks['replay_close_matches']
                or checks['jia_close_device'] != 'S2'
                or checks['jia_receipt_device'] != 'S1'):
            raise RuntimeError(f'调位样例核对失败: {json.dumps(checks, ensure_ascii=False)}')
        print('SEAT_SWAP_DEMO ' + json.dumps(checks, ensure_ascii=False))
        evidence = {
            'case_id': 'seat-swap',
            'input': {
                'question': 'pulses', 'answer': 'A', 'points': 3,
                'events': ['a:S1:A(reply-lost)', 'u:S2:B(held)', 'swap S1/S2',
                           'display', 'b:S1:B(new-auth)', 'release u',
                           'a resume', 'close', 'reopen replay'],
            },
            'actual': checks,
            'oracle': '甲原单领回 blind/3/S1；乙新授权 S1 首交 hinted/0；'
                      '旧授权 u 迟达 409；复盘按最终设备序 S1乙 S2甲 S3丙。',
        }
        print('POINTWISE_SEAT_SWAP_SCENARIO '
              + json.dumps(evidence, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description='松岚听辨教室')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('demo')
    server = commands.add_parser('serve')
    server.add_argument('--data', type=Path, required=True)
    server.add_argument('--audio-dir', type=Path, default=SAMPLES)
    server.add_argument('--score-port', type=int, default=0)
    server.add_argument('--room-port', type=int, default=0)
    args = parser.parse_args()
    if args.command == 'demo':
        run_demo()
    else:
        serve_local(args.data, args.audio_dir, args.score_port, args.room_port)


if __name__ == '__main__':
    main()
