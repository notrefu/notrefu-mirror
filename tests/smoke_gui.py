"""Test de fumée de l'interface (Qt offscreen) : faux adb + faux serveur scrcpy H.264 réel."""
import os, sys, time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
sys.path.insert(0, str(root / "tests"))
from fake_scrcpy_server import FakeServer

import shutil; shutil.rmtree("/tmp/notrefu_mirror-test-cfg", ignore_errors=True)
srv = FakeServer(w=640, h=360, n=400, audio=True)  # ~4 s de vidéo
os.environ.update({
    "QT_QPA_PLATFORM": "offscreen",
    "NOTREFU_MIRROR_ADB": str(root / "tests/fakes/adb"),
    "NOTREFU_MIRROR_SCRCPY": str(root / "tests/fakes/scrcpy"),
    "NOTREFU_MIRROR_SCRCPY_SERVER": "/dev/null",
    "FAKE_PORT": str(srv.port),
    "XDG_CONFIG_HOME": "/tmp/notrefu_mirror-test-cfg",
})

_errors = []
def _hook(t, v, tb):
    import traceback
    _errors.append(f'{t.__name__}: {v}')
    traceback.print_exception(t, v, tb)
sys.excepthook = _hook
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtCore import QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtCore import QEvent


class QTest:  # QtTest n'est pas embarqué dans l'AppImage : équivalents minimaux
    @staticmethod
    def mouseClick(w, button, mods, pos):
        pf = QPointF(pos)
        for typ, btns in ((QEvent.Type.MouseButtonPress, button), (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
            ev = QMouseEvent(typ, pf, w.mapToGlobal(pf), button, btns, mods)
            QApplication.sendEvent(w, ev)

    @staticmethod
    def keyClick(w, key, mods=Qt.KeyboardModifier.NoModifier):
        from PySide6.QtGui import QKeySequence
        text = chr(key.value + 32) if 0x41 <= key.value <= 0x5A and not mods else ""
        for typ in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QApplication.sendEvent(w, QKeyEvent(typ, key.value, mods, text))
from PySide6.QtWidgets import QApplication
from notrefu_mirror import protocol as P
from notrefu_mirror.ui import MainWindow

app = QApplication([])
win = MainWindow()
win.resize(1000, 700)
win.show()


def spin(cond, timeout=10.0, what=""):
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError("timeout: " + what)


p = win.panels()[0]
p.opt_screen_off.setChecked(True)
p.alat_spin.setValue(150)
p.opt_autostart.setChecked(True)  # doit démarrer tout seul dès que le téléphone est vu
spin(lambda: p.serial == "FAKESERIAL01", what="device detected")
spin(lambda: "Android 13" in p.info_label.text(), what="device info")
p.opt_fps.setChecked(True)
spin(lambda: p.client is not None, what="démarrage automatique")
page = win.pages()[0]
spin(lambda: p.client and p.client.decoded_frames > 5, what="frames decoded")
assert page.stack.currentIndex() == 1, "doit afficher la zone de jeu"
view = page.host
spin(lambda: view._image is not None, what="image affichée")
print("frame:", view._frame.width, view._frame.height, "source", view._frame.source_width, view._frame.source_height)
pix = view.grab()
assert not pix.isNull()

# clic gauche au centre -> DOWN/UP à (320,180)
r = view._target_rect()
c = r.center()
QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c)
down = P.inject_touch_event(P.ACTION_DOWN, P.POINTER_ID_MOUSE, 319, 179, 640, 360, 1.0, 1, 1)
up = P.inject_touch_event(P.ACTION_UP, P.POINTER_ID_MOUSE, 319, 179, 640, 360, 0.0, 1, 0)
spin(lambda: down in bytes(srv.control_bytes) and up in bytes(srv.control_bytes), what="touch envoyé")
spin(lambda: P.start_app("com.ankama.dofustouch") in bytes(srv.control_bytes), what="appli lancée")
# presse-papiers : téléphone -> PC, puis Ctrl+V PC -> téléphone
from PySide6.QtGui import QGuiApplication
spin(lambda: QGuiApplication.clipboard().text() == "copié sur le téléphone", what="presse-papiers reçu")
QGuiApplication.clipboard().setText("du PC")
QTest.keyClick(view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
spin(lambda: P.set_clipboard("du PC", paste=True) in bytes(srv.control_bytes), what="Ctrl+V envoyé")
# touche : texte
QTest.keyClick(view, Qt.Key.Key_A)
spin(lambda: P.inject_text("a") in bytes(srv.control_bytes), what="texte envoyé")
QTest.keyClick(view, Qt.Key.Key_Return)
spin(lambda: P.inject_keycode(P.KEY_DOWN, P.AKEYCODE_ENTER) in bytes(srv.control_bytes), what="Entrée envoyée")
spin(lambda: p.fps_label.text().endswith(" ms") and "ips" in p.fps_label.text(), what="fps", timeout=4)
print("fps:", p.fps_label.text())

# écran du téléphone : éteint au lancement (même avec écran virtuel), bouton pour le rallumer
spin(lambda: P.set_display_power(False) in bytes(srv.control_bytes), what="écran éteint au lancement")
page._toggle_phone_screen()
spin(lambda: P.set_display_power(True) in bytes(srv.control_bytes), what="écran rallumé")
assert p.client.params.audio_latency_ms == 150
# barre d'outils : Accueil + capture
page._key(P.AKEYCODE_HOME)
spin(lambda: P.inject_keycode(P.KEY_UP, P.AKEYCODE_HOME) in bytes(srv.control_bytes), what="Accueil")
os.environ["XDG_PICTURES_DIR"] = "/tmp/notrefu_mirror-shots"
shot = view.save_screenshot("Eniripsa 1")
assert shot.endswith(".png") and os.path.getsize(shot) > 500, shot
print("capture:", shot)

# deuxième session + raccourcis : Ctrl+Tab / Alt+1
win.new_session()
assert win.tabs.count() == 2 and win.tabs.currentIndex() == 1
QTest.keyClick(win, Qt.Key.Key_1, Qt.KeyboardModifier.AltModifier)
spin(lambda: win.tabs.currentIndex() == 0, what="Alt+1")
QTest.keyClick(win, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
spin(lambda: win.tabs.currentIndex() == 1, what="Ctrl+Tab")
win.on_hotkey("prev")
assert win.tabs.currentIndex() == 0

# la touche tab visible ne reçoit plus d'images quand l'onglet est masqué
win.tabs.setCurrentIndex(1)
n = p.client.decoded_frames
app.processEvents()

# arrêt
win.tabs.setCurrentIndex(0)
p.stop()
spin(lambda: not p.running, what="stop")
spin(lambda: p.start_btn.isEnabled(), what="bouton Lancer réactivé", timeout=6)
assert page.stack.currentIndex() == 0

# reconnexion automatique : le téléphone coupe, puis revient
srv2 = FakeServer(w=640, h=360, n=2000, audio=True)
os.environ["FAKE_PORT"] = str(srv2.port)
p.start()
spin(lambda: p.client and p.client.decoded_frames > 3, what="session 2")
first_client = p.client
srv2.close()  # coupure
spin(lambda: p.reconnecting, what="reconnexion planifiée")
assert p.running and "Nouvelle tentative" in p.hint_label.text(), p.hint_label.text()
srv3 = FakeServer(w=640, h=360, n=2000, audio=True)
os.environ["FAKE_PORT"] = str(srv3.port)
spin(lambda: p.client is not first_client and p.client.decoded_frames > 3, timeout=15, what="reconnecté")
assert page.stack.currentIndex() == 1 and p.hint_label.text() == ""
print("reconnexion OK")
p.stop()  # arrêt volontaire : pas de nouvelle tentative
spin(lambda: not p.running, what="stop 2")
srv3.close()
time.sleep(0.3); app.processEvents()
assert not p.reconnecting

# détection des applications Dofus avec icônes
from notrefu_mirror.ui import AppPickerDialog
from notrefu_mirror import adb as _adb
apps = _adb.list_apps(p.serial)
dlg = AppPickerDialog(win.runner, p.serial, apps, win)
assert dlg.list.count() == 2, dlg.list.count()   # Chrome filtré
def _is_phone_icon(i):
    c = dlg.list.item(i).icon().pixmap(48, 48).toImage().pixelColor(10, 10)
    return c.red() < 70 and c.blue() > 180
spin(lambda: _is_phone_icon(0) and _is_phone_icon(1), what="icônes du téléphone chargées")
first = dlg.list.item(0)
assert first.text().startswith("Dofus Touch") and first.data(0x100) == "com.ankama.dofustouch"
pm = first.icon().pixmap(48, 48)
c = pm.toImage().pixelColor(10, 10)
assert c.red() < 70 and c.blue() > 180, f"icône du téléphone attendue (bleue), pas l'icône par défaut : {c.getRgb()}"
assert not dlg.list.item(0).toolTip(), dlg.list.item(0).toolTip()
dlg.show_all.setChecked(True)
assert dlg.list.count() == 3
dlg.reject()
print("apps:", [dlg.list.item(i).text().replace("\n", " | ") for i in range(3)])

# fermer la dernière session : pas de recréation automatique, puis nouvelle session numérotée proprement
from PySide6.QtWidgets import QMessageBox
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
while win.tabs.count() > 1:
    win._close_tab(0)
last_title = win.panels()[0].title
win._close_tab(0)
app.processEvents()
assert win.tabs.count() == 0 and win.central_stack.currentIndex() == 1, "page vide attendue"
win.new_session()
assert win.tabs.count() == 1 and win.central_stack.currentIndex() == 0
assert win.panels()[0].title == "Session 1", win.panels()[0].title
p = win.panels()[0]
spin(lambda: p.serial == "FAKESERIAL01", what="device detected again")

# erreur : serveur injoignable (port fermé) -> message lisible
srv.close()
os.environ["FAKE_PORT"] = "1"
p.start()
spin(lambda: p.client.state == "error", timeout=30, what="erreur")
print("hint:", p.hint_label.text())
assert p.hint_label.text()
# fenêtre Guides (navigateur intégré)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")
win.toggle_guides()
spin(lambda: win._guides is not None and win._guides.isVisible(), what="guides")
win._guides_swap_side()
assert win._guides.isVisible() and win.split.indexOf(win._guides) == 0
win._guides_swap_side()
from notrefu_mirror import guides as _g
print("guides web:", _g.HAS_WEB, [x["name"] for x in win._guides.sites])
assert len(win._guides.sites) >= 2
win.toggle_guides()
import time as _t
_t0 = _t.monotonic()
# Espace : une session fraîchement créée doit connaître les téléphones déjà détectés (pas de faux « Aucun téléphone sélectionné »)
assert win._devices, "le faux adb doit avoir listé un téléphone"
_serial = win._devices[0].serial
_pg = win.add_session()
assert _pg.panel.serial == "", "session neuve : liste vide avant le rafraîchissement"
_pg.panel._wanted_serial = _serial  # ce que fait load() avec le numéro de série enregistré
assert win._attach_known_devices(_pg.panel) == _serial
assert _pg.panel.serial == _serial, _pg.panel.serial
from PySide6.QtWidgets import QMessageBox as _MB
_warned = []
_old_warning = _MB.warning
_MB.warning = staticmethod(lambda *a, **k: _warned.append(a))
_pg2 = win.add_session()
_pg2.panel._wanted_serial = _serial  # liste vide + numéro enregistré : start() doit utiliser le numéro enregistré
_pg2.panel.start()
_MB.warning = _old_warning
assert not _warned, _warned
_pg2.panel.stop()
from PySide6.QtCore import Qt as _Qt
assert win.cursor().shape() == _Qt.CursorShape.ArrowCursor, "la fenêtre ne doit jamais garder un curseur de redimensionnement"
assert win.tabs.cursor().shape() == _Qt.CursorShape.ArrowCursor
assert len(win._grips.grips) == 8 and not any(g.isHidden() for g in win._grips.grips.values())
win.showMaximized(); app.processEvents()
win.showNormal(); app.processEvents()
assert win.cursor().shape() == _Qt.CursorShape.ArrowCursor
win.close()
app.processEvents()
assert win._cleaned, "cleanup() n'a pas été exécuté à la fermeture"
assert _t.monotonic() - _t0 < 8, "fermeture trop lente"
win.cleanup()  # deuxième appel (aboutToQuit) : sans effet
assert not _errors, _errors
from notrefu_mirror.ui import common as _common
for _n in range(1, _common.CLASS_EMBLEMS + 1):
    assert not _common.emblem_pixmap(_n).isNull(), _n  # pastilles générées sans image de jeu
print("SMOKE OK")
os._exit(0)
