"""Mémoire du téléphone (RAM globale / jeu), décodage matériel avec repli, QtWebEngine paresseux."""
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from notrefu_mirror import engine, phonehealth as ph  # noqa: E402
from notrefu_mirror.engine import ClientParams, ScrcpyClient, TcpTransport  # noqa: E402
from fake_scrcpy_server import FakeServer  # noqa: E402


def wait(cond, t=10):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class Memory(unittest.TestCase):
    def test_ram_is_total_minus_available_not_free(self):
        # MemFree est minuscule sous Android (le cache occupe tout) : seul MemAvailable compte
        text = "MemTotal: 8000000 kB\nMemFree: 150000 kB\nMemAvailable: 3000000 kB\n"
        h = ph.parse(f"@@T\n@@S\n@@M\n{text}@@C\n")
        self.assertEqual((h.mem_total_mb, h.mem_mb), (7812, 2929))
        self.assertEqual(h.ram_pct, 63)  # (total - disponible) / total, pas 98 %
        self.assertIn("MemTotal|MemAvailable", ph.READ_COMMAND)  # la commande ne lit jamais MemFree

    def test_game_memory_formats(self):
        new = "** MEMINFO in pid 1234 [com.ankama.dofustouch] **\n   TOTAL PSS:   524288            TOTAL RSS:   700000      TOTAL SWAP PSS:        0\n"
        old = "                 Pss  Private\n  TOTAL   409600   300000\n"
        self.assertEqual(ph.parse_pkg_meminfo(new), 512)
        self.assertEqual(ph.parse_pkg_meminfo(old), 400)
        self.assertIsNone(ph.parse_pkg_meminfo("No process found for: com.x"))

    def test_summary_shows_game_ram_separately(self):
        h = ph.Health(level=80, mem_mb=2000, mem_total_mb=8000, game_mb=512)
        self.assertEqual(h.summary(), "80 % · RAM 75 % (jeu 512 Mo)")
        self.assertEqual(ph.Health(level=80, mem_mb=2000, mem_total_mb=8000).summary(), "80 % · RAM 75 %")


class HwDecode(unittest.TestCase):
    def setUp(self):
        self.logs = []
        self.c = ScrcpyClient(ClientParams(), TcpTransport(), on_log=self.logs.append)

    def test_software_on_linux(self):
        ctx = self.c._new_decoder()
        self.assertEqual(self.c.hw_name, "")
        self.assertEqual(ctx.name, "h264")

    def test_windows_without_gpu_decoder_falls_back_to_software(self):
        with mock.patch.object(engine.sys, "platform", "win32"), mock.patch("av.codec.hwaccel.hwdevices_available", return_value=["cuda"]):
            self.c._new_decoder()
        self.assertEqual(self.c.hw_name, "")

    def test_windows_prefers_d3d11va_then_dxva2(self):
        with mock.patch.object(engine.sys, "platform", "win32"), mock.patch("av.codec.hwaccel.hwdevices_available", return_value=["dxva2", "d3d11va"]):
            self.c._new_decoder()
        self.assertEqual(self.c.hw_name, "d3d11va")
        with mock.patch.object(engine.sys, "platform", "win32"), mock.patch("av.codec.hwaccel.hwdevices_available", return_value=["dxva2"]):
            self.c._new_decoder()
        self.assertEqual(self.c.hw_name, "dxva2")

    def test_setting_can_disable_gpu(self):
        with mock.patch.object(engine, "HW_DECODE_ENABLED", False), mock.patch.object(engine.sys, "platform", "win32"), \
             mock.patch("av.codec.hwaccel.hwdevices_available", return_value=["d3d11va"]):
            self.c._new_decoder()
        self.assertEqual(self.c.hw_name, "")

    def test_fallback_is_permanent(self):
        with mock.patch.object(engine.sys, "platform", "win32"), mock.patch("av.codec.hwaccel.hwdevices_available", return_value=["d3d11va"]):
            self.c._new_decoder()
            self.assertEqual(self.c.hw_name, "d3d11va")
            self.assertTrue(self.c._hw_fallback("test"))
            self.c._new_decoder()  # plus d'essai du GPU après un échec
        self.assertEqual(self.c.hw_name, "")
        self.assertTrue(any("abandonné" in l for l in self.logs))

    def test_stream_still_decodes_when_gpu_path_is_selected(self):
        srv = FakeServer(w=320, h=200, n=12)
        c = ScrcpyClient(ClientParams(), TcpTransport(port=srv.port), on_log=self.logs.append)
        with mock.patch.object(engine.sys, "platform", "win32"), mock.patch("av.codec.hwaccel.hwdevices_available", return_value=["d3d11va"]):
            c.start()
            self.assertTrue(wait(lambda: c.decoded_frames >= 5), self.logs)
        self.assertTrue(any("[décodeur]" in l for l in self.logs))
        c.stop()


