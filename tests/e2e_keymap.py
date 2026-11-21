"""Touches personnalisées de bout en bout : édition à la souris, puis jeu avec un faux téléphone qui compte les messages reçus."""
import os
import struct
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "src"))
sys.path.insert(0, str(root / "tests"))
from fake_scrcpy_server import FakeServer  # noqa: E402

import shutil  # noqa: E402

shutil.rmtree("/tmp/e2e-keymap-cfg", ignore_errors=True)  # réglages vierges à chaque exécution
srv = FakeServer(w=640, h=360, n=3000, audio=True)
os.environ.update({"QT_QPA_PLATFORM": "offscreen", "NOTREFU_MIRROR_NO_WEB": "1", "NOTREFU_MIRROR_ADB": str(root / "tests/fakes/adb"),
                   "NOTREFU_MIRROR_SCRCPY": str(root / "tests/fakes/scrcpy"), "NOTREFU_MIRROR_SCRCPY_SERVER": "/dev/null",
                   "FAKE_PORT": str(srv.port), "XDG_CONFIG_HOME": "/tmp/e2e-keymap-cfg"})
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from notrefu_mirror import protocol as P  # noqa: E402
from notrefu_mirror.ui import MainWindow  # noqa: E402

app = QApplication([])
_NOMOD = Qt.KeyboardModifier.NoModifier


class QTest:  # QtTest n'est pas dans l'AppImage : mini équivalent
    @staticmethod
    def mouseClick(w, button, mods, pos):
        p = QPointF(pos)
        for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            app.sendEvent(w, QMouseEvent(kind, p, w.mapToGlobal(p), button, button if kind == QEvent.Type.MouseButtonPress else Qt.MouseButton.NoButton, mods))

    @staticmethod
    def _txt(key, mods):
        return chr(key).lower() if 32 < key < 127 and not mods else ""

    @staticmethod
    def keyPress(w, key, mods=_NOMOD):
        app.sendEvent(w, QKeyEvent(QEvent.Type.KeyPress, key, mods, QTest._txt(int(key), mods)))

    @staticmethod
    def keyRelease(w, key, mods=_NOMOD):
        app.sendEvent(w, QKeyEvent(QEvent.Type.KeyRelease, key, mods, QTest._txt(int(key), mods)))

    @staticmethod
    def keyClick(w, key, mods=_NOMOD):
        QTest.keyPress(w, key, mods)
        QTest.keyRelease(w, key, mods)
win = MainWindow()
win.resize(1000, 700)
win.show()


