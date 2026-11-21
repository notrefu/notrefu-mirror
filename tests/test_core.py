import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from notrefu_mirror import adb  # noqa: E402
from notrefu_mirror.scrcpy_cmd import Settings, build_command, explain_failure, valid_package  # noqa: E402

DEVICES = """List of devices attached
FAKESERIAL01            device usb:1-2 product:a52qxx model:SM_A525F device:a52q transport_id:1
192.168.1.42:5555      device product:husky model:Pixel_8_Pro device:husky transport_id:3
adb-ABC123-xyz._adb-tls-connect._tcp device product:p model:Pixel_7 device:panther transport_id:4
0123456789ABCDEF       unauthorized usb:1-3 transport_id:5
FEDCBA9876543210       no permissions (user in plugdev group; are your udev rules wrong?); see [http://developer.android.com/tools/device.html]
ZZZ                    offline
* daemon started successfully
"""


class ParseTests(unittest.TestCase):
    def test_devices(self):
        d = adb.parse_devices(DEVICES)
        self.assertEqual([x.serial for x in d][:3], ["FAKESERIAL01", "192.168.1.42:5555", "adb-ABC123-xyz._adb-tls-connect._tcp"])
        self.assertEqual(len(d), 6)
        self.assertFalse(d[0].wireless)
        self.assertTrue(d[1].wireless)
        self.assertTrue(d[2].wireless)
        self.assertEqual(d[0].model, "SM_A525F")
        self.assertEqual(d[3].state, "unauthorized")
        self.assertEqual(d[4].state, "no permissions")
        self.assertEqual(d[5].state, "offline")
        self.assertIn("Wi-Fi", d[1].label)

    def test_wifi_ip(self):
        self.assertEqual(adb.parse_wifi_ip("    inet 192.168.1.42/24 brd 192.168.1.255 scope global wlan0"), "192.168.1.42")
        self.assertEqual(adb.parse_wifi_ip("192.168.0.0/24 dev wlan0 proto kernel scope link src 192.168.0.17"), "192.168.0.17")
        self.assertIsNone(adb.parse_wifi_ip("    inet 127.0.0.1/8 scope host lo"))
        self.assertIsNone(adb.parse_wifi_ip(""))

    def test_wm(self):
        self.assertEqual(adb.parse_wm("Physical size: 1080x2400\n", "size"), "1080x2400")
        self.assertEqual(adb.parse_wm("Physical size: 1080x2400\nOverride size: 720x1600\n", "size"), "720x1600")
        self.assertEqual(adb.parse_wm("Physical density: 420\n", "density"), "420")

    def test_validators(self):
        self.assertTrue(adb.valid_size("1080x2400"))
        self.assertTrue(adb.valid_size("1080×2400"))
        self.assertFalse(adb.valid_size("1080"))
        self.assertFalse(adb.valid_size("1080x2400; rm -rf"))
        self.assertTrue(adb.valid_dpi("420"))
        self.assertFalse(adb.valid_dpi("10"))
        self.assertFalse(adb.valid_dpi("abc"))
        self.assertTrue(valid_package("com.ankama.dofustouch"))
        self.assertFalse(valid_package("com.ankama.dofustouch --evil"))
        self.assertFalse(valid_package("nodots"))


