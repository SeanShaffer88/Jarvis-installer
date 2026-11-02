import unittest
from unittest.mock import patch

from jarvis_win import session_steer_win, session_watch_win
from tests._stubs import session_steer_module, session_watch_module


class SessionPatchTests(unittest.TestCase):
    def test_windows_pid_liveness_and_pipe_steerability(self):
        module = session_watch_module()
        session_watch_win.apply(module)
        with patch.object(session_watch_win.win32, "pid_alive",
                          return_value=True) as alive, \
             patch.object(session_watch_win.transport, "transport_exists",
                          return_value=True) as exists:
            self.assertTrue(module.pid_alive(4242))
            entry = module.RosterEntry(socket_path=r"\\.\pipe\jarvis-1")
            self.assertTrue(entry.steerable)
        alive.assert_called_once_with(4242)
        exists.assert_called_once_with(r"\\.\pipe\jarvis-1")

    def test_steer_delegates_to_transport_with_same_outcomes(self):
        module = session_steer_module()
        session_steer_win.apply(module)
        with patch.object(session_steer_win.transport, "send_payload",
                          return_value=module.SENT) as send:
            outcome = module.post_to_session(r"\\.\pipe\jarvis-1", "hello", timeout=2.0)
        self.assertEqual(outcome, module.SENT)
        send.assert_called_once_with(r"\\.\pipe\jarvis-1", "hello", timeout=2.0)


if __name__ == "__main__":
    unittest.main()
