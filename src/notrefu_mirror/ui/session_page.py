"""Interface Qt de notrefu-mirror : session_page."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QFrame,
    QSizePolicy,
    QMenu,
    QMessageBox,
    QFileDialog,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..appsettings import app_settings
from .. import APP_NAME, adb, phonehealth, theme
from .. import protocol as P
from ..gameview import GameView

from ..scrcpy_cmd import (
    valid_package,
)

from .common import _ElideLabel, _Runner
from .dialogs import JournalDialog
from .phone_panel import PhonePanel


class SessionPage(QWidget):
    """Une session = page de réglages + zone de jeu intégrée."""

    _screen_probe = Signal(object)

    def __init__(self, runner: _Runner, title: str) -> None:
        super().__init__()
        self.panel = PhonePanel(runner, title)
        self.host = GameView()
        self.panel.view = self.host
        self.host.bind_keymap(self.panel.keymap)
        self.panel.keymap_changed.connect(self.host.overlay.refresh)
        self.host.overlay.changed.connect(self._keymap_changed)
        self.host.overlay.status.connect(self.panel.message.emit)
        self.host.overlay.exit_requested.connect(lambda: self.set_keymap_editing(False))
        self.panel.area_size = self._area_size

        self.stack = QStackedWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.panel)
        settings_page = QWidget()
        spl = QVBoxLayout(settings_page)
        spl.setContentsMargins(0, 0, 0, 0)
        spl.setSpacing(0)
        spl.addWidget(scroll, 1)
        spl.addWidget(self.panel.action_bar)
        self.stack.addWidget(settings_page)  # 0 : réglages

        game = QWidget()  # 1 : jeu
        gl = QVBoxLayout(game)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(0)
        self.bar = QWidget()
        self.bar.setObjectName("gamebar")
        bl = QHBoxLayout(self.bar)
        bl.setContentsMargins(10, 6, 10, 6)
        bl.setSpacing(6)
        # Barre de session en trois groupes : session | navigation Android | outils, puis état et « Arrêter » à droite.
        # Boutons à icône seule (le texte s'y coupait) ; l'infobulle donne le nom complet.
        def tool(icon: str, tip: str, slot=None, checkable: bool = False) -> QToolButton:
            b = QToolButton()
            b.setObjectName("tool")
            b.setCheckable(checkable)
            theme.bind_icon(b, icon)
            b.setToolTip(tip)
            b.setAccessibleName(tip)
            if slot is not None:
                b.clicked.connect(slot)
            return b

        def sep() -> QFrame:
            f = QFrame()
            f.setObjectName("barsep")
            f.setFrameShape(QFrame.Shape.NoFrame)
            f.setFixedWidth(1)
            return f

        self.settings_btn = tool("sliders", "Réglages de cette session (qualité, affichage, options)")
        self.relaunch_btn = tool("refresh", "Relancer le jeu (ferme puis rouvre l'application, sans couper la session)", self._relaunch_game)
        self.fit_btn = tool("tablet", "Adapter l'écran du jeu à la taille de la fenêtre (relance la session, le jeu reste lancé sur le téléphone)", self.panel.restart)
        self.nav_btns = [
            tool("back", "Retour", lambda: self._key(P.AKEYCODE_BACK)),
            tool("home", "Accueil", lambda: self._key(P.AKEYCODE_HOME)),
            tool("recents", "Applications récentes", lambda: self._key(P.AKEYCODE_APP_SWITCH)),
        ]
        self.shot_btn = tool("camera", "Capture d'écran (dossier Images)", self._screenshot)
        self.rec_btn = tool("record", "Enregistrer la session en vidéo avec le son du jeu (.mkv) — clic droit : choisir le dossier",
                            self._toggle_record, checkable=True)
        self.rec_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.rec_btn.customContextMenuRequested.connect(self._rec_menu)
        self.bell_btn = tool("bell", "Panneau de notifications du téléphone", lambda: self._send(P.simple_message(P.MSG_EXPAND_NOTIFICATION_PANEL)))
        self.power_btn = tool("power", "Éteindre / allumer l'écran du téléphone", self._toggle_phone_screen)
        self.keys_btn = tool("keyboard", "Touches personnalisées : une touche du clavier = un appui à un endroit précis de l'écran")
        self.keys_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.keys_menu = QMenu(self.keys_btn)
        self.act_edit = self.keys_menu.addAction("Modifier les touches", lambda: self.set_keymap_editing(not self.host.overlay.editing))
        self.act_edit.setCheckable(True)
        self.act_active = self.keys_menu.addAction("Touches actives (désactive-les pour écrire dans le chat)",
                                                   lambda: self.toggle_keymap_active())
        self.act_active.setCheckable(True)
        self.act_show = self.keys_menu.addAction("Afficher les repères sur le jeu", self._toggle_keymap_show)
        self.act_show.setCheckable(True)
        self.keys_menu.addSeparator()
        self.copy_menu = self.keys_menu.addMenu("Copier ces touches vers…")
        self.keys_menu.addAction("Tout effacer…", self._clear_keymap)
        self.keys_menu.aboutToShow.connect(self._sync_keys_menu)
        self.keys_btn.setMenu(self.keys_menu)
        self.journal_btn = tool("list", "Journal technique de la session (utile pour comprendre un problème)", self.show_journal)
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(self.panel.volume)
        self.vol_slider.setFixedWidth(90)
        self.vol_slider.setToolTip("Volume du son de cette session (0–100 %)")
        self.vol_slider.valueChanged.connect(self.panel.set_volume)
        self.panel.volume_changed.connect(lambda v: self.vol_slider.value() != v and self.vol_slider.setValue(v))
        self.stats_label = _ElideLabel("")
        self.stats_label.setObjectName("stats")
        self.stats_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.stop_btn = QToolButton()
        self.stop_btn.setText("Arrêter")
        self.stop_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        theme.bind_icon(self.stop_btn, "stop", "danger_text")
        self.stop_btn.setObjectName("tool-stop")
        self.stop_btn.setToolTip("Arrêter cette session")
        self.more_btn = tool("more", "Autres actions")
        self.more_btn.setVisible(False)
        self.more_btn.clicked.connect(self._show_more)

        for w in (self.settings_btn, self.relaunch_btn, self.fit_btn, sep(), *self.nav_btns, sep(),
                  self.shot_btn, self.rec_btn, self.bell_btn, self.power_btn, self.keys_btn, sep(), self.vol_slider, self.journal_btn):
            bl.addWidget(w)
        bl.addWidget(self.more_btn)
        bl.addWidget(self.stats_label, 1)  # prend la place libre, s'abrège si elle manque
        bl.addWidget(self.stop_btn)
        # Ordre de repli quand la barre est étroite : les premiers de la liste passent dans le menu « ⋯ »
        self._overflow = [self.journal_btn, self.fit_btn, self.bell_btn, self.power_btn, self.shot_btn, self.vol_slider]
        self.bar.setMinimumWidth(180)
        gl.addWidget(self.bar)
        gl.addWidget(self.host, 1)
        self.game_layout = gl  # la vue en grille y remet la zone de jeu en quittant
        self.stack.addWidget(game)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)

        self._screen_probe.connect(self._apply_screen_toggle)
        self.settings_btn.clicked.connect(self.show_settings)
        self.stop_btn.clicked.connect(self.panel.stop)
        self.panel.stats.connect(self._set_stats)
        self.panel.show_game.connect(self.show_game)
        self.panel.started.connect(self._on_started)
        self.panel.ended.connect(self._on_ended)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout_bar()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._relayout_bar)

    def _set_stats(self, text: str) -> None:
        self.stats_label.setText(text)
        # texte complet au survol (la barre elle-même reste inchangée) + détail de la RAM de l'appareil quand un relevé existe
        tip = text
        if self.panel.running:
            tip += "\n\n" + (self.panel.health_tip or phonehealth.ram_detail(None))
        self.stats_label.setToolTip(tip)

    def _relayout_bar(self) -> None:
        """Replie les boutons les moins utiles dans « ⋯ » quand la barre manque de place (jamais de texte coupé)."""
        hidden = []
        for w in self._overflow:
            w.setVisible(True)
        self.more_btn.setVisible(False)
        for w in self._overflow:
            if self.bar.layout().minimumSize().width() <= self.bar.width():
                break
            w.setVisible(False)
            hidden.append(w)
            self.more_btn.setVisible(True)
        self._hidden_actions = [w for w in hidden if isinstance(w, QToolButton)]

    def _show_more(self) -> None:
        m = QMenu(self)
        for b in getattr(self, "_hidden_actions", []):
            m.addAction(b.toolTip().split(" (")[0].split(" — ")[0], b.click)
        m.exec(self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft()))

    # ---- touches personnalisées ----------------------------------------------
    def _sync_keys_menu(self) -> None:
        km = self.panel.keymap
        self.act_edit.setChecked(self.host.overlay.editing)
        self.act_active.setChecked(km.active)
        self.act_show.setChecked(km.show)
        self.copy_menu.clear()
        win = self.window()
        others = [pg for pg in (win._all_pages() if hasattr(win, "_all_pages") else []) if pg is not self]
        self.copy_menu.setEnabled(bool(others) and len(km) > 0)
        for pg in others:
            self.copy_menu.addAction(pg.panel.title, lambda pg=pg: self._copy_keymap_to(pg))
        if len(others) > 1:
            self.copy_menu.addSeparator()
            self.copy_menu.addAction("Toutes les autres sessions", lambda: self._copy_keymap_to(*others))

    def _keymap_changed(self) -> None:
        win = self.window()
        if hasattr(win, "state_dirty"):
            win.state_dirty()  # enregistré avec le reste de l'état

    def set_keymap_editing(self, on: bool) -> None:
        if on and self.stack.currentIndex() != 1:
            self.stack.setCurrentIndex(1)
        if on and not self.panel.running:
            self.panel.message.emit("Démarre la session avant de placer des touches.")
            on = False
        self.host.set_keymap_editing(on)
        if on:
            self.panel.keymap.active = True  # on édite pour s'en servir : on réactive

    def toggle_keymap_edit(self) -> None:
        self.set_keymap_editing(not self.host.overlay.editing)

    def toggle_keymap_active(self) -> None:
        km = self.panel.keymap
        km.active = not km.active
        self.host.translator.release_all()
        self.host.overlay.refresh()
        self._keymap_changed()
        self.panel.message.emit(f"{self.panel.title} : touches personnalisées {'activées' if km.active else 'désactivées'}.")

    def _toggle_keymap_show(self) -> None:
        km = self.panel.keymap
        km.show = not km.show
        self.host.overlay.refresh()
        self._keymap_changed()

    def _copy_keymap_to(self, *targets: "SessionPage") -> None:
        """Recopie les touches de cette session vers d'autres (chacune garde ensuite sa propre disposition)."""
        src = self.panel.keymap
        if not len(src):
            return
        names = ", ".join(f"« {t.panel.title} »" for t in targets)
        if any(len(t.panel.keymap) for t in targets) and QMessageBox.question(
                self, APP_NAME, f"Remplacer les touches de {names} par les {len(src)} touches de « {self.panel.title} » ?"
        ) != QMessageBox.StandardButton.Yes:
            return
        for t in targets:
            t.host.translator.release_all()
            t.panel.keymap.copy_keys_from(src)
            t.host.overlay.refresh()
        self._keymap_changed()
        self.panel.message.emit(f"{len(src)} touches copiées de {self.panel.title} vers {names}.")

    def _clear_keymap(self) -> None:
        if len(self.panel.keymap) and QMessageBox.question(
                self, APP_NAME, f"Effacer les {len(self.panel.keymap)} touches de « {self.panel.title} » ?") == QMessageBox.StandardButton.Yes:
            self.panel.keymap.clear()
            self.host.overlay.refresh()
            self._keymap_changed()

    def show_journal(self) -> None:
        old = getattr(self, "_journal", None)
        try:
            if old is not None and old.isVisible():
                old.raise_()
                old.activateWindow()
                return
        except RuntimeError:
            pass
        dlg = JournalDialog(self.panel.title, self.panel.log, self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._journal = dlg
        dlg.show()

    def show_settings(self) -> None:
        self.stack.setCurrentIndex(0)

    def _area_size(self) -> tuple[int, int]:
        """Taille de la zone de jeu. Les onglets masqués n'ont pas la bonne taille : on mesure l'onglet visible."""
        win = self.window()
        if hasattr(win, "game_area_size"):
            return win.game_area_size()
        return (self.stack.width(), self.stack.height() - self.bar.sizeHint().height())

    def _send(self, msg: bytes) -> None:
        c = self.panel.client
        if c:
            c.send(msg)

    def _key(self, code: int) -> None:
        self._send(P.inject_keycode(P.KEY_DOWN, code))
        self._send(P.inject_keycode(P.KEY_UP, code))
        self.host.setFocus()

    def _relaunch_game(self) -> None:
        panel = self.panel
        spec = panel.app_edit.text().strip()
        if not panel.running or not panel.serial or not spec or not valid_package(spec):
            QMessageBox.information(self, APP_NAME, "Démarre d'abord la session et indique l'application du jeu dans les réglages.")
            return
        if not self.relaunch_btn.isEnabled():
            return  # une relance est déjà en cours (clics répétés)
        self.relaunch_btn.setEnabled(False)
        serial = panel.serial
        panel.message.emit(f"{panel.title} : relance du jeu…")
        panel.runner.run(lambda: adb.restart_game(serial, spec), lambda res, err: self._relaunch_step2(serial, spec, res, err))

    def _relaunch_step2(self, serial: str, spec: str, res, err) -> None:
        panel = self.panel
        if err is not None or res is None:
            self.relaunch_btn.setEnabled(True)
            panel.message.emit(f"{panel.title} : relance impossible ({err})")
            return
        pkg, user, display = res
        if user is None:
            self.relaunch_btn.setEnabled(True)
            self._send(P.start_app(pkg))  # même chemin que le premier lancement
            panel.message.emit(f"{panel.title} : jeu relancé.")
            return

        def done(_r, e) -> None:
            self.relaunch_btn.setEnabled(True)
            panel.message.emit(f"{panel.title} : jeu relancé." if e is None else f"{panel.title} : relance impossible ({e})")

        panel.runner.run(lambda: adb.launch_game(serial, pkg, user, display), done)

    def _toggle_phone_screen(self) -> None:
        """Interroge l'état RÉEL de l'écran (il a pu être allumé à la main), puis l'inverse."""
        serial = self.panel.serial

        self.panel.runner.run(
            lambda: adb.display_is_on(serial) if serial else None,
            lambda real_on, err: self._apply_screen_toggle(real_on if err is None else None),
        )

    def _apply_screen_toggle(self, real_on) -> None:
        current = getattr(self, "_phone_screen_on", True) if real_on is None else bool(real_on)
        target = not current
        self._phone_screen_on = target
        self._send(P.set_display_power(target))
        if target:
            serial = self.panel.serial
            if serial:
                threading.Thread(target=adb.wake_up, args=(serial,), daemon=True).start()
        self.panel.message.emit("Écran du téléphone allumé." if target else "Écran du téléphone éteint.")

    def _screenshot(self) -> None:
        path = self.host.save_screenshot(self.panel.title)
        self.panel.message.emit(f"Capture enregistrée : {path}" if path else "Aucune image à enregistrer.")

    @staticmethod
    def _rec_folder() -> str:
        saved = str(app_settings().value("rec_dir", "") or "")
        return saved or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MoviesLocation) or str(Path.home())

    def _rec_menu(self, pos) -> None:
        m = QMenu(self)
        m.addAction("Dossier des enregistrements…", self._choose_rec_folder)
        m.addAction("Ouvrir le dossier des enregistrements", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self._rec_folder())))
        m.exec(self.rec_btn.mapToGlobal(pos))

    def _choose_rec_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choisir le dossier des enregistrements", self._rec_folder())
        if d:
            app_settings().setValue("rec_dir", d)
            self.panel.message.emit(f"Dossier des enregistrements : {d}")

    def _toggle_record(self) -> None:
        c = self.panel.client
        if not c or not c.running:
            self.rec_btn.setChecked(False)
            return
        if c.recording:
            out = c.stop_recording()
            self.rec_btn.setChecked(False)
            self.panel.message.emit(f"Enregistrement terminé (conversion en cours) : {out}")
            return
        folder = self._rec_folder()
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
        except OSError:
            folder = str(Path.home())
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in self.panel.title)
        path = str(Path(folder) / f"notrefu-mirror-{safe}-{time.strftime('%Y%m%d-%H%M%S')}.mkv")
        c.start_recording(path)
        self.rec_btn.setChecked(True)
        self.panel.message.emit(f"Enregistrement en cours (vidéo et son du jeu) : {path}")

    def show_game(self) -> None:
        if self.panel.running:
            self.stack.setCurrentIndex(1)
            QTimer.singleShot(60, self.focus_game)

    def focus_game(self) -> None:
        if self.stack.currentIndex() == 1:
            self.host.setFocus()

    def set_immersive(self, on: bool) -> None:
        self.bar.setVisible(not on)

    def _on_started(self, _client) -> None:
        self._phone_screen_on = not self.panel.opt_screen_off.isChecked()
        self.stack.setCurrentIndex(1)
        QTimer.singleShot(60, self.focus_game)

    def _on_ended(self) -> None:
        self.rec_btn.setChecked(False)
        # En cas d'erreur le message reste visible dans la zone de jeu ; sinon retour aux réglages.
        if self.panel.client and self.panel.client.state == "error":
            self.panel.refitting = False
            self.stack.setCurrentIndex(0)
        elif self.panel.refitting:
            pass  # adaptation à la fenêtre : la dernière image reste affichée pendant la reconnexion
        else:
            self.host.attach(None)
            self.show_settings()


class EmptyPage(QWidget):
    """Page affichée quand toutes les sessions sont fermées."""