class CommandTests(unittest.TestCase):
    def test_default_horizontal(self):
        s = Settings(serial="ABC")
        s.apply_preset("haut")
        cmd = build_command("scrcpy", s)
        self.assertEqual(cmd[:3], ["scrcpy", "-s", "ABC"])
        self.assertIn("--video-bit-rate=8M", cmd)
        self.assertIn("--max-fps=60", cmd)
        self.assertIn("--new-display=1920x1080/240", cmd)
        self.assertIn("--start-app=com.ankama.dofustouch", cmd)
        self.assertNotIn("--no-audio", cmd)
        self.assertFalse(any(a.startswith("--max-size") for a in cmd))

    def test_standard_and_options(self):
        s = Settings(serial="X", mode="standard")
        s.apply_preset("haut")
        s.screen_off = s.show_fps = s.show_touches = s.stay_awake = s.power_off_on_close = True
        s.control = s.audio = s.clipboard = False
        s.reopen_app = False
        s.keyboard = "uhid"
        s.shortcut_mod = "lctrl"
        cmd = build_command("scrcpy", s)
        for flag in ("--max-size=1920", "--turn-screen-off", "--print-fps", "--show-touches", "--no-control",
                     "--no-audio", "--no-clipboard-autosync", "--stay-awake", "--power-off-on-close",
                     "--keyboard=uhid", "--shortcut-mod=lctrl", "--video-bit-rate=8M"):
            self.assertIn(flag, cmd)
        self.assertFalse(any(a.startswith(("--new-display", "--start-app")) for a in cmd))

    def test_always_landscape(self):
        s = Settings(serial="X", width=1080, height=1920)
        self.assertIn("--new-display=1920x1080/280", build_command("scrcpy", s))

    def test_bad_package_is_not_passed(self):
        s = Settings(serial="X", app_package="bad name; x")
        self.assertFalse(any(a.startswith("--start-app") for a in build_command("scrcpy", s)))

    def test_no_shell_injection_possible(self):
        s = Settings(serial="X; reboot", title="a b; c")
        cmd = build_command("scrcpy", s)
        self.assertIn("X; reboot", cmd)  # un seul argument, jamais interprété par un shell

    def test_explain(self):
        self.assertIn("autorisé", explain_failure("ERROR: device unauthorized"))
        self.assertIn("règles USB", explain_failure("error: insufficient permissions for device"))
        self.assertIsNone(explain_failure("tout va bien"))


LIST_APPS = """scrcpy 5.0.1 <https://github.com/Genymobile/scrcpy>
[server] INFO: List of apps:
 * Android System                         android
 * Chrome                                 com.android.chrome
 - Dofus Touch                            com.ankama.dofustouch
 - Dofus Touch 2                          com.ankama.dofustouch2 (1.2.3)
"""


class AppsTests(unittest.TestCase):
    def test_parse_list_apps(self):
        apps = adb.parse_list_apps(LIST_APPS)
        self.assertIn(("Dofus Touch", "com.ankama.dofustouch"), apps)
        self.assertIn(("Dofus Touch 2", "com.ankama.dofustouch2"), apps)
        self.assertIn(("Chrome", "com.android.chrome"), apps)
        self.assertEqual(len(apps), 3)  # "android" (un seul mot) n'est pas un nom de paquet valide ici


class WmOverrideTests(unittest.TestCase):
    def test_parse_override(self):
        from notrefu_mirror import adb
        self.assertEqual(adb.parse_wm_override("Physical size: 1220x2712\nOverride size: 1080x1920\n"), "1080x1920")
        self.assertIsNone(adb.parse_wm_override("Physical size: 1220x2712\n"))


