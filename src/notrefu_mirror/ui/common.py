"""Interface Qt de notrefu-mirror : common."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QLabel,
)

import shiboken6

from .. import i18n


i18n.install()  # les textes affichés passent par i18n.tr() (français ou anglais, changeable à chaud)



MAX_SESSIONS = 8  # au-delà, la mémoire et le décodage vidéo deviennent ingérables (~200 widgets par session)
RESOURCES = Path(__file__).parent.parent / "resources"


CLASS_NAMES = ("Cra", "Écaflip", "Eniripsa", "Enutrof", "Féca", "Steamer", "Iop", "Zobal", "Osamodas", "Pandawa", "Roublard", "Sacrieur", "Sadida", "Sram", "Xélor")


CLASS_EMBLEMS = 15  # emblèmes facultatifs que l'utilisateur peut déposer dans resources/classes/01.png … 15.png


def emblem_pixmap(n: int, size: int = 64) -> QPixmap:
    """Emblème n° `n` : l'image personnelle de l'utilisateur si elle existe dans resources/classes/, sinon un badge
    généré (pastille colorée + initiale de la classe). notrefu-mirror n'embarque aucune image protégée."""
    pm = QPixmap(str(RESOURCES / "classes" / f"{n:02d}.png"))
    if not pm.isNull():
        return pm
    n = max(1, min(n, CLASS_EMBLEMS))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(SESSION_COLORS[(n - 1) % len(SESSION_COLORS)]))
    p.drawEllipse(3, 3, size - 6, size - 6)
    f = QFont()
    f.setBold(True)
    f.setPixelSize(int(size * 0.5))
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, CLASS_NAMES[n - 1][:1])
    p.end()
    return pm




# --------------------------------------------------------------------------
# Exécution asynchrone (adb peut bloquer plusieurs secondes)
# --------------------------------------------------------------------------
class _Runner(QObject):
    """Exécute des tâches bloquantes (adb…) hors du fil de l'interface et rend le résultat dans ce fil.

    - un pool à part (8 fils) : quelques commandes adb lentes n'affament pas le reste de l'application ;
    - un résultat qui arrive après la destruction du widget demandeur est abandonné au lieu de lever une erreur ;
    - `shutdown()` vide la file et attend (brièvement) les tâches en cours avant de quitter.
    """

    _result = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._result.connect(self._deliver)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(8)
        self._closed = False

    @Slot(object)
    def _deliver(self, payload) -> None:
        cb, value, error = payload
        owner = getattr(cb, "__self__", None)
        if isinstance(owner, QObject) and not shiboken6.isValid(owner):
            return  # le widget qui attendait ce résultat n'existe plus
        try:
            cb(value, error)
        except RuntimeError as exc:
            if "already deleted" not in str(exc):
                raise  # une vraie erreur : on ne la masque pas

    def run(self, fn, cb) -> None:
        if self._closed:
            return
        runner = self

        class Task(QRunnable):
            def run(self) -> None:  # noqa: D401
                try:
                    payload = (cb, fn(), None)
                except Exception as exc:  # noqa: BLE001
                    payload = (cb, None, exc)
                try:
                    runner._result.emit(payload)
                except RuntimeError:  # fenêtre déjà fermée : résultat sans objet
                    pass

        self._pool.start(Task())

    def shutdown(self, wait_ms: int = 1500) -> bool:
        """Plus de nouvelle tâche ; les tâches en attente sont abandonnées ; True si tout s'est arrêté à temps."""
        self._closed = True
        self._pool.clear()
        return self._pool.waitForDone(wait_ms)


# --------------------------------------------------------------------------
# Panneau d'une session (un téléphone / une fenêtre scrcpy)
# --------------------------------------------------------------------------
class _Bridge(QObject):
    """Fait passer les événements des threads du client vers le fil Qt."""

    state = Signal(str, str)
    log = Signal(str)
    clipboard = Signal(str)


class _DiagSignal(QObject):
    done = Signal(str)


SESSION_COLORS = ("#ef4444", "#f97316", "#eab308", "#22c55e", "#06b6d4", "#3b82f6", "#8b5cf6", "#ec4899")


class _ElideLabel(QLabel):
    """Étiquette à texte aligné à droite qui s'abrège (…) au lieu de déborder sur les boutons voisins."""

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        txt = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width())
        p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), txt)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, super().minimumSizeHint().height())
