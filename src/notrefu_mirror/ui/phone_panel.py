"""Interface Qt de notrefu-mirror : phone_panel."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QBoxLayout,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QFileDialog,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, adb, compat, power, theme
from .. import protocol as P
from ..engine import AdbTransport, ScrcpyClient
from ..session_config import SessionConfig
from ..session_logic import ATTEMPT_TIMEOUT_S, MAX_ATTEMPTS, ReconnectPolicy, build_client_params, failure_reason, wm_fix
from ..session_plan import DisplayRequest, plan_display

from ..scrcpy_cmd import (
    DOFUS_TOUCH_PACKAGE,
    MODES,
    PRESETS,
    SHORTCUT_MODS,
    WINDOW_PREFIX,
    Settings,
    explain_failure,
    preset_summary,
    valid_package,
)

from .common import CLASS_EMBLEMS, CLASS_NAMES, RESOURCES, _Bridge, _Runner, emblem_pixmap
from ..health_monitor import stats_text
from ..keymap import KeyMap
from ..wireless import device_state_hint, devices_banner, pair_ip, parse_port, valid_ip
from .dialogs import AppPickerDialog, ShortcutsDialog


def _emit_safe(emit, *args) -> None:
    """Émet un signal depuis un fil du moteur ; sans effet si le widget a déjà été détruit (onglet fermé)."""
    try:
        emit(*args) if not hasattr(emit, "emit") else emit.emit(*args)
    except RuntimeError:
        pass


class PhonePanel(QWidget):
    def _relayout(self, width: int) -> None:
        """Réglages sur une seule colonne quand la zone visible est étroite."""
        cols = getattr(self, "cols", None)
        if cols is not None:
            want = QBoxLayout.Direction.TopToBottom if width < 900 else QBoxLayout.Direction.LeftToRight
            if cols.direction() != want:
                cols.setDirection(want)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        vp = self.parentWidget()
        if vp is not None and not getattr(self, "_vp_watched", False):
            self._vp_watched = True
            vp.installEventFilter(self)
        self._relayout(vp.width() if vp is not None else self.width())

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Resize and obj is self.parentWidget():
            self._relayout(obj.width())
        return super().eventFilter(obj, event)

    def _apply_effects(self) -> None:
        """Ombres douces derrière les panneaux et lueur sous le bouton principal (jamais sur la vidéo)."""
        try:
            for g in self.findChildren(QGroupBox):
                theme.shadow(g, blur=32, dy=8, alpha=110)
            theme.shadow(self.start_btn, blur=28, dy=4, alpha=105, color=theme.C["accent"])
        except RuntimeError:  # widgets déjà détruits (fermeture)
            pass

    message = Signal(str)
    title_changed = Signal(str)
    color_changed = Signal(str)
    volume_changed = Signal(int)
    keymap_changed = Signal()  # touches rechargées (réglages chargés ou copiés) : la vue doit se redessiner
    started = Signal(object)  # ScrcpyClient démarré
    state_changed = Signal(str, str)
    log_line = Signal(str)
    ended = Signal()
    show_game = Signal()
    diagnose_requested = Signal()  # le bandeau d'aide demande d'ouvrir Aide → Diagnostic
    stats = Signal(str)

    def __init__(self, runner: _Runner, title: str) -> None:
        super().__init__()
        self.runner = runner
        self.title = title
        self.client: ScrcpyClient | None = None
        self._bridge = _Bridge()
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(lambda: self.start(auto=True))
        self._policy = ReconnectPolicy()
        self._gen = 0  # numéro de la tentative en cours : les événements d'une tentative abandonnée sont ignorés
        self._attempt_timer = QTimer(self)  # garde-fou : une tentative qui reste « en démarrage » est abandonnée
        self._attempt_timer.setSingleShot(True)
        self._attempt_timer.timeout.connect(self._attempt_timed_out)
        self.keymap = KeyMap()  # touches personnalisées de cette session (ratios de l'écran du téléphone)
        self._restart_pending = False  # un « Redémarrer » est en cours : les clics répétés sont ignorés, « Arrêter » l'annule
        self._last_serial = ""
        self._wm_baseline: tuple[str | None, str | None] | None = None
        self._fps_mark = (0.0, 0)
        self._control = True
        self.embed = True  # le jeu est affiché dans la fenêtre de notrefu-mirror (client intégré)
        self.view = None  # GameView associée (fixée par SessionPage)
        self.token = ""
        self._devices: list[adb.Device] = []
        self._wanted_serial = ""
        self.color = ""
        self.icon_path = ""
        self.volume = 100
        self.was_running = False
        self._log_text = ""
        self._info_sdk = 0
        self._build_ui()
        self._wire()
        self._bridge.state.connect(self._on_state)
        self._bridge.log.connect(self._append)
        self._bridge.clipboard.connect(self._clip_from_phone)
        QGuiApplication.clipboard().dataChanged.connect(self._clip_to_phone)
        self._clip_last = ""
        self._refresh_quality_ui()
        self._refresh_mode_ui()
        self._update_buttons()

    # ---- construction --------------------------------------------------
    def _build_ui(self) -> None:
        # Une seule colonne centrée (lecture de haut en bas, dans l'ordre de la tâche) :
        # 1 Téléphone · 2 Jeu · 3 Qualité · 4 Options · puis réglages avancés repliés.
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        col = QWidget()
        col.setMaximumWidth(760)
        outer.addWidget(col, 100)
        outer.addStretch(1)
        root = QVBoxLayout(col)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(16)

        self._build_phone_block(root)
        aform = self._build_game_block(root)  # le formulaire « affichage » est rangé dans les réglages avancés
        self._build_quality_block(root)
        self._build_options_block(root)
        self._build_advanced_block(root, aform)
        self._build_actions_block(root)

    def _build_phone_block(self, root: QVBoxLayout) -> None:
        """Téléphone et connexion."""
        # --- 1. Téléphone
        gphone = QGroupBox("Téléphone")
        pv = QVBoxLayout(gphone)
        pv.setSpacing(10)
        top = QHBoxLayout()
        self.dev_combo = QComboBox()
        self.dev_combo.setMinimumWidth(240)
        top.addWidget(self.dev_combo, 1)
        self.refresh_btn = QPushButton("Actualiser")
        top.addWidget(self.refresh_btn)
        pv.addLayout(top)
        self.banner = QLabel("")  # problème de connexion, avec la marche à suivre
        self.banner.setWordWrap(True)
        self.banner.setObjectName("hint")
        self.banner.setVisible(False)
        pv.addWidget(self.banner)
        self.diag_btn = QPushButton("Ouvrir le diagnostic")  # sortie brute d'adb + état du serveur, à copier-coller en cas de souci
        self.diag_btn.setVisible(False)
        self.diag_btn.clicked.connect(self.diagnose_requested.emit)
        pv.addWidget(self.diag_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setObjectName("info")
        pv.addWidget(self.info_label)
        self.brand_label = QLabel("")  # conseil ciblé selon la marque (Samsung, Xiaomi/POCO, Oppo/Realme/OnePlus)
        self.brand_label.setWordWrap(True)
        self.brand_label.setObjectName("hint")
        self.brand_label.setVisible(False)
        pv.addWidget(self.brand_label)
        self._brand_tip = ""
        self.adb_error = ""

        # --- Connexion
        v = pv
        row = QHBoxLayout()
        self.rb_usb = QRadioButton("USB (câble)")
        self.rb_wifi = QRadioButton("Sans fil (Wi-Fi)")
        self.rb_usb.setChecked(True)
        row.addWidget(self.rb_usb)
        row.addWidget(self.rb_wifi)
        v.addLayout(row)
        self.usb_help = QLabel(
            "Activez le <b>débogage USB</b> sur le téléphone, branchez-le, puis acceptez la fenêtre "
            "d'autorisation. Il apparaît alors dans la liste ci-dessus."
        )
        self.usb_help.setWordWrap(True)
        self.usb_help.setObjectName("muted")
        v.addWidget(self.usb_help)
        self.wifi_box = QWidget()
        wv = QVBoxLayout(self.wifi_box)
        wv.setContentsMargins(0, 0, 0, 0)
        wh = QLabel(
            "1. Première fois (et après chaque redémarrage du téléphone) : branchez-le en USB et cliquez "
            "sur <b>Activer le sans-fil</b>. L'adresse se remplit toute seule.<br>"
            "2. Débranchez le câble (même Wi-Fi sur le PC et le téléphone).<br>"
            "3. Cliquez sur <b>Connecter sans fil</b>."
        )
        wh.setWordWrap(True)
        wh.setObjectName("muted")
        wv.addWidget(wh)
        form = QFormLayout()
        self.ip_edit = QLineEdit()
        self.ip_edit.setPlaceholderText("192.168.1.42")
        self.port_edit = QLineEdit("5555")
        self.port_edit.setMaximumWidth(80)
        form.addRow("Adresse IP du téléphone", self.ip_edit)
        form.addRow("Port", self.port_edit)
        wv.addLayout(form)
        btns = QHBoxLayout()
        self.enable_wifi_btn = QPushButton("Activer le sans-fil")
        self.connect_btn = QPushButton("Connecter sans fil")
        self.pair_btn = QPushButton("Appairer (Android 11+)…")
        self.pair_btn.setToolTip("Débogage sans fil d'Android 11+ : appairage avec un code, sans câble.")
        btns.addWidget(self.enable_wifi_btn)
        btns.addWidget(self.connect_btn)
        btns.addWidget(self.pair_btn)
        wv.addLayout(btns)
        v.addWidget(self.wifi_box)
        self.wifi_box.setVisible(False)
        root.addWidget(gphone)

    def _build_game_block(self, root: QVBoxLayout) -> QFormLayout:
        """Jeu : nom, couleur, emblème, application, taille."""
        # --- Affichage
        g = QGroupBox("Jeu")
        form = QFormLayout(g)
        form.setVerticalSpacing(10)
        aform = QFormLayout()  # affichage : rangé dans « Réglages avancés »
        aform.setVerticalSpacing(10)
        self.name_edit = QLineEdit(self.title)
        self.name_edit.setToolTip(
            "Nom de l'onglet et de la fenêtre. Astuce : préfixez-le d'un numéro (« 1 Eniripsa », « 2 Roublard ») "
            "pour changer de fenêtre avec --focus 1, --focus 2 (voir le README)."
        )
        form.addRow("Nom de la session", self.name_edit)
        swrow = QWidget()
        swl = QHBoxLayout(swrow)
        swl.setContentsMargins(0, 0, 0, 0)
        swl.setSpacing(6)
        self._swatches: dict[str, QToolButton] = {"": QToolButton()}  # plus de couleurs d'onglet : seulement les emblèmes
        self.img_btn = QPushButton("Image…")
        self.img_btn.setToolTip("Utiliser une image de ton ordinateur comme icône de l'onglet (par exemple l'emblème de ta classe)")
        self.img_btn.clicked.connect(self._pick_icon)
        self.emb_btn = QPushButton("Emblèmes")
        self.emb_btn.setToolTip("Choisir un emblème de classe pour l'onglet")
        emb_menu = QMenu(self.emb_btn)
        for n in range(1, CLASS_EMBLEMS + 1):
            act = emb_menu.addAction(QIcon(emblem_pixmap(n)), CLASS_NAMES[n - 1])
            act.triggered.connect(lambda _=False, n=n: self.set_icon(f"builtin:{n:02d}"))
        self.emb_btn.setMenu(emb_menu)
        self.img_clear = QPushButton("Retirer")
        self.img_clear.clicked.connect(lambda: self.set_icon(""))
        self.img_clear.setVisible(False)
        swl.addSpacing(8)
        swl.addWidget(self.emb_btn)
        swl.addWidget(self.img_btn)
        swl.addWidget(self.img_clear)
        swl.addStretch(1)
        form.addRow("Emblème de l'onglet", swrow)
        self.mode_combo = QComboBox()
        for key, label in MODES.items():
            self.mode_combo.addItem(label, key)
        self.mode_combo.setCurrentIndex(1)
        aform.addRow("Mode", self.mode_combo)
        self.mode_help = QLabel("")
        self.mode_help.setWordWrap(True)
        self.mode_help.setObjectName("muted")
        aform.addRow(self.mode_help)
        self.app_edit = QLineEdit(DOFUS_TOUCH_PACKAGE)
        self.app_edit.setToolTip("Nom de paquet Android de l'application à lancer (ex. com.ankama.dofustouch).")
        self.detect_btn = QPushButton("Détecter…")
        self.detect_btn.setToolTip("Cherche Dofus Touch et ses clones installés sur le téléphone.")
        app_row = QHBoxLayout()
        app_row.addWidget(self.app_edit, 1)
        app_row.addWidget(self.detect_btn)
        form.addRow("Application", app_row)
        self.shape_combo = QComboBox()
        for key, label in (
            ("auto", "Suivre la fenêtre (sans bandes noires)"),
            ("16:9", "16:9 (téléphone classique)"),
            ("2:1", "2:1 (large)"),
            ("21:9", "21:9 (très large)"),
            ("perso", "Largeur × hauteur de « Perso »"),
        ):
            self.shape_combo.addItem(label, key)
        self.shape_combo.setToolTip(
            "Forme de l'écran virtuel du jeu. « Suivre la fenêtre » prend la forme actuelle de la fenêtre au lancement ; "
            "les autres formes sont fixes (des bandes noires peuvent apparaître si la fenêtre n'a pas la même forme)."
        )
        aform.addRow("Format de la fenêtre", self.shape_combo)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(60, 200)
        self.zoom_slider.setSingleStep(5)
        self.zoom_slider.setPageStep(10)
        self.zoom_slider.setValue(100)
        self.zoom_label = QLabel("100 %")
        self.zoom_label.setMinimumWidth(52)
        self.zoom_slider.valueChanged.connect(lambda v: self.zoom_label.setText(f"{v} %"))
        self.zoom_slider.setToolTip("Plus grand = interface du jeu plus grosse (le nombre de pixels reste celui de la qualité choisie).")
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(self.zoom_slider, 1)
        zoom_row.addWidget(self.zoom_label)
        aform.addRow("Taille de l'interface du jeu", zoom_row)
        self.reopen_chk = QCheckBox("Lancer le jeu automatiquement à la connexion")
        self.reopen_chk.setChecked(True)
        form.addRow(self.reopen_chk)
        root.addWidget(g)
        return aform

    def _build_quality_block(self, root: QVBoxLayout) -> None:
        """Qualité vidéo."""
        # --- Qualité
        g = QGroupBox("Qualité")
        v = QVBoxLayout(g)
        row = QHBoxLayout()
        self.q_group = QButtonGroup(self)
        self.q_buttons: dict[str, QRadioButton] = {}
        for key in list(PRESETS) + ["perso"]:
            label = PRESETS[key][0] if key in PRESETS else "Perso"
            rb = QRadioButton(label)
            self.q_group.addButton(rb)
            self.q_buttons[key] = rb
            row.addWidget(rb)
        self.q_buttons["moyen"].setChecked(True)
        v.addLayout(row)
        self.q_summary = QLabel("")
        self.q_summary.setObjectName("muted")
        v.addWidget(self.q_summary)
        self.bw_label = QLabel("")
        self.bw_label.setObjectName("muted")
        self.bw_label.setWordWrap(True)
        v.addWidget(self.bw_label)
        self.perso_box = QWidget()
        pf = QFormLayout(self.perso_box)
        pf.setContentsMargins(0, 0, 0, 0)
        self.br_spin = QSpinBox()
        self.br_spin.setRange(1, 80)
        self.br_spin.setSuffix(" Mbit/s")
        self.br_spin.setValue(6)
        self.br_spin.setMaximumWidth(160)
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(10, 120)
        self.fps_spin.setSuffix(" ips")
        self.fps_spin.setValue(60)
        self.w_spin = QSpinBox()
        self.w_spin.setRange(480, 3840)
        self.w_spin.setValue(1920)
        self.h_spin = QSpinBox()
        self.h_spin.setRange(480, 3840)
        self.h_spin.setValue(1080)
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 960)
        self.dpi_spin.setValue(280)
        pf.addRow("Débit vidéo", self.br_spin)
        pf.addRow("Images par seconde", self.fps_spin)
        pf.addRow("Largeur", self.w_spin)
        pf.addRow("Hauteur", self.h_spin)
        pf.addRow("DPI (écran virtuel)", self.dpi_spin)
        v.addWidget(self.perso_box)
        root.addWidget(g)

    def _build_options_block(self, root: QVBoxLayout) -> None:
        """Options (son, téléphone, contrôle, session)."""
        # --- Options
        g = QGroupBox("Options")
        self.opt_screen_off = QCheckBox("Éteindre l'écran du téléphone pendant la session")
        self.opt_screen_off.setToolTip("Le contrôle continue, l'écran du téléphone reste noir.")
        self.opt_screen_off.setChecked(True)  # activé par défaut (nouvelles sessions)
        self.opt_fps = QCheckBox("Afficher la fluidité (images/s)")
        self.opt_touches = QCheckBox("Montrer les appuis sur l'écran du téléphone")
        self.opt_control = QCheckBox("Contrôle souris et clavier")
        self.opt_control.setChecked(True)
        self.opt_audio = QCheckBox("Transférer le son (Android 11+)")
        self.opt_audio.setChecked(True)
        self.opt_audio.setText("Transférer le son (Android 11+)")
        self.opt_audio.setToolTip("Seule la session affichée joue du son.")
        self.opt_gameaudio = QCheckBox("Son du jeu seulement")
        self.opt_gameaudio.setChecked(True)
        self.opt_gameaudio.setToolTip(
            "Ne transfère que le son des applications (jeu, musique) : pas les notifications ni les sons système. "
            "Demande Android 13+ ; sinon tout le son est transféré. S'applique après « Appliquer et relancer »."
        )
        self.opt_dnd = QCheckBox("Couper les notifications du téléphone")
        self.opt_dnd.setChecked(True)
        self.opt_dnd.setToolTip(
            "Active « Ne pas déranger » (prioritaire) sur le téléphone pendant la session, puis le rétablit à l'arrêt : "
            "plus de sons de notification dans le jeu ni sur le PC. Le son du jeu n'est pas touché."
        )
        self.opt_clip = QCheckBox("Synchroniser le presse-papiers")
        self.opt_clip.setChecked(True)
        self.opt_clip.setText("Synchroniser le presse-papiers")
        self.opt_clip.setToolTip("Copier/coller entre le PC et le téléphone.")
        self.opt_awake = QCheckBox("Empêcher la mise en veille du téléphone (USB)")
        self.opt_awake.setChecked(True)  # activé par défaut (nouvelles sessions)
        self.opt_poweroff = QCheckBox("Éteindre l'écran du téléphone en quittant")
        self.opt_closeapp = QCheckBox("Fermer le jeu sur le téléphone quand j'arrête ou supprime la session")
        self.opt_closeapp.setChecked(True)
        self.opt_closeapp.setToolTip("Sinon le jeu reste ouvert en arrière-plan sur le téléphone (batterie, réseau, compte connecté).\n"
                                     "Ne s'applique qu'au jeu lancé par notrefu-mirror (case « Lancer le jeu automatiquement »), "
                                     "jamais lors d'une reconnexion ou d'un redémarrage de la session.")
        self.opt_log = QCheckBox("Afficher le journal technique")
        self.opt_reconnect = QCheckBox("Reconnexion automatique")
        self.opt_reconnect.setChecked(True)
        self.opt_reconnect.setToolTip("Rétablit la session si le câble ou le Wi-Fi coupe.")
        self.opt_native = QCheckBox("Image nette (peut ralentir)")
        self.opt_native.setChecked(False)
        self.opt_native.setToolTip(
            "L'écran virtuel prend exactement la taille de la zone de jeu : aucun redimensionnement de l'image, "
            "donc un texte plus net et moins de travail pour le téléphone. Le préréglage de qualité reste le maximum."
        )
        self.opt_autofit = QCheckBox("Adapter le jeu quand je redimensionne la fenêtre")
        self.opt_autofit.setToolTip(
            "Quand tu changes la taille de la fenêtre, la session est relancée pour que l'écran du jeu "
            "reprenne la nouvelle forme (le téléphone ne sait pas redimensionner l'écran virtuel en direct)."
        )
        self._session_ratio = 0.0
        self.stall_guard = power.StallGuard()  # Wi-Fi saturé ? (voir power.py)
        self.throttle_note = ""  # « ips limités à 30 (chauffe) », rempli par la fenêtre principale
        self.health_tip = ""  # détail RAM pour l'info-bulle de la barre (phonehealth.ram_detail)
        self.health_text = ""  # « 83 % · 36,5 °C · CPU 23 % · RAM 64 % », mis à jour par la fenêtre principale
        self.play_seconds = 0  # temps de jeu cumulé de cette session (enregistré)
        self.refitting = False  # relance d'adaptation en cours : on garde la dernière image à l'écran
        self.area_size = lambda: (0, 0)  # fixé par SessionPage : taille de la zone de jeu
        self.opt_autostart = QCheckBox("Démarrer cette session à l'ouverture de notrefu-mirror")
        self.opt_autostart.setToolTip("Cette session démarre toute seule à l'ouverture de notrefu-mirror.")
        self._autostarted = False
        self.kb_combo = QComboBox()
        self.kb_combo.addItem("Standard (sdk)", "sdk")
        self.kb_combo.addItem("Clavier physique simulé (uhid)", "uhid")
        self.mod_combo = QComboBox()
        for key, label in SHORTCUT_MODS.items():
            self.mod_combo.addItem(label, key)
        self.alat_spin = QSpinBox()
        self.alat_spin.setRange(20, 500)
        self.alat_spin.setSingleStep(10)
        self.alat_spin.setSuffix(" ms")
        self.alat_spin.setValue(120)
        self.alat_spin.setMaximumWidth(160)
        self.alat_spin.setToolTip("Son qui grésille ou saccade : augmente. Son en retard sur l'image : diminue.")
        self.gamemode_combo = QComboBox()
        self.gamemode_combo.addItem("Ne pas changer", "")
        for key, label in adb.GAME_MODES.items():
            self.gamemode_combo.addItem(label, key)
        self.gamemode_combo.setToolTip(
            "Mode jeu d'Android pour Dofus Touch : « Performance » donne plus de puissance au jeu (le téléphone chauffe davantage), "
            "« Économie de batterie » en donne moins. Appliqué au lancement de la session ; sans effet si le téléphone n'a pas de mode jeu."
        )
        self.antifreeze_btn = QPushButton("Empêcher le jeu de s'endormir…")
        self.antifreeze_btn.setToolTip(
            "À utiliser seulement si la fenêtre d'un compte se fige au bout d'un moment : demande à Android de ne pas endormir le jeu. "
            "Ne change rien au jeu lui-même ni aux tours ; le téléphone consomme juste un peu plus de batterie."
        )
        self.shortcuts_btn = QPushButton("Liste des raccourcis")

        def sub(text: str) -> QLabel:
            lab = QLabel(text)
            lab.setObjectName("subhead")
            return lab

        ov = QVBoxLayout(g)
        ov.setSpacing(8)
        ov.addWidget(sub("Son"))
        ov.addWidget(self.opt_audio)
        ov.addWidget(self.opt_gameaudio)
        lat = QHBoxLayout()
        lat.addWidget(QLabel("Latence du son"))
        lat.addWidget(self.alat_spin)
        lat.addStretch(1)
        ov.addLayout(lat)
        ov.addSpacing(6)
        ov.addWidget(sub("Téléphone"))
        for w in (self.opt_dnd, self.opt_screen_off, self.opt_awake, self.opt_poweroff, self.opt_closeapp):
            ov.addWidget(w)
        ov.addSpacing(6)
        ov.addWidget(sub("Contrôle"))
        for w in (self.opt_control, self.opt_clip):
            ov.addWidget(w)
        ov.addSpacing(6)
        ov.addWidget(sub("Session"))
        for w in (self.opt_reconnect, self.opt_autostart, self.opt_autofit):
            ov.addWidget(w)
        root.addWidget(g)

    def _build_advanced_block(self, root: QVBoxLayout, aform: QFormLayout) -> None:
        """Réglages avancés repliés."""
        # --- Réglages avancés (repliés par défaut)
        self.adv_btn = QToolButton()
        self.adv_btn.setObjectName("disclosure")
        self.adv_btn.setText("Réglages avancés")
        self.adv_btn.setCheckable(True)
        self.adv_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.adv_btn.setArrowType(Qt.ArrowType.RightArrow)
        self.adv_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        root.addWidget(self.adv_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.adv_box = QGroupBox("Réglages avancés")
        self.adv_box.setVisible(False)
        av = QVBoxLayout(self.adv_box)
        av.setSpacing(8)
        aform.addRow("Priorité au jeu (Android)", self.gamemode_combo)
        av.addLayout(aform)
        for w in (self.opt_native, self.opt_fps, self.opt_touches, self.opt_log):
            av.addWidget(w)
        av.addSpacing(4)
        av.addWidget(self.antifreeze_btn)
        av.addWidget(self.shortcuts_btn)
        root.addWidget(self.adv_box)
        root.addStretch(1)

        def toggle_adv(on: bool) -> None:
            self.adv_box.setVisible(on)
            self.adv_btn.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)

        self.adv_btn.toggled.connect(toggle_adv)

    def _build_actions_block(self, root: QVBoxLayout) -> None:
        """Actions, état et journal."""
        # --- Actions + journal
        bar = QHBoxLayout()
        self.start_btn = QPushButton("Lancer le mirroring")
        self.start_btn.setObjectName("primary")
        self.start_btn.setMinimumHeight(42)
        self.start_btn.setDefault(True)
        self.stop_btn = QPushButton("Arrêter")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setMinimumHeight(42)
        self.back_btn = QPushButton("Retour au jeu")
        self.back_btn.setMinimumHeight(42)
        self.back_btn.setVisible(False)
        self.restart_btn = QPushButton("Appliquer et relancer")
        self.restart_btn.setMinimumHeight(42)
        self.restart_btn.setToolTip("Qualité, écran, options : les changements ne comptent qu'au prochain lancement.")
        self.restart_btn.setVisible(False)
        self.fps_label = QLabel("")
        bar.addWidget(self.fps_label)
        bar.addStretch(1)
        bar.addWidget(self.back_btn)
        bar.addWidget(self.restart_btn)
        bar.addWidget(self.stop_btn)
        bar.addWidget(self.start_btn)  # action principale : en bas à droite
        self.start_btn.setMinimumWidth(220)
        self.stop_btn.setMinimumWidth(140)
        for btn, name, col in (
            (self.start_btn, "play", "on_accent"), (self.stop_btn, "stop", "danger_text"),
            (self.back_btn, "arrow-left", "text"), (self.refresh_btn, "reload", "text"),
            (self.detect_btn, "search", "text"), (self.restart_btn, "reload", "text"),
        ):
            theme.bind_icon(btn, name, col)
            btn.setIconSize(QSize(18, 18))
        self._apply_effects()
        theme.signals.changed.connect(self._apply_effects)
        self.hint_label = QLabel("")
        self.hint_label.setWordWrap(True)
        self.hint_label.setObjectName("hint")
        self.live_label = QLabel("")
        self.live_label.setObjectName("muted")
        self.live_label.setVisible(False)
        # Barre d'actions toujours visible en bas de la page de réglages (SessionPage la place hors du défilement)
        self.action_bar = QWidget()
        self.action_bar.setObjectName("actionbar")
        al = QVBoxLayout(self.action_bar)
        al.setContentsMargins(24, 10, 24, 14)
        al.setSpacing(8)
        al.addWidget(self.live_label)
        al.addWidget(self.hint_label)
        al.addLayout(bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setMaximumHeight(140)
        self.log.setVisible(False)
        root.addWidget(self.log)

    def _wire(self) -> None:
        self.refresh_btn.clicked.connect(lambda: self.message.emit("refresh"))
        self.rb_usb.toggled.connect(lambda on: self.wifi_box.setVisible(not on))
        self.rb_usb.toggled.connect(lambda on: self.usb_help.setVisible(on))
        self.dev_combo.currentIndexChanged.connect(self._on_device_changed)
        self.mode_combo.currentIndexChanged.connect(self._refresh_mode_ui)
        for rb in self.q_buttons.values():
            rb.toggled.connect(self._refresh_quality_ui)
            rb.toggled.connect(lambda *_: self._check_sdk_hint())
        self.br_spin.valueChanged.connect(lambda *_: self._check_sdk_hint())
        self.opt_log.toggled.connect(self.log.setVisible)
        self.name_edit.textChanged.connect(self._on_name_changed)
        self.detect_btn.clicked.connect(self._detect_apps)
        self.start_btn.clicked.connect(self.start)
        self.stop_btn.clicked.connect(self.stop)
        self.back_btn.clicked.connect(self.show_game.emit)
        self.restart_btn.clicked.connect(self.restart)
        self.enable_wifi_btn.clicked.connect(self._enable_wireless)
        self.connect_btn.clicked.connect(self._connect_wireless)
        self.pair_btn.clicked.connect(self._pair)
        self.shortcuts_btn.clicked.connect(lambda: ShortcutsDialog(self).exec())
        self.antifreeze_btn.clicked.connect(self.run_anti_freeze)

    # ---- état de l'UI --------------------------------------------------
    @property
    def serial(self) -> str:
        return self.dev_combo.currentData() or ""

    def run_anti_freeze(self) -> None:
        spec = self.app_edit.text().strip()
        if not self.serial or not spec or not valid_package(spec):
            QMessageBox.information(self, APP_NAME, "Choisis d'abord un téléphone et l'application du jeu.")
            return
        ask = QMessageBox.question(
            self, APP_NAME,
            f"Demander à Android de ne pas endormir « {spec} » quand sa fenêtre est en arrière-plan ?\n\n"
            "C'est réversible (réglage de batterie de l'application sur le téléphone) et ne change rien aux tours de jeu.")
        if ask != QMessageBox.StandardButton.Yes:
            return
        serial = self.serial
        self.runner.run(lambda: adb.anti_freeze(serial, spec), lambda res, err: self._anti_freeze_done(serial, spec, res, err))

    def _anti_freeze_done(self, serial: str, spec: str, res, err) -> None:
        if err is not None or res is None:
            QMessageBox.warning(self, APP_NAME, f"Échec : {err}")
            return
        lines = [f"{'✔' if ok else '✘'} {title}" + ("" if ok else f" : {msg[:120]}") for title, ok, msg in res]
        extra = ("\n\nSur Xiaomi / HyperOS, ouvre aussi la page de l'application et règle « Économiseur de batterie » sur « Aucune restriction » "
                 "et active « Démarrage automatique ». Ouvrir cette page sur le téléphone maintenant ?")
        r = QMessageBox.question(self, APP_NAME, "\n".join(lines) + extra)
        if r == QMessageBox.StandardButton.Yes:
            def opened(_res, exc) -> None:
                if exc is not None:
                    QMessageBox.warning(self, APP_NAME, f"Impossible d'ouvrir la page : {exc}")

            self.runner.run(lambda: adb.open_battery_settings(serial, spec), opened)  # hors du fil de l'interface

    def apply_quality(self, key: str) -> None:
        """Raccourcis « Qualité 1 à 4 » : change le préréglage et relance la session si elle tourne."""
        if key not in self.q_buttons or key not in PRESETS:
            return
        self.q_buttons[key].setChecked(True)
        label = PRESETS[key][0]
        if self.running:
            self.message.emit(f"{self.title} : qualité {label}, relance de la session…")
            self.restart()
        else:
            self.message.emit(f"{self.title} : qualité {label} (appliquée au prochain lancement).")

    def bitrate_mbit(self) -> int:
        """Débit vidéo maximal de cette session (préréglage choisi ou valeur « Perso »)."""
        k = self._quality_key()
        return PRESETS[k][1] if k in PRESETS else self.br_spin.value()

    @property
    def running(self) -> bool:
        return self.reconnecting or (self.client is not None and self.client.state in ("starting", "running"))

    @property
    def reconnecting(self) -> bool:
        return self._retry_timer.isActive()

    def _quality_key(self) -> str:
        for key, rb in self.q_buttons.items():
            if rb.isChecked():
                return key
        return "moyen"

    def _refresh_quality_ui(self) -> None:
        key = self._quality_key()
        perso = key == "perso"
        self.perso_box.setVisible(perso)
        if perso:
            self.q_summary.setText("Réglages personnalisés.")
        else:
            self.q_summary.setText(f"{PRESETS[key][0]} — {preset_summary(key)}")
            _, mbps, fps, w, h, dpi = PRESETS[key]
            for spin, val in ((self.br_spin, mbps), (self.fps_spin, fps), (self.w_spin, w), (self.h_spin, h), (self.dpi_spin, dpi)):
                spin.setValue(val)

    def _refresh_mode_ui(self) -> None:
        horizontal = self.mode_combo.currentData() == "horizontal"
        if horizontal:
            self.mode_help.setText(
                "Un écran virtuel horizontal est créé : le jeu s'y ouvre sans toucher à l'écran du téléphone "
                "(Android 10+, idéal Android 11+)."
            )
        else:
            self.mode_help.setText("L'écran du téléphone, tel quel.")
        self.dpi_spin.setEnabled(horizontal)
        self.shape_combo.setEnabled(horizontal)
        self.zoom_slider.setEnabled(horizontal)
        self._check_sdk_hint()

    def _set_brand_tip(self, tip: str) -> None:
        self._brand_tip = tip
        self.brand_label.setText(tip)
        self.brand_label.setVisible(bool(tip))

    def _check_sdk_hint(self) -> None:
        if self.mode_combo.currentData() == "horizontal" and 0 < self._info_sdk < 29:
            self.hint_label.setText("Ce téléphone est sous Android 9 ou moins : l'écran virtuel n'est pas disponible, utilisez le mode Standard.")
        elif not self.running and self._is_wifi_selected() and self.br_spin.value() >= 12:
            self.hint_label.setText("En sans fil, l'USB est conseillé à partir de la qualité « Haut » : si ça saccade, baissez le débit.")
        elif not self.running:
            self.hint_label.setText("")

    def _update_buttons(self) -> None:
        run = self.running
        usable = any(d.serial == self.serial and d.state == "device" for d in self._devices)
        self.start_btn.setEnabled(not run and usable)
        self.start_btn.setVisible(not run)  # un seul bouton principal à la fois : Lancer ou Arrêter
        self.stop_btn.setVisible(run)
        self.stop_btn.setEnabled(run)
        self.back_btn.setVisible(run and self.embed)
        self.restart_btn.setVisible(run)
        if not run:
            self.live_label.setVisible(False)
        for w in (self.dev_combo, self.mode_combo, self.app_edit):
            w.setEnabled(not run)
        self.detect_btn.setEnabled(usable and not run)
        self.enable_wifi_btn.setEnabled(usable and not self._is_wifi_selected())

    def _is_wifi_selected(self) -> bool:
        return any(d.serial == self.serial and d.wireless for d in self._devices)

    # ---- liste des téléphones -----------------------------------------
    def _refresh_banner(self) -> None:
        text = devices_banner([d.state for d in self._devices], self.adb_error, sys.platform)
        self.banner.setText(text)
        self.banner.setVisible(bool(text))
        self.diag_btn.setVisible(bool(text))

    def set_devices(self, devices: list[adb.Device]) -> None:
        if devices == self._devices and self.dev_combo.count() > 0:
            self._refresh_banner()
            return
        current = self.serial or self._wanted_serial
        self._devices = devices
        if self._device_state() == "device":
            was_waiting = self._policy.not_ready > 0
            self._policy.device_ready()  # prêt : le délai progressif repart de zéro
            if was_waiting and self._retry_timer.isActive() and self._retry_timer.remainingTime() > 1500:
                self._retry_timer.start(1000)  # il était en veille profonde et vient de se réveiller : on n'attend pas la fin du délai
        self.dev_combo.blockSignals(True)
        self.dev_combo.clear()
        if not devices:
            self.dev_combo.addItem("Aucun téléphone détecté", "")
        for d in devices:
            self.dev_combo.addItem(d.label, d.serial)
        idx = self.dev_combo.findData(current)
        self.dev_combo.setCurrentIndex(max(idx, 0))
        self.dev_combo.blockSignals(False)
        self._wanted_serial = ""
        self._on_device_changed()
        self._explain_device_state()
        self._refresh_banner()

    def _explain_device_state(self) -> None:
        d = next((d for d in self._devices if d.serial == self.serial), None)
        if d is None or self.running:
            return
        hint = device_state_hint(d.state)
        if hint:
            self.hint_label.setText(hint)
        else:
            self._check_sdk_hint()

    def select_serial(self, serial: str) -> None:
        self._wanted_serial = serial
        idx = self.dev_combo.findData(serial)
        if idx >= 0:
            self.dev_combo.setCurrentIndex(idx)

    def _on_device_changed(self) -> None:
        self._update_buttons()
        serial = self.serial
        d = next((d for d in self._devices if d.serial == serial), None)
        if not serial or d is None or d.state != "device":
            self.info_label.setText("")
            self._set_brand_tip("")
            self._info_sdk = 0
            return

        def work():
            info = adb.device_info(serial)
            return info

        def done(res, err):
            if err or serial != self.serial:
                return
            info = res
            try:
                self._info_sdk = int(info.get("sdk") or 0)
            except ValueError:
                self._info_sdk = 0
            self.info_label.setText(f"{info.get('model', '')} · Android {info.get('android', '?')} (SDK {self._info_sdk or '?'})")
            self._set_brand_tip(compat.brand_tip(info.get("manufacturer", ""), info.get("model", ""), sys.platform))
            self._check_sdk_hint()

        self.runner.run(work, done)

    # ---- connexion sans fil -------------------------------------------
    def _port(self) -> int | None:
        return parse_port(self.port_edit.text())

    def _enable_wireless(self) -> None:
        serial, port = self.serial, self._port()
        if not serial or port is None:
            QMessageBox.warning(self, APP_NAME, "Sélectionnez un téléphone USB et un port valide.")
            return
        self.enable_wifi_btn.setEnabled(False)
        self.message.emit("Activation du sans-fil…")

        def work():
            ip = adb.wifi_ip(serial)
            out = adb.enable_tcpip(serial, port)
            return ip, out

        def done(res, err):
            self._update_buttons()
            if err:
                self.message.emit("Échec : " + str(err))
                QMessageBox.warning(self, APP_NAME, f"Impossible d'activer le sans-fil :\n{err}")
                return
            ip, out = res
            if ip:
                self.ip_edit.setText(ip)
                self.message.emit(f"Sans-fil activé sur {ip}:{port}. Vous pouvez débrancher le câble puis cliquer « Connecter sans fil ».")
            else:
                self.message.emit("Sans-fil activé, mais l'adresse IP n'a pas été trouvée : saisissez-la à la main.")

        self.runner.run(work, done)

    def _connect_wireless(self) -> None:
        ip, port = self.ip_edit.text().strip(), self._port()
        if not valid_ip(ip) or port is None:
            QMessageBox.warning(self, APP_NAME, "Adresse IP ou port invalide.")
            return
        self.connect_btn.setEnabled(False)
        self.message.emit(f"Connexion à {ip}:{port}…")

        def done(res, err):
            self.connect_btn.setEnabled(True)
            if err:
                self.message.emit("Échec de la connexion sans fil.")
                QMessageBox.warning(
                    self, APP_NAME,
                    f"Connexion impossible :\n{err}\n\nVérifiez que le PC et le téléphone sont sur le même Wi-Fi "
                    "et que « Activer le sans-fil » a été fait en USB depuis le dernier redémarrage du téléphone.",
                )
                return
            self.message.emit(str(res))
            self._wanted_serial = f"{ip}:{port}"
            self.message.emit("refresh")

        self.runner.run(lambda: adb.connect(ip, port), done)

    def _pair(self) -> None:
        addr, ok = QInputDialog.getText(
            self, "Appairer",
            "Sur le téléphone : Options pour les développeurs → Débogage sans fil → « Associer avec un code ».\n"
            "Saisissez l'adresse IP:port affichée :",
        )
        if not ok or not addr.strip():
            return
        code, ok = QInputDialog.getText(self, "Appairer", "Code d'association à 6 chiffres :")
        if not ok or not code.strip():
            return

        def done(res, err):
            if err:
                QMessageBox.warning(self, APP_NAME, f"Appairage échoué :\n{err}")
            else:
                ip = pair_ip(addr)
                self.ip_edit.setText(ip)
                QMessageBox.information(
                    self, APP_NAME,
                    "Appairage réussi. Saisissez maintenant le port affiché sur l'écran principal "
                    "« Débogage sans fil » (différent de celui de l'appairage), puis « Connecter sans fil ».",
                )

        self.runner.run(lambda: adb.pair(addr.strip(), code.strip()), done)

    # ---- scrcpy --------------------------------------------------------
    def set_volume(self, v: int) -> None:
        self.volume = max(0, min(100, int(v)))
        self.volume_changed.emit(self.volume)

    def _pick_icon(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choisir une image", str(Path.home()), "Images (*.png *.jpg *.jpeg *.svg *.webp)")
        if path:
            self.set_icon(path)

    def set_icon(self, path: str) -> None:
        self.icon_path = path if path and (path.startswith("builtin:") or Path(path).is_file()) else ""
        self.img_clear.setVisible(bool(self.icon_path))
        self.color_changed.emit(self.color)

    def set_color(self, col: str) -> None:
        self.color = col if col in self._swatches else ""
        for c, b in self._swatches.items():
            b.setChecked(c == self.color)
        self.color_changed.emit(self.color)

    def _on_name_changed(self, text: str) -> None:
        self.title = text.strip() or "Session"
        self.title_changed.emit(self.title)

    def _detect_apps(self) -> None:
        serial = self.serial
        if not serial:
            return
        self.detect_btn.setEnabled(False)
        self.message.emit("Recherche des applications Dofus Touch…")

        def done(apps, err):
            self._update_buttons()
            if err:
                QMessageBox.warning(self, APP_NAME, f"Lecture des applications impossible :\n{err}")
                return
            if not apps:
                QMessageBox.information(self, APP_NAME, "Aucune application trouvée sur ce téléphone.")
                return
            dlg = AppPickerDialog(self.runner, serial, apps, self)
            if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.package():
                return
            choice = dlg.package()
            self.app_edit.setText(choice)
            self.message.emit(f"Application : {choice}")

        self.runner.run(lambda: adb.list_apps(serial), done)

    def collect_settings(self) -> Settings:
        key = self._quality_key()
        s = Settings(serial=self.serial, mode=self.mode_combo.currentData(), quality=key)
        s.bitrate_mbps = self.br_spin.value()
        s.fps = self.fps_spin.value()
        s.width, s.height, s.dpi = self.w_spin.value(), self.h_spin.value(), self.dpi_spin.value()
        s.screen_off = self.opt_screen_off.isChecked()
        s.show_fps = self.opt_fps.isChecked()
        s.show_touches = self.opt_touches.isChecked()
        s.control = self.opt_control.isChecked()
        s.audio = self.opt_audio.isChecked()
        s.clipboard = self.opt_clip.isChecked()
        s.stay_awake = self.opt_awake.isChecked()
        s.power_off_on_close = self.opt_poweroff.isChecked()
        s.reopen_app = self.reopen_chk.isChecked()
        s.app_package = self.app_edit.text().strip()
        s.keyboard = self.kb_combo.currentData()
        s.shortcut_mod = self.mod_combo.currentData()
        s.title = WINDOW_PREFIX + self.title
        return s

    def start(self, auto: bool = False) -> None:
        if self.running:
            return
        s = self.collect_settings()
        if auto:
            s.serial = self._last_serial  # le téléphone peut avoir disparu de la liste pendant la coupure
        else:
            self._policy.reset()
            if not s.serial and self._wanted_serial:
                s.serial = self._wanted_serial  # liste pas encore remplie (session créée à l'instant) : le téléphone enregistré fait foi
        if not s.serial:
            QMessageBox.warning(self, APP_NAME, "Aucun téléphone sélectionné.")
            return
        if s.reopen_app and s.app_package and not valid_package(s.app_package):
            QMessageBox.warning(self, APP_NAME, "Nom de paquet invalide (ex. com.ankama.dofustouch).")
            return
        adb_path, server = adb.find_tool("adb"), adb.server_path()
        if not adb_path or not server:
            QMessageBox.critical(self, APP_NAME, "adb ou scrcpy-server est introuvable (ni dans l'application ni sur le PC).")
            return
        aw, ah = self.area_size()
        plan = plan_display(DisplayRequest(
            mode=s.mode, width=s.width, height=s.height, dpi=s.dpi, shape=self.shape_combo.currentData(),
            area_w=aw, area_h=ah, native=self.opt_native.isChecked(), pixel_ratio=self.devicePixelRatioF(),
            zoom_percent=self.zoom_slider.value(),
        ))
        self._session_ratio = plan.ratio or 0.0
        new_display, max_size = plan.new_display, plan.max_size
        params = build_client_params(
            s, max_size=max_size, new_display=new_display, audio_latency_ms=self.alat_spin.value(),
            game_audio=self.opt_gameaudio.isChecked(), quiet_notifications=self.opt_dnd.isChecked(),
            game_mode=str(self.gamemode_combo.currentData() or ""),
        )
        self._last_serial = s.serial
        if not auto:
            self._record_wm_baseline(s.serial)
            self._log_text = ""
            self.log.clear()
            self.hint_label.setText("")
        self._control = s.control
        view = self.view
        self._gen += 1
        gen = self._gen
        client = ScrcpyClient(
            params, AdbTransport(adb_path, server, adb.tool_env()),
            on_state=lambda st, d, g=gen: _emit_safe(self._bridge.state, st, d) if g == self._gen else None,
            on_log=lambda line, g=gen: _emit_safe(self._bridge.log, line) if g == self._gen else None,
            on_frame=lambda: _emit_safe(view.notify_frame) if view else None,
            wants_frames=lambda: bool(view and view.isVisible()),
            on_clipboard=lambda text: _emit_safe(self._bridge.clipboard, text),
            wants_audio=lambda: bool(view and view.isVisible() and view.audio_on),
            audio_gain=lambda: self.volume,
            env=adb.tool_env(),
        )
        self.client = client
        self.live_label.setText(
            f"Session en cours avec : {new_display or 'écran du téléphone'} · {int(s.bitrate_mbps)} Mbit/s · {int(s.fps)} ips"
            + (f" · plafond {max_size} px" if max_size else "")
            + ". Les changements de réglages s'appliquent après « Appliquer et relancer »."
        )
        self.live_label.setVisible(True)
        if view:
            view.attach(client, s.control, s.clipboard, keep_image=self.refitting)
            view.set_message("Connexion au téléphone…")
        self.fps_label.setText("")
        self._fps_mark = (time.monotonic(), 0)
        if auto:
            self._append(f"[reconnexion] tentative {self._policy.attempts}/{MAX_ATTEMPTS} : nettoyage, vérification de l'appareil, relance du serveur…")
        client.start()
        self._attempt_timer.start(ATTEMPT_TIMEOUT_S * 1000)
        self._update_buttons()
        self.message.emit(f"{self.title} : mirroring en cours…")
        self.refitting = False
        self.started.emit(client)

    def _release_inputs(self) -> None:
        if self.view:
            self.view.translator.release_all()  # aucun doigt/touche ne reste enfoncé quand la session s'arrête

    def stop(self) -> None:
        self._restart_pending = False  # annule un redémarrage en attente
        self._policy.device_ready()
        self._release_inputs()
        self._ask_close_app()
        self._stop_session()

    def _ask_close_app(self) -> None:
        """Arrêt voulu (bouton Arrêter, onglet supprimé, fermeture de l'application) : le jeu sera fermé sur le téléphone."""
        if self.client:
            self.client.close_app_on_stop = self.opt_closeapp.isChecked() and self.reopen_chk.isChecked()

    def _stop_session(self) -> None:
        self._policy.user_stop = True
        self._attempt_timer.stop()
        if self.reconnecting:
            self._retry_timer.stop()
            self._finish_session()
        elif self.running and self.client:
            self.client.stop(wait=0)  # le fil du client nettoie (serveur, tunnel) en arrière-plan

    def _record_wm_baseline(self, serial: str) -> None:
        """Mémorise la résolution/densité du téléphone avant la session, pour pouvoir les restaurer."""
        self._wm_baseline = None

        def done(res, err):
            if not err and res is not None and self.running:
                self._wm_baseline = res

        self.runner.run(lambda: adb.wm_overrides(serial), done)

    def _restore_wm_if_changed(self) -> None:
        """Filet de sécurité : si la résolution du téléphone a changé pendant la session sans que
        tu l'aies demandé (boutons Appliquer/Réinitialiser), on remet l'état d'avant."""
        base, serial = self._wm_baseline, self._last_serial
        self._wm_baseline = None
        if base is None or not serial:
            return

        def work():
            fix = wm_fix(base, adb.wm_overrides(serial))
            if fix.fix_size:
                adb.set_size(serial, fix.size)
            if fix.fix_density:
                adb.set_density(serial, fix.density)
            return bool(fix)

        def done(restored, err):
            if restored:
                self._append("[résolution/densité du téléphone restaurées à leur état d'avant la session]")
                self.message.emit(f"{self.title} : résolution du téléphone restaurée.")

        self.runner.run(work, done)

    def _finish_session(self) -> None:
        self._restore_wm_if_changed()
        self._append("[session terminée]")
        self.fps_label.setText("")
        self.stats.emit("")
        self._update_buttons()
        self.message.emit(f"{self.title} : arrêté.")
        self.ended.emit()

    def _device_state(self) -> str | None:
        """État adb du téléphone de cette session d'après la dernière liste (None = absent de la liste)."""
        serial = self._last_serial or self.serial
        for d in self._devices:
            if d.serial == serial:
                return d.state
        return None

    def _schedule_retry(self, detail: str) -> bool:
        """Connexion perdue après une session réussie : on réessaie toutes les quelques secondes."""
        retry = self._policy.next_retry(self.opt_reconnect.isChecked(), self._device_state())
        if retry is None:
            if self._policy.gave_up:
                self._append(f"[reconnexion abandonnée après {MAX_ATTEMPTS} essais]")
            return False
        delay = retry.delay_s
        msg = f"Connexion perdue ({detail}). Nouvelle tentative {retry.attempt} dans {delay} s…"
        self._append(f"[reconnexion] échec : {failure_reason(detail)} — {detail}")
        self._append(f"[{msg}]")
        self.hint_label.setText(msg)
        if self.view:
            self.view.attach(None)
            self.view.set_message(msg)
        self.message.emit(f"{self.title} : connexion perdue, reconnexion…")
        self._retry_timer.start(delay * 1000)
        return True  # la remise en état (adb disconnect/connect en Wi-Fi) est faite par la tentative elle-même (AdbTransport.preflight)

    def _attempt_timed_out(self) -> None:
        c = self.client
        if not c or c.state != "starting":
            return
        detail = f"délai dépassé : la tentative n'a pas abouti en {ATTEMPT_TIMEOUT_S} s"
        c.abandon()
        self._on_state("error", detail)

    def _on_state(self, state: str, detail: str) -> None:
        if state != "starting":
            self._attempt_timer.stop()
        self.state_changed.emit(state, detail)
        if state == "running":
            if self.view:
                self.view.set_message("Réception de l'image…")
            self.message.emit(f"{self.title} : connecté ({detail}).")
            self._policy.connected()
            notes = " · ".join(self.client.auto_notes) if self.client else ""
            self.hint_label.setText(notes)  # infos discrètes : audio désactivé (Android < 11), repli vidéo automatique
            if notes:
                self.message.emit(f"{self.title} : {notes}")
        elif state in ("stopped", "error"):
            if state == "error":
                self._append(f"[erreur] {detail}")
                if self._schedule_retry(detail):
                    self._update_buttons()
                    return
                self.hint_label.setText(explain_failure(self._log_text) or detail)
                self.opt_log.setChecked(True)
                if self.view:
                    self.view.set_message(detail)
            self._finish_session()

    def _append(self, text: str) -> None:
        if not text:
            return
        self._log_text += text + "\n"
        self._log_text = self._log_text[-20000:]
        self.log.appendPlainText(text)
        if self._brand_tip and self.running and ("INJECT_EVENTS" in text or "SecurityException" in text):
            self.hint_label.setText("Le téléphone refuse les clics. " + self._brand_tip)

    def _clip_from_phone(self, text: str) -> None:
        cb = QGuiApplication.clipboard()
        if text and text != cb.text():
            self._clip_last = text  # évite de renvoyer au téléphone ce qu'il vient de nous donner
            cb.setText(text)

    def _clip_to_phone(self) -> None:
        """Le presse-papiers du PC a changé : on le copie sur le téléphone (session affichée uniquement)."""
        c = self.client
        if not (c and c.running and self.opt_clip.isChecked() and self._control and self.view and self.view.isVisible()):
            return
        text = QGuiApplication.clipboard().text()
        if text and text != self._clip_last:
            self._clip_last = text
            c.send(P.set_clipboard(text))

    def fit_drift(self) -> bool:
        """Vrai si la zone de jeu n'a plus la forme de l'écran virtuel de la session en cours (écart > 8 %)."""
        if not (self.running and self._session_ratio and self.mode_combo.currentData() == "horizontal"
                and self.shape_combo.currentData() == "auto"):
            return False
        aw, ah = self.area_size()
        if aw < 300 or ah < 200:
            return False
        cur = min(max(aw / ah, 1.33), 2.4)
        return abs(cur - self._session_ratio) / self._session_ratio > 0.08

    def restart(self) -> None:
        """Arrête la session puis la relance avec les réglages actuels."""
        if self._restart_pending:
            return
        if not self.running:
            self.start()
            return
        self._restart_pending = True
        self._stop_session()
        tries = {"n": 0}

        def again() -> None:
            if not self._restart_pending:  # l'utilisateur a cliqué sur Arrêter entre-temps : on ne relance pas
                return
            tries["n"] += 1
            if not self.running:
                self._restart_pending = False
                self.start()
            elif tries["n"] < 30:
                QTimer.singleShot(300, again)
            else:
                self._restart_pending = False  # l'ancienne session ne s'arrête pas : on abandonne proprement

        QTimer.singleShot(400, again)

    def tick_stats(self) -> None:
        """Appelé chaque seconde : images par seconde réellement décodées."""
        c = self.client
        if not c or not c.running:
            return
        self.play_seconds += 1
        now, prev = time.monotonic(), self._fps_mark
        fps = (c.decoded_frames - prev[1]) / max(now - prev[0], 0.001)
        rx_prev = getattr(self, "_rx_mark", (now, 0))
        mbps = (c.rx_bytes - rx_prev[1]) * 8 / max(now - rx_prev[0], 0.001) / 1e6
        self._rx_mark = (now, c.rx_bytes)
        self._fps_mark = (now, c.decoded_frames)
        txt = f"{fps:.0f} ips · {mbps:.1f} Mbit/s reçus · décodage {c.decode_ms:.0f} ms"
        self.fps_label.setText(txt)
        self.stats.emit(stats_text(txt, c.audio_state, self.health_text, self.opt_fps.isChecked(), self.opt_audio.isChecked(),
                                   self.throttle_note))

    def shutdown(self) -> None:
        """Demande l'arrêt sans bloquer l'interface : le fil du client termine le nettoyage (serveur, tunnel) seul.
        À la fermeture de l'application, `MainWindow.closeEvent` attend ensuite toutes les sessions en parallèle."""
        self._policy.user_stop = True
        self._retry_timer.stop()
        self._release_inputs()
        self._attempt_timer.stop()  # aucun minuteur ne doit survivre à la fermeture de l'onglet
        self._gen += 1  # les rappels tardifs d'une ancienne tentative sont ignorés
        self._ask_close_app()
        if self.client:
            self.client.stop(wait=0)

    # ---- persistance ---------------------------------------------------
    def to_config(self) -> SessionConfig:
        """Lit les widgets une seule fois et renvoie les réglages sous forme de données."""
        return SessionConfig(
            mode=self.mode_combo.currentData(), shape=self.shape_combo.currentData(), zoom=self.zoom_slider.value(),
            quality=self._quality_key(),
            spins={n: sp.value() for n, sp in (("br", self.br_spin), ("fps", self.fps_spin), ("w", self.w_spin),
                                               ("h", self.h_spin), ("dpi", self.dpi_spin), ("alat", self.alat_spin))},
            checks={n: c.isChecked() for n, c in self._checks().items()},
            app=self.app_edit.text(), playtime=int(self.play_seconds), gamemode=self.gamemode_combo.currentData(),
            name=self.title, ip=self.ip_edit.text(), port=self.port_edit.text(),
            kb=self.kb_combo.currentData(), mod=self.mod_combo.currentData(), serial=self.serial, color=self.color,
            icon=self.icon_path, volume=self.volume, was_running=self.running,
            keymap=self.keymap.to_json() if len(self.keymap) else "",
        )

    def apply_config(self, cfg: SessionConfig) -> None:
        """Pousse des réglages dans les widgets (les valeurs absentes laissent le widget tel quel)."""
        def setcombo(combo: QComboBox, value) -> None:
            i = combo.findData(value)
            if i >= 0:
                combo.setCurrentIndex(i)

        self.play_seconds = cfg.playtime
        setcombo(self.mode_combo, cfg.mode)
        setcombo(self.gamemode_combo, cfg.gamemode)
        setcombo(self.shape_combo, cfg.shape)
        if cfg.zoom is not None:
            self.zoom_slider.setValue(cfg.zoom)
        setcombo(self.kb_combo, cfg.kb)
        setcombo(self.mod_combo, cfg.mod)
        if cfg.quality in self.q_buttons:
            self.q_buttons[cfg.quality].setChecked(True)
        if cfg.quality == "perso":
            for name, spin in (("br", self.br_spin), ("fps", self.fps_spin), ("w", self.w_spin), ("h", self.h_spin), ("dpi", self.dpi_spin)):
                if name in cfg.spins:
                    spin.setValue(cfg.spins[name])
        for name, chk in self._checks().items():
            if name in cfg.checks:
                chk.setChecked(cfg.checks[name])
        self.app_edit.setText(cfg.app)
        if cfg.name:
            self.name_edit.setText(cfg.name)
        self.ip_edit.setText(cfg.ip)
        self.port_edit.setText(cfg.port)
        self._wanted_serial = cfg.serial
        self.set_color(cfg.color)
        self.set_icon(cfg.icon)
        self.set_volume(cfg.volume)
        self.was_running = cfg.was_running
        self.keymap.load_json(cfg.keymap)  # sur place : la vue de jeu partage ce même objet
        self.keymap_changed.emit()

    def save(self, qs: QSettings, prefix: str) -> None:
        self.to_config().save(qs, prefix)

    def load(self, qs: QSettings, prefix: str) -> None:
        self.apply_config(SessionConfig.load(qs, prefix, tuple(self._checks()), CLASS_EMBLEMS))

    def copy_from(self, other: "PhonePanel", qs: QSettings) -> None:
        """Reprend les réglages d'une autre session (qualité, options…), en gardant son propre nom."""
        own = self.title
        other.save(qs, "_copy")
        self.load(qs, "_copy")
        qs.remove("_copy")
        self.name_edit.setText(own)
        self.set_color("")
        self.set_icon("")
        self.was_running = False

    def _checks(self) -> dict[str, QCheckBox]:
        return {
            "screen_off": self.opt_screen_off, "fps": self.opt_fps, "touches": self.opt_touches,
            "control": self.opt_control, "audio": self.opt_audio, "gameaudio": self.opt_gameaudio, "dnd": self.opt_dnd, "clip": self.opt_clip,
            "awake": self.opt_awake, "poweroff": self.opt_poweroff, "closeapp": self.opt_closeapp, "log": self.opt_log,
            "reopen": self.reopen_chk, "reconnect": self.opt_reconnect, "autostart": self.opt_autostart,
            "autofit": self.opt_autofit,
            "native2": self.opt_native,
        }