class IconTests(unittest.TestCase):
    def test_prefers_full_legacy_icon_over_adaptive_foreground(self):
        from notrefu_mirror import adb
        entries = [(26607, "res/mipmap-xxhdpi-v26/ic_launcher_foreground.png"),
                   (32355, "res/mipmap-xxhdpi-v4/ic_launcher.png"),
                   (10676, "res/mipmap-xxhdpi-v4/ic_launcher_round.png"),
                   (8153, "res/mipmap-xxhdpi-v26/ic_launcher_background.png"),
                   (909, "res/drawable-hdpi-v4/notification_oversize_large_icon_bg.png")]
        ranked = adb.rank_icon_candidates(entries)
        self.assertEqual(ranked[0], "res/mipmap-xxhdpi-v4/ic_launcher.png")
        self.assertNotIn("res/mipmap-xxhdpi-v26/ic_launcher_background.png", ranked)

    def test_webp_size(self):
        from notrefu_mirror import adb
        vp8x = b"RIFF" + b"\0" * 4 + b"WEBPVP8X" + b"\0" * 8 + (191).to_bytes(3, "little") + (191).to_bytes(3, "little") + b"\0" * 4
        self.assertEqual(adb.image_size(vp8x), (192, 192))


    def test_find_icon_in_real_zip(self):
        """Lecture de l'icône sans décompresser tout le fichier : seuls fin d'archive + image sont lus."""
        from pathlib import Path
        from notrefu_mirror import adb
        apk = Path(__file__).parent / "fakes" / "~~abc==" / "com.x-1==" / "base.apk"
        data = apk.read_bytes()
        calls = []

        def read_range(start, length):
            calls.append(length)
            return data[start:start + length]

        icon = adb.find_icon_in_zip(read_range, len(data)) if hasattr(adb, "find_icon_in_zip") else adb.find_zip_icon(read_range, len(data))
        self.assertIsNotNone(icon)
        self.assertEqual(adb.png_size(icon), (128, 128))
        self.assertEqual(icon, (Path(__file__).parent / "fakes" / "icon.png").read_bytes())

    def test_rank_and_png(self):
        from notrefu_mirror import adb
        out = ("      2044  2026-01-01 00:00   res/mipmap-xxhdpi/ic_launcher.png\n"
               "     90000  2026-01-01 00:00   res/drawable/splash_screen.png\n"
               "      9000  2026-01-01 00:00   res/mipmap-xxxhdpi/ic_launcher.png\n"
               "       100  2026-01-01 00:00   AndroidManifest.xml\n")
        self.assertEqual(adb.rank_icon_candidates(adb.parse_zip_listing(out)),
                         ["res/mipmap-xxxhdpi/ic_launcher.png", "res/mipmap-xxhdpi/ic_launcher.png"])
        self.assertEqual(adb.png_size(b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + (128).to_bytes(4, "big") * 2 + b"\0" * 8), (128, 128))
        self.assertIsNone(adb.png_size(b"not a png at all, sorry......."))


class DisplayStateTests(unittest.TestCase):
    def test_parse_display_on(self):
        self.assertTrue(adb.parse_display_on("Display Power: state=ON\n"))
        self.assertFalse(adb.parse_display_on("mWakefulness=Awake\nDisplay Power: state=OFF"))
        self.assertFalse(adb.parse_display_on("mWakefulness=Asleep"))
        self.assertIsNone(adb.parse_display_on("rien"))


class SplitPackageTests(unittest.TestCase):
    def test_split(self):
        self.assertEqual(adb.split_package("com.ankama.dofustouch"), ("com.ankama.dofustouch", None))
        self.assertEqual(adb.split_package("com.ankama.dofustouch@999"), ("com.ankama.dofustouch", 999))

    def test_users(self):
        out = "Users:\n\tUserInfo{0:Propriétaire:c13} running\n\tUserInfo{999:Second space:4010} running\n"
        self.assertEqual(adb.parse_users(out), [(0, "Propriétaire"), (999, "Second space")])

    def test_valid_package_with_user(self):
        from notrefu_mirror.scrcpy_cmd import valid_package
        self.assertTrue(valid_package("com.ankama.dofustouch@999"))
        self.assertFalse(valid_package("com.ankama.dofustouch@x"))


class LauncherDumpTests(unittest.TestCase):
    def test_parse_launcher(self):
        dump = (
            "Activity Resolver Table:\n"
            "  Non-Data Actions:\n"
            "      android.intent.action.MAIN:\n"
            "        3e4c1f com.ankama.dofustouch/.UnityPlayerActivity filter 5a1d\n"
            "          Action: \"android.intent.action.MAIN\"\n"
            "          Category: \"android.intent.category.LAUNCHER\"\n"
        )
        self.assertEqual(adb.parse_launcher_from_dump(dump, "com.ankama.dofustouch"), "com.ankama.dofustouch/.UnityPlayerActivity")
        self.assertIsNone(adb.parse_launcher_from_dump(dump, "autre.paquet"))


