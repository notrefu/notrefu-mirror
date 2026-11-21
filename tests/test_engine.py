import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from notrefu_mirror import protocol as P  # noqa: E402
from notrefu_mirror.engine import ClientParams, ScrcpyClient, TcpTransport  # noqa: E402
from fake_scrcpy_server import FakeServer  # noqa: E402


def wait(cond, t=8):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class EngineTest(unittest.TestCase):
    def test_video_and_control(self):
        srv = FakeServer(n=15)
        states, clips = [], []
        c = ScrcpyClient(ClientParams(app_package="com.ankama.dofustouch", clipboard=True), TcpTransport(port=srv.port),
                         on_state=lambda s, d: states.append(s), on_clipboard=clips.append)
        c.start()
        self.assertTrue(wait(lambda: c.decoded_frames >= 10), f"frames={c.decoded_frames} {states}")
        self.assertEqual(c.device_name, "Fake Phone")
        f = c.latest_frame()
        self.assertEqual((f.width, f.height, f.source_width, f.source_height), (320, 240, 320, 240))
        self.assertEqual(len(f.data), f.stride * f.height)
        c.set_view_size(160, 120)
        f = c.refresh_frame()
        self.assertEqual((f.width, f.height), (160, 120))
        msg = P.inject_touch_event(P.ACTION_DOWN, P.POINTER_ID_MOUSE, 10, 20, 320, 240, 1.0, 1, 1)
        c.send(msg)
        # START_APP envoyé automatiquement après la session
        self.assertTrue(wait(lambda: msg in bytes(srv.control_bytes) and P.start_app("com.ankama.dofustouch") in bytes(srv.control_bytes)))
        self.assertTrue(wait(lambda: clips == ["copié sur le téléphone"]), clips)
        c.stop()
        srv.close()
        self.assertEqual(c.state, "stopped")

    def test_audio_pcm_reaches_player(self):
        import tempfile, os
        out = tempfile.mktemp()
        srv = FakeServer(n=5, audio=True)
        c = ScrcpyClient(ClientParams(audio=True), TcpTransport(port=srv.port))
        c._audio_player = ["sh", "-c", f"cat > {out}"]
        c.start()
        self.assertTrue(wait(lambda: os.path.exists(out) and os.path.getsize(out) >= 3 * 3840), "pcm non reçu")
        time.sleep(0.4)
        c.stop()
        srv.close()
        data = open(out, "rb").read()
        self.assertEqual(data[:3840], bytes([1]) * 3840)
        self.assertEqual(len(data) % 3840, 0)
        os.unlink(out)

    def test_audio_backlog_is_dropped(self):
        """Un lecteur trop lent ne doit pas faire dériver le son : le surplus est abandonné."""
        import io, socket, threading, struct, time
        from notrefu_mirror import audio
        a, b = socket.socketpair()
        out = tempfile_path = None
        import tempfile, os
        out = tempfile.mktemp()
        stop = threading.Event()
        t = threading.Thread(target=lambda: audio.run_audio(b, stop, lambda m: None, player=["sh", "-c", f"cat > {out}"]), daemon=True)
        a.sendall(b"\0raw")
        t.start()
        for i in range(50):  # 1 s de son envoyé d'un coup
            a.sendall(struct.pack(">QI", 0, 3840) + bytes([1]) * 3840)
        time.sleep(0.5)
        stop.set(); a.close(); t.join(3)
        size = os.path.getsize(out)
        self.assertLess(size, 50 * 3840)
        self.assertGreaterEqual(size, 5 * 3840)
        os.unlink(out)

    def test_connection_refused(self):
        import socket
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        c = ScrcpyClient(ClientParams(), TcpTransport(port=port))
        c.start()
        self.assertTrue(wait(lambda: c._finished.is_set(), 20))
        self.assertEqual(c.state, "error")


if __name__ == "__main__":
    unittest.main()


