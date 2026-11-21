"""Reconnexion : délais stricts, état de l'appareil, nettoyage, abandon d'une tentative bloquée."""
import socket
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from notrefu_mirror import adb  # noqa: E402
from notrefu_mirror.engine import AdbTransport, ClientParams, EngineError, ScrcpyClient, _connect_first  # noqa: E402
from notrefu_mirror.session_logic import failure_reason  # noqa: E402


class FastEvent(threading.Event):
    def wait(self, timeout=None):  # les pauses du test ne doivent pas durer
        return self.is_set()


class FakeAdb(AdbTransport):
    """Transport dont les appels adb sont scriptés : `script(args)` renvoie du texte ou lève EngineError."""

    def __init__(self, script):
        super().__init__("adb", "server.jar", {})
        self.script, self.calls = script, []

    def _run(self, args, timeout=10):
        self.calls.append(list(args))
        return self.script(args)


class RunCmd(unittest.TestCase):
    def test_timeout_is_strict(self):
        t = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            adb.run_cmd([sys.executable, "-c", "import time; time.sleep(30)"], 1.0)
        self.assertLess(time.monotonic() - t, 6)

    def test_background_child_holding_output_does_not_hang(self):
        # adb relance son serveur en tâche de fond : subprocess.run(capture_output) attendait alors ce démon (Windows)
        code = "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(25)']); print('ok')"
        t = time.monotonic()
        rc, out = adb.run_cmd([sys.executable, "-c", code], 10)
        self.assertEqual((rc, out.strip()), (0, "ok"))
        self.assertLess(time.monotonic() - t, 8)


class Parsers(unittest.TestCase):
    def test_device_state(self):
        out = "List of devices attached\nABC\toffline\n10.0.0.5:5555\tdevice\nXYZ\tunauthorized\n"
        self.assertEqual(adb.parse_device_state(out, "ABC"), "offline")
        self.assertEqual(adb.parse_device_state(out, "10.0.0.5:5555"), "device")
        self.assertEqual(adb.parse_device_state(out, "XYZ"), "unauthorized")
        self.assertEqual(adb.parse_device_state(out, "NOPE"), "missing")

    def test_servers_and_forwards(self):
        ps = "  PID ARGS\n 1 init\n 4321 app_process / com.genymobile.scrcpy.Server 5.0.1 scid=0000abcd log_level=info\n"
        self.assertEqual(adb.parse_scrcpy_servers(ps), [(4321, 0xABCD)])
        fw = "SER tcp:5001 localabstract:scrcpy_0000abcd\nSER tcp:5002 tcp:1234\n"
        self.assertEqual(adb.parse_scrcpy_forwards(fw), [("tcp:5001", 0xABCD)])

    def test_failure_reason(self):
        self.assertEqual(failure_reason("délai dépassé après 8 s : adb connect"), "délai dépassé")
        self.assertEqual(failure_reason("bind failed: Address already in use"), "port occupé")
        self.assertEqual(failure_reason("appareil hors ligne (offline)"), "appareil hors ligne")
        self.assertIn("non autorisé", failure_reason("error: device unauthorized"))


class ConnectDeadline(unittest.TestCase):
    def test_gives_up_quickly(self):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()  # port fermé
        t = time.monotonic()
        with self.assertRaises(EngineError) as cm:
            _connect_first("127.0.0.1", port, threading.Event(), lambda: True, timeout_s=0.6)
        self.assertIn("délai dépassé", str(cm.exception))
        self.assertLess(time.monotonic() - t, 4)