class GainTests(unittest.TestCase):
    def test_gain(self):
        from notrefu_mirror.audio import apply_gain
        import struct
        d = struct.pack("<hh", 1000, -1000)
        self.assertEqual(apply_gain(d, 100), d)
        self.assertEqual(apply_gain(d, 0), bytes(4))
        self.assertEqual(struct.unpack("<hh", apply_gain(d, 50)), (250, -250))


class GuidesSites(unittest.TestCase):
    def test_clean_url(self):
        from notrefu_mirror import guides
        self.assertEqual(guides.clean_url("papycha.fr"), "https://papycha.fr")
        self.assertEqual(guides.clean_url("http://a.fr/x"), "http://a.fr/x")
        self.assertEqual(guides.clean_url("javascript:alert(1)"), "")
        self.assertEqual(guides.clean_url("rien"), "")


if __name__ == "__main__":
    unittest.main()

class PhoneHealthTests(unittest.TestCase):
    OUT = (
        "Current Battery Service state:\n  AC powered: false\n  USB powered: true\n  status: 2\n  level: 83\n"
        "  temperature: 365\n@@T\n  Thermal Status: 0\n@@S\n/dev/block/dm-9 232000000 100000000 131072000 44% /data\n"
        "@@M\nMemTotal:        8192000 kB\nMemAvailable:    2048000 kB\n"
        "@@C\ncpu  1000 0 500 8000 500 0 0 0 0 0\ncpu  1100 0 550 8300 550 0 0 0 0 0\n"
    )

    def test_parse(self):
        from notrefu_mirror import phonehealth as ph
        h = ph.parse(self.OUT)
        self.assertEqual(h.level, 83)
        self.assertAlmostEqual(h.temp_c, 36.5)
        self.assertTrue(h.charging)
        self.assertEqual(h.thermal, 0)
        self.assertAlmostEqual(h.free_gb, 125.0, delta=0.1)
        self.assertEqual(h.mem_mb, 2000)
        self.assertEqual(h.mem_total_mb, 8000)
        self.assertEqual(h.ram_pct, 75)
        self.assertEqual(h.cpu_pct, 30)  # 150 occupé sur 500 (inactif : 300 + 50)
        self.assertEqual(h.summary(), "83 % ⚡ · 36,5 °C · CPU 30 % · RAM 75 %")
        self.assertNotIn("Go", h.summary())
        self.assertEqual(ph.alerts(h), [])

    def test_cpu_ram_edge_cases(self):
        from notrefu_mirror import phonehealth as ph
        self.assertIsNone(ph.parse_cpu(""))
        self.assertIsNone(ph.parse_cpu("cpu  a b c d\ncpu  1 2 3 4"))
        self.assertIsNone(ph.parse_cpu("cpu  10 0 5 80 5\ncpu  10 0 5 80 5"))  # aucun temps écoulé
        self.assertEqual(ph.parse_cpu("12.5% TOTAL: 8% user + 4% kernel"), 12)
        self.assertEqual(ph.parse_cpu("cpu  0 0 0 100 0\ncpu  100 0 0 100 0"), 100)
        self.assertIsNone(ph.Health(mem_mb=100).ram_pct)
        self.assertIsNone(ph.Health(mem_mb=100, mem_total_mb=0).ram_pct)
        self.assertEqual(ph.Health(level=50, mem_mb=0, mem_total_mb=1000).summary(), "50 % · RAM 100 %")
        self.assertEqual(ph.parse("garbage").summary(), "")

    def test_alerts(self):
        from notrefu_mirror import phonehealth as ph
        h = ph.Health(level=8, temp_c=46.0, charging=False, thermal=4, free_gb=1.0, mem_mb=300)
        keys = [a[0] for a in ph.alerts(h)]
        self.assertEqual(keys, ["battery", "heat", "thermal", "storage", "memory"])
        self.assertTrue(all(g for k, _t, g in ph.alerts(h) if k in ("battery", "heat", "thermal")))
        self.assertEqual(ph.alerts(ph.Health(level=8, charging=True)), [])

    def test_bandwidth_and_duration(self):
        from notrefu_mirror import phonehealth as ph
        self.assertIn("saccade", ph.bandwidth_text(16, 48, 3, True))
        self.assertNotIn("saccade", ph.bandwidth_text(4, 12, 3, True))
        self.assertEqual(ph.format_duration(125 * 60), "2 h 05")
        self.assertEqual(ph.format_duration(59), "0 min")

    def test_garbage(self):
        from notrefu_mirror import phonehealth as ph
        h = ph.parse("n'importe quoi")
        self.assertIsNone(h.level)
        self.assertEqual(ph.alerts(h), [])


