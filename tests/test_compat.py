"""Compatibilité : anciens Android (audio), marques, repli vidéo, conflit de serveur adb, ratios de tablettes."""
import os
import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from notrefu_mirror import adb, compat, protocol as P  # noqa: E402
from notrefu_mirror.engine import AdbTransport, ClientParams, Connection, ScrcpyClient, TcpTransport, VideoStartError  # noqa: E402
from notrefu_mirror.keymap import KeyMap, KeyTranslator  # noqa: E402
from fake_scrcpy_server import FakeServer  # noqa: E402

ROOT = Path(__file__).resolve().parent


def wait(cond, t=10):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class Pure(unittest.TestCase):
    def test_audio_threshold(self):
        self.assertFalse(compat.audio_supported(29))
        self.assertFalse(compat.audio_supported(28))
        self.assertTrue(compat.audio_supported(30))
        self.assertTrue(compat.audio_supported(34))
        self.assertTrue(compat.audio_supported(0))  # SDK inconnu : on tente

    def test_brands(self):
        for maker in ("Xiaomi", "POCO", "Redmi", "xiaomi"):
            self.assertEqual(compat.brand_of(maker), "xiaomi", maker)
        for maker in ("OPPO", "realme", "OnePlus"):
            self.assertEqual(compat.brand_of(maker), "oppo", maker)
        self.assertEqual(compat.brand_of("samsung"), "samsung")
        self.assertEqual(compat.brand_of("unknown", "POCO X7 Pro"), "xiaomi")  # le modèle aide quand le fabricant est générique
        self.assertEqual(compat.brand_of("Google"), "")
        self.assertIn("Débogage USB (Paramètres de sécurité)", compat.brand_tip("Xiaomi"))
        self.assertIn("surveillance des autorisations", compat.brand_tip("realme"))
        self.assertIn("Bloqueur automatique", compat.brand_tip("samsung", platform="linux"))
        self.assertNotIn("Samsung Android USB Driver", compat.brand_tip("samsung", platform="linux"))
        self.assertIn("Samsung Android USB Driver", compat.brand_tip("samsung", platform="win32"))
        self.assertEqual(compat.brand_tip("Google"), "")

    def test_video_fallback_levels(self):
        base = (20_000_000, 60, 0, "i-frame-interval:int=2")
        self.assertEqual(compat.video_fallback(0, *base), base)
        br, fps, size, opts = compat.video_fallback(1, *base)
        self.assertEqual((br, fps, size, opts), (8_000_000, 30, 1280, "profile:int=1"))
        br, fps, size, opts = compat.video_fallback(2, *base)
        self.assertEqual((br, fps, size, opts), (3_000_000, 30, 960, "profile:int=1"))
        # un réglage déjà bas n'est jamais relevé
        self.assertEqual(compat.video_fallback(1, 2_000_000, 24, 720, "x")[:3], (2_000_000, 24, 720))

    def test_shrink_display(self):
        self.assertEqual(compat.shrink_display("1920x1080/280", 1280), "1280x720/186")
        self.assertEqual(compat.shrink_display("1280x720/200", 1280), "1280x720/200")  # déjà assez petit
        self.assertEqual(compat.shrink_display("", 1280), "")
        w, h = compat.shrink_display("2560x1600/320", 960).split("/")[0].split("x")
        self.assertEqual((int(w) % 8, int(h) % 8), (0, 0))
        self.assertAlmostEqual(int(w) / int(h), 1.6, delta=0.03)  # le ratio 16:10 est conservé


