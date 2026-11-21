"""Interface Qt de notrefu-mirror : titlebar."""

from __future__ import annotations

from typing import TYPE_CHECKING


from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QToolButton,
    QWidget,
)

from .. import APP_NAME, __version__, theme


from .common import RESOURCES


if TYPE_CHECKING:
    from .main_window import MainWindow


class TitleBar(QWidget):
    """Barre de titre personnalisée : déplacement à la souris, double-clic = agrandir, boutons de fenêtre."""

    def __init__(self, win: "MainWindow") -> None:
        super().__init__()
        self.win = win
        self.setObjectName("titlebar")
        self.setFixedHeight(46)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 8, 0)
        lay.setSpacing(6)
        self.logo = QLabel()
        dpr = QGuiApplication.primaryScreen().devicePixelRatio() if QGuiApplication.primaryScreen() else 1.0
        pm = QPixmap(str(RESOURCES / "notrefu_mirror.png")).scaled(
            int(28 * dpr), int(28 * dpr), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        self.logo.setPixmap(pm)
        self.logo.setFixedSize(28, 28)
        self.logo.setToolTip(f"{APP_NAME} {__version__} — clic : à propos")
        self.logo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logo.mousePressEvent = lambda e: win.about() if e.button() == Qt.MouseButton.LeftButton else None
        lay.addWidget(self.logo)
        lay.addSpacing(14)
        self.tab_host = QWidget()  # les onglets de session vivent dans la barre de titre (une seule ligne)
        hl = QHBoxLayout(self.tab_host)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(4)
        lay.addWidget(self.tab_host, 1)
        self.chrome: list[QToolButton] = []
        for text, icon, tip, slot in (
            ("Espaces", "list", "Groupes de comptes enregistrés, style TabDesk", None),
            ("Réglages", "sliders", "Téléphones, raccourcis, thème, langue, export des réglages", None),
            ("Aide", "help", "Aide et à propos", None),
        ):
            b = QToolButton()
            b.setObjectName("chrome")
            b.setText(text)
            b.setToolTip(tip)
            b.setIconSize(QSize(18, 18))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            theme.bind_icon(b, icon, "muted")
            if slot:
                b.clicked.connect(slot)
            elif text == "Espaces":
                b.clicked.connect(lambda _=False, w=b: win.show_spaces_menu(w))
            elif text == "Réglages":
                b.clicked.connect(lambda _=False, w=b: win.show_settings_menu(w))
            else:
                b.clicked.connect(lambda _=False, w=b: win.show_help_menu(w))
            lay.addWidget(b)
            self.chrome.append(b)
        lay.addSpacing(8)
        self.min_btn = self._winbtn("minus", "Réduire", win.showMinimized)
        self.max_btn = self._winbtn("square", "Agrandir", self.toggle_max)
        self.close_btn = self._winbtn("x", "Fermer", win.close, "winclose")
        for b in (self.min_btn, self.max_btn, self.close_btn):
            lay.addWidget(b)

    def _winbtn(self, icon: str, tip: str, slot, name: str = "winbtn") -> QToolButton:
        b = QToolButton()
        b.setObjectName(name)
        b.setToolTip(tip)
        b.setIconSize(QSize(16, 16))
        b.setFixedSize(36, 32)
        theme.bind_icon(b, icon, "text")
        b.clicked.connect(slot)
        return b

    def set_compact(self, compact: bool) -> None:
        st = Qt.ToolButtonStyle.ToolButtonIconOnly if compact else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        for b in self.chrome:
            b.setToolButtonStyle(st)

    def update_max_icon(self) -> None:
        maxed = self.win.isMaximized()
        theme.bind_icon(self.max_btn, "restore" if maxed else "square", "text")
        self.max_btn.setToolTip("Restaurer" if maxed else "Agrandir")

    def toggle_max(self) -> None:
        self.win.showNormal() if self.win.isMaximized() else self.win.showMaximized()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            h = self.win.windowHandle()
            if h is not None:
                h.startSystemMove()  # déplacement géré par le système (X11 et Wayland)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_max()
        else:
            super().mouseDoubleClickEvent(event)
