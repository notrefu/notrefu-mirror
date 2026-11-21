"""Conversion écran -> téléphone de la vue de jeu pour tous les ratios (tablettes 16:10, 5:3, 4:3, portrait, paysage)."""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from notrefu_mirror.engine import Frame  # noqa: E402
from notrefu_mirror.gameview import GameView  # noqa: E402

app = QApplication.instance() or QApplication([])
SIZES = [(1920, 1200), (1800, 1080), (1600, 1200), (1200, 1920), (1080, 2400), (1920, 1080)]


class MapTest(unittest.TestCase):
    def test_centre_and_corners_for_every_ratio(self):
        for sw, sh in SIZES:
            with self.subTest(f"{sw}x{sh}"):
                v = GameView()
                v.resize(900, 700)
                v._frame = Frame(sw // 4, sh // 4, 0, b"", sw, sh)
                self.assertIsNotNone(v._frame)
                r = v._target_rect()
                self.assertAlmostEqual(r.width() / r.height(), sw / sh, delta=0.02)  # le ratio du téléphone, pas 16:9
                cx, cy = v._to_device(r.center())
                self.assertAlmostEqual(cx / sw, 0.5, delta=0.01)
                self.assertAlmostEqual(cy / sh, 0.5, delta=0.01)
                self.assertEqual(v._to_device(QPoint(r.left(), r.top())), (0, 0))
                ex, ey = v._to_device(QPoint(r.right(), r.bottom()))  # arrondi au pixel d'écran : < 1 % d'écart
                self.assertAlmostEqual(ex / sw, 1.0, delta=0.01)
                self.assertAlmostEqual(ey / sh, 1.0, delta=0.01)
                v.deleteLater()


if __name__ == "__main__":
    unittest.main()
