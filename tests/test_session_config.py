import unittest
from notrefu_mirror.session_config import SessionConfig


class FakeStore(dict):
    def value(self, key, default=None):
        return self.get(key, default)

    def setValue(self, key, v):
        self[key] = v


CHECKS = ("audio", "fps", "stay")


def full():
    return SessionConfig(mode="horizontal", shape="auto", zoom=130, quality="perso",
                         spins={"br": 12, "fps": 60, "w": 1920, "h": 1080, "dpi": 320, "alat": 150},
                         checks={"audio": True, "fps": False, "stay": True}, app="a.b.c", playtime=42,
                         gamemode="x", name="Iop", ip="1.2.3.4", port="5556", kb="azerty", mod="alt",
                         serial="S1", color="#fff", icon="builtin:03", volume=70, was_running=True)


class Config(unittest.TestCase):
    def test_roundtrip(self):
        st = FakeStore()
        c = full()
        c.save(st, "panel0")
        self.assertEqual(SessionConfig.load(st, "panel0", CHECKS), c)

    def test_keys_unchanged(self):
        st = FakeStore()
        full().save(st, "p")
        for k in ("mode", "shape", "zoom", "quality", "br_v", "fps_v", "w_v", "h_v", "dpi_v", "alat_v", "audio",
                  "fps", "app", "playtime", "gamemode", "name", "ip", "port", "kb", "mod", "serial", "color",
                  "icon", "volume", "was_running"):
            self.assertIn(f"p/{k}", st)

    def test_defaults_when_empty(self):
        c = SessionConfig.load(FakeStore(), "panel3", CHECKS)
        self.assertEqual((c.app, c.port, c.volume, c.was_running, c.zoom, c.checks), ("com.ankama.dofustouch", "5555", 100, False, None, {}))
        self.assertEqual(c.icon, "builtin:04")

    def test_legacy(self):
        st = FakeStore({"p/fit": "false", "p/br": "8", "p/fps": "false", "p/fps_v": "30"})
        c = SessionConfig.load(st, "p", ("fps",))
        self.assertEqual(c.shape, "perso")
        self.assertEqual(c.spins["br"], 8)
        self.assertEqual(c.spins["fps"], 30)
        self.assertEqual(c.checks["fps"], False)

    def test_bad_values_ignored(self):
        st = FakeStore({"p/br_v": "oops", "p/zoom": "x", "p/playtime": "?", "p/was_running": "True"})
        c = SessionConfig.load(st, "p")
        self.assertNotIn("br", c.spins)
        self.assertIsNone(c.zoom)
        self.assertEqual(c.playtime, 0)
        self.assertTrue(c.was_running)


if __name__ == "__main__":
    unittest.main()
