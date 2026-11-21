"""Cas limites trouvés par l'audit QA : chaque test reproduit un défaut réel corrigé."""
import json
import os
import tempfile
import unittest

from notrefu_mirror import settingsio
from notrefu_mirror.scrcpy_cmd import valid_package
from notrefu_mirror.session_config import SessionConfig
from notrefu_mirror.session_logic import stop_clients, wifi_target
from notrefu_mirror.session_plan import DisplayRequest, plan_display
from notrefu_mirror.wireless import parse_port, valid_ip


class Inputs(unittest.TestCase):
    def test_unicode_digits_do_not_crash(self):
        for s in ("²", "٣", "５５５５", "1e3", "-1", "+5"):
            self.assertIsNone(parse_port(s))
        self.assertIsNone(wifi_target("h:²"))

    def test_package_rejects_newline_and_exotic_digits(self):
        self.assertFalse(valid_package("com.a.b\n@1"))
        self.assertFalse(valid_package("com.a.b@²"))
        self.assertFalse(valid_package("com.évil.x"))
        self.assertFalse(valid_package("a.b;rm -rf /"))
        self.assertTrue(valid_package("com.ankama.dofustouch@10"))

    def test_ip_strict(self):
        for bad in ("999.999.999.999", "١٩٢.١٦٨.١.١", "1.2.3", "1.2.3.4.5", "::1", "a.b.c.d", ""):
            self.assertFalse(valid_ip(bad), bad)
        self.assertTrue(valid_ip(" 192.168.1.20 "))

    def test_plan_display_never_divides_by_zero(self):
        for w in (0, -5, 1):
            for h in (0, -5, 1):
                plan_display(DisplayRequest("horizontal", w, h, 0, "perso", 301, 201, True, 3.0, -10))

    def test_config_load_survives_garbage(self):
        class S(dict):
            def value(self, k, d=None): return self.get(k, d)
        for bad in (float("inf"), "²", object(), [1], "nan"):
            SessionConfig.load(S({f"p/{k}": bad for k in ("zoom", "br_v", "playtime", "volume")}), "p")


class ImportFile(unittest.TestCase):
    def test_deeply_nested_json_is_an_error_not_a_crash(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.json")
            with open(p, "w") as f:
                f.write("[" * 200000 + "]" * 200000)
            with self.assertRaises(settingsio.SettingsFileError):
                settingsio.read_file(p)

    def test_bad_keys_skipped(self):
        class Q(dict):
            def allKeys(self): return list(self)
            def remove(self, k): self.pop(k, None)
            def setValue(self, k, v): self[k] = v
            def sync(self): pass
        q = Q()
        n = settingsio.apply_to(q, {"": 1, "/": 2, "a//b": 3, "../x": 4, "ok": 5})
        self.assertEqual((n, dict(q)), (1, {"ok": 5}))


class Shutdown(unittest.TestCase):
    def test_failing_client_does_not_block_others(self):
        class Bad:
            def stop(self, wait=0): raise RuntimeError("boom")
            def wait_stopped(self, t): return True

        class Good:
            stopped = False
            def stop(self, wait=0): Good.stopped = True
            def wait_stopped(self, t): return True
        stop_clients([Bad(), Good()], 1.0)
        self.assertTrue(Good.stopped)


if __name__ == "__main__":
    unittest.main()


class Handshake(unittest.TestCase):
    def _pair(self):
        import socket
        a, b = socket.socketpair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        return a, b

    def test_silent_server_is_interrupted_by_stop(self):
        import threading
        import time
        from notrefu_mirror.engine import recv_handshake
        a, _b = self._pair()  # _b accepte mais n'envoie jamais rien
        stop = threading.Event()
        threading.Timer(0.3, stop.set).start()
        t0 = time.monotonic()
        with self.assertRaises(EOFError):
            recv_handshake(a, 64, stop, timeout_s=30)
        self.assertLess(time.monotonic() - t0, 2.5)

    def test_silent_server_times_out(self):
        import threading
        from notrefu_mirror.engine import recv_handshake
        a, _b = self._pair()
        with self.assertRaises(EOFError):
            recv_handshake(a, 64, threading.Event(), timeout_s=1.2)

    def test_data_arrives_in_pieces(self):
        import threading
        from notrefu_mirror.engine import recv_handshake
        a, b = self._pair()
        b.sendall(b"ab")
        threading.Timer(0.2, lambda: b.sendall(b"cdef")).start()
        self.assertEqual(recv_handshake(a, 6, threading.Event(), 5), b"abcdef")
        self.assertIsNone(a.gettimeout())  # le délai est bien retiré après la poignée de main

    def test_oversized_packet_constant(self):
        from notrefu_mirror import protocol as P
        self.assertGreater(P.MAX_PACKET_SIZE, 4 << 20)  # assez large pour une image clé 4K
