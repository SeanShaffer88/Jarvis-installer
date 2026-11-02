import json
import unittest

from jarvis_win import transport


class FakePipeAPI:
    def __init__(self, available=True, fail=False):
        self.available = available
        self.fail = fail
        self.waits = []
        self.writes = []

    def wait(self, path, timeout_ms):
        self.waits.append((path, timeout_ms))
        return self.available

    def write(self, path, payload, timeout_ms):
        if self.fail:
            raise OSError("pipe write failed")
        self.writes.append((path, payload, timeout_ms))


class FakeSocket:
    def __init__(self, refuse=False):
        self.refuse = refuse
        self.sent = b""
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def connect(self, path):
        if self.refuse:
            raise ConnectionRefusedError()
        self.path = path

    def sendall(self, payload):
        self.sent = payload

    def close(self):
        self.closed = True


class FakeSocketModule:
    AF_UNIX = object()
    SOCK_STREAM = object()

    def __init__(self, socket):
        self.socket = lambda *_args: socket


class TransportTests(unittest.TestCase):
    def test_classify_paths(self):
        self.assertEqual(transport.classify_socket_path(None), "missing")
        self.assertEqual(transport.classify_socket_path(""), "missing")
        self.assertEqual(transport.classify_socket_path(r"\\.\pipe\jarvis-1"),
                         "named_pipe")
        self.assertEqual(transport.classify_socket_path("//./pipe/jarvis-1"),
                         "named_pipe")
        self.assertEqual(transport.classify_socket_path("/tmp/jarvis.sock"),
                         "unix_socket")

    def test_payload_has_auth_then_user_line(self):
        payload = transport.build_payload("  hello  ", token="tok").decode()
        lines = payload.strip().splitlines()
        self.assertEqual(json.loads(lines[0]), {"type": "auth", "token": "tok"})
        self.assertEqual(json.loads(lines[1])["message"]["content"], "hello")

    def test_named_pipe_send(self):
        pipe = FakePipeAPI()
        outcome = transport.send_payload("//./pipe/jarvis-1", "hello",
                                         token="tok", pipe_api=pipe)
        self.assertEqual(outcome, transport.SENT)
        self.assertEqual(len(pipe.writes), 1)
        self.assertTrue(pipe.writes[0][0].startswith(transport.PIPE_PREFIX))
        self.assertIn(b'"type": "auth"', pipe.writes[0][1])

    def test_named_pipe_not_live_and_failed(self):
        self.assertEqual(transport.send_payload(r"\\.\pipe\none", "hello",
                                                pipe_api=FakePipeAPI(False)),
                         transport.NOT_LIVE)
        self.assertEqual(transport.send_payload(r"\\.\pipe\broken", "hello",
                                                pipe_api=FakePipeAPI(True, True)),
                         transport.FAILED)

    def test_af_unix_send(self):
        sock = FakeSocket()
        outcome = transport.send_payload("/tmp/jarvis.sock", "hello",
                                         token="", socket_module=FakeSocketModule(sock),
                                         exists=lambda _path: True)
        self.assertEqual(outcome, transport.SENT)
        self.assertTrue(sock.closed)
        self.assertIn(b'"type": "user"', sock.sent)

    def test_refused_and_blank_prompt(self):
        self.assertEqual(transport.send_payload(None, "hello"), transport.NOT_LIVE)
        self.assertEqual(transport.send_payload("/tmp/x.sock", "   "),
                         transport.REFUSED)
        sock = FakeSocket(refuse=True)
        self.assertEqual(transport.send_payload("/tmp/x.sock", "hello",
                                                socket_module=FakeSocketModule(sock),
                                                exists=lambda _path: True),
                         transport.NOT_LIVE)


if __name__ == "__main__":
    unittest.main()
