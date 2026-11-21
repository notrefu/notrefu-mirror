import struct
import unittest

from notrefu_mirror import protocol as P
from notrefu_mirror.keymap import MAX_BINDINGS, MAX_HOLD_S, MIN_PRESS_GAP_S, KeyMap, KeyTranslator, check_key_name


class Clock:
    def __init__(self): self.t = 100.0
    def __call__(self): return self.t


def decode(msg):
    """(action, pointer_id, x, y) d'un message de toucher."""
    assert msg[0] == P.MSG_INJECT_TOUCH_EVENT
    action = msg[1]
    pid, x, y = struct.unpack(">Qii", msg[2:18])
    return action, pid, x, y


def make(size=(1000, 500)):
    km, sent, clk = KeyMap(), [], Clock()
    km.set("A", 0.5, 0.5)
    km.set("Space", 0.1, 0.9)
    return km, sent, clk, KeyTranslator(km, sent.append, lambda: size, clk)


class Model(unittest.TestCase):
    def test_set_validates(self):
        km = KeyMap()
        self.assertIsNone(km.set("A", 0.2, 0.3))
        for name in ("", "Ctrl+A", "Shift", "Esc", "x" * 30):
            self.assertIsNotNone(km.set(name, 0.5, 0.5), name)
        for x, y in ((-0.1, 0.5), (1.1, 0.5), (float("nan"), 0.5), (0.5, float("inf")), ("a", 0.5), (None, 0.5)):
            self.assertIsNotNone(km.set("B", x, y), (x, y))
        self.assertEqual(list(km.keys), ["A"])

    def test_cap(self):
        km = KeyMap()
        for i in range(MAX_BINDINGS):
            self.assertIsNone(km.set(f"K{i}", 0.5, 0.5))
        self.assertIsNotNone(km.set("Z", 0.5, 0.5))
        self.assertIsNone(km.set("K0", 0.9, 0.9))  # remplacer une existante reste permis

    def test_roundtrip_and_garbage(self):
        km = KeyMap(); km.set("A", 0.25, 0.75); km.active = False; km.show = False
        k2 = KeyMap(); k2.load_json(km.to_json())
        self.assertEqual((k2.keys, k2.active, k2.show), ({"A": (0.25, 0.75)}, False, False))
        for bad in ("", None, "[]", "null", "{", "[" * 100000, '{"keys":[1]}', '{"keys":{"A":[5,5],"B":"x","C":[0.1]}}', b"\xff"):
            k = KeyMap(); k.load_json(bad)
            self.assertEqual(len(k), 0, bad if not isinstance(bad, str) or len(bad) < 40 else "long")

    def test_key_at(self):
        km = KeyMap(); km.set("A", 0.5, 0.5); km.set("B", 0.52, 0.5)
        self.assertEqual(km.key_at(0.519, 0.5, 0.05), "B")
        self.assertIsNone(km.key_at(0.9, 0.9, 0.05))

    def test_reserved(self):
        self.assertIsNotNone(check_key_name("F11", {"F11"}))
        self.assertIsNone(check_key_name("F11"))


class Translator(unittest.TestCase):
    def test_one_press_one_tap(self):
        km, sent, clk, tr = make()
        self.assertTrue(tr.press("A"))
        self.assertEqual(len(sent), 1)
        self.assertEqual(decode(sent[0])[0], P.ACTION_DOWN)
        self.assertEqual(decode(sent[0])[2:], (500, 250))
        self.assertTrue(tr.release("A"))
        self.assertEqual([decode(m)[0] for m in sent], [P.ACTION_DOWN, P.ACTION_UP])
        self.assertEqual(decode(sent[1])[2:], (500, 250))  # le doigt se lève là où il s'est posé

    def test_no_auto_repeat(self):
        km, sent, clk, tr = make()
        tr.press("A")
        for _ in range(50):  # le clavier répète : rien de plus ne part
            clk.t += 0.03
            self.assertTrue(tr.press("A", auto_repeat=True))
            self.assertTrue(tr.press("A"))  # même sans le drapeau : touche déjà enfoncée
        self.assertEqual(len(sent), 1)

    def test_must_release_before_next_action(self):
        km, sent, clk, tr = make()
        tr.press("A"); clk.t += 1; tr.release("A"); clk.t += 1; tr.press("A")
        self.assertEqual([decode(m)[0] for m in sent], [P.ACTION_DOWN, P.ACTION_UP, P.ACTION_DOWN])

    def test_glitchy_release_press_pairs_are_dropped(self):
        km, sent, clk, tr = make()
        tr.press("A")
        for _ in range(20):  # répétition « fausse » sans drapeau : release+press quasi simultanés
            clk.t += MIN_PRESS_GAP_S / 4
            tr.release("A"); tr.press("A")
        downs = [m for m in sent if decode(m)[0] == P.ACTION_DOWN]
        self.assertEqual(len(downs), 1)

    def test_unmapped_or_inactive_not_consumed(self):
        km, sent, clk, tr = make()
        self.assertFalse(tr.press("Q"))
        self.assertFalse(tr.release("Q"))
        km.active = False
        self.assertFalse(tr.press("A"))
        self.assertEqual(sent, [])

    def test_no_frame_no_tap(self):
        km, sent, clk, tr = make(size=None)
        self.assertTrue(tr.press("A"))
        self.assertEqual(sent, [])

    def test_two_keys_two_distinct_fingers_one_message_each(self):
        km, sent, clk, tr = make()
        tr.press("A"); tr.press("Space")
        a, b = decode(sent[0]), decode(sent[1])
        self.assertNotEqual(a[1], b[1])
        self.assertNotEqual(a[1], P.POINTER_ID_MOUSE)
        tr.release("Space"); tr.release("A")
        self.assertEqual(len(sent), 4)

    def test_release_all_and_expire(self):
        km, sent, clk, tr = make()
        tr.press("A"); tr.press("Space")
        tr.release_all()
        self.assertEqual([decode(m)[0] for m in sent].count(P.ACTION_UP), 2)
        self.assertFalse(tr.holding)
        tr.release_all()  # idempotent
        self.assertEqual(len(sent), 4)
        sent.clear(); clk.t += 1; tr.press("A"); clk.t += MAX_HOLD_S + 0.1; tr.expire()
        self.assertEqual([decode(m)[0] for m in sent], [P.ACTION_DOWN, P.ACTION_UP])

    def test_no_broadcast_each_translator_has_its_own_sink(self):
        km1, s1, c1, t1 = make(); km2, s2, c2, t2 = make()
        t1.press("A"); t1.release("A")
        self.assertEqual((len(s1), len(s2)), (2, 0))

    def test_never_more_than_two_messages_per_physical_press(self):
        km, sent, clk, tr = make()
        for i in range(100):
            clk.t += 0.2
            tr.press("A"); tr.release("A")
        self.assertEqual(len(sent), 200)  # exactement DOWN+UP par appui, jamais plus


if __name__ == "__main__":
    unittest.main()


class CopyKeysTests(unittest.TestCase):
    def test_copy_keys_keeps_flags_and_is_independent(self):
        from notrefu_mirror.keymap import KeyMap
        a, b = KeyMap(), KeyMap()
        a.set("A", 0.1, 0.2); a.set("Z", 0.9, 0.8)
        b.set("Q", 0.5, 0.5); b.active = False; b.show = False
        self.assertEqual(b.copy_keys_from(a), 2)
        self.assertEqual(sorted(b.keys), ["A", "Z"])
        self.assertFalse(b.active); self.assertFalse(b.show)
        b.remove("A")
        self.assertIn("A", a.keys)  # copie indépendante
