"""Poignées de redimensionnement de la fenêtre sans bordure.

Chaque poignée est un petit widget transparent posé dans la marge de la fenêtre, avec SON PROPRE curseur. Rien n'est
affecté au curseur de la fenêtre principale : un curseur posé sur la fenêtre serait hérité par tous ses widgets
(zone vidéo, onglets, barre de session) et resterait en double-flèche en quittant le bord, surtout sous KDE Wayland où
aucun événement de sortie n'arrive tant que la souris reste dans la fenêtre. Ici le curseur de redimensionnement n'existe
que tant que la souris est exactement sur la poignée, sans filtre d'événements global."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QWidget

MARGIN = 6  # épaisseur de la zone de saisie, en pixels

_E = Qt.Edge
_CURSORS = {
    _E.LeftEdge: Qt.CursorShape.SizeHorCursor, _E.RightEdge: Qt.CursorShape.SizeHorCursor,
    _E.TopEdge: Qt.CursorShape.SizeVerCursor, _E.BottomEdge: Qt.CursorShape.SizeVerCursor,
    _E.LeftEdge | _E.TopEdge: Qt.CursorShape.SizeFDiagCursor, _E.RightEdge | _E.BottomEdge: Qt.CursorShape.SizeFDiagCursor,
    _E.RightEdge | _E.TopEdge: Qt.CursorShape.SizeBDiagCursor, _E.LeftEdge | _E.BottomEdge: Qt.CursorShape.SizeBDiagCursor,
}


def grip_rects(w: int, h: int, m: int = MARGIN) -> dict:
    """Rectangles des 8 poignées pour une fenêtre de w×h : 4 côtés (entre les coins) et 4 coins m×m."""
    if w < 4 * m or h < 4 * m:
        return {}
    return {
        _E.LeftEdge: QRect(0, m, m, h - 2 * m), _E.RightEdge: QRect(w - m, m, m, h - 2 * m),
        _E.TopEdge: QRect(m, 0, w - 2 * m, m), _E.BottomEdge: QRect(m, h - m, w - 2 * m, m),
        _E.LeftEdge | _E.TopEdge: QRect(0, 0, m, m), _E.RightEdge | _E.TopEdge: QRect(w - m, 0, m, m),
        _E.LeftEdge | _E.BottomEdge: QRect(0, h - m, m, m), _E.RightEdge | _E.BottomEdge: QRect(w - m, h - m, m, m),
    }


class EdgeGrip(QWidget):
    def __init__(self, window: QWidget, edges: Qt.Edge) -> None:
        super().__init__(window)
        self._edges = edges
        self.setCursor(_CURSORS[edges])
        self.setMouseTracking(False)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        handle = self.window().windowHandle()
        if event.button() == Qt.MouseButton.LeftButton and handle is not None:
            handle.startSystemResize(self._edges)
            event.accept()
        else:
            super().mousePressEvent(event)


class EdgeGrips:
    """Les 8 poignées d'une fenêtre ; `layout(w, h)` les replace, `set_enabled(False)` les cache (maximisée / plein écran)."""

    def __init__(self, window: QWidget) -> None:
        self.grips = {edges: EdgeGrip(window, edges) for edges in _CURSORS}

    def layout(self, w: int, h: int) -> None:
        rects = grip_rects(w, h)
        for edges, grip in self.grips.items():
            if edges in rects:
                grip.setGeometry(rects[edges])
                grip.show()
                grip.raise_()
            else:
                grip.hide()

    def set_enabled(self, on: bool, w: int, h: int) -> None:
        if on:
            self.layout(w, h)
        else:
            for grip in self.grips.values():
                grip.hide()
