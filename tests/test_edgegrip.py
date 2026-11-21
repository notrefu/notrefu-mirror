"""Poignées de redimensionnement : curseurs propres à chaque poignée, jamais hérités par les widgets internes."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from notrefu_mirror.ui.edgegrip import EdgeGrips, grip_rects

_app = QApplication.instance() or QApplication([])


class EdgeGripTests(unittest.TestCase):
    def test_rects_cover_the_margin_without_touching_the_inside(self):
        rects = grip_rects(800, 600, 6)
        self.assertEqual(len(rects), 8)
        inner = (6, 6, 800 - 6, 600 - 6)
        for r in rects.values():
            self.assertTrue(r.right() < inner[0] or r.left() >= inner[2] or r.bottom() < inner[1] or r.top() >= inner[3], r)
        self.assertEqual(grip_rects(10, 10), {})  # fenêtre minuscule : pas de poignées

    def test_cursors_belong_to_grips_not_to_the_window(self):
        host = QWidget()
        inner = QLabel("jeu", host)
        host.resize(400, 300)
        grips = EdgeGrips(host)
        grips.layout(400, 300)
        shapes = {g.cursor().shape() for g in grips.grips.values()}
        self.assertEqual(shapes, {Qt.CursorShape.SizeHorCursor, Qt.CursorShape.SizeVerCursor,
                                  Qt.CursorShape.SizeFDiagCursor, Qt.CursorShape.SizeBDiagCursor})
        self.assertEqual(host.cursor().shape(), Qt.CursorShape.ArrowCursor)  # la fenêtre n'hérite de rien
        self.assertEqual(inner.cursor().shape(), Qt.CursorShape.ArrowCursor)
        self.assertEqual(sum(1 for g in grips.grips.values() if not g.isHidden()), 8)

    def test_hidden_when_maximized_and_back(self):
        host = QWidget()
        host.resize(400, 300)
        grips = EdgeGrips(host)
        grips.set_enabled(False, 400, 300)
        self.assertTrue(all(g.isHidden() for g in grips.grips.values()))
        grips.set_enabled(True, 400, 300)
        self.assertTrue(all(not g.isHidden() for g in grips.grips.values()))


if __name__ == "__main__":
    unittest.main()
