import unittest
from notrefu_mirror.scrcpy_cmd import Settings
from notrefu_mirror.session_logic import MAX_ATTEMPTS, ReconnectPolicy, build_client_params, wifi_target, wm_fix


class Policy(unittest.TestCase):
    def test_no_retry_before_first_connection(self):
        p = ReconnectPolicy()
        self.assertIsNone(p.next_retry(True))

    def test_backoff_and_reset_on_connect(self):
        p = ReconnectPolicy(); p.connected()
        delays = [p.next_retry(True).delay_s for _ in range(8)]
        self.assertEqual(delays, [3, 4, 5, 6, 7, 8, 8, 8])
        p.connected()
        self.assertEqual(p.next_retry(True).attempt, 1)

    def test_user_stop_and_disabled(self):
        p = ReconnectPolicy(); p.connected()
        self.assertIsNone(p.next_retry(False))
        p.user_stop = True
        self.assertIsNone(p.next_retry(True))
        p.reset(); self.assertIsNone(p.next_retry(True))

    def test_gives_up(self):
        p = ReconnectPolicy(); p.connected()
        for _ in range(MAX_ATTEMPTS):
            self.assertIsNotNone(p.next_retry(True))
        self.assertIsNone(p.next_retry(True))
        self.assertTrue(p.gave_up)


class Misc(unittest.TestCase):
    def test_wifi_target(self):
        self.assertEqual(wifi_target("192.168.1.5:5555"), ("192.168.1.5", 5555))
        self.assertIsNone(wifi_target("ABC123"))
        self.assertIsNone(wifi_target("host:abc"))

    def test_wm_fix(self):
        self.assertFalse(wm_fix(("1080x2400", "440"), ("1080x2400", "440")))
        f = wm_fix(("1080x2400", None), ("1920x1080", "300"))
        self.assertTrue(f.fix_size and f.fix_density)
        self.assertEqual((f.size, f.density), ("1080x2400", None))
        self.assertEqual(wm_fix(("a", "440"), ("a", "1")).density, 440)

    def test_params(self):
        s = Settings(serial="S", mode="horizontal", quality="perso")
        s.bitrate_mbps, s.fps, s.reopen_app, s.app_package = 12, 60, True, " a.b "
        p = build_client_params(s, max_size=0, new_display="1920x1080/320", audio_latency_ms=120,
                                game_audio=True, quiet_notifications=False, game_mode="")
        self.assertEqual((p.serial, p.video_bit_rate, p.max_fps, p.app_package, p.audio_source),
                         ("S", 12_000_000, 60, "a.b", "playback"))
        s.reopen_app = False
        self.assertEqual(build_client_params(s, max_size=0, new_display="", audio_latency_ms=1, game_audio=False,
                                             quiet_notifications=False, game_mode="").app_package, "")


if __name__ == "__main__":
    unittest.main()
