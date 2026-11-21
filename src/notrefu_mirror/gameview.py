"""Zone de jeu : affiche le flux du téléphone et transforme souris/clavier en commandes tactiles."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QKeyEvent, QPainter
from PySide6.QtWidgets import QWidget

from . import protocol as P
from .engine import Frame, ScrcpyClient
from .keymap import KeyMap, KeyTranslator
from .keymap_view import KeyMapOverlay, key_name

_Q = Qt.Key
KEYMAP = {
    _Q.Key_Return: P.AKEYCODE_ENTER, _Q.Key_Enter: P.AKEYCODE_ENTER, _Q.Key_Backspace: P.AKEYCODE_DEL,
    _Q.Key_Delete: P.AKEYCODE_FORWARD_DEL, _Q.Key_Escape: P.AKEYCODE_BACK, _Q.Key_Tab: P.AKEYCODE_TAB,
    _Q.Key_Left: P.AKEYCODE_DPAD_LEFT, _Q.Key_Right: P.AKEYCODE_DPAD_RIGHT,
    _Q.Key_Up: P.AKEYCODE_DPAD_UP, _Q.Key_Down: P.AKEYCODE_DPAD_DOWN,
    _Q.Key_PageUp: P.AKEYCODE_PAGE_UP, _Q.Key_PageDown: P.AKEYCODE_PAGE_DOWN,
    _Q.Key_Home: P.AKEYCODE_MOVE_HOME, _Q.Key_End: P.AKEYCODE_MOVE_END,
}


class GameView(QWidget):
    frame_ready = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.client: ScrcpyClient | None = None
        self.message = "Aucune session en cours."
        self.control = True
        self.clipboard = False
        self.audio_on = True  # vue en grille : seule la cellule choisie joue du son
        self._frame: Frame | None = None
        self._image: QImage | None = None
        self._down = False
        self.setMinimumSize(320, 200)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(False)
        self._notified = False
        self.frame_ready.connect(self._on_frame, Qt.ConnectionType.QueuedConnection)
        # Touches personnalisées : modèle (ratios), traducteur (touche -> un seul toucher) et surcouche d'édition.
        # Le traducteur écrit UNIQUEMENT dans le client de cette vue : jamais de diffusion vers d'autres sessions.
        self.keymap = KeyMap()
        self.translator = KeyTranslator(self.keymap, self._send_control, self._frame_dims)
        self.reserved_keys = lambda: set()  # touches déjà prises par des raccourcis de l'application (fourni par la fenêtre)
        self.overlay = KeyMapOverlay(self, self.keymap, lambda: self.reserved_keys())
        app = QGuiApplication.instance()
        if app is not None:  # l'application passe en arrière-plan (alt-tab, boîte de dialogue d'un autre programme) : tout relâcher
            app.applicationStateChanged.connect(self._app_state_changed)
        self._hold_timer = QTimer(self)
        self._hold_timer.setInterval(250)
        self._hold_timer.timeout.connect(self._expire_keys)

    # ---- liaison avec le client ----------------------------------------
    def attach(self, client: ScrcpyClient | None, control: bool = True, clipboard: bool = False,
               keep_image: bool = False) -> None:
        self.translator.release_all()  # aucun « doigt » ne reste posé sur l'ancienne session
        self.client = client
        self.control = control
        self.clipboard = clipboard
        if not keep_image:  # keep_image : relance d'adaptation, la dernière image reste jusqu'à la première nouvelle
            self._frame = self._image = None
        self._down = False
        if client:
            client.set_view_size(self.width(), self.height())
        self.update()

    def set_message(self, text: str) -> None:
        self.message = text
        self.update()

    def notify_frame(self) -> None:
        """Appelé depuis un thread du moteur. Un seul signal en attente à la fois : si l'interface a du retard,
        les images intermédiaires ne s'empilent pas (seule la dernière image compte)."""
        if self._notified:
            return
        self._notified = True
        self.frame_ready.emit()

    def _on_frame(self) -> None:
        self._notified = False
        if not self.client or not self.isVisible():
            return
        self._set_frame(self.client.latest_frame())

    def _set_frame(self, f: Frame | None) -> None:
        if f is None:
            return
        self._frame = f
        self._image = QImage(f.data, f.width, f.height, f.stride, QImage.Format.Format_RGB888)
        self._image.setDevicePixelRatio(self.devicePixelRatioF())
        self.update()

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        if self.client:
            self._push_view_size()
            self._set_frame(self.client.refresh_frame())

    def hideEvent(self, ev) -> None:  # noqa: N802
        self.translator.release_all()
        super().hideEvent(ev)

    def _app_state_changed(self, state) -> None:
        if state != Qt.ApplicationState.ApplicationActive:
            self.translator.release_all()

    def changeEvent(self, ev) -> None:  # noqa: N802
        if ev.type() == ev.Type.ActivationChange and not self.isActiveWindow():
            self.translator.release_all()  # la fenêtre (ou une boîte de dialogue ouverte par-dessus) a pris l'activation
        super().changeEvent(ev)

    def focusOutEvent(self, ev) -> None:  # noqa: N802
        self.translator.release_all()  # on perd le focus : plus aucune touche ne peut agir
        super().focusOutEvent(ev)

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        self.overlay.setGeometry(self.rect())
        if self.client:
            self._push_view_size()

    def _push_view_size(self) -> None:
        d = self.devicePixelRatioF()  # taille en vrais pixels : le décodeur réduit l'image exactement à cette taille
        self.client.set_view_size(int(self.width() * d), int(self.height() * d))

    # ---- dessin ---------------------------------------------------------
    def _target_rect(self) -> QRect:
        f = self._frame
        if not f or not f.source_width or not f.source_height:
            return QRect()
        sw, sh = f.source_width, f.source_height
        scale = min(self.width() / sw, self.height() / sh)
        w, h = int(sw * scale), int(sh * scale)
        return QRect((self.width() - w) // 2, (self.height() - h) // 2, w, h)

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(16, 16, 20))
        r = self._target_rect()
        if self._image is not None and not r.isEmpty():
            d = self._image.devicePixelRatio() or 1.0
            iw, ih = self._image.width() / d, self._image.height() / d
            if abs(iw - r.width()) <= 3 and abs(ih - r.height()) <= 3:
                # image déjà à la bonne taille : on la pose pixel pour pixel (aucun second redimensionnement = pas de flou)
                p.drawImage(QPointF(r.x() + (r.width() - iw) / 2, r.y() + (r.height() - ih) / 2), self._image)
            else:
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                p.drawImage(r, self._image)
        else:
            p.setPen(QColor(170, 170, 180))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)

    # ---- souris ---------------------------------------------------------
    def _to_device(self, pos: QPoint) -> tuple[int, int] | None:
        r, f = self._target_rect(), self._frame
        if r.isEmpty() or not f:
            return None
        x = (pos.x() - r.x()) * f.source_width / r.width()
        y = (pos.y() - r.y()) * f.source_height / r.height()
        return min(max(int(x), 0), f.source_width - 1), min(max(int(y), 0), f.source_height - 1)

    def _touch(self, action: int, pos: QPoint, pressure: float) -> None:
        pt = self._to_device(pos)
        if pt is None or not self.client or not self._frame:
            return
        f = self._frame
        self.client.send(P.inject_touch_event(
            action, P.POINTER_ID_MOUSE, pt[0], pt[1], f.source_width, f.source_height, pressure,
            P.BUTTON_PRIMARY if action != P.ACTION_MOVE else 0, P.BUTTON_PRIMARY if pressure else 0))

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        self.setFocus()
        if not (self.client and self.control):
            return
        b = ev.button()
        if b == Qt.MouseButton.LeftButton:
            self._down = True
            self._touch(P.ACTION_DOWN, ev.position().toPoint(), 1.0)
        elif b == Qt.MouseButton.RightButton:
            self.client.send(P.back_or_screen_on(P.KEY_DOWN))
            self.client.send(P.back_or_screen_on(P.KEY_UP))
        elif b == Qt.MouseButton.MiddleButton:
            self.client.send(P.inject_keycode(P.KEY_DOWN, P.AKEYCODE_HOME))
            self.client.send(P.inject_keycode(P.KEY_UP, P.AKEYCODE_HOME))

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if self._down and self.client and self.control:
            self._touch(P.ACTION_MOVE, ev.position().toPoint(), 1.0)

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton and self._down:
            self._down = False
            if self.client and self.control:
                self._touch(P.ACTION_UP, ev.position().toPoint(), 0.0)

    def wheelEvent(self, ev) -> None:  # noqa: N802
        pt, f = self._to_device(ev.position().toPoint()), self._frame
        if pt and f and self.client and self.control:
            d = ev.angleDelta()
            self.client.send(P.inject_scroll_event(pt[0], pt[1], f.source_width, f.source_height,
                                                   d.x() / 120, d.y() / 120))

    # ---- clavier --------------------------------------------------------
    def keyPressEvent(self, ev: QKeyEvent) -> None:  # noqa: N802
        self._key(ev, True)

    def keyReleaseEvent(self, ev: QKeyEvent) -> None:  # noqa: N802
        self._key(ev, False)

    # ---- touches personnalisées ---------------------------------------------
    def _send_control(self, msg: bytes) -> None:
        if self.client and self.control:
            self.client.send(msg)

    def _frame_dims(self) -> tuple[int, int] | None:
        f = self._frame
        return (f.source_width, f.source_height) if f and f.source_width and f.source_height else None

    def bind_keymap(self, keymap: KeyMap) -> None:
        """Utilise le modèle de touches de la session (le même objet que celui des réglages)."""
        self.keymap = self.translator.keymap = self.overlay.keymap = keymap
        self.overlay.refresh()

    def set_keymap_editing(self, on: bool) -> None:
        self.translator.release_all()
        self.overlay.set_editing(on)

    def _expire_keys(self) -> None:
        self.translator.expire()
        if not self.translator.holding:
            self._hold_timer.stop()

    def _mapped_key(self, ev: QKeyEvent, down: bool) -> bool:
        """True si l'événement est une touche assignée : elle est traduite en UN toucher et ne va nulle part ailleurs."""
        if self.overlay.editing or ev.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
                                                      | Qt.KeyboardModifier.MetaModifier):
            return False
        name = key_name(ev)
        if not name:
            return False
        if ev.isAutoRepeat():  # répétition du clavier : consommée, jamais traduite
            return self.keymap.active and name in self.keymap.keys
        handled = self.translator.press(name) if down else self.translator.release(name)
        if self.translator.holding and not self._hold_timer.isActive():
            self._hold_timer.start()
        return handled

    def _key(self, ev: QKeyEvent, down: bool) -> None:
        if not (self.client and self.control):
            return
        if self._mapped_key(ev, down):
            return
        if ev.isAutoRepeat() and not down:
            return
        mods = ev.modifiers()
        if (self.clipboard and mods == Qt.KeyboardModifier.ControlModifier
                and ev.key() in (Qt.Key.Key_C, Qt.Key.Key_X, Qt.Key.Key_V)):
            if down and not ev.isAutoRepeat():  # une pression = un collage, jamais de répétition
                self._clipboard_key(ev.key())
            return
        if (mods == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
                and ev.key() == Qt.Key.Key_V):
            if down and not ev.isAutoRepeat():
                self._type_clipboard()
            return
        code = KEYMAP.get(Qt.Key(ev.key()))
        ctrl_alt = mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        if code is not None:
            self.client.send(P.inject_keycode(P.KEY_DOWN if down else P.KEY_UP, code))
        elif down and ev.text() and not ctrl_alt and ev.text().isprintable():
            self.client.send(P.inject_text(ev.text()))

    def _clipboard_key(self, key: int) -> None:
        """Ctrl+C / Ctrl+X : le téléphone copie sa sélection (elle arrive ensuite sur le PC) ; Ctrl+V : colle le texte du PC."""
        if key == Qt.Key.Key_V:
            text = QGuiApplication.clipboard().text()
            if text:
                self.client.send(P.set_clipboard(text, paste=True))
        else:
            self.client.send(P.get_clipboard(P.COPY_KEY_COPY if key == Qt.Key.Key_C else P.COPY_KEY_CUT))

    def _type_clipboard(self) -> None:
        """Ctrl+Maj+V : tape le texte du presse-papiers du PC comme au clavier (pour les champs qui ignorent « Coller »,
        comme ceux de Unity). Les caractères que le clavier Android ne sait pas taper (certains accents) sont ignorés."""
        text = QGuiApplication.clipboard().text()
        if text:
            self.client.send(P.inject_text(text.replace("\r", "").replace("\n", " ")))

    def save_screenshot(self, name: str) -> str:
        """Enregistre l'image affichée en PNG dans le dossier Images ; renvoie le chemin ('' si rien)."""
        import re, time
        from pathlib import Path

        from PySide6.QtCore import QStandardPaths

        if self._image is None:
            return ""
        folder = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation) or Path.home())
        folder.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w-]+", "_", name).strip("_") or "session"
        path = folder / f"notrefu-mirror-{safe}-{time.strftime('%Y%m%d-%H%M%S')}.png"
        return str(path) if self._image.save(str(path), "PNG") else ""