class Preflight(unittest.TestCase):
    def test_wifi_disconnect_before_connect(self):
        state = {"s": "offline"}

        def script(a):
            if a == ["devices"]:
                return f"List of devices attached\n10.0.0.5:5555\t{state['s']}"
            if a[:1] == ["connect"]:
                state["s"] = "device"
                return "connected to 10.0.0.5:5555"
            if a[-2:] == ["echo", "ok"]:
                return "ok"
            return ""

        t = FakeAdb(script)
        logs = []
        t.preflight("10.0.0.5:5555", logs.append, FastEvent())
        names = [c[0] for c in t.calls if c[0] in ("disconnect", "connect")]
        self.assertEqual(names, ["disconnect", "connect"])
        self.assertTrue(any("offline" in l for l in logs))

    def test_unauthorized_fails_with_reason(self):
        t = FakeAdb(lambda a: "List of devices attached\nUSB1\tunauthorized")
        with self.assertRaises(EngineError) as cm:
            t.preflight("USB1", lambda _l: None, FastEvent())
        self.assertIn("non autorisé", str(cm.exception))

    def test_missing_usb_device_fails_without_hanging(self):
        t = FakeAdb(lambda a: "List of devices attached\n")
        with self.assertRaises(EngineError) as cm:
            t.preflight("USB1", lambda _l: None, FastEvent())
        self.assertIn("introuvable", str(cm.exception))

    def test_ready_device_is_quick(self):
        def script(a):
            return "List of devices attached\nUSB1\tdevice" if a == ["devices"] else "ok"

        t = FakeAdb(script)
        t.preflight("USB1", lambda _l: None, FastEvent())
        self.assertEqual(len(t.calls), 2)


class Strays(unittest.TestCase):
    def test_only_orphans_are_cleaned(self):
        ps = " 10 app_process / com.genymobile.scrcpy.Server 5.0.1 scid=00000001\n 11 app_process / com.genymobile.scrcpy.Server 5.0.1 scid=00000002\n"

        def script(a):
            if a[-1] == "--list":
                return "S tcp:5001 localabstract:scrcpy_00000001\nS tcp:5002 localabstract:scrcpy_00000002"
            if "ps" in a:
                return ps
            return ""

        t = FakeAdb(script)
        AdbTransport._live_scids.add(1)  # session vivante
        try:
            t.cleanup_strays("S", lambda _l: None)
        finally:
            AdbTransport._live_scids.discard(1)
        removed = [c[-1] for c in t.calls if "--remove" in c]
        killed = [c[-1] for c in t.calls if c[-2:-1] == ["kill"]]
        self.assertEqual(removed, ["tcp:5002"])
        self.assertEqual(killed, ["11"])


class Abandon(unittest.TestCase):
    def test_hung_attempt_is_abandoned_and_silent(self):
        release = threading.Event()
        events = []

        class HangTransport:
            def open(self, params, scid, stop, log):
                release.wait(10)  # simule un adb bloqué
                raise EngineError("trop tard")

        c = ScrcpyClient(ClientParams(serial="X"), HangTransport(), on_state=lambda s, d: events.append(s))
        c.start()
        time.sleep(0.2)
        self.assertEqual(c.state, "starting")
        c.abandon()
        self.assertEqual(c.state, "error")
        release.set()
        self.assertTrue(c.wait_stopped(3))
        self.assertEqual(c.state, "error")
        self.assertEqual(events, ["starting"])


class NotReadyBackoff(unittest.TestCase):
    def test_progressive_delay_then_cap(self):
        from notrefu_mirror.session_logic import ReconnectPolicy

        p = ReconnectPolicy()
        p.connected()
        d = [p.next_retry(True, "offline").delay_s for _ in range(5)]
        self.assertEqual(d, [3, 5, 8, 8, 8])

    def test_reset_when_device_ready_or_manual(self):
        from notrefu_mirror.session_logic import ReconnectPolicy

        p = ReconnectPolicy()
        p.connected()
        p.next_retry(True, "unauthorized"); p.next_retry(True, "offline")
        p.device_ready()
        self.assertEqual(p.next_retry(True, "offline").delay_s, 3)
        p.reset(); p.connected()
        self.assertEqual(p.next_retry(True, "offline").delay_s, 3)

    def test_other_states_keep_normal_delays(self):
        from notrefu_mirror.session_logic import ReconnectPolicy

        p = ReconnectPolicy()
        p.connected()
        self.assertEqual([p.next_retry(True, "device").delay_s for _ in range(3)], [3, 4, 5])
        self.assertEqual(p.next_retry(True, None).delay_s, 6)


if __name__ == "__main__":
    unittest.main()