class Conflict(unittest.TestCase):
    MSG = "adb server version (41) doesn't match this client (40); killing...\nerror: could not install *smartsocket* listener"

    def test_detection(self):
        self.assertTrue(adb.server_conflict(self.MSG))
        self.assertTrue(adb.server_conflict("adb server is out of date.  killing..."))
        self.assertFalse(adb.server_conflict("List of devices attached\n"))

    def test_run_adb_restarts_server_once_and_retries(self):
        calls = []

        def fake_run(cmd, timeout, env=None):
            calls.append(cmd[1:])
            return (1, self.MSG) if len(calls) == 1 else (0, "List of devices attached\n")

        with mock.patch.object(adb, "find_tool", return_value="adb"), mock.patch.object(adb, "run_cmd", side_effect=fake_run), \
             mock.patch.object(adb, "restart_server", return_value=True) as restart:
            out = adb.run_adb(["devices"])
        self.assertIn("List of devices", out)
        restart.assert_called_once()
        self.assertEqual(calls, [["devices"], ["devices"]])

    def test_unresolved_conflict_gives_clear_message(self):
        with mock.patch.object(adb, "find_tool", return_value="adb"), mock.patch.object(adb, "run_cmd", return_value=(1, self.MSG)), \
             mock.patch.object(adb, "restart_server", return_value=False):
            with self.assertRaises(adb.AdbError) as cm:
                adb.run_adb(["devices"])
        self.assertIn("port 5037", str(cm.exception))

    def test_restart_server_sequence(self):
        seen = []

        def fake_run(cmd, timeout, env=None):
            seen.append(cmd[1])
            return 0, "List of devices attached\n"

        adb._last_restart = 0.0
        logs = []
        with mock.patch.object(adb, "run_cmd", side_effect=fake_run):
            self.assertTrue(adb.restart_server("adb", {}, logs.append))
            self.assertEqual(seen, ["kill-server", "start-server", "devices"])
            self.assertFalse(adb.restart_server("adb", {}, logs.append))  # jamais deux fois en moins de 10 s : pas de boucle
        self.assertTrue(any("conflit" in l for l in logs))
        adb._last_restart = 0.0


class FlakyTransport:
    """Niveau 0 : le serveur du téléphone s'arrête sans envoyer de vidéo ; niveau ≥ `ok_from` : un vrai flux."""

    def __init__(self, port, ok_from=1):
        self.inner, self.ok_from, self.seen = TcpTransport(port=port), ok_from, []
        self.closed = 0

    def open(self, params, scid, stop, log):
        self.seen.append(params.fallback)
        if params.fallback >= self.ok_from:
            return self.inner.open(params, scid, stop, log)
        a, b = socket.socketpair()
        c1, c2 = socket.socketpair()
        b.close()  # le serveur « meurt » : plus rien ne viendra
        def closed():
            self.closed += 1
        return Connection(a, c1, None, "Tablette", closed)


class VideoFallback(unittest.TestCase):
    def test_retries_with_compatible_profile(self):
        srv = FakeServer(w=320, h=200, n=15)
        t = FlakyTransport(srv.port)
        logs, states = [], []
        c = ScrcpyClient(ClientParams(video_bit_rate=20_000_000, max_fps=60), t, on_log=logs.append, on_state=lambda s, d: states.append(s))
        c.start()
        self.assertTrue(wait(lambda: c.decoded_frames >= 5), f"{states} {logs}")
        self.assertEqual(t.seen, [0, 1])
        self.assertEqual(t.closed, 1)  # la tentative ratée a été nettoyée comme à l'arrêt
        self.assertTrue(any("profil compatible" in l for l in logs))
        self.assertTrue(any("Vidéo : profil compatible" in n for n in c.auto_notes))
        self.assertNotIn("error", states)
        c.stop()

    def test_gives_up_after_last_level_with_clear_error(self):
        t = FlakyTransport(0, ok_from=99)
        states = []
        c = ScrcpyClient(ClientParams(), t, on_state=lambda s, d: states.append((s, d)))
        c.start()
        self.assertTrue(wait(lambda: c._finished.is_set()))
        self.assertEqual(t.seen, [0, 1, 2])
        self.assertEqual(c.state, "error")
        self.assertIn("flux vidéo", states[-1][1])

    def test_silent_stream_is_detected(self):
        a, b = socket.socketpair()
        b.sendall(P.CODEC_H264.to_bytes(4, "big"))  # en-tête de codec, puis plus rien (écran noir)
        c = ScrcpyClient(ClientParams(), TcpTransport())
        conn = Connection(a, a, None, "x", lambda: None)
        t0 = time.monotonic()
        with self.assertRaises(VideoStartError) as cm:
            c._await_video(conn, timeout_s=1.0)
        self.assertIn("aucune image", str(cm.exception))
        self.assertLess(time.monotonic() - t0, 4)

    def test_refused_codec_is_detected(self):
        a, b = socket.socketpair()
        b.sendall((0).to_bytes(4, "big"))
        c = ScrcpyClient(ClientParams(), TcpTransport())
        with self.assertRaises(VideoStartError):
            c._await_video(Connection(a, a, None, "x", lambda: None), timeout_s=2.0)