class LazyWeb(unittest.TestCase):
    def test_webengine_not_loaded_at_startup(self):
        code = ("import sys; sys.path.insert(0, %r)\n"
                "import notrefu_mirror.ui.main_window, notrefu_mirror.guides as g\n"
                "bad = [m for m in sys.modules if m.startswith(('PySide6.QtWebEngine', 'PySide6.QtWebChannel'))]\n"
                "print('LOADED' if bad else 'CLEAN', g.HAS_WEB)\n") % str(SRC)
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, env=env, timeout=60)
        self.assertIn("CLEAN False", out.stdout, out.stdout + out.stderr)

    def test_load_web_is_lazy_and_cached(self):
        from notrefu_mirror import guides

        with mock.patch.dict(os.environ, {"NOTREFU_MIRROR_NO_WEB": "1"}):
            guides._WEB_TRIED, guides._WEB = False, None
            self.assertIsNone(guides.load_web())
            self.assertIsNone(guides.load_web())
            self.assertFalse(guides.HAS_WEB)
        guides._WEB_TRIED = False


class Light(unittest.TestCase):
    OUT = ("MemTotal:        8000000 kB\nMemAvailable:    2000000 kB\n@@C\n"
           "cpu  100 0 100 800 0 0 0 0\ncpu  150 0 150 900 0 0 0 0\n")

    def test_parse_light(self):
        h = ph.parse_light(self.OUT)
        self.assertEqual(h.ram_pct, 75)
        self.assertEqual(h.cpu_pct, 50)

    def test_merge_keeps_slow_values(self):
        full = ph.Health(level=80, temp_c=35.0, charging=True, thermal=1, free_gb=10.0, game_mb=900)
        h = ph.merge_light(full, ph.parse_light(self.OUT))
        self.assertEqual((h.level, h.game_mb, h.thermal), (80, 900, 1))
        self.assertIn("RAM 75 %", h.summary())

    def test_light_command_has_no_dumpsys(self):
        self.assertNotIn("dumpsys", ph.LIGHT_COMMAND)
        self.assertIn("globales", ph.GLOBAL_NOTE)

    def test_full_every_60s(self):
        from notrefu_mirror.health_monitor import HealthMonitor

        m = HealthMonitor()
        self.assertTrue(m.wants_full("A", 100.0))
        m.finish("A", ph.Health(level=50), 100.0, True)
        self.assertFalse(m.wants_full("A", 105.0))
        txt, _ = m.finish("A", ph.parse_light(self.OUT), 105.0, False)
        self.assertIn("50 %", txt)
        self.assertTrue(m.wants_full("A", 161.0))
        m.forget("A")
        self.assertTrue(m.wants_full("A", 132.0))


class Profiles(unittest.TestCase):
    def test_presets_change_scrcpy_params(self):
        from notrefu_mirror.scrcpy_cmd import Settings, PRESETS
        from notrefu_mirror.session_logic import build_client_params

        got = {}
        for k in ("moyen", "ultra"):
            s = Settings(serial="X")
            s.apply_preset(k)
            p = build_client_params(s, max_size=max(s.width, s.height), new_display="", audio_latency_ms=50,
                                    game_audio=False, quiet_notifications=False, game_mode="")
            got[k] = (p.video_bit_rate, p.max_fps, p.max_size)
        self.assertEqual(got["moyen"], (4_000_000, 45, 1280))
        self.assertEqual(got["ultra"], (16_000_000, 60, 2560))

    def test_hw_devices_per_platform(self):
        self.assertIn("vaapi", engine.HW_DEVICES_LINUX)
        self.assertIn("d3d11va", engine.HW_DEVICES_WIN)