def spin(cond, timeout=10.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def pump(s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.005)


def touches():
    """Messages de toucher reçus par le faux téléphone : (action, pointer, x, y). Les mouvements de la souris ne sont pas comptés."""
    b, out, i = bytes(srv.control_bytes), [], 0
    size = struct.calcsize(">BBQiiHHHII")
    while i + size <= len(b):
        if b[i] == P.MSG_INJECT_TOUCH_EVENT:
            _t, action, pid, x, y = struct.unpack(">BBQii", b[i:i + 18])
            out.append((action, pid, x, y))
            i += size
        else:
            i += 1
    return out


page = win.pages()[0]
panel, host = page.panel, page.host
assert spin(lambda: panel.serial == "FAKESERIAL01"), "téléphone non détecté"
panel.start()
assert spin(lambda: panel.running and host._frame is not None), "pas d'image"
pump(0.3)
page.stack.setCurrentIndex(1)
pump(0.2)
base = len(touches())

# --- 1. mode édition : clic = repère en attente, puis touche = assignation
page.set_keymap_editing(True)
assert host.overlay.editing and host.overlay.isVisible()
r = host._target_rect()
center = QPoint(r.x() + r.width() // 2, r.y() + r.height() // 4)  # milieu, quart haut
QTest.mouseClick(host.overlay, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
assert host.overlay._pending is not None, "le clic n'a pas créé de repère en attente"
QTest.keyClick(host.overlay, Qt.Key.Key_A)
assert "A" in panel.keymap.keys, panel.keymap.keys
rx, ry = panel.keymap.keys["A"]
assert abs(rx - 0.5) < 0.02 and abs(ry - 0.25) < 0.02, (rx, ry)
assert len(touches()) == base, "l'édition ne doit rien envoyer au téléphone"

# Échap : refusé comme touche, puis quitte l'édition
QTest.mouseClick(host.overlay, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(r.x() + 20, r.y() + 20))
QTest.keyClick(host.overlay, Qt.Key.Key_Escape)
assert host.overlay._pending is None and "Esc" not in panel.keymap.keys
QTest.keyClick(host.overlay, Qt.Key.Key_Escape)
assert not host.overlay.editing, "Échap hors saisie doit quitter le mode édition"

# --- 2. mode jeu : une pression = DOWN puis UP, rien d'autre
QTest.keyPress(host, Qt.Key.Key_A)
pump(0.2)
QTest.keyRelease(host, Qt.Key.Key_A)
pump(0.3)
t = touches()[base:]
assert [x[0] for x in t] == [P.ACTION_DOWN, P.ACTION_UP], t
assert abs(t[0][2] - 320) <= 2 and abs(t[0][3] - 90) <= 2, t  # 640x360 : (0,5 ; 0,25)
assert t[0][1] != P.POINTER_ID_MOUSE


# --- 3. répétition automatique : maintenue 2 s avec répétitions, un seul DOWN
def key_event(kind, key, auto):
    return QKeyEvent(kind, key, Qt.KeyboardModifier.NoModifier, "a", auto, 1)


base2 = len(touches())
app.sendEvent(host, key_event(QEvent.Type.KeyPress, Qt.Key.Key_A, False))
for _ in range(60):
    app.sendEvent(host, key_event(QEvent.Type.KeyPress, Qt.Key.Key_A, True))
    app.sendEvent(host, key_event(QEvent.Type.KeyRelease, Qt.Key.Key_A, True))  # faux relâchements de répétition
    pump(0.02)
t = touches()[base2:]
assert [x[0] for x in t] == [P.ACTION_DOWN], f"la répétition a envoyé des touchers : {t}"
app.sendEvent(host, key_event(QEvent.Type.KeyRelease, Qt.Key.Key_A, False))
pump(0.3)
assert [x[0] for x in touches()[base2:]] == [P.ACTION_DOWN, P.ACTION_UP]

# --- 4. perte du focus pendant qu'une touche est enfoncée : le doigt se lève
pump(0.2)
base3 = len(touches())
app.sendEvent(host, key_event(QEvent.Type.KeyPress, Qt.Key.Key_A, False))
pump(0.1)
host.translator.release_all()  # ce que fait focusOutEvent
pump(0.3)
assert [x[0] for x in touches()[base3:]] == [P.ACTION_DOWN, P.ACTION_UP]
app.sendEvent(host, key_event(QEvent.Type.KeyRelease, Qt.Key.Key_A, False))  # le relâchement tardif ne renvoie rien
pump(0.2)
assert len(touches()) == base3 + 2

# --- 5. touche non assignée : texte normal, aucun toucher ; Ctrl+A : jamais traduit
base4 = len(touches())
QTest.keyClick(host, Qt.Key.Key_B)
QTest.keyClick(host, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
pump(0.3)
assert len(touches()) == base4, "touche non assignée ou Ctrl+A ne doivent pas toucher l'écran"

# --- 6. touches désactivées : la touche redevient du texte
panel.keymap.active = False
QTest.keyClick(host, Qt.Key.Key_A)
pump(0.3)
assert len(touches()) == base4
panel.keymap.active = True

# --- 7. sauvegarde / chargement / copie vers une autre session
cfg = panel.to_config()
assert '"A"' in cfg.keymap
page2 = win.add_session()
page2.panel.copy_from(panel, win.qs)
_a2, _a1 = page2.panel.keymap.keys.get("A"), panel.keymap.keys["A"]
assert _a2 and abs(_a2[0] - _a1[0]) < 1e-4 and abs(_a2[1] - _a1[1]) < 1e-4, "la copie de session doit reprendre les touches"  # arrondi à 5 décimales
assert page2.host.keymap is page2.panel.keymap, "la vue et les réglages doivent partager le même modèle"
assert page2.host.translator._send != host.translator._send

# --- 8. ratios : la position suit le redimensionnement de la fenêtre
win.resize(1400, 800)
pump(0.5)
r2 = host._target_rect()
pos = host.overlay._to_pos(*panel.keymap.keys["A"])
assert abs((pos.x() - r2.x()) / r2.width() - 0.5) < 0.01

if os.environ.get("KEYMAP_SHOT"):
    win.tabs.setCurrentIndex(0)
    page.stack.setCurrentIndex(1)
    page.set_keymap_editing(True)
    for k, (x, y) in {"Space": (0.82, 0.78), "E": (0.9, 0.55), "R": (0.74, 0.88)}.items():
        panel.keymap.set(k, x, y)
    host.overlay._selected = "E"
    host.overlay._pending = (0.35, 0.6)
    pump(0.3)
    win.grab().save(os.environ["KEYMAP_SHOT"])
print("E2E KEYMAP OK")
os._exit(0)
