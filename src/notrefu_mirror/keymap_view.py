"""Surcouche transparente du mode édition des touches personnalisées (vue du modèle `keymap.KeyMap`).

Mode édition : clic sur le jeu = nouveau repère, puis « appuie sur la touche » ; glisser = déplacer ;
double-clic = changer la touche ; clic droit ou Suppr = supprimer ; Échap = terminer.
En mode jeu, la surcouche ne fait que dessiner de petits repères et laisse passer la souris.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import theme
from .i18n import tr
from .keymap import KeyMap

_MODIFIER_KEYS = {Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta, Qt.Key.Key_AltGr,
                  Qt.Key.Key_CapsLock, Qt.Key.Key_NumLock, Qt.Key.Key_ScrollLock, Qt.Key.Key_Super_L, Qt.Key.Key_Super_R,
                  Qt.Key.Key_unknown}
_BLOCKING_MODS = (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier)
RADIUS_PX = 17
_SHORT = {"Space": "Esp", "Return": "↵", "Enter": "↵", "Backspace": "⌫", "Tab": "⇥", "Delete": "Suppr", "Insert": "Ins",
          "PgUp": "PgUp", "PgDown": "PgDn", "Left": "←", "Right": "→", "Up": "↑", "Down": "↓"}


def short_label(name: str) -> str:
    """Texte tenant dans le repère rond (« Space » -> « Esp »)."""
    return _SHORT.get(name) or (name if len(name) <= 3 else name[:3] + "…")


def key_name(ev: QKeyEvent) -> str:
    """Nom portable de la touche (« A », « Space », « F5 »…) ; vide pour un modificateur seul ou une touche inconnue.
    Le nom suit la disposition du clavier (AZERTY comme QWERTY) et ignore Maj."""
    key = ev.key()
    if key in _MODIFIER_KEYS or key <= 0:
        return ""
    return QKeySequence(key).toString(QKeySequence.SequenceFormat.PortableText)


class KeyMapOverlay(QWidget):
    changed = Signal()  # le dessin des touches a changé : à enregistrer
    exit_requested = Signal()  # Échap hors saisie : quitter le mode édition
    status = Signal(str)  # message court pour la barre d'état

    def __init__(self, view: QWidget, keymap: KeyMap, reserved: Callable[[], set[str]] = lambda: set()) -> None:
        super().__init__(view)
        self.view, self.keymap, self._reserved = view, keymap, reserved
        self.editing = False
        self._pending: tuple[float, float] | None = None  # position choisie, en attente d'une touche
        self._replacing: str | None = None  # touche en cours de réassignation
        self._moving: str | None = None
        self._moved = False
        self._selected: str | None = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.hide()

    # ---- état ---------------------------------------------------------------
    def refresh(self) -> None:
        """Affiche ou masque la surcouche selon le mode (édition / repères visibles / rien)."""
        visible = self.editing or (self.keymap.show and self.keymap.active and len(self.keymap) > 0)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not self.editing)
        self.setVisible(visible)
        if visible:
            self.raise_()
        self.update()

    def set_editing(self, on: bool) -> None:
        if on == self.editing:
            return
        self.editing = on
        self._pending = self._replacing = self._moving = self._selected = None
        if on:
            self.setGeometry(self.view.rect())
            self.refresh()
            self.setFocus()
            self.status.emit(tr("Mode édition : clique sur le jeu pour ajouter une touche — Échap pour terminer."))
        else:
            self.refresh()
            self.view.setFocus()

    # ---- conversions image <-> écran -----------------------------------------
    def _rect(self) -> QRectF:
        r = self.view._target_rect()  # type: ignore[attr-defined]  # zone réellement occupée par l'image du téléphone
        return QRectF(r)

    def _to_ratio(self, p: QPointF) -> tuple[float, float] | None:
        r = self._rect()
        if r.isEmpty() or not r.contains(p):
            return None
        return (p.x() - r.x()) / r.width(), (p.y() - r.y()) / r.height()

    def _to_pos(self, rx: float, ry: float) -> QPointF:
        r = self._rect()
        return QPointF(r.x() + rx * r.width(), r.y() + ry * r.height())

    def _key_under(self, p: QPointF) -> str | None:
        best, best_d = None, float(RADIUS_PX)
        for name, (rx, ry) in self.keymap.keys.items():
            c = self._to_pos(rx, ry)
            d = ((c.x() - p.x()) ** 2 + (c.y() - p.y()) ** 2) ** 0.5
            if d <= best_d:
                best, best_d = name, d
        return best

    # ---- souris (mode édition uniquement : sinon la souris traverse la surcouche) ----
    def mousePressEvent(self, ev) -> None:  # noqa: N802
        self.setFocus()
        p = ev.position()
        hit = self._key_under(p)
        if ev.button() == Qt.MouseButton.RightButton:
            if hit:
                self.keymap.remove(hit)
                self._selected = None
                self.changed.emit()
                self.status.emit(tr("Touche {} supprimée.").format(hit))
            self._pending = self._replacing = None
        elif ev.button() == Qt.MouseButton.LeftButton:
            if hit and self._pending is None:
                self._moving, self._selected, self._moved = hit, hit, False
            else:
                self._selected = None
                pos = self._to_ratio(p)
                if pos:
                    self._pending, self._replacing = pos, None
                    self.status.emit(tr("Appuie maintenant sur la touche à assigner (Échap pour annuler)."))
        self.update()

    def mouseDoubleClickEvent(self, ev) -> None:  # noqa: N802
        hit = self._key_under(ev.position())
        if hit and ev.button() == Qt.MouseButton.LeftButton:
            self._moving = None
            self._pending, self._replacing = self.keymap.keys[hit], hit
            self.status.emit(tr("Appuie sur la nouvelle touche pour ce repère (actuellement {}).").format(hit))
            self.update()

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if self._moving:
            r = self._rect()
            if not r.isEmpty():
                p = ev.position()
                rx = min(max((p.x() - r.x()) / r.width(), 0.0), 1.0)
                ry = min(max((p.y() - r.y()) / r.height(), 0.0), 1.0)
                self.keymap.keys[self._moving] = (rx, ry)
                self._moved = True
                self.update()

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        if self._moving and self._moved:
            self.changed.emit()
        self._moving = None

    # ---- clavier : saisie de la touche à assigner -------------------------------
    def keyPressEvent(self, ev: QKeyEvent) -> None:  # noqa: N802
        if ev.isAutoRepeat():
            return
        name = key_name(ev)
        if self._pending is not None:
            if ev.key() == Qt.Key.Key_Escape:
                self._pending = self._replacing = None
                self.status.emit(tr("Annulé."))
            elif name:
                self._assign(name, ev)
            self.update()
            return
        if ev.key() == Qt.Key.Key_Escape:
            self.exit_requested.emit()
        elif ev.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self._selected:
            self.keymap.remove(self._selected)
            self.status.emit(tr("Touche {} supprimée.").format(self._selected))
            self._selected = None
            self.changed.emit()
            self.update()

    def _assign(self, name: str, ev: QKeyEvent) -> None:
        if ev.modifiers() & _BLOCKING_MODS:
            self.status.emit(tr("Une seule touche, sans Ctrl / Alt."))
            return
        assert self._pending is not None
        rx, ry = self._pending
        err = self.keymap.set(name, rx, ry, reserved=self._reserved() | {"Esc"})
        if err:
            self.status.emit(tr("Impossible : {}.").format(tr(err)))
            return
        if self._replacing and self._replacing != name:
            self.keymap.remove(self._replacing)
        self._selected = name
        self._pending = self._replacing = None
        self.changed.emit()
        self.status.emit(tr("Touche {} assignée. Une pression = un seul appui sur l'écran.").format(name))

    # ---- dessin --------------------------------------------------------------------------
    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        accent = QColor(theme.C.get("accent", "#7c5cff"))
        text = QColor(theme.C.get("on_accent", "#ffffff"))
        r = self._rect()
        if self.editing:
            if r.isEmpty():
                p.setPen(QColor(220, 220, 230))
                p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("Démarre la session pour placer des touches."))
                return
            p.fillRect(r, QColor(0, 0, 0, 55))
            pen = QPen(accent, 2, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(r.adjusted(1, 1, -1, -1))
            self._banner(p, r)
        font = QFont(self.font())
        font.setPointSizeF(9.5 if self.editing else 8.5)
        font.setBold(True)
        p.setFont(font)
        for name, (rx, ry) in self.keymap.keys.items():
            c = self._to_pos(rx, ry)
            alpha = 215 if self.editing else 120
            fill = QColor(accent)
            fill.setAlpha(alpha)
            if self.editing and name == self._selected:
                p.setPen(QPen(QColor(255, 255, 255), 2.5))
            else:
                p.setPen(QPen(QColor(255, 255, 255, 190 if self.editing else 110), 1.5))
            p.setBrush(fill)
            rad = RADIUS_PX if self.editing else RADIUS_PX - 4
            p.drawEllipse(c, rad, rad)
            p.setPen(text if self.editing else QColor(255, 255, 255, 230))
            p.drawText(QRectF(c.x() - rad, c.y() - rad, 2 * rad, 2 * rad), Qt.AlignmentFlag.AlignCenter, short_label(name))
        if self.editing and self._pending is not None:
            c = self._to_pos(*self._pending)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255), 2, Qt.PenStyle.DashLine))
            p.drawEllipse(c, RADIUS_PX, RADIUS_PX)
            p.setPen(QColor(255, 255, 255))
            p.drawText(QRectF(c.x() - RADIUS_PX, c.y() - RADIUS_PX, 2 * RADIUS_PX, 2 * RADIUS_PX), Qt.AlignmentFlag.AlignCenter, "?")

    def _banner(self, p: QPainter, r: QRectF) -> None:
        msg = tr("Mode édition — clic : ajouter · glisser : déplacer · double-clic : changer la touche · clic droit : supprimer · Échap : terminer")
        font = QFont(self.font())
        font.setPointSizeF(9.0)
        p.setFont(font)
        fm = p.fontMetrics()
        w = min(int(r.width()) - 20, fm.horizontalAdvance(msg) + 24)
        box = QRectF(r.x() + (r.width() - w) / 2, r.y() + 8, w, fm.height() + 12)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 175))
        p.drawRoundedRect(box, 8, 8)
        p.setPen(QColor(255, 255, 255))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, fm.elidedText(msg, Qt.TextElideMode.ElideRight, w - 16))
