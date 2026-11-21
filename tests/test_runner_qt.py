import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QObject  # noqa: E402
import shiboken6  # noqa: E402

from notrefu_mirror.ui.common import _Runner  # noqa: E402

app = QCoreApplication.instance() or QCoreApplication([])


def pump(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end and not cond():
        app.processEvents()
        time.sleep(0.01)
    return cond()


class Owner(QObject):
    def __init__(self):
        super().__init__()
        self.got = []

    def done(self, value, err):
        self.got.append((value, err))


class RunnerTests(unittest.TestCase):
    def test_result_and_error(self):
        r, got = _Runner(), []
        r.run(lambda: 42, lambda v, e: got.append((v, e)))
        r.run(lambda: 1 / 0, lambda v, e: got.append((v, type(e).__name__)))
        self.assertTrue(pump(lambda: len(got) == 2))
        self.assertIn((42, None), got)
        self.assertIn((None, "ZeroDivisionError"), got)
        r.shutdown()

    def test_dead_owner_is_skipped(self):
        r, o = _Runner(), Owner()
        r.run(lambda: (time.sleep(0.2), 1)[1], o.done)
        shiboken6.delete(o)  # le widget disparaît avant la fin de la tâche
        pump(lambda: False, 0.6)  # ne doit lever aucune erreur
        r.shutdown()

    def test_deleted_object_error_is_swallowed_but_others_raise(self):
        r = _Runner()

        def gone(v, e):
            raise RuntimeError("Internal C++ object (X) already deleted.")
        r._deliver((gone, 1, None))  # sans effet
        with self.assertRaises(RuntimeError):
            r._deliver((lambda v, e: (_ for _ in ()).throw(RuntimeError("autre")), 1, None))
        r.shutdown()

    def test_shutdown_stops_new_work(self):
        r, got = _Runner(), []
        self.assertTrue(r.shutdown(500))
        r.run(lambda: 1, lambda v, e: got.append(v))
        pump(lambda: False, 0.3)
        self.assertEqual(got, [])


if __name__ == "__main__":
    unittest.main()