class OldAndroid(unittest.TestCase):
    def _run(self, sdk, audio=True):
        srv = FakeServer(w=320, h=200, n=10, audio=False)  # un serveur SANS socket audio : planterait si on en demandait un
        env = dict(os.environ, FAKE_PORT=str(srv.port), FAKE_SDK=str(sdk))
        t = AdbTransport(str(ROOT / "fakes" / "adb"), "server.jar", env)
        logs = []
        c = ScrcpyClient(ClientParams(serial="FAKESERIAL01", audio=audio), t, on_log=logs.append)
        c.start()
        ok = wait(lambda: c.decoded_frames >= 3 or c.state == "error", 15)
        return c, logs, ok

    def test_audio_is_turned_off_below_android_11(self):
        c, logs, ok = self._run(29)
        try:
            self.assertTrue(ok and c.state == "running", f"{c.state} {logs}")
            self.assertIn(compat.AUDIO_OFF_NOTE, c.auto_notes)
            self.assertTrue(any("Android 11+" in l for l in logs))
            self.assertIsNone(c._conn.audio)
        finally:
            c.stop()

    def test_android_9_also(self):
        c, logs, ok = self._run(28)
        try:
            self.assertTrue(ok and c.state == "running", f"{c.state} {logs}")
        finally:
            c.stop()


class Ratios(unittest.TestCase):
    """Le ratio réel envoyé par scrcpy est utilisé partout : jamais de 16:9 supposé."""

    SIZES = {"16:10": (320, 200), "5:3": (300, 180), "4:3": (320, 240), "3:4 portrait": (240, 320), "10:16 portrait": (200, 320), "16:9": (320, 176)}

    def test_stream_size_follows_the_phone(self):
        for name, (w, h) in self.SIZES.items():
            with self.subTest(name):
                srv = FakeServer(w=w, h=h, n=8)
                c = ScrcpyClient(ClientParams(), TcpTransport(port=srv.port))
                c.start()
                self.assertTrue(wait(lambda: c.decoded_frames >= 3), name)
                f = c.latest_frame()
                self.assertEqual((f.source_width, f.source_height), (w, h))
                self.assertEqual((f.width, f.height), (w, h))
                c.stop()

    def test_keymap_uses_real_frame_size(self):
        for name, (w, h) in self.SIZES.items():
            with self.subTest(name):
                km = KeyMap()
                km.set("A", 0.25, 0.75)
                km.active = True
                sent = []
                tr = KeyTranslator(km, sent.append, lambda w=w, h=h: (w, h), clock=lambda: 100.0)
                self.assertTrue(tr.press("A"))
                msg = sent[0]
                x, y = int.from_bytes(msg[10:14], "big"), int.from_bytes(msg[14:18], "big")
                mw, mh = int.from_bytes(msg[18:20], "big"), int.from_bytes(msg[20:22], "big")
                self.assertEqual((mw, mh), (w, h))
                self.assertEqual((x, y), (int(0.25 * w), int(0.75 * h)))


if __name__ == "__main__":
    unittest.main()
