import unittest
from notrefu_mirror import phonehealth, udev_setup
from notrefu_mirror.guides_layout import autofit_width
from notrefu_mirror.health_monitor import HealthMonitor, tab_status
from notrefu_mirror.wireless import device_state_hint, pair_ip, parse_port, valid_ip


class Wireless(unittest.TestCase):
    def test_port(self):
        self.assertEqual(parse_port(" 5555 "), 5555)
        for bad in ("", "0", "65536", "abc", "-1"):
            self.assertIsNone(parse_port(bad))

    def test_ip_pair_hint(self):
        self.assertTrue(valid_ip("192.168.1.20"))
        self.assertFalse(valid_ip("192.168.1"))
        self.assertEqual(pair_ip(" 10.0.0.5:37123 "), "10.0.0.5")
        self.assertIn("autorisé", device_state_hint("unauthorized"))
        self.assertIsNone(device_state_hint("device"))


class Layout(unittest.TestCase):
    def test_autofit(self):
        # 1920 de large, jeu 16:9 sur 720 px de haut = 1280 px + poignée 6 → reste 634
        self.assertEqual(autofit_width(total=1920, handle=6, host_w=1280, host_h=720, page_w=1280, aspect=16 / 9, current=400), 634)
        self.assertIsNone(autofit_width(total=1920, handle=6, host_w=1280, host_h=720, page_w=1280, aspect=16 / 9, current=630))

    def test_bounds(self):
        self.assertEqual(autofit_width(total=1000, handle=6, host_w=900, host_h=900, page_w=900, aspect=2, current=0), 260)
        self.assertEqual(autofit_width(total=1000, handle=6, host_w=100, host_h=100, page_w=100, aspect=1, current=0), 740)


class Monitor(unittest.TestCase):
    def test_polling_busy(self):
        m = HealthMonitor()
        self.assertEqual(m.to_poll(["a", "b"]), ["a", "b"])
        self.assertEqual(m.to_poll(["a", "c"]), ["c"])
        m.failed("a")
        self.assertEqual(m.to_poll(["a"]), ["a"])

    def test_alert_throttle(self):
        m = HealthMonitor()
        hot = phonehealth.Health(temp_c=60.0)
        alerts = phonehealth.alerts(hot)
        self.assertTrue(alerts)  # sinon le test ne prouve rien
        _, first = m.finish("a", hot, 1000.0)
        _, again = m.finish("a", phonehealth.Health(temp_c=60.0), 1010.0)
        self.assertTrue(first)
        self.assertEqual(again, [])
        _, later = m.finish("a", phonehealth.Health(temp_c=60.0), 1000.0 + 5000)
        self.assertTrue(later)

    def test_tab_status(self):
        self.assertEqual(tab_status(True, False, "", 0), ("warn", "Reconnexion en cours…"))
        st, tip = tab_status(False, True, "38 °C", 3700)
        self.assertEqual(st, "ok")
        self.assertIn("38 °C", tip)
        self.assertIn("Temps de jeu", tip)
        self.assertEqual(tab_status(False, False, "x", 10), ("muted", "Arrêté"))


class Udev(unittest.TestCase):
    def test_commands(self):
        self.assertIn("udevadm", udev_setup.manual_command())
        self.assertIn('install -m 0644 "/t.rules"', udev_setup.install_shell("/t.rules"))


if __name__ == "__main__":
    unittest.main()


class Stats(unittest.TestCase):
    def test_health_first_and_short_audio(self):
        from notrefu_mirror.health_monitor import audio_note, stats_text
        self.assertEqual(audio_note("actif"), "")
        self.assertEqual(audio_note("silence reçu (jeu muet ou capture bloquée par le téléphone)"), "son : silence")
        t = stats_text("30 ips", "silence reçu (x)", "🔋 80 %", True, True)
        self.assertEqual(t, "🔋 80 %  ·  30 ips  ·  son : silence")
        self.assertEqual(stats_text("30 ips", "silence", "🔋 80 %", False, False), "🔋 80 %")


class PowerTests(unittest.TestCase):
    def test_thermal_levels_with_hysteresis(self):
        from notrefu_mirror import power
        self.assertEqual(power.thermal_level(0, 36.0, 0), 0)
        self.assertEqual(power.thermal_level(0, 41.5, 0), 1)
        self.assertEqual(power.thermal_level(0, 38.0, 2), 1)  # état Android « moderate »
        self.assertEqual(power.thermal_level(0, 44.5, 0), 2)
        self.assertEqual(power.thermal_level(1, 40.0, 0), 1)  # entre les seuils : on reste
        self.assertEqual(power.thermal_level(1, 39.0, 0), 0)
        self.assertEqual(power.thermal_level(2, 43.0, 0), 2)
        self.assertEqual(power.thermal_level(2, 42.0, 0), 1)
        self.assertEqual(power.thermal_level(2, None, None), 2)  # mesure absente : aucun changement
        self.assertEqual(power.thermal_level(0, None, None), 0)

    def test_caps_lowest_wins(self):
        from notrefu_mirror import power
        c = power.FpsCaps()
        self.assertIsNone(c.effective())
        self.assertTrue(c.set("wifi", 12))
        self.assertFalse(c.set("wifi", 12))
        c.set("thermal", 30)
        self.assertEqual(c.effective(), 12)
        c.set("wifi", None)
        self.assertEqual(c.effective(), 30)
        c.set("thermal", None)
        self.assertIsNone(c.effective())

    def test_stall_guard(self):
        from notrefu_mirror import power
        g = power.StallGuard()
        self.assertEqual(g.update(1, 0), 0)
        self.assertEqual(g.update(2, 5), 1)  # 3 blocages en moins de 10 s
        self.assertEqual(g.update(3, 6), 1)  # trop tôt pour monter encore
        self.assertEqual(g.update(0, 20), 1)
        self.assertEqual(g.update(0, 50), 0)  # 30 s calmes : on redescend

    def test_wake_rules(self):
        from notrefu_mirror import power
        self.assertTrue(power.should_wake(None, 100, True, False))
        self.assertFalse(power.should_wake(90, 100, True, False))
        self.assertTrue(power.should_wake(70, 100, True, False))
        self.assertFalse(power.should_wake(None, 100, False, False))
        self.assertFalse(power.should_wake(None, 100, True, True))  # écran éteint voulu

    def test_note_and_no_background_throttling_left(self):
        from notrefu_mirror import power
        self.assertFalse(hasattr(power, "clamp_bg_fps"))  # plus d'économie d'énergie pour les sessions sans focus
        self.assertFalse(hasattr(power, "DEFAULT_BG_FPS"))
        self.assertEqual(power.throttle_note(0, 0), "")
        self.assertIn("30", power.throttle_note(1, 0))
        self.assertIn("Wi-Fi", power.throttle_note(0, 2))

    def test_report_masks_private_data(self):
        from notrefu_mirror import report
        self.assertEqual(report.mask_ip("connexion 192.168.1.42:5555 ok"), "connexion 192.168.x.x:5555 ok")
        self.assertEqual(report.mask_serial("192.168.1.42:5555"), "192.168.x.x:5555")
        self.assertEqual(report.mask_serial("ABCDEF123456"), "ABC…56")
        self.assertEqual(report.mask_serial(""), "—")
        text = report.build_report({"notrefu-mirror": "1"}, "✔ adb 10.0.0.5", [{"title": "S1", "state": "en cours", "log": ["x 10.0.0.9"]}])
        self.assertNotIn("10.0.0.5", text)
        self.assertNotIn("10.0.0.9", text)
        self.assertIn("S1", text)