class AdbExtrasTests(unittest.TestCase):
    def test_game_mode(self):
        self.assertEqual(adb.parse_game_mode("Game mode for x: current mode: performance, available game modes: [standard, performance, battery]"),
                         ("performance", ["standard", "performance", "battery"]))
        self.assertEqual(adb.parse_game_mode("rien"), (None, []))

    def test_input_blocked(self):
        self.assertTrue(adb.input_blocked("java.lang.SecurityException: Injecting input events requires the caller to have INJECT_EVENTS"))
        self.assertFalse(adb.input_blocked(""))

    def test_anti_freeze_commands(self):
        calls = []
        old = adb.run_adb
        adb.run_adb = lambda args, serial=None, timeout=15.0: calls.append(args) or "ok"
        try:
            res = adb.anti_freeze("S", "com.ankama.dofustouch@999")
        finally:
            adb.run_adb = old
        self.assertTrue(all(ok for _t, ok, _m in res))
        self.assertIn(["shell", "cmd", "deviceidle", "whitelist", "+com.ankama.dofustouch"], calls)
        self.assertIn(["shell", "cmd", "appops", "set", "--user", "999", "com.ankama.dofustouch", "RUN_IN_BACKGROUND", "allow"], calls)


class SettingsIoTests(unittest.TestCase):
    def test_roundtrip(self):
        import json, tempfile, os
        from notrefu_mirror import settingsio

        class FakeQs:
            def __init__(self, d): self.d = dict(d)
            def allKeys(self): return list(self.d)
            def value(self, k, default=None): return self.d.get(k, default)
            def setValue(self, k, v): self.d[k] = v
            def remove(self, k): self.d.pop(k, None)
            def sync(self): pass

        src = FakeQs({"tabs": 2, "panel0/name": "sakloz", "geometry": b"xx", "detached/a/geometry": "g", "theme": "zinc", "ws/x/count": 1})
        path = os.path.join(tempfile.mkdtemp(), "r.json")
        n = settingsio.export_to(src, path, "0.9.0")
        self.assertEqual(n, 4)  # sans géométrie ni fenêtres détachées
        doc = json.load(open(path, encoding="utf-8"))
        self.assertEqual(doc["app"], settingsio.MARKER)
        dst = FakeQs({"tabs": 9, "panel5/name": "vieux", "geometry": b"keep"})
        settingsio.apply_to(dst, settingsio.read_file(path))
        self.assertEqual(dst.d["tabs"], 2)
        self.assertNotIn("panel5/name", dst.d)
        self.assertEqual(dst.d["geometry"], b"keep")
        bad = os.path.join(tempfile.mkdtemp(), "b.json")
        open(bad, "w").write("{}")
        with self.assertRaises(settingsio.SettingsFileError):
            settingsio.read_file(bad)


class HotkeyConflictTests(unittest.TestCase):
    def test_conflicts(self):
        from notrefu_mirror.hotkeys import find_conflicts, default_bindings
        self.assertEqual(find_conflicts(default_bindings()), {})
        b = default_bindings()
        b["grid"] = "ctrl+shift+s"
        self.assertEqual(list(find_conflicts(b).values()), [["screenshot", "grid"]])