class ZeroCopy(unittest.TestCase):
    def test_frame_is_qimage_compatible(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import av
        from PySide6.QtGui import QImage

        c = ScrcpyClient.__new__(ScrcpyClient)
        c.source_size, c._view_size = (0, 0), (0, 0)
        v = av.VideoFrame(64, 48, "yuv420p")
        f = ScrcpyClient._convert(c, v)
        img = QImage(f.data, f.width, f.height, f.stride, QImage.Format.Format_RGB888)
        self.assertEqual((img.width(), img.height()), (64, 48))
        self.assertIsNotNone(f.keep)


class HiddenAndPolling(unittest.TestCase):
    def test_stale_input_is_never_replayed_but_releases_pass(self):
        from notrefu_mirror import protocol as P

        down = P.inject_touch_event(P.ACTION_DOWN, 1, 10, 10, 100, 100, 1.0, P.BUTTON_PRIMARY, 0)
        move = P.inject_touch_event(P.ACTION_MOVE, 1, 11, 11, 100, 100, 1.0, P.BUTTON_PRIMARY, 0)
        up = P.inject_touch_event(P.ACTION_UP, 1, 11, 11, 100, 100, 0.0, P.BUTTON_PRIMARY, 0)
        self.assertTrue(P.is_stale_droppable(down))
        self.assertTrue(P.is_stale_droppable(move))
        self.assertFalse(P.is_stale_droppable(up))
        self.assertFalse(P.is_stale_droppable(P.inject_keycode(P.ACTION_UP, 4, 0, 0)))
        self.assertTrue(P.is_stale_droppable(P.inject_keycode(P.ACTION_DOWN, 4, 0, 0)))

    def test_writer_drops_old_actions(self):
        import queue as _q
        import socket

        c = ScrcpyClient.__new__(ScrcpyClient)
        c._outbox = _q.Queue(); c._stop = __import__("threading").Event(); c.dropped_stale = 0
        from notrefu_mirror import protocol as P

        a, b = socket.socketpair()
        down = P.inject_touch_event(P.ACTION_DOWN, 1, 1, 1, 10, 10, 1.0, P.BUTTON_PRIMARY, 0)
        up = P.inject_touch_event(P.ACTION_UP, 1, 1, 1, 10, 10, 0.0, P.BUTTON_PRIMARY, 0)
        old = time.monotonic() - 5
        c._outbox.put((old, down)); c._outbox.put((old, up)); c._outbox.put(None)

        class Conn:
            control = a

        c._fail = lambda *_: None
        ScrcpyClient._control_writer(c, Conn())
        a.close()
        got = b.recv(4096)
        self.assertEqual(got, up)  # le DOWN périmé est abandonné, le relâchement est livré
        self.assertEqual(c.dropped_stale, 1)

    def test_hidden_phones_polled_less_often(self):
        from notrefu_mirror.health_monitor import HealthMonitor, HIDDEN_POLL_S

        m = HealthMonitor()
        self.assertEqual(m.to_poll({"A"}, 100.0, set()), ["A"])  # premier relevé
        m.failed("A")
        self.assertEqual(m.to_poll({"A"}, 105.0, set()), [])  # masqué : trop tôt
        self.assertEqual(m.to_poll({"A"}, 105.0, {"A"}), ["A"])  # visible : à chaque tick
        m.failed("A")
        self.assertEqual(m.to_poll({"A"}, 105.0 + HIDDEN_POLL_S, set()), ["A"])

    def test_game_ram_spaced(self):
        from notrefu_mirror.health_monitor import HealthMonitor, GAME_RAM_EVERY_S

        m = HealthMonitor()
        self.assertTrue(m.wants_game("A", 0.0))
        m.game_read("A", 0.0)
        self.assertFalse(m.wants_game("A", 60.0))
        self.assertTrue(m.wants_game("A", GAME_RAM_EVERY_S))
        h = m.finish("A", ph.Health(level=50), 10.0, True)
        full = ph.Health(level=49)
        self.assertEqual(ph.merge_full(ph.Health(game_mb=700), full).game_mb, 700)


class RamTooltip(unittest.TestCase):
    def test_units_and_used(self):
        self.assertEqual(ph.format_mem(512), "512 Mo")
        self.assertEqual(ph.format_mem(5324.8), "5,2 Go")
        self.assertEqual(ph.format_mem(8192), "8,0 Go")

    def test_ram_from_meminfo_kb(self):
        h = ph.parse_light("MemTotal:  8388608 kB\nMemAvailable:  3145728 kB\n@@C\n")
        self.assertEqual((h.mem_total_mb, h.mem_mb, h.ram_pct), (8192, 3072, 62))
        self.assertIn("5,0 / 8,0 Go utilisés (62 %)", ph.ram_detail(h))

    def test_detail_with_game(self):
        h = ph.Health(mem_mb=2867, mem_total_mb=8192, game_mb=512)
        d = ph.ram_detail(h)
        self.assertIn("5,2 / 8,0 Go", d)
        self.assertIn("Jeu : ~512 Mo", d)
        self.assertIn("pas uniquement celle du jeu", d)

    def test_detail_missing_values(self):
        self.assertIn("en attente du premier relevé", ph.ram_detail(None))
        d = ph.ram_detail(ph.Health(mem_mb=1000, mem_total_mb=2000))
        self.assertIn("Jeu : non disponible", d)
        self.assertIn("indisponible", ph.ram_detail(ph.Health()))

    def test_bar_text_unchanged(self):
        h = ph.Health(level=80, temp_c=35.0, cpu_pct=23, mem_mb=2867, mem_total_mb=8192, game_mb=512)
        self.assertEqual(h.summary(), "80 % · 35,0 °C · CPU 23 % · RAM 65 % (jeu 512 Mo)")


class Emblems(unittest.TestCase):
    def test_generated_badges_without_images(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtGui import QGuiApplication
        from notrefu_mirror.ui import common

        self.assertEqual(list(common.RESOURCES.joinpath("classes").glob("*.png")), [])  # aucune image protégée embarquée
        if not isinstance(QGuiApplication.instance(), QGuiApplication):
            return  # pas d'application graphique dans ce processus : la génération est vérifiée par smoke_gui
        for n in range(1, common.CLASS_EMBLEMS + 1):
            pm = common.emblem_pixmap(n)
            self.assertFalse(pm.isNull())
            self.assertEqual(pm.width(), 64)


class LegacyMigration(unittest.TestCase):
    def test_settings_copied_once_from_old_name(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import tempfile
        from PySide6.QtCore import QSettings
        from notrefu_mirror.appsettings import migrate_legacy

        d = tempfile.mkdtemp()
        old = QSettings(os.path.join(d, "old.ini"), QSettings.Format.IniFormat)
        new = QSettings(os.path.join(d, "new.ini"), QSettings.Format.IniFormat)
        old.setValue("theme", "sombre"); old.setValue("session0/name", "Iop"); old.sync()
        self.assertEqual(migrate_legacy(new, old), 2)
        self.assertEqual(new.value("session0/name"), "Iop")
        old.setValue("theme", "clair"); old.sync()
        self.assertEqual(migrate_legacy(new, old), 0)  # une seule fois
        self.assertEqual(new.value("theme"), "sombre")

    def test_existing_new_settings_never_overwritten(self):
        import tempfile
        from PySide6.QtCore import QSettings
        from notrefu_mirror.appsettings import migrate_legacy

        d = tempfile.mkdtemp()
        old = QSettings(os.path.join(d, "o.ini"), QSettings.Format.IniFormat); old.setValue("a", 1); old.sync()
        new = QSettings(os.path.join(d, "n.ini"), QSettings.Format.IniFormat); new.setValue("b", 2); new.sync()
        self.assertEqual(migrate_legacy(new, old), 0)
        self.assertFalse(new.contains("a"))


if __name__ == "__main__":
    unittest.main()
