"""Interface Qt de notrefu-mirror : main_window."""

from __future__ import annotations

import sys

import shutil
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QSize, QObject, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QFrame,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QFileDialog,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__, adb, engine, i18n, phonehealth, power, report, settingsio, theme
from ..stores import GuidesStore, StartupStore, WorkspaceStore, space_name
from .. import guides
from ..appsettings import app_settings
from ..hotkeys import SIZE_PRESETS, default_bindings, normalize as normalize_combo


from ..guides_layout import autofit_width
from ..health_monitor import LIGHT_POLL_S, HealthMonitor, tab_status
from .. import udev_setup
from ..engine import join_background
from ..session_logic import stop_clients
from .common import CLASS_EMBLEMS, MAX_SESSIONS, RESOURCES, _DiagSignal, _Runner, emblem_pixmap
from .dialogs import DevicesDialog, HotkeysDialog
from .phone_panel import PhonePanel
from .edgegrip import MARGIN as EDGE_MARGIN
from .edgegrip import EdgeGrips
from .session_page import EmptyPage, SessionPage
from .titlebar import TitleBar


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)  # barre de titre dessinée par notrefu-mirror
        self.setContentsMargins(EDGE_MARGIN, EDGE_MARGIN, EDGE_MARGIN, EDGE_MARGIN)  # zone des poignées de redimensionnement
        self._grips = EdgeGrips(self)
        self.resize(1280, 860)
        geo = app_settings().value("geometry")
        if geo:
            self.restoreGeometry(geo)
        self.setMinimumSize(560, 420)
        self.runner = _Runner()
        self.qs = app_settings()
        self.workspaces = WorkspaceStore(self.qs)
        self.startup = StartupStore(self.qs)
        self.guides_cfg = GuidesStore(self.qs)
        self._apply_video_flags()
        self.lang = str(self.qs.value("lang", "fr"))
        i18n.set_lang(self.lang)  # avant de créer les widgets : ils naissent déjà traduits
        self._polling = False
        self._counter = 0
        self._immersive = False
        self._restore_done = False
        self._detached: list = []
        self._compact = str(self.qs.value("compact", "false")).lower() in ("true", "1")
        self._devices: list[adb.Device] = []

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.tabBar().hide()  # remplacée par les onglets de la barre de titre
        self.tabs.setTabsClosable(False)  # bouton ✕ posé à la main sur chaque onglet (plus visible)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.tabBarDoubleClicked.connect(self._rename_tab)
        self.tabs.currentChanged.connect(lambda _i: QTimer.singleShot(60, self._focus_current))
        plus = QToolButton()
        plus.setObjectName("plus")
        plus.setToolTip("Nouvelle session")
        plus.setIconSize(QSize(18, 18))
        theme.bind_icon(plus, "plus", "accent")
        plus.clicked.connect(self.new_session)
        self._plus = plus

        # Page affichée quand toutes les sessions sont fermées
        self.empty = EmptyPage()
        el = QVBoxLayout(self.empty)
        el.addStretch(2)
        hint = QLabel("Aucune session ouverte.")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setObjectName("muted")
        el.addWidget(hint)
        new_btn = QPushButton("Nouvelle session")
        new_btn.setObjectName("primary")
        new_btn.setMinimumHeight(40)
        new_btn.setMinimumWidth(200)
        new_btn.setIconSize(QSize(18, 18))
        theme.bind_icon(new_btn, "plus", "on_accent")
        new_btn.clicked.connect(self.new_session)
        el.addWidget(new_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        el.addStretch(3)
        self.central_stack = QStackedWidget()
        self.central_stack.addWidget(self.tabs)
        self.central_stack.addWidget(self.empty)
        frame = QWidget()
        frame.setObjectName("frame")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)
        self.titlebar = TitleBar(self)
        self._build_title_tabs()
        fl.addWidget(self.titlebar)
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(6)
        self.split.addWidget(self.central_stack)
        self.split.splitterMoved.connect(self._guides_moved)
        self._guides = None
        self._guides_auto = True
        self._guides_timer = QTimer(self)
        self._guides_timer.setSingleShot(True)
        self._guides_timer.timeout.connect(self._guides_tick)
        self.central_stack.setMinimumWidth(240)  # sans cela la barre d'outils d'une session empêche de rétrécir librement
        fl.addWidget(self.split, 1)
        self.setCentralWidget(frame)
        self.statusBar().setSizeGripEnabled(False)

        self.bindings = default_bindings()
        for name, default in list(self.bindings.items()):
            v = self.qs.value(f"hotkeys/{name}", None)
            self.bindings[name] = default if v is None else str(v)
        self.shortcuts: list[QShortcut] = []
        self._apply_hotkeys()

        # Au démarrage : « restore » rouvre les onglets de la dernière fois (même zéro, s'ils avaient tous été fermés) ;
        # « empty » ne crée aucune session (on ouvre un espace ou on clique sur « Nouvelle session »).
        self._locked = self._startup_mode() == "empty"  # démarrage à vide : on ne touche pas au dernier état tant qu'aucune session n'est ouverte
        if self._startup_mode() == "empty":
            n = 0
        else:
            n = self.startup.tab_count()
        for i in range(n):
            self.add_session(load_index=i)
        if self.tabs.count():
            self.tabs.setCurrentIndex(0)
        self._sync_empty_state()
        self._apply_compact()
        if self._startup_raw().startswith("space:"):
            QTimer.singleShot(600, lambda n=self._startup_raw()[6:]: self._open_startup_space(n))
        # État enregistré en continu (et pas seulement à la fermeture) : un plantage ou une session fermée de force
        # ne fait plus perdre les onglets.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save_state)
        self._autosave = QTimer(self)
        self._autosave.timeout.connect(self.save_state)
        self._autosave.start(30000)

        self._autofit_timer = QTimer(self)
        self._autofit_timer.setSingleShot(True)
        self._autofit_timer.timeout.connect(self._autofit_check)
        self.tabs.currentChanged.connect(lambda _i: self._autofit_timer.start(1500))
        self.tabs.currentChanged.connect(lambda _i: self._guides_kick())
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(3000)
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self._tick)
        self.stats_timer.start(1000)
        self._grid_pages: list[SessionPage] = []
        self._grid_cells: dict = {}
        self.tabs.currentChanged.connect(lambda _i: self._exit_grid())
        self._thermal: dict[str, int] = {}  # niveau de limitation des ips par téléphone (chauffe)
        self._wake_at: dict[str, float] = {}
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.monitor = HealthMonitor()
        self.health_timer = QTimer(self)
        self.health_timer.timeout.connect(self._poll_health)
        self.health_timer.start(LIGHT_POLL_S * 1000)
        QTimer.singleShot(8000, self._poll_health)
        QTimer.singleShot(200, self.poll)
        self.statusBar().showMessage(
            "Prêt. Ctrl+Tab : session suivante · Alt+1…9 : aller à une session · F11 : plein écran."
        )

    # ---- sessions ------------------------------------------------------
    def pages(self) -> list[SessionPage]:
        return [self.tabs.widget(i) for i in range(self.tabs.count())]  # type: ignore[misc]

    def _startup_raw(self) -> str:
        return self.startup.raw()

    def _startup_mode(self) -> str:
        """« restore » rouvre les dernières sessions ; « empty » (ou un espace de démarrage) part sans session."""
        return self.startup.mode()

    def _open_startup_space(self, name: str, tries: int = 0) -> None:
        """Ouvre l'espace choisi au démarrage, une fois la liste des téléphones connue (pour lancer les sessions)."""
        if name not in self._space_names() or self.tabs.count():
            return
        if not getattr(self, "_devices", None) and tries < 16:
            QTimer.singleShot(500, lambda: self._open_startup_space(name, tries + 1))
            return
        self.open_space(name)

    def _set_startup_mode(self, mode: str) -> None:
        self.startup.set(mode)
        if mode == "restore" and self.tabs.count():
            self.save_state()  # sans session ouverte, on garde le dernier état enregistré
        self.statusBar().showMessage(
            "Au démarrage : notrefu-mirror rouvrira les dernières sessions." if mode == "restore"
            else f"Au démarrage : notrefu-mirror ouvrira l'espace « {mode[6:]} »." if mode.startswith("space:")
            else "Au démarrage : notrefu-mirror s'ouvrira sans aucune session.", 5000)

    def state_dirty(self) -> None:
        """Planifie un enregistrement de l'état des onglets (regroupe les changements rapprochés)."""
        t = getattr(self, "_save_timer", None)
        if t is not None:
            t.start(1500)

    def save_state(self) -> None:
        """Enregistre les onglets (y compris ceux des fenêtres détachées) pour le prochain démarrage."""
        if self._startup_mode() == "empty" or getattr(self, "_locked", False):
            return  # on démarre toujours sans session : le dernier état « rouvrir » reste intact
        pages = self.pages() + [w._page for w in self._detached if w._page is not None]
        self.startup.set_tab_count(len(pages))
        for i, pg in enumerate(pages):
            pg.panel.save(self.qs, f"panel{i}")
        self.qs.sync()

    def panels(self) -> list[PhonePanel]:
        return [p.panel for p in self.pages()]

    def add_session(self, load_index: int | None = None, copy_from: PhonePanel | None = None) -> SessionPage:
        page = SessionPage(self.runner, self._next_title())
        page.panel.message.connect(self._on_panel_message)
        page.panel.diagnose_requested.connect(self.show_diagnostic)
        page.host.reserved_keys = self.reserved_keymap_keys
        if load_index is not None:
            page.panel.load(self.qs, f"panel{load_index}")
        elif copy_from is not None:
            page.panel.copy_from(copy_from, self.qs)
        else:
            page.panel.set_icon(f"builtin:{self.tabs.count() % CLASS_EMBLEMS + 1:02d}")  # emblème différent par session
        if load_index is None and copy_from is None and self.tabs.count() >= 1:
            page.panel.q_buttons["multi"].setChecked(True)  # un 2e compte et plus : réglage léger « Multi-compte »
        self.tabs.addTab(page, page.panel.title)
        x = QToolButton()
        x.setObjectName("tabclose")
        x.setIconSize(QSize(14, 14))
        theme.bind_icon(x, "x", "muted")
        x.setToolTip("Fermer cette session")
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.clicked.connect(lambda _=False, pg=page: self._close_tab(self.tabs.indexOf(pg)))
        self.tabs.tabBar().setTabButton(self.tabs.indexOf(page), QTabBar.ButtonPosition.RightSide, x)
        page.panel.title_changed.connect(lambda text, pg=page: (self.tabs.setTabText(self.tabs.indexOf(pg), text), self._sync_title_tabs()))
        page.panel.color_changed.connect(lambda col, pg=page: self._tab_color(pg, col))
        self._tab_color(page, page.panel.color)
        self.tabs.setCurrentWidget(page)
        self._sync_title_tabs()
        page.set_immersive(self._compact or self._immersive)
        i18n.translate(page)
        page.panel.ended.connect(lambda *_a: QTimer.singleShot(0, self._grid_prune))
        if hasattr(self, "_save_timer"):
            self._locked = False
            self.state_dirty()
        page.rec_btn.toggled.connect(lambda _c, pg=page: self._tab_color(pg, pg.panel.color))
        self._sync_empty_state()
        QTimer.singleShot(0, self.poll)
        return page

    def _build_title_tabs(self) -> None:
        tt = QTabBar()
        tt.setDocumentMode(True)
        tt.setDrawBase(False)
        tt.setMovable(True)
        tt.setIconSize(QSize(18, 18))
        tt.setExpanding(False)
        tt.setUsesScrollButtons(True)
        tt.setElideMode(Qt.TextElideMode.ElideRight)
        tt.setStyleSheet("QTabBar::tab{margin:6px 3px;padding:5px 10px;min-width:60px;}")
        self.title_tabs = tt
        self._tt_ids: list[int] = []
        self._tt_block = False
        tt.currentChanged.connect(lambda i: None if self._tt_block or i < 0 else self.tabs.setCurrentIndex(i))
        tt.tabBarDoubleClicked.connect(self._rename_tab)
        tt.tabMoved.connect(self._title_tab_moved)
        tt.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tt.customContextMenuRequested.connect(self._title_tab_menu)
        lay = self.titlebar.tab_host.layout()
        lay.addWidget(tt)
        lay.addWidget(self._plus)
        lay.addStretch(1)
        self.tabs.currentChanged.connect(lambda _i: self._sync_title_tabs())

    def _title_tab_menu(self, pos) -> None:
        i = self.title_tabs.tabAt(pos)
        if i < 0:
            return
        m = QMenu(self)
        m.addAction("Détacher dans une fenêtre", lambda: self.detach_tab(i))
        m.addAction("Renommer", lambda: self._rename_tab(i))
        m.addAction("Fermer", lambda: self._close_tab(i))
        m.exec(self.title_tabs.mapToGlobal(pos))

    # ---- vue en grille : plusieurs sessions en cours côte à côte ---------------------------------
    def toggle_grid(self) -> None:
        if self._grid_pages:
            self._exit_grid()
            return
        running = [pg for pg in self.pages() if pg.panel.running]
        if len(running) < 2:
            self.statusBar().showMessage("Vue en grille : lance au moins 2 sessions pour les voir côte à côte.", 6000)
            return
        self._enter_grid(running[:6])

    def _enter_grid(self, pages: list["SessionPage"]) -> None:
        w = QWidget()
        lay = QGridLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        cols = 1 if len(pages) == 1 else 2 if len(pages) <= 4 else 3
        self._grid_cells: dict[SessionPage, QFrame] = {}
        for i, pg in enumerate(pages):
            cell = QFrame()
            cell.setObjectName("gridcell")
            v = QVBoxLayout(cell)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)
            head = QPushButton(pg.panel.title + "  ↗")
            head.setFlat(True)
            head.setCursor(Qt.CursorShape.PointingHandCursor)
            head.setToolTip("Ouvrir cette session en grand")
            head.clicked.connect(lambda _c=False, pg=pg: self._exit_grid(select=pg))
            pg.game_layout.removeWidget(pg.host)
            v.addWidget(head)
            v.addWidget(pg.host, 1)
            pg.host.show()
            f = _GridAudioFocus(self, pg)
            pg.host.installEventFilter(f)
            pg.host._grid_filter = f  # type: ignore[attr-defined]
            lay.addWidget(cell, i // cols, i % cols)
            self._grid_cells[pg] = cell
        self._grid_pages = list(pages)
        self._grid_widget = w
        self.central_stack.addWidget(w)
        self.central_stack.setCurrentWidget(w)
        self.grid_audio(pages[0])
        self.statusBar().showMessage("Vue en grille : clique sur une cellule pour entendre son son, sur son titre pour l'ouvrir en grand.", 8000)

    def grid_audio(self, page: "SessionPage") -> None:
        """Une seule cellule joue du son : celle sur laquelle on a cliqué en dernier."""
        accent = theme.C.get("accent", "#8b5cf6")
        self._maybe_wake(page)
        for pg, cell in getattr(self, "_grid_cells", {}).items():
            pg.host.audio_on = pg is page
            cell.setStyleSheet(f"#gridcell {{ border: 2px solid {accent}; }}" if pg is page else "#gridcell { border: 2px solid transparent; }")

    def _exit_grid(self, select: "SessionPage | None" = None) -> None:
        if not self._grid_pages:
            return
        pages, self._grid_pages = self._grid_pages, []
        for pg in pages:
            try:
                pg.host.removeEventFilter(pg.host._grid_filter)  # type: ignore[attr-defined]
            except (AttributeError, RuntimeError):
                pass
            pg.host.audio_on = True
            pg.game_layout.insertWidget(1, pg.host, 1)
            pg.host.show()
        w = self._grid_widget
        self.central_stack.setCurrentIndex(0 if self.tabs.count() else 1)
        self.central_stack.removeWidget(w)
        w.deleteLater()
        self._grid_cells = {}
        if select is not None and self.tabs.indexOf(select) >= 0:
            self.tabs.setCurrentIndex(self.tabs.indexOf(select))

    def _grid_prune(self) -> None:
        """Une session de la grille s'est arrêtée : on la retire (et on quitte la grille s'il en reste moins de 2)."""
        if not self._grid_pages:
            return
        alive = [pg for pg in self._grid_pages if pg.panel.running]
        if len(alive) == len(self._grid_pages):
            return
        self._exit_grid()
        if len(alive) >= 2:
            self._enter_grid(alive)

    def detach_tab(self, index: int) -> None:
        """Sort une session de la barre d'onglets pour la mettre dans sa propre fenêtre (deuxième écran, par exemple)."""
        if index < 0 or index >= self.tabs.count():
            return
        self._exit_grid()
        page: SessionPage = self.tabs.widget(index)  # type: ignore[assignment]
        self.tabs.removeTab(index)
        win = _DetachedWindow(self, page)
        self._detached.append(win)
        self._sync_title_tabs()
        self._sync_empty_state()
        win.show()

    def arrange_detached(self, mode: str) -> None:
        """Répartit les fenêtres détachées sur l'écran (côte à côte ou en pile). Sous Wayland, seule la taille est garantie."""
        wins = [w for w in self._detached if w.isVisible()]
        if not wins:
            return
        geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        n = len(wins)
        for i, w in enumerate(wins):
            w.showNormal()
            if mode == "cols":
                w.setGeometry(geo.x() + i * geo.width() // n, geo.y(), geo.width() // n, geo.height())
            else:
                w.setGeometry(geo.x(), geo.y() + i * geo.height() // n, geo.width(), geo.height() // n)
        self.statusBar().showMessage(f"{n} fenêtre(s) rangée(s).", 4000)

    def reattach(self, win: "_DetachedWindow") -> None:
        page = win.take_page()
        if win in self._detached:
            self._detached.remove(win)
        self.tabs.addTab(page, page.panel.title)
        self._tab_color(page, page.panel.color)
        self.tabs.setCurrentWidget(page)
        self._sync_title_tabs()
        self._sync_empty_state()
        page.show()

    def _title_tab_moved(self, src: int, dst: int) -> None:
        if self._tt_block:
            return
        self.tabs.tabBar().moveTab(src, dst)
        self._sync_title_tabs()

    def _sync_title_tabs(self) -> None:
        tt = getattr(self, "title_tabs", None)
        if tt is None:
            return
        pages = self.pages()
        self._tt_block = True
        try:
            if [id(p) for p in pages] != self._tt_ids:
                while tt.count():
                    tt.removeTab(0)
                for pg in pages:
                    i = tt.addTab(pg.panel.title)
                    x = QToolButton()
                    x.setObjectName("tabclose")
                    x.setIconSize(QSize(14, 14))
                    theme.bind_icon(x, "x", "muted")
                    x.setToolTip("Fermer cette session")
                    x.setCursor(Qt.CursorShape.PointingHandCursor)
                    x.clicked.connect(lambda _=False, g=pg: self._close_tab(self.tabs.indexOf(g)))
                    tt.setTabButton(i, QTabBar.ButtonPosition.RightSide, x)
                self._tt_ids = [id(p) for p in pages]
            for i, pg in enumerate(pages):
                tt.setTabText(i, pg.panel.title)
                tt.setTabIcon(i, self.tabs.tabIcon(i))
            tt.setCurrentIndex(self.tabs.currentIndex())
            tt.setVisible(tt.count() > 0)  # sans session : pas de zone vide avant le « + »
        finally:
            self._tt_block = False

    @staticmethod
    def _rec_dot(pm: QPixmap) -> QPixmap:
        """Petit point rouge en bas à droite : cette session enregistre."""
        out = QPixmap(pm)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = max(8, out.width() // 3)
        p.setBrush(QColor("#ef4444"))
        p.setPen(QColor("#18181B"))
        p.drawEllipse(out.width() - r - 1, out.height() - r - 1, r, r)
        p.end()
        return out

    def _tab_color(self, page: "SessionPage", col: str) -> None:
        i = self.tabs.indexOf(page)
        if i < 0:
            return
        rec = page.rec_btn.isChecked()
        if page.panel.icon_path:
            ip = page.panel.icon_path
            pm = emblem_pixmap(int(ip[8:] or 1)) if ip.startswith("builtin:") else QPixmap(ip)
            if not pm.isNull():
                pm = pm.scaled(36, 36, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.tabs.setTabIcon(i, QIcon(self._rec_dot(pm) if rec else pm))
                self._sync_title_tabs()
                return
        if not col:
            if rec:
                blank = QPixmap(36, 36)
                blank.fill(Qt.GlobalColor.transparent)
                self.tabs.setTabIcon(i, QIcon(self._rec_dot(blank)))
            else:
                self.tabs.setTabIcon(i, QIcon())
            self._sync_title_tabs()
            return
        pm = QPixmap(14, 14)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(col))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(1, 1, 12, 12)
        p.end()
        self.tabs.setTabIcon(i, QIcon(pm))
        self._sync_title_tabs()

    def new_session(self) -> None:
        if self.tabs.count() >= MAX_SESSIONS:
            self.statusBar().showMessage(f"Maximum : {MAX_SESSIONS} sessions en même temps.", 4000)
            return
        cur = self.tabs.currentWidget()
        page = self.add_session(copy_from=cur.panel if cur else None)  # type: ignore[union-attr]
        page.show_settings()

    # ---- fenêtre sans bordure : redimensionnement par les bords --------------
    # Les curseurs de redimensionnement appartiennent aux poignées (ui/edgegrip.py), jamais à la fenêtre : un curseur posé sur
    # la fenêtre serait hérité par la zone vidéo, les onglets et la barre de session et resterait bloqué en double-flèche.
    def _reset_cursor(self) -> None:
        self.unsetCursor()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._reset_cursor()
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._reset_cursor()
        super().leaveEvent(event)

    def _layout_grips(self) -> None:
        full = self.isMaximized() or self.isFullScreen()
        self._grips.set_enabled(not full, self.width(), self.height())
        self._reset_cursor()

    def _sync_chrome(self) -> None:
        full = self.isMaximized() or self.isFullScreen()
        m = 0 if full else EDGE_MARGIN
        self.setContentsMargins(m, m, m, m)
        self.titlebar.update_max_icon()
        self._layout_grips()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_grips()
        if hasattr(self, "titlebar"):
            self.titlebar.set_compact(self.width() < 1000)
            if hasattr(self, "_autofit_timer"):
                self._autofit_timer.start(1500)  # après la fin du redimensionnement
            self._guides_kick()

    def _autofit_check(self) -> None:
        page = self.tabs.currentWidget()
        if page is None or self.isMinimized() or self._grid_pages:
            return
        p = page.panel
        if p.opt_autofit.isChecked() and p.fit_drift():
            p.message.emit(f"{p.title} : fenêtre redimensionnée, adaptation de l'écran du jeu…")
            p.refitting = True
            QTimer.singleShot(20000, lambda: setattr(p, "refitting", False))
            p.restart()

    def _next_title(self) -> str:
        used = {p.panel.title for p in self.pages()}
        n = 1
        while f"Session {n}" in used:
            n += 1
        return f"Session {n}"

    def _sync_empty_state(self) -> None:
        self.central_stack.setCurrentIndex(0 if self.tabs.count() else 1)

    def game_area_size(self) -> tuple[int, int]:
        page = self.tabs.currentWidget()
        if page is None:
            return (0, 0)
        return (page.stack.width(), page.stack.height() - page.bar.sizeHint().height())

    def _tick(self) -> None:
        """Chaque seconde : images/s et couleur des onglets (vert = en cours, orange = reconnexion)."""
        bar = self.tabs.tabBar()
        for i, page in enumerate(self.pages()):
            page.panel.tick_stats()
            p = page.panel
            state, tip = tab_status(p.reconnecting, p.running, p.health_text, p.play_seconds)
            color = QColor(theme.C[state])
            for b in (bar, self.title_tabs):
                if i < b.count():
                    b.setTabTextColor(i, color)
                    b.setTabToolTip(i, tip)

        for w in self._detached:  # les sessions détachées comptent aussi (images/s, temps de jeu)
            if w._page is not None:
                w._page.panel.tick_stats()
        self._update_bandwidth()
        self._guard_wifi()
        self._apply_fps_caps()

    # ---- économie d'énergie, protection du téléphone, réveil (voir power.py) ----------------------
    def _flag(self, key: str, default: bool) -> bool:
        v = self.qs.value(key, default)
        return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes")

    def _apply_fps_caps(self) -> None:
        """Limitation des ips pour tout un téléphone qui chauffe ou un Wi-Fi saturé (réglage désactivé par défaut).
        Aucune session n'est jamais ralentie parce qu'elle n'a pas le focus : en grille ou en onglets, toutes restent en temps réel."""
        auto = self._flag("power/auto_throttle", False)
        for pg in self._all_pages():
            p = pg.panel
            c = p.client
            thermal = self._thermal.get(p.serial, 0) if auto else 0
            wifi = p.stall_guard.level if auto and p._is_wifi_selected() else 0
            p.throttle_note = power.throttle_note(thermal, wifi) if c else ""
            if not c:
                continue
            c.set_fps_cap("thermal", power.LEVEL_CAPS[thermal])
            c.set_fps_cap("wifi", power.LEVEL_CAPS[wifi])

    def _guard_wifi(self) -> None:
        now = time.monotonic()
        for pg in self._all_pages():
            p = pg.panel
            c = p.client
            if not c or not p._is_wifi_selected():
                continue
            before = p.stall_guard.level
            level = p.stall_guard.update(c.pop_stalls(), now)
            if level > before:
                p.message.emit(f"⚠ Wi-Fi saturé : ips limités à {power.LEVEL_CAPS[level]} pour fluidifier le flux.")
            elif level < before:
                p.message.emit("Wi-Fi redevenu stable : ips rétablis." if level == 0 else "Wi-Fi plus stable : limitation allégée.")

    def _on_tab_changed(self, index: int) -> None:
        self._apply_fps_caps()
        page = self.tabs.widget(index) if index >= 0 else None
        if page is not None:
            self._maybe_wake(page)

    def _maybe_wake(self, page: "SessionPage") -> None:
        """Clic sur une session : réveille l'écran du téléphone (touche « réveil » seule, ne déverrouille pas, ne fait rien s'il est allumé)."""
        p = page.panel
        serial = p.serial
        now = time.monotonic()
        if not (p.running and serial) or not power.should_wake(
                self._wake_at.get(serial), now, self._flag("power/wake_on_click", True), p.opt_screen_off.isChecked()):
            return
        self._wake_at[serial] = now
        self.runner.run(lambda: adb.run_adb(["shell", "input", "keyevent", "KEYCODE_WAKEUP"], serial=serial, timeout=6),
                        lambda _res, _err: None)

    def _set_flag(self, key: str, on: bool) -> None:
        self.qs.setValue(key, on)
        self._apply_fps_caps()
        self._apply_video_flags()

    def _apply_video_flags(self) -> None:
        """Décodage matériel (GPU) : pris en compte au prochain démarrage de session."""
        engine.HW_DECODE_ENABLED = self._flag("video/hw_decode", True)

    def _all_pages(self) -> list["SessionPage"]:
        return self.pages() + [w._page for w in self._detached if w._page is not None]

    def _update_bandwidth(self) -> None:
        panels = [pg.panel for pg in self._all_pages()]
        for p in panels:
            same = [q for q in panels if q.serial == p.serial and (q.running or q is p)]
            total = sum(q.bitrate_mbit() for q in same)
            p.bw_label.setText(phonehealth.bandwidth_text(p.bitrate_mbit(), total, len(same), p._is_wifi_selected()))

    # ---- santé du téléphone (relevé léger /proc toutes les 5 s, complet toutes les 30 s, pour les téléphones en cours de jeu) --------
    def _poll_health(self) -> None:
        # seulement les téléphones dont une session tourne (pas pendant une reconnexion : l'appareil ne répondrait pas)
        live = [pg for pg in self._all_pages() if pg.panel.serial and pg.panel.client is not None
                and pg.panel.client.state in ("starting", "running")]
        serials = {pg.panel.serial for pg in live}
        visible = set() if self.isMinimized() else {pg.panel.serial for pg in live if pg.panel.view and pg.panel.view.isVisible()}
        pkgs: dict[str, str] = {}  # téléphone -> paquet du jeu (pour afficher la RAM du jeu seul, en plus de celle du téléphone)
        for pg in live:
            if pg.panel.app_edit.text().strip():
                pkgs.setdefault(pg.panel.serial, adb.split_package(pg.panel.app_edit.text().strip())[0])

        def read(s: str, pkg: str, full: bool, game: bool):
            if not full:  # relevé léger : une seule commande adb (/proc/meminfo + /proc/stat)
                return phonehealth.parse_light(adb.run_adb(["shell", phonehealth.LIGHT_COMMAND], serial=s, timeout=8))
            h = phonehealth.parse(adb.run_adb(["shell", phonehealth.READ_COMMAND], serial=s, timeout=12))
            if pkg and game:
                h.game_mb = adb.game_memory_mb(s, pkg)
            return h

        now = time.monotonic()
        for gone in [s for s in list(self.monitor.health) if s not in serials]:
            self.monitor.forget(gone)  # téléphone plus en jeu : le prochain relevé sera complet
        for serial in self.monitor.to_poll(serials, now, visible):
            full = self.monitor.wants_full(serial, now)
            game = full and self.monitor.wants_game(serial, now)
            if game:
                self.monitor.game_read(serial, now)
            self.runner.run(lambda s=serial, f=full, g=game: read(s, pkgs.get(s, ""), f, g),
                            lambda h, err, s=serial, f=full: self._health_done(s, h, err, f))

    def _health_done(self, serial: str, h, err, full: bool = True) -> None:
        if err is not None or h is None:
            self.monitor.failed(serial)
            return
        text, alerts = self.monitor.finish(serial, h, time.monotonic(), full)
        panels = [pg.panel for pg in self._all_pages() if pg.panel.serial == serial]
        before = self._thermal.get(serial, 0)
        level = self._thermal[serial] = power.thermal_level(before, h.temp_c, h.thermal)
        if level != before and panels and self._flag("power/auto_throttle", False):
            msg = (f"⚠ Téléphone chaud : ips limités à {power.LEVEL_CAPS[level]} (retour à la normale quand il refroidit)."
                   if level > before else "Téléphone refroidi : limitation des ips allégée." if level else "Téléphone refroidi : ips rétablis.")
            panels[0].message.emit(msg)
        self._apply_fps_caps()
        tip = phonehealth.ram_detail(self.monitor.health.get(serial))
        for p in panels:
            p.health_text = text
            p.health_tip = tip
        if panels:
            for msg in alerts:
                panels[0].message.emit(f"⚠ {msg}")

    def _close_tab(self, index: int) -> None:
        page: SessionPage = self.tabs.widget(index)  # type: ignore[assignment]
        if page.panel.running:
            ok = QMessageBox.question(self, APP_NAME, f"« {page.panel.title} » est en cours. L'arrêter et fermer l'onglet ?")
            if ok != QMessageBox.StandardButton.Yes:
                return
        page.panel.shutdown()
        self.tabs.removeTab(index)
        page.deleteLater()
        self._sync_title_tabs()
        self._sync_empty_state()  # dernière session fermée : page vide (plus de recréation automatique)
        self.state_dirty()

    def _rename_tab(self, index: int) -> None:
        if index < 0:
            return
        page: SessionPage = self.tabs.widget(index)  # type: ignore[assignment]
        text, ok = QInputDialog.getText(self, "Renommer la session", "Nom (ex. Eniripsa) :", text=page.panel.title)
        if ok and text.strip():
            page.panel.name_edit.setText(text.strip()[:40])

    def _focus_current(self) -> None:
        page = self.tabs.currentWidget()
        if page is not None:
            page.focus_game()  # type: ignore[attr-defined]

    def changeEvent(self, ev) -> None:  # noqa: N802
        super().changeEvent(ev)
        if ev.type() == QEvent.Type.WindowStateChange:
            if hasattr(self, "titlebar"):
                self._sync_chrome()
        if ev.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            QTimer.singleShot(100, self._focus_current)

    # ---- raccourcis ----------------------------------------------------
    def _apply_hotkeys(self) -> None:
        for sc in self.shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        self.shortcuts = []
        for name, combo in self.bindings.items():
            if not combo.strip():
                continue
            sc = QShortcut(QKeySequence(combo), self)
            sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
            sc.activated.connect(lambda n=name: self.on_hotkey(n))
            self.shortcuts.append(sc)

    def reserved_keymap_keys(self) -> set[str]:
        """Touches seules déjà prises par un raccourci de l'application (F10, F11…) : inutilisables comme touche assignée."""
        out = set()
        for combo in self.bindings.values():
            n = normalize_combo(combo)
            if n and "+" not in n.strip("+"):
                out.add(n)
        return out

    def on_hotkey(self, name: str) -> None:
        n = self.tabs.count()
        if name == "next" and n:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + 1) % n)
        elif name == "prev" and n:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() - 1) % n)
        elif name.startswith("goto"):
            i = int(name[4:]) - 1
            if 0 <= i < n:
                self.tabs.setCurrentIndex(i)
        elif name == "fullscreen":
            self.toggle_immersive()
        elif name == "compact":
            self.toggle_compact()
        elif name == "grid":
            self.toggle_grid()
        elif name in ("keymap", "keymap_edit"):
            page = self.tabs.currentWidget()
            if page is not None:
                (page.toggle_keymap_active if name == "keymap" else page.toggle_keymap_edit)()  # type: ignore[union-attr]
        elif name == "guides":
            self.toggle_guides()
        elif name in SIZE_PRESETS:
            cur = self.tabs.currentWidget()
            if cur is not None:
                cur.panel.apply_quality(SIZE_PRESETS[name])  # type: ignore[union-attr]
        elif name == "detach":
            active = QApplication.activeWindow()
            if isinstance(active, _DetachedWindow):
                active.close()  # la fermeture remet la session dans les onglets
            elif n:
                self.detach_tab(self.tabs.currentIndex())
        elif name == "screenshot":
            cur = self.tabs.currentWidget()
            if cur is not None and cur.panel.running:  # type: ignore[union-attr]
                cur._screenshot()  # type: ignore[union-attr]

    def toggle_compact(self, on: bool | None = None) -> None:
        """Garde barre de titre et onglets mais libère la barre d'outils et la barre d'état pour le jeu."""
        self._compact = (not self._compact) if on is None else on
        self.qs.setValue("compact", self._compact)
        self._apply_compact()

    def _apply_compact(self) -> None:
        QTimer.singleShot(200, self._guides_kick)
        hide = self._compact or self._immersive
        self.statusBar().setVisible(not hide)
        for page in self.pages():
            page.set_immersive(hide)

    def toggle_immersive(self) -> None:
        self._immersive = not self._immersive
        im = self._immersive
        self.titlebar.setVisible(not im)
        self._apply_compact()
        self.showFullScreen() if im else self.showNormal()
        self._sync_chrome()

    def edit_hotkeys(self) -> None:
        dlg = HotkeysDialog(self.bindings, True, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.bindings = dlg.values()
            for name, combo in self.bindings.items():
                self.qs.setValue(f"hotkeys/{name}", combo)
            self._apply_hotkeys()

    # ---- appareils -----------------------------------------------------
    def _on_panel_message(self, text: str) -> None:
        if text == "refresh":
            self.poll()
            # un second passage laisse le temps à adb d'enregistrer la connexion
            QTimer.singleShot(1200, self.poll)
            return
        self.statusBar().showMessage(text, 15000)

    def poll(self) -> None:
        if self._polling:
            return
        self._polling = True

        def done(devs, err):
            self._polling = False
            if err:
                self.statusBar().showMessage(f"adb : {err}", 5000)
                devs = []
            for p in self.panels():
                p.adb_error = str(err) if err else ""
            self._devices = devs
            self._offer_restore(devs)
            for p in self.panels():
                p.set_devices(devs)
                # relance la sélection voulue (connexion sans fil fraîchement établie)
                if p._wanted_serial:
                    p.select_serial(p._wanted_serial)
                # démarrage automatique (une seule fois, quand le téléphone est prêt)
                if p.opt_autostart.isChecked() and not p._autostarted and not p.running:
                    if any(d.serial == p.serial and d.state == "device" for d in devs):
                        p._autostarted = True
                        p.start()

        self.runner.run(adb.list_devices, done)

    def _offer_restore(self, devs) -> None:
        """Au démarrage : propose de relancer les sessions qui tournaient à la fermeture (une seule fois)."""
        if self._restore_done or not devs:
            return
        todo = [
            p for p in self.panels()
            if p.was_running and not p.running and any(d.serial == p._wanted_serial and d.state == "device" for d in devs)
        ]
        self._restore_done = True
        if not todo:
            return
        mode = self.startup.restore_policy()
        if mode == "never":
            return
        if mode != "always":
            box = QMessageBox(self)
            box.setWindowTitle(APP_NAME)
            box.setText(f"Relancer {len(todo)} session(s) qui tournaient à la dernière fermeture ?\n"
                        + "\n".join(f"• {p.title}" for p in todo))
            chk = QCheckBox("Toujours relancer sans demander")
            box.setCheckBox(chk)
            yes = box.addButton("Relancer", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Non", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not yes:
                return
            if chk.isChecked():
                self.startup.set_restore_always()
        for p in todo:
            p.select_serial(p._wanted_serial)
            p._autostarted = True
            p.start()

    def show_devices(self) -> None:
        DevicesDialog(self._devices, self.install_udev, self.poll, self).exec()

    # ---- espaces (groupes de comptes) ---------------------------------
    def _space_names(self) -> list[str]:
        return self.workspaces.names()

    def show_spaces_menu(self, anchor: QWidget) -> None:
        m = QMenu(self)
        m.addAction("Enregistrer les sessions actuelles comme espace…", self.save_space).setEnabled(self.tabs.count() > 0)
        names = self._space_names()
        if names:
            m.addSeparator()
            for n in names:
                count = self.workspaces.count(n)
                m.addAction(f"Ouvrir « {n} » ({count} session{'s' if count > 1 else ''})", lambda n=n: self.open_space(n))
            dm = m.addMenu("Supprimer un espace")
            for n in names:
                dm.addAction(n, lambda n=n: self.delete_space(n))
        m.addSeparator()
        m.addAction("Guides (Papycha, Almanax)…", self.toggle_guides)
        g = m.addAction("Vue en grille (sessions en cours)", self.toggle_grid)
        g.setCheckable(True)
        g.setChecked(bool(self._grid_pages))
        mode = self._startup_raw()
        a1 = m.addAction("Au démarrage : rouvrir les dernières sessions", lambda: self._set_startup_mode("restore"))
        a1.setCheckable(True)
        a1.setChecked(mode == "restore")
        a2 = m.addAction("Au démarrage : ne rien ouvrir", lambda: self._set_startup_mode("empty"))
        a2.setCheckable(True)
        a2.setChecked(mode == "empty")
        if names:
            sm = m.addMenu("Au démarrage : ouvrir un espace")
            for n in names:
                act = sm.addAction(n, lambda n=n: self._set_startup_mode(f"space:{n}"))
                act.setCheckable(True)
                act.setChecked(mode == f"space:{n}")
        if self._detached:
            m.addSeparator()
            m.addAction("Ranger les fenêtres détachées côte à côte", lambda: self.arrange_detached("cols"))
            m.addAction("Ranger les fenêtres détachées en pile", lambda: self.arrange_detached("rows"))
        m.addSeparator()
        m.addAction("Appliquer le style TabDesk (16:9, barres réduites)", self.apply_tabdesk_style).setEnabled(self.tabs.count() > 0)
        m.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def toggle_guides(self) -> None:
        """Affiche ou masque le panneau Guides ; il prend la place libre à côté d'un jeu sans bandes noires."""
        g = self._guides
        if g is not None:  # fermeture : on libère le moteur web (plusieurs centaines de Mo), il sera recréé à la réouverture
            self._guides_timer.stop()
            g.shutdown()
            g.hide()
            g.setParent(None)
            g.deleteLater()
            self._guides = None
            return
        if g is None:
            g = guides.GuidesPanel(self.qs)
            g.close_requested.connect(self.toggle_guides)
            g.side_requested.connect(self._guides_swap_side)
            g.fit_requested.connect(lambda: self._guides_set_auto(True))
            self._guides = g
            self.split.insertWidget(0 if self._guides_side() == "left" else 1, g)
            i18n.translate(g)
        g.show()
        self._guides_auto = self.guides_cfg.auto
        if self._guides_auto:
            self._guides_autofit()
        else:
            self._guides_apply_width(self.guides_cfg.width)
        self._guides_kick()
        QTimer.singleShot(1500, self._guides_kick)  # l'image du jeu n'est pas encore là à l'ouverture

    def _guides_kick(self) -> None:
        """Demande un réajustement (regroupe les demandes rapprochées) : plus de sondage permanent."""
        t = getattr(self, "_guides_timer", None)
        if t is not None and self._guides is not None:
            t.start(150)

    def _guides_set_auto(self, on: bool) -> None:
        self._guides_auto = on
        self.guides_cfg.auto = on
        if on:
            self._guides_autofit()

    def _guides_apply_width(self, w: int) -> None:
        g = self._guides
        total = max(1, self.split.width())
        w = max(260, min(w, total - 260))
        sizes = [w, total - w] if self._guides_side() == "left" else [total - w, w]
        self.split.setSizes(sizes)

    def _guides_autofit(self) -> None:
        """Largeur du panneau = largeur libre quand le jeu occupe toute la hauteur sans bandes noires."""
        g = self._guides
        page = self.tabs.currentWidget()
        if g is None or not g.isVisible() or page is None:
            return
        host = page.host  # type: ignore[attr-defined]
        img = getattr(host, "_image", None)
        aspect = (img.width() / img.height()) if img is not None and img.height() > 0 else 16 / 9
        target = autofit_width(total=self.split.width(), handle=self.split.handleWidth(), host_w=host.width(),
                               host_h=host.height(), page_w=page.width(), aspect=aspect, current=g.width())
        if target is not None:
            self._guides_apply_width(target)

    def _guides_tick(self) -> None:
        if self._guides_auto and self._guides is not None and self._guides.isVisible() and not self._grid_pages:
            self._guides_autofit()

    def _guides_side(self) -> str:
        return self.guides_cfg.side

    def _guides_swap_side(self) -> None:
        was_open = self._guides is not None
        if was_open:
            self.toggle_guides()
        self.guides_cfg.side = "right" if self._guides_side() == "left" else "left"
        if was_open:
            self.toggle_guides()

    def _guides_moved(self, *_args) -> None:
        """L'utilisateur a déplacé la séparation : on arrête l'ajustement automatique et on retient la largeur."""
        g = self._guides
        if g is not None and g.isVisible():
            self._guides_auto = False
            self.guides_cfg.auto = False
            self.guides_cfg.width = g.width()

    def save_space(self) -> None:
        name, ok = QInputDialog.getText(self, "Enregistrer l'espace", "Nom de l'espace (ex. Mes 4 persos) :")
        name = space_name(name)
        if not ok or not name:
            return
        panels = self.panels()
        self.workspaces.save(name, [p.to_config() for p in panels])
        self.statusBar().showMessage(f"Espace « {name} » enregistré ({len(panels)} sessions).", 5000)

    def delete_space(self, name: str) -> None:
        if QMessageBox.question(self, APP_NAME, f"Supprimer l'espace « {name} » ?") == QMessageBox.StandardButton.Yes:
            self.workspaces.delete(name)

    def open_space(self, name: str) -> None:
        n = self.workspaces.count(name)
        if n <= 0:
            return
        if self.tabs.count():
            box = QMessageBox(self)
            box.setWindowTitle(APP_NAME)
            box.setText(f"Ouvrir « {name} » : remplacer les sessions actuelles ou les ajouter aux onglets ?")
            rep = box.addButton("Remplacer", QMessageBox.ButtonRole.AcceptRole)
            add = box.addButton("Ajouter", QMessageBox.ButtonRole.ActionRole)
            box.addButton("Annuler", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            c = box.clickedButton()
            if c is rep:
                for i in range(self.tabs.count() - 1, -1, -1):
                    pg = self.tabs.widget(i)
                    pg.panel.shutdown()  # type: ignore[union-attr]
                    self.tabs.removeTab(i)
                    pg.deleteLater()
            elif c is not add:
                return
        serials = {d.serial for d in getattr(self, "_devices", []) if d.state == "device"}
        started = 0
        for i in range(min(n, MAX_SESSIONS - self.tabs.count())):  # un fichier importé peut annoncer des centaines de sessions
            page = self.add_session()
            page.panel.load(self.qs, self.workspaces.prefix(name, i))
            wanted = self._attach_known_devices(page.panel)
            if wanted in serials:
                page.panel._autostarted = True
                page.panel.start()
                started += 1
        self._sync_title_tabs()
        self.statusBar().showMessage(f"Espace « {name} » ouvert : {n} sessions, {started} lancée(s).", 6000)

    def _attach_known_devices(self, panel: PhonePanel) -> str:
        """Donne à une session fraîchement créée la liste des téléphones déjà détectés et sélectionne celui qu'elle réclame.
        Sans ça, sa liste déroulante est vide jusqu'au prochain rafraîchissement : lancer tout de suite la session affichait à
        tort « Aucun téléphone sélectionné ». Renvoie le numéro de série réclamé par la session (celui enregistré)."""
        wanted = panel._wanted_serial
        devices = getattr(self, "_devices", [])
        if devices:
            panel.set_devices(devices)  # efface _wanted_serial : on le mémorise avant
            if wanted:
                panel.select_serial(wanted)
        return wanted

    def apply_tabdesk_style(self) -> None:
        """Rendu proche de TabDesk : écran 16:9, interface à 100 %, barre d'outils masquée (F10)."""
        for p in self.panels():
            p.shape_combo.setCurrentIndex(p.shape_combo.findData("16:9"))
            p.zoom_slider.setValue(100)
            p.opt_native.setChecked(False)
        self.toggle_compact(True)
        self.statusBar().showMessage("Style TabDesk appliqué. « Appliquer et relancer » dans Réglages pour les sessions en cours (F10 : barres).", 8000)

    def show_theme_menu(self, anchor: QWidget) -> None:
        m = QMenu(self)
        for key, info in theme.THEMES.items():
            act = m.addAction(info[0])
            act.setCheckable(True)
            act.setChecked(key == theme.current())
            act.triggered.connect(lambda _=False, k=key: self.set_theme(k))
        m.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def set_theme(self, key: str) -> None:
        if key not in theme.THEMES:
            key = theme.DEFAULT_THEME  # nom inconnu (réglage ancien ou abîmé)
        theme.apply(QApplication.instance(), key)
        self.qs.setValue("theme", key)
        self.statusBar().showMessage(f"Thème : {theme.THEMES[key][0]}", 4000)


    def show_settings_menu(self, anchor: QWidget) -> None:
        """Réglages de l'application (pas ceux d'une session) : téléphones, raccourcis, apparence, langue, export."""
        m = QMenu(self)
        m.addAction("Téléphones détectés et règles USB…", self.show_devices)
        m.addAction("Raccourcis clavier…", self.edit_hotkeys)
        tm = m.addMenu("Thème")
        for key, info in theme.THEMES.items():
            act = tm.addAction(info[0])
            act.setCheckable(True)
            act.setChecked(key == theme.current())
            act.triggered.connect(lambda _=False, k=key: self.set_theme(k))
        m.addAction("Langue : English" if self.lang == "fr" else "Langue : Français", self.toggle_language)
        pm = m.addMenu("Téléphone : chauffe et réveil")
        for key, default, label in (
                ("power/auto_throttle", False, "Limiter les ips de tout le téléphone s'il chauffe ou si le Wi-Fi sature (retard possible)"),
                ("power/wake_on_click", True, "Réveiller le téléphone quand je clique sur une session")):
            act = pm.addAction(label)
            act.setCheckable(True)
            act.setChecked(self._flag(key, default))
            act.toggled.connect(lambda on, k=key: self._set_flag(k, on))
        if engine.HW_DEVICES:
            hw = m.addAction("Décodage vidéo par la carte graphique (repli automatique sur le processeur)")
            hw.setCheckable(True)
            hw.setChecked(self._flag("video/hw_decode", True))
            hw.toggled.connect(lambda on: self._set_flag("video/hw_decode", on))
        m.addSeparator()
        m.addAction("Exporter les réglages…", self.export_settings)
        m.addAction("Importer des réglages…", self.import_settings)
        m.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def show_help_menu(self, anchor: QWidget) -> None:
        m = QMenu(self)
        m.addAction("Guide de démarrage", self.show_guide)
        m.addAction("Diagnostic…", self.show_diagnostic)
        if sys.platform.startswith("linux"):
            m.addAction("Installer les règles USB (Linux)…", self.install_udev)
        m.addSeparator()
        m.addAction("À propos", self.about)
        m.exec(anchor.mapToGlobal(anchor.rect().topRight()))

    def export_settings(self) -> None:
        self.save_state()
        self.qs.sync()
        default = str(Path.home() / "notrefu-mirror-reglages.json")
        path, _ = QFileDialog.getSaveFileName(self, "Exporter les réglages", default, "Réglages notrefu-mirror (*.json)")
        if not path:
            return
        try:
            n = settingsio.export_to(self.qs, path, __version__)
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"Export impossible : {exc}")
            return
        self.statusBar().showMessage(f"{n} réglages exportés dans {path}.", 8000)

    def import_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importer des réglages", str(Path.home()), "Réglages notrefu-mirror (*.json)")
        if not path:
            return
        try:
            data = settingsio.read_file(path)
        except settingsio.SettingsFileError as exc:
            QMessageBox.warning(self, APP_NAME, f"Import impossible : {exc}")
            return
        ok = QMessageBox.question(
            self, APP_NAME,
            f"Remplacer toutes les sessions, espaces et réglages par ceux du fichier ({len(data)} valeurs) ?\n"
            "Les changements s'appliquent au prochain démarrage de notrefu-mirror.")
        if ok != QMessageBox.StandardButton.Yes:
            return
        settingsio.apply_to(self.qs, data)
        self._locked = True  # sinon la fermeture réécrirait les onglets actuels par-dessus l'import
        self.statusBar().showMessage("Réglages importés : ferme puis relance notrefu-mirror pour les appliquer.", 15000)

    def toggle_language(self) -> None:
        self.lang = "en" if self.lang == "fr" else "fr"
        self.qs.setValue("lang", self.lang)
        i18n.set_lang(self.lang)

    def show_diagnostic(self) -> None:
        from . import diag

        dlg = QDialog(self)
        dlg.setWindowTitle("Diagnostic")
        dlg.resize(620, 520)
        lay = QVBoxLayout(dlg)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText("Vérification en cours…")
        lay.addWidget(view, 1)
        row = QHBoxLayout()
        again = QPushButton("Relancer")
        copy = QPushButton("Copier le rapport")
        close = QPushButton("Fermer")
        close.setObjectName("primary")
        for b in (again, copy):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        sig = _DiagSignal()

        def go() -> None:
            view.setPlainText("Vérification en cours…")
            self.runner.run(diag.run_diagnostics, lambda res, err: sig.done.emit(
                f"Erreur : {err}" if err else self._full_report(diag.format_report(res))))

        sig.done.connect(view.setPlainText)
        again.clicked.connect(go)
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(view.toPlainText()))
        close.clicked.connect(dlg.accept)
        go()
        dlg.exec()

    def _full_report(self, diagnostic: str) -> str:
        """Diagnostic + versions + état de chaque session + derniers messages, IP et séries masqués (voir report.py)."""
        import platform

        from PySide6.QtCore import qVersion

        app = {"notrefu-mirror": __version__, "Système": platform.platform(), "Python": platform.python_version(),
               "Qt": qVersion(), "Langue": self.lang, "Thème": theme.current()}
        sessions = []
        for pg in self._all_pages():
            p = pg.panel
            c = p.client
            cfg = p.to_config()
            info = {"title": p.title, "state": "reconnexion" if p.reconnecting else "en cours" if p.running else "arrêtée",
                    "phone": report.mask_serial(p.serial), "link": "Wi-Fi" if p._is_wifi_selected() else "USB",
                    "quality": f"{cfg.quality} · {cfg.spins.get('br', '?')} Mbit/s · {cfg.spins.get('fps', '?')} ips · "
                               f"{cfg.spins.get('w', '?')}×{cfg.spins.get('h', '?')}",
                    "health": p.health_text}
            if c:
                cap = c.caps.effective()
                info.update({"fps_cap": f"{cap} ips" if cap else "", "perf": p.fps_label.text(), "audio": c.audio_state,
                             "log": list(c.log_tail)})
            sessions.append(info)
        return report.build_report(app, diagnostic, sessions)

    def install_udev(self) -> None:
        pkexec = shutil.which("pkexec")
        manual = udev_setup.manual_command()
        text = (
            "Cette règle autorise l'accès USB aux téléphones en mode débogage (adb) pour l'utilisateur connecté. "
            "Elle n'est utile que pour la connexion par câble ; le Wi-Fi n'en a pas besoin.\n\n"
        )
        if not pkexec:
            QMessageBox.information(self, APP_NAME, text + "pkexec est absent. Dans un terminal :\n\n" + manual)
            return
        if QMessageBox.question(self, APP_NAME, text + f"Écrire {adb.UDEV_RULE_PATH} (mot de passe administrateur demandé) ?") != QMessageBox.StandardButton.Yes:
            return

        def done(_res, err):
            if err:
                QMessageBox.warning(self, APP_NAME, f"Installation échouée :\n{err}\n\nEn terminal :\n\n{manual}")
            else:
                QMessageBox.information(self, APP_NAME, "Règle installée. Débranchez puis rebranchez le téléphone.")

        self.runner.run(lambda: udev_setup.install_rule(pkexec), done)

    def show_guide(self) -> None:
        QMessageBox.information(
            self, "Guide de démarrage",
            "1. Sur le téléphone : Paramètres → À propos → touchez 7 fois « Numéro de build », puis "
            "Options pour les développeurs → activez « Débogage USB ».\n"
            "2. Branchez le câble, acceptez « Autoriser le débogage USB ».\n"
            "3. Dans une session : choisissez le téléphone, réglez la qualité, puis « Lancer le mirroring ». "
            "Le jeu s'affiche dans l'onglet.\n\n"
            "Plusieurs comptes : bouton « Nouvelle session » (réglages copiés de la session courante), "
            "double-clic sur un onglet pour le renommer.\n\n"
            "Naviguer : Ctrl+Tab / Ctrl+Maj+Tab, Alt+1…9, F11 pour le plein écran (modifiables dans « Raccourcis »).\n\n"
            "Sans fil : section « Connecter le téléphone » des réglages de la session.",
        )

    def about(self) -> None:
        scrcpy = adb.find_tool("scrcpy")

        def probe() -> str:
            if not scrcpy:
                return "introuvable"
            try:
                return subprocess.run([scrcpy, "--version"], capture_output=True, text=True, timeout=5,
                                      env=adb.tool_env()).stdout.splitlines()[0]
            except Exception:  # noqa: BLE001
                return "indisponible"

        self.runner.run(probe, lambda ver, _err: self._show_about(ver or "indisponible"))  # la sonde ne bloque plus l'interface

    def _show_about(self, ver: str) -> None:
        QMessageBox.about(
            self, f"À propos de {APP_NAME}",
            f"<b>{APP_NAME} {__version__}</b><br>Interface de réplication d'écran Android.<br><br>"
            f"Moteur : {ver} (Apache-2.0, © Genymobile / Romain Vimont) et adb (Android SDK Platform-Tools).<br>"
            "Interface : Qt for Python (LGPL).<br><br>"
            "Projet indépendant, sans lien avec Ankama ni avec un site tiers. Aucune émulation, aucune "
            "automatisation : le jeu tourne sur le téléphone et vous le pilotez vous-même.",
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        self._exit_grid()
        if self._guides is not None:
            self._guides.shutdown()
        for w in list(self._detached):
            w.close()  # les fenêtres détachées reviennent dans les onglets avant l'enregistrement des réglages
        self.qs.setValue("geometry", self.saveGeometry())
        self.save_state()
        for page in self.pages():
            page.panel.shutdown()
        self.hide()  # la fenêtre disparaît tout de suite ; le nettoyage se termine dans la fonction suivante
        self.cleanup()
        super().closeEvent(event)

    def cleanup(self) -> None:
        """Arrêt propre, une seule fois : sessions arrêtées en parallèle (4 s au total, pas 4 s chacune),
        conversions d'enregistrement terminées, tâches adb abandonnées, serveur adb privé arrêté."""
        if getattr(self, "_cleaned", False):
            return
        self._cleaned = True
        stop_clients([pg.panel.client for pg in self.pages() if pg.panel.client], 4.0)
        join_background(15.0)  # un enregistrement en cours de conversion ne doit pas être coupé net
        self.runner.shutdown(1500)
        # Le serveur adb (privé à notrefu-mirror) est lancé depuis l'AppImage : on l'arrête
        # pour ne pas laisser un processus qui garde le point de montage occupé.
        try:
            adb.run_adb(["kill-server"], timeout=4)
        except adb.AdbError:
            pass


class _GridAudioFocus(QObject):
    """Vue en grille : un clic dans une cellule lui donne le son (l'événement n'est pas consommé)."""

    def __init__(self, main: "MainWindow", page: "SessionPage") -> None:
        super().__init__(page.host)
        self._main, self._page = main, page

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        if ev.type() == QEvent.Type.MouseButtonPress:
            self._main.grid_audio(self._page)
        return False


class _DetachedWindow(QWidget):
    """Fenêtre indépendante qui contient une session sortie des onglets ; la fermer la remet dans les onglets."""

    def __init__(self, main: "MainWindow", page: "SessionPage") -> None:
        super().__init__()
        self._main = main
        self._page: SessionPage | None = page
        self.setWindowTitle(f"{page.panel.title} — {APP_NAME}")
        self.setWindowIcon(main.windowIcon())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(page)
        page.show()
        page.panel.title_changed.connect(lambda t: self.setWindowTitle(f"{t} — {APP_NAME}"))
        self.resize(1280, 760)
        self._geo_key = f"detached/{page.panel.title}/geometry"
        geo = main.qs.value(self._geo_key)
        if geo:
            self.restoreGeometry(geo)

    def take_page(self) -> "SessionPage":
        page = self._page
        assert page is not None
        self._page = None
        self.layout().removeWidget(page)
        return page

    def closeEvent(self, event) -> None:  # noqa: N802
        self._main.qs.setValue(self._geo_key, self.saveGeometry())
        if self._page is not None:
            self._main.reattach(self)
        super().closeEvent(event)
        self.deleteLater()


def run(argv: list[str]) -> int:
    QGuiApplication.setDesktopFileName("notrefu_mirror")
    # Navigateur intégré (Guides) : le bac à sable de Chromium ne peut pas fonctionner depuis un AppImage
    # QtWebEngine n'est plus chargé au démarrage (seulement à l'ouverture des Guides) : cet attribut, qui doit précéder la création
    # de l'application, évite l'avertissement « QtWebEngineWidgets doit être importé avant QCoreApplication ».
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    theme.apply(app, str(app_settings().value("theme", theme.DEFAULT_THEME)))
    icon = RESOURCES / "notrefu_mirror.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    win = MainWindow()
    win.show()
    app.aboutToQuit.connect(win.cleanup)  # quitter sans passer par la croix (Ctrl+C, arrêt de session…) nettoie aussi
    _install_signal_handlers(app, win)
    return app.exec()


def _install_signal_handlers(app: QApplication, win: "MainWindow") -> None:
    """Ctrl+C dans le terminal ou `kill` : fermeture normale (arrêt des sessions, du serveur adb, du lecteur audio)
    au lieu de laisser des processus orphelins. Le minuteur laisse à Python l'occasion de traiter le signal."""
    import signal

    def request_close(*_a) -> None:
        win.close()
        app.quit()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, request_close)
        except (ValueError, OSError):
            return
    tick = QTimer(app)
    tick.timeout.connect(lambda: None)
    tick.start(500)