class PacingTests(unittest.TestCase):
    def test_stall_detection_needs_burst_after_silence(self):
        from notrefu_mirror.engine import ScrcpyClient, ClientParams

        c = ScrcpyClient(ClientParams(), transport=None)  # type: ignore[arg-type]
        t = 100.0
        for _ in range(12):  # flux normal : 60 images/s
            t += 0.016
            c._note_arrival(0.016, t)
        t += 0.6  # écran immobile : silence puis une seule image : pas un blocage
        c._note_arrival(0.6, t)
        for _ in range(3):
            t += 0.016
            c._note_arrival(0.016, t)
        self.assertEqual(c.pop_stalls(), 0)
        for _ in range(12):
            t += 0.016
            c._note_arrival(0.016, t)
        t += 0.6  # silence puis rafale d'images d'un coup : le réseau a bloqué
        c._note_arrival(0.6, t)
        for _ in range(5):
            t += 0.001
            c._note_arrival(0.001, t)
        self.assertEqual(c.pop_stalls(), 1)
        self.assertEqual(c.pop_stalls(), 0)

    def test_stalls_ignored_while_throttled(self):
        from notrefu_mirror.engine import ScrcpyClient, ClientParams

        c = ScrcpyClient(ClientParams(), transport=None)  # type: ignore[arg-type]
        c.set_fps_cap("thermal", 12)
        c._cap_changed = 0.0
        t = 500.0
        for _ in range(12):
            t += 0.016
            c._note_arrival(0.016, t)
        t += 0.6
        c._note_arrival(0.6, t)
        for _ in range(6):
            t += 0.001
            c._note_arrival(0.001, t)
        self.assertEqual(c.pop_stalls(), 0)


class CapEndToEndTest(unittest.TestCase):
    def test_cap_slows_then_releases(self):
        srv = FakeServer(n=400)  # le faux serveur envoie ~100 images/s
        c = ScrcpyClient(ClientParams(), TcpTransport(port=srv.port))
        c.set_fps_cap("thermal", 10)
        c.start()
        self.assertTrue(wait(lambda: c.decoded_frames >= 3, 8))
        n0, t0 = c.decoded_frames, time.monotonic()
        time.sleep(2.0)
        rate = (c.decoded_frames - n0) / (time.monotonic() - t0)
        self.assertTrue(6 <= rate <= 14, f"{rate:.1f} ips avec un plafond à 10")
        c.set_fps_cap("thermal", None)
        self.assertTrue(wait(lambda: c.decoded_frames >= n0 + 150, 8), c.decoded_frames)
        c.stop()
        srv.close()


class CatchUpTest(unittest.TestCase):
    def test_slow_conversion_does_not_accumulate_lag(self):
        """Conversion lente (processeur modeste en Ultra) : le client doit rattraper le flux au lieu de prendre du retard."""
        srv = FakeServer(n=300)  # ~3 s d'envoi à 100 images/s
        c = ScrcpyClient(ClientParams(), TcpTransport(port=srv.port))
        real = c._convert

        def slow(decoded):
            time.sleep(0.03)  # 30 ms par conversion : sans rattrapage il faudrait ~9 s pour tout traiter
            return real(decoded)

        c._convert = slow  # type: ignore[method-assign]
        c.start()
        t0 = time.monotonic()
        self.assertTrue(wait(lambda: c.decoded_frames >= 295, 8), c.decoded_frames)
        self.assertLess(time.monotonic() - t0, 5.5)
        c.stop()
        srv.close()


class CloseAppTest(unittest.TestCase):
    def _client(self, **kw):
        c = ScrcpyClient(ClientParams(serial="S", app_package="com.ankama.dofustouch@10", **kw), transport=None)  # type: ignore[arg-type]
        c._log = lambda *_a, **_k: None  # type: ignore[method-assign]
        return c

    def test_force_stop_only_when_requested_and_launched(self):
        from unittest import mock

        with mock.patch("notrefu_mirror.engine.adb.run_adb") as run:
            c = self._client()
            c._close_app_on_phone()  # pas demandé
            c.close_app_on_stop = True
            c._close_app_on_phone()  # demandé mais le jeu n'a pas été lancé par la session
            run.assert_not_called()
            c._app_started = True
            c._close_app_on_phone()
            run.assert_called_once_with(["shell", "am", "force-stop", "--user", "10", "com.ankama.dofustouch"], "S", timeout=4)

    def test_main_user_has_no_user_flag(self):
        from unittest import mock

        with mock.patch("notrefu_mirror.engine.adb.run_adb") as run:
            c = ScrcpyClient(ClientParams(serial="S", app_package="com.ankama.dofustouch"), transport=None)  # type: ignore[arg-type]
            c._log = lambda *_a, **_k: None  # type: ignore[method-assign]
            c.close_app_on_stop = c._app_started = True
            c._close_app_on_phone()
            self.assertEqual(run.call_args.args[0], ["shell", "am", "force-stop", "com.ankama.dofustouch"])

    def test_adb_failure_is_not_fatal(self):
        from unittest import mock
        from notrefu_mirror import adb

        with mock.patch("notrefu_mirror.engine.adb.run_adb", side_effect=adb.AdbError("x")):
            c = self._client()
            c.close_app_on_stop = c._app_started = True
            c._close_app_on_phone()
