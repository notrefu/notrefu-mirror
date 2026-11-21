import unittest
from notrefu_mirror.session_config import SessionConfig
from notrefu_mirror.stores import GuidesStore, StartupStore, WorkspaceStore, space_name


class Fake(dict):
    def value(self, k, d=None): return self.get(k, d)
    def setValue(self, k, v): self[k] = v
    def allKeys(self): return list(self)
    def remove(self, k):
        for key in [x for x in self if x == k or x.startswith(k + "/")]:
            del self[key]


class Stores(unittest.TestCase):
    def test_space_name(self):
        self.assertEqual(space_name("  a/b  "), "a-b")
        self.assertEqual(len(space_name("x" * 90)), 40)

    def test_workspaces(self):
        st = Fake(); w = WorkspaceStore(st)
        self.assertEqual(w.names(), [])
        w.save("Mes 4", [SessionConfig(name="A"), SessionConfig(name="B")])
        w.save("Autre", [SessionConfig(name="C")])
        self.assertEqual(w.names(), ["Autre", "Mes 4"])
        self.assertEqual((w.count("Mes 4"), w.count("Autre"), w.count("x")), (2, 1, 0))
        self.assertEqual(SessionConfig.load(st, w.prefix("Mes 4", 1)).name, "B")
        w.save("Mes 4", [SessionConfig(name="Z")])  # remplace, sans reste de l'ancienne version
        self.assertEqual((w.count("Mes 4"), "ws/Mes 4/1/name" in st), (1, False))
        w.delete("Autre")
        self.assertEqual(w.names(), ["Mes 4"])

    def test_startup(self):
        st = Fake(); s = StartupStore(st)
        self.assertEqual((s.raw(), s.mode(), s.tab_count(), s.restore_policy()), ("restore", "restore", 1, "ask"))
        s.set("space:Mes 4"); self.assertEqual((s.raw(), s.mode()), ("space:Mes 4", "empty"))
        s.set("n'importe quoi"); self.assertEqual(s.raw(), "restore")
        s.set_tab_count(0); self.assertEqual(s.tab_count(), 0)
        s.set_tab_count(20); self.assertEqual(s.tab_count(), 8)
        st["tabs"] = "abc"; self.assertEqual(s.tab_count(), 1)
        s.set_restore_always(); self.assertEqual(s.restore_policy(), "always")

    def test_guides(self):
        st = Fake(); g = GuidesStore(st)
        self.assertEqual((g.auto, g.width, g.side), (True, 480, "right"))
        g.auto = False; g.width = 600; g.side = "left"
        self.assertEqual((g.auto, g.width, g.side), (False, 600, "left"))
        st["guides/auto"] = "false"; self.assertFalse(g.auto)


if __name__ == "__main__":
    unittest.main()
