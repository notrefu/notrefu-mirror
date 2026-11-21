import threading
import time
import unittest

from notrefu_mirror import engine
from notrefu_mirror.session_logic import stop_clients


class FakeClient:
    def __init__(self, delay=0.0):
        self.delay, self.stopped, self._done = delay, False, threading.Event()

    def stop(self, wait=4.0):
        self.stopped = True
        threading.Timer(self.delay, self._done.set).start()

    def wait_stopped(self, timeout):
        return self._done.wait(max(0.0, timeout))


class StopClients(unittest.TestCase):
    def test_parallel_not_sequential(self):
        cs = [FakeClient(0.4) for _ in range(5)]
        t0 = time.monotonic()
        late = stop_clients(cs, 3.0)
        took = time.monotonic() - t0
        self.assertEqual(late, 0)
        self.assertTrue(all(c.stopped for c in cs))
        self.assertLess(took, 1.2)  # en série ce serait 2 s

    def test_deadline_is_global(self):
        cs = [FakeClient(30) for _ in range(4)]
        t0 = time.monotonic()
        late = stop_clients(cs, 0.6)
        self.assertEqual(late, 4)
        self.assertLess(time.monotonic() - t0, 1.5)  # 0,6 s au total, pas 0,6 s par session

    def test_none_ignored(self):
        self.assertEqual(stop_clients([None], 0.1), 0)


class Background(unittest.TestCase):
    def test_join_background(self):
        ev = threading.Event()
        t = threading.Thread(target=lambda: ev.wait(5), daemon=True)
        with engine._BG_LOCK:
            engine._BG_THREADS[:] = [t]
        t.start()
        self.assertFalse(engine.join_background(0.2))
        ev.set()
        self.assertTrue(engine.join_background(2))


if __name__ == "__main__":
    unittest.main()
