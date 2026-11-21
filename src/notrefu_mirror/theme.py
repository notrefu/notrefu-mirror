"""Thème de notrefu-mirror : palette, feuille de style (QSS), icônes SVG et ombres portées.

Direction : outil de jeu sombre, zinc + violet. Tout est vectoriel :
- les icônes sont des SVG générés à la volée dans la couleur du thème (nets à toute taille et à tout DPI) ;
- aucune image bitmap n'est utilisée dans l'interface ;
- les ombres sont de vrais QGraphicsDropShadowEffect (jamais posés sur la vidéo : les performances du flux restent intactes).
"""
from __future__ import annotations

import os
import tempfile
import weakref
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget


def _mix(a: str, b: str, t: float) -> str:
    ca, cb = QColor(a), QColor(b)
    return QColor(
        round(ca.red() + (cb.red() - ca.red()) * t),
        round(ca.green() + (cb.green() - ca.green()) * t),
        round(ca.blue() + (cb.blue() - ca.blue()) * t),
    ).name()


# nom -> (libellé, fond, panneaux, boutons, texte, texte atténué, accent, texte sur accent, avertissement)
THEMES = {
    "zinc": ("Zinc violet (défaut)", "#18181B", "#27272A", "#3F3F46", "#FAFAFA", "#A1A1AA", "#8B5CF6", "#FFFFFF", "#F59E0B"),
    "electrique": ("Bleu électrique", "#18181B", "#27272A", "#3F3F46", "#FAFAFA", "#A1A1AA", "#3B82F6", "#FFFFFF", "#F59E0B"),
    "bonta": ("Bonta", "#0e1a30", "#15264a", "#1d3461", "#e9f0fb", "#8fa6c9", "#f0c64a", "#2a2005", "#ff9f5a"),
    "brakmar": ("Brakmar", "#170c0e", "#241216", "#33191e", "#f2e4e1", "#b08f8a", "#e5473a", "#ffffff", "#f0b04a"),
    "wabbit": ("Wabbit", "#1f1409", "#2e1e0f", "#402a15", "#fbeedd", "#c2a384", "#ff8a1f", "#2a1200", "#ffd45e"),
    "pandala": ("Pandala", "#0d1f1c", "#143029", "#1c443a", "#e8f5ee", "#8fb8a8", "#3ddc97", "#04241a", "#ff6b4a"),
    "frigost": ("Frigost", "#0b1a24", "#112636", "#183648", "#e8f4fa", "#8db3c7", "#7fd6f5", "#04222e", "#ffc861"),
    "amakna": ("Amakna", "#0f1d12", "#16291a", "#1f3a25", "#eaf3e4", "#93b08a", "#d9b44a", "#2a2005", "#ff9f5a"),
    "dofustouch": ("Dofus Touch", "#221b14", "#2f261c", "#3f3326", "#f3e9d6", "#b9a98c", "#9bd12b", "#16230a", "#ffa21f"),
    "clair": ("Clair", "#f4f4f5", "#ffffff", "#e4e4e7", "#18181b", "#52525b", "#7c3aed", "#ffffff", "#b45309"),
}
DEFAULT_THEME = "zinc"
FONT_FAMILIES = ["Inter", "Noto Sans", "Cantarell", "DejaVu Sans"]
C: dict[str, str] = {}
_current = DEFAULT_THEME


class _Signals(QObject):
    changed = Signal()


signals = _Signals()


def _fill(name: str) -> None:
    _l, bg, surface, raised, text, muted, accent, on_accent, warn = THEMES[name]
    light = QColor(bg).lightnessF() > 0.6
    C.clear()
    C.update(
        bg=bg, surface=surface, raised=raised, text=text, muted=muted, accent=accent, on_accent=on_accent,
        warn=warn, ok="#22C55E", danger="#EF4444",
        field=raised if light else _mix(bg, "#000000", 0.25),
        hover=_mix(raised, text, 0.08), line=_mix(surface, text, 0.14), edge=_mix(bg, text, 0.38),
        dim=_mix(raised, text, 0.36), accent_dim=_mix(accent, bg, 0.55), accent_hi=_mix(accent, "#ffffff", 0.18),
        accent_soft=_mix(surface, accent, 0.22),
        danger_bg=_mix(surface, "#EF4444", 0.25), danger_text=_mix("#EF4444", text, 0.4),
    )
    C["light"] = "1" if light else ""


_fill(DEFAULT_THEME)  # valeurs disponibles même avant apply()


def current() -> str:
    return _current


# ---------------------------------------------------------------------------
# Icônes SVG (style trait, 24×24). {c} = couleur.
# ---------------------------------------------------------------------------
_S = 'fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
ICONS = {
    "x": f'<path {_S} d="M6 6L18 18M18 6L6 18"/>',
    "minus": f'<path {_S} d="M5 12H19"/>',
    "square": f'<rect {_S} x="5" y="5" width="14" height="14" rx="2.5"/>',
    "restore": f'<rect {_S} x="8.5" y="8.5" width="10.5" height="10.5" rx="2"/><path {_S} d="M5 15V7.5A2.5 2.5 0 0 1 7.5 5H15"/>',
    "plus": f'<path {_S} d="M12 5V19M5 12H19"/>',
    "phone": f'<rect {_S} x="7" y="2.5" width="10" height="19" rx="2.5"/><path {_S} d="M11 18.5H13"/>',
    "keyboard": f'<rect {_S} x="2.5" y="6" width="19" height="12" rx="2.5"/><path {_S} d="M6.5 10H6.6M10 10H10.1M13.9 10H14M17.4 10H17.5M7.5 14H16.5"/>',
    "palette": f'<path {_S} d="M12 3a9 9 0 1 0 0 18c1.3 0 1.9-.9 1.9-1.8 0-.5-.2-.9-.5-1.3s-.5-.8-.5-1.3c0-1 .8-1.8 1.8-1.8H17a4 4 0 0 0 4-4c0-4.4-4-8.8-9-8.8z"/><path {_S} d="M7.5 11H7.6M10 7.5H10.1M14.5 7.5H14.6"/>',
    "help": f'<circle {_S} cx="12" cy="12" r="9"/><path {_S} d="M9.6 9.4a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1.1.9-1.1 1.8M12 17H12.1"/>',
    "sliders": f'<path {_S} d="M4 7H13M19 7H20M4 17H5M11 17H20"/><circle {_S} cx="16" cy="7" r="2.5"/><circle {_S} cx="8" cy="17" r="2.5"/>',
    "record": '<circle {s} cx="12" cy="12" r="8"/><circle fill="{c}" cx="12" cy="12" r="3.6"/>'.replace("{s}", _S),
    "stop": '<rect fill="{c}" x="6.5" y="6.5" width="11" height="11" rx="2.5"/>',
    "play": '<path fill="{c}" stroke="{c}" stroke-width="2" stroke-linejoin="round" d="M8 5.5L18.5 12L8 18.5Z"/>',
    "more": f'<path {_S} d="M6 12H6.1M12 12H12.1M18 12H18.1"/>',
    "refresh": f'<path {_S} d="M20 12a8 8 0 1 1-2.6-5.9M20 4V9H15"/>',
    "home": f'<path {_S} d="M4 11.5L12 4.5L20 11.5M6.5 10V19.5H17.5V10"/>',
    "back": f'<path {_S} d="M16.5 5V19L6 12Z"/>',
    "recents": f'<rect {_S} x="5" y="5" width="14" height="14" rx="3.5"/>',
    "bell": f'<path {_S} d="M6 16.5V11a6 6 0 0 1 12 0v5.5L19.5 18.5H4.5ZM10 21H14"/>',
    "camera": f'<rect {_S} x="3" y="7" width="18" height="13" rx="2.5"/><path {_S} d="M8 7L9.5 4H14.5L16 7"/><circle {_S} cx="12" cy="13.5" r="3.5"/>',
    "power": f'<path {_S} d="M12 3V11M6.3 6.8a8 8 0 1 0 11.4 0"/>',
    "chev-down": f'<path {_S} d="M6 9.5L12 15.5L18 9.5"/>',
    "chev-up": f'<path {_S} d="M6 14.5L12 8.5L18 14.5"/>',
    "check": '<path fill="none" stroke="{c}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" d="M5.5 12.5L10 17L18.5 7.5"/>',
    "reload": f'<path {_S} d="M20 12a8 8 0 1 1-2.4-5.7M20 4V9H15"/>',
    "arrow-left": f'<path {_S} d="M19 12H5M11 6L5 12L11 18"/>',
    "search": f'<circle {_S} cx="11" cy="11" r="6.5"/><path {_S} d="M20 20L15.8 15.8"/>',
    "list": f'<path {_S} d="M8 6H20M8 12H20M8 18H20M4 6H4.1M4 12H4.1M4 18H4.1"/>',
    "tablet": f'<rect {_S} x="3" y="5" width="18" height="14" rx="2.5"/><path {_S} d="M18.5 12H18.6"/>',
}

_dir: Path | None = None


def _icon_dir() -> Path:
    global _dir
    if _dir is None:
        uid = os.getuid() if hasattr(os, "getuid") else 0
        _dir = Path(tempfile.gettempdir()) / f"notrefu_mirror-svg-{uid}"
        _dir.mkdir(parents=True, exist_ok=True)
    return _dir


def icon_path(name: str, color: str) -> str:
    """Chemin d'un SVG (créé au besoin) : tout est vectoriel, donc net à n'importe quelle taille."""
    col = QColor(color).name()
    path = _icon_dir() / f"{name}-{col[1:]}.svg"
    if not path.exists():
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">'
            + ICONS[name].replace("{c}", col)
            + "</svg>"
        )
        path.write_text(svg, encoding="utf-8")
    return path.as_posix()


def icon(name: str, color: str = "text") -> QIcon:
    return QIcon(icon_path(name, C.get(color, color)))


_bound: list[tuple[weakref.ref, str, str]] = []


def bind_icon(widget, name: str, color: str = "text") -> None:
    """Pose une icône SVG sur un bouton et la recolore automatiquement au changement de thème."""
    widget.setIcon(icon(name, color))
    _bound[:] = [t for t in _bound if t[0]() is not widget]
    _bound.append((weakref.ref(widget), name, color))


def _refresh_icons() -> None:
    alive = []
    for ref, name, color in _bound:
        w = ref()
        if w is None:
            continue
        try:
            w.setIcon(icon(name, color))
            alive.append((ref, name, color))
        except RuntimeError:  # widget C++ déjà détruit
            pass
    _bound[:] = alive


# ---------------------------------------------------------------------------
# Ombres portées
# ---------------------------------------------------------------------------
def shadow(widget: QWidget, blur: int = 30, dy: int = 8, alpha: int = 120, color: str | None = None) -> None:
    """Ombre douce derrière un panneau. À ne JAMAIS poser sur la zone vidéo (rendu hors écran coûteux)."""
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    col = QColor(color or "#000000")
    col.setAlpha(alpha)
    eff.setColor(col)
    widget.setGraphicsEffect(eff)


def apply(app, name: str = DEFAULT_THEME) -> None:
    global _current
    if name not in THEMES:
        name = DEFAULT_THEME
    _current = name
    _fill(name)
    f = QFont()
    f.setFamilies(FONT_FAMILIES)
    f.setPointSizeF(10.5)
    app.setFont(f)
    pal = QPalette()
    for role, key in (
        (QPalette.ColorRole.Window, "bg"), (QPalette.ColorRole.Base, "field"),
        (QPalette.ColorRole.AlternateBase, "surface"), (QPalette.ColorRole.Button, "raised"),
        (QPalette.ColorRole.Text, "text"), (QPalette.ColorRole.WindowText, "text"),
        (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.ToolTipBase, "surface"),
        (QPalette.ColorRole.ToolTipText, "text"), (QPalette.ColorRole.Highlight, "accent"),
        (QPalette.ColorRole.HighlightedText, "on_accent"), (QPalette.ColorRole.PlaceholderText, "muted"),
    ):
        pal.setColor(role, QColor(C[key]))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet())
    _refresh_icons()
    signals.changed.emit()


def stylesheet() -> str:
    v = dict(C)
    for n in ("chev-down", "chev-up"):
        v["i_" + n.replace("-", "_")] = icon_path(n, C["muted"])
    v["i_check"] = icon_path("check", C["on_accent"])
    v["i_x"] = icon_path("x", C["muted"])
    v["i_x_hover"] = icon_path("x", C["text"])
    return """
* { outline: none; }
QWidget { color: %(text)s; }
QMainWindow, QDialog { background: %(bg)s; }
QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget, PhonePanel, EmptyPage { background: transparent; }
QToolTip { background: %(surface)s; color: %(text)s; border: 1px solid %(line)s; padding: 6px 10px; border-radius: 8px; }
QStatusBar { background: %(surface)s; color: %(muted)s; border-top: 1px solid %(line)s; }
QStatusBar::item { border: none; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: %(raised)s; border-radius: 4px; min-height: 36px; }
QScrollBar::handle:vertical:hover { background: %(accent_dim)s; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:horizontal { background: %(raised)s; border-radius: 4px; min-width: 36px; }
QScrollBar::handle:horizontal:hover { background: %(accent_dim)s; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { height: 0; width: 0; background: none; }

/* ---------- Cadre de la fenêtre et barre de titre ---------- */
QWidget#frame { background: %(bg)s; border: 1px solid %(line)s; }
QWidget#titlebar { background: %(surface)s; border-bottom: 1px solid %(line)s; }
QLabel#apptitle { font-weight: 700; font-size: 11pt; background: transparent; }
QLabel#appver { color: %(muted)s; background: transparent; }
QToolButton#winbtn { background: transparent; border: none; border-radius: 8px; padding: 6px; }
QToolButton#winbtn:hover { background: %(raised)s; }
QToolButton#winbtn:pressed { background: %(accent_dim)s; }
QToolButton#winclose { background: transparent; border: none; border-radius: 8px; padding: 6px; }
QToolButton#winclose:hover { background: %(danger)s; }
QToolButton#winclose:pressed { background: %(danger_bg)s; }
QToolButton#chrome { background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 6px 10px; color: %(muted)s; }
QToolButton#chrome:hover { background: %(raised)s; color: %(text)s; border-color: %(accent)s; }
QToolButton#chrome:pressed { background: %(accent_dim)s; }

/* ---------- Onglets ---------- */
QTabWidget::pane { border: none; background: transparent; }
QTabBar { background: transparent; }
QTabBar::tab {
    background: transparent; color: %(muted)s; padding: 8px 14px; margin: 8px 3px 6px 3px;
    border: 1px solid transparent; border-radius: 10px; min-width: 70px;
}
QTabBar::tab:hover { background: %(surface)s; color: %(text)s; }
QTabBar::tab:selected { background: %(accent_soft)s; color: %(text)s; font-weight: 600; border: 1px solid %(accent)s; }
QToolButton#tabclose { background: transparent; border: none; border-radius: 6px; padding: 3px; margin: 0 0 0 4px; }
QToolButton#tabclose:hover { background: %(danger_bg)s; }
QToolButton#plus { background: %(surface)s; border: 1px solid %(line)s; border-radius: 9px; padding: 5px; margin: 8px 6px 6px 8px; }
QToolButton#plus:hover { border-color: %(accent)s; background: %(raised)s; }
QToolButton#plus:pressed { background: %(accent_dim)s; }

/* ---------- Boutons ---------- */
QPushButton, QToolButton {
    background: %(raised)s; border: 1px solid %(line)s; border-radius: 9px; padding: 7px 14px; color: %(text)s;
}
QPushButton:hover, QToolButton:hover { background: %(hover)s; border-color: %(accent)s; }
QPushButton:pressed, QToolButton:pressed { background: %(accent_dim)s; border-color: %(accent)s; }
QPushButton:disabled, QToolButton:disabled { color: %(dim)s; background: %(surface)s; border-color: %(line)s; }
QPushButton:focus, QToolButton:focus { border-color: %(accent)s; }
QToolButton::menu-indicator { image: none; width: 0; }
QPushButton#primary {
    background: %(accent)s; color: %(on_accent)s; border: 1px solid %(accent_hi)s; font-weight: 700; font-size: 11.5pt;
    padding: 10px 24px; border-radius: 12px;
}
QPushButton#primary:hover { background: %(accent_hi)s; border-color: %(accent_hi)s; }
QPushButton#primary:pressed { background: %(accent_dim)s; color: %(text)s; }
QPushButton#primary:disabled { background: %(raised)s; color: %(dim)s; border-color: %(line)s; }
QPushButton#danger { border-color: %(danger_bg)s; color: %(danger_text)s; padding: 10px 20px; border-radius: 12px; }
QPushButton#danger:hover { background: %(danger_bg)s; border-color: %(danger)s; }
QPushButton#danger:pressed { background: %(danger)s; color: #ffffff; }
QPushButton#danger:disabled { color: %(dim)s; border-color: %(line)s; background: %(surface)s; }
QToolButton#tool:checked { border: 1px solid %(accent)s; color: %(text)s; }
QFrame#barsep { background: %(line)s; margin: 6px 5px; }
QToolButton#tool { background: %(raised)s; border: 1px solid transparent; padding: 7px 11px; border-radius: 9px; }
QToolButton#tool:hover { background: %(hover)s; border-color: %(accent)s; }
QToolButton#tool:pressed { background: %(accent_dim)s; }
QToolButton#tool-stop { background: transparent; border: 1px solid %(danger_bg)s; color: %(danger_text)s; padding: 7px 11px; border-radius: 9px; }
QToolButton#tool-stop:hover { background: %(danger_bg)s; border-color: %(danger)s; }
QToolButton#tool-stop:pressed { background: %(danger)s; }

/* ---------- Panneaux de réglages ---------- */
QGroupBox {
    background: %(surface)s; border: 1px solid %(line)s; border-radius: 14px;
    margin-top: 14px; padding: 18px 16px 12px 16px; font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 16px; top: 2px; padding: 0 8px; color: %(text)s; font-size: 11pt; }
QGroupBox QLabel, QGroupBox QCheckBox, QGroupBox QRadioButton { font-weight: 400; }
QLabel { background: transparent; }
QLabel#hint { color: %(warn)s; }
QLabel#muted, QLabel#stats, QLabel#info { color: %(muted)s; }
QLabel#subhead { color: %(muted)s; font-weight: 600; padding-top: 4px; }
QToolButton#disclosure { border: none; background: transparent; color: %(muted)s; padding: 4px 2px; }
QToolButton#disclosure:hover { color: %(text)s; }
QLabel#info { padding: 0 2px; }

/* ---------- Champs ---------- */
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {
    background: %(field)s; border: 1px solid %(line)s; border-radius: 9px; padding: 7px 11px;
    selection-background-color: %(accent_dim)s; selection-color: %(text)s;
}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover { border-color: %(edge)s; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus { border-color: %(accent)s; }
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled { color: %(dim)s; background: %(surface)s; }
QComboBox { padding-right: 30px; }
QComboBox::drop-down { border: none; width: 28px; subcontrol-origin: padding; subcontrol-position: center right; }
QComboBox::down-arrow { image: url(%(i_chev_down)s); width: 14px; height: 14px; }
QComboBox QAbstractItemView { background: %(surface)s; border: 1px solid %(line)s; border-radius: 8px; selection-background-color: %(accent_soft)s; selection-color: %(text)s; padding: 4px; outline: none; }
QSpinBox { padding-right: 24px; }
QSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 22px; border: none; background: transparent; }
QSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 22px; border: none; background: transparent; }
QSpinBox::up-arrow { image: url(%(i_chev_up)s); width: 12px; height: 12px; }
QSpinBox::down-arrow { image: url(%(i_chev_down)s); width: 12px; height: 12px; }
QPlainTextEdit { font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace; font-size: 9pt; color: %(muted)s; }

/* ---------- Curseurs (sliders) ---------- */
QSlider::groove:horizontal { height: 6px; background: %(raised)s; border-radius: 3px; }
QSlider::sub-page:horizontal { background: %(accent)s; border-radius: 3px; }
QSlider::handle:horizontal { background: %(text)s; border: 2px solid %(accent)s; width: 14px; height: 14px; margin: -6px 0; border-radius: 9px; }
QSlider::handle:horizontal:hover { background: %(accent_hi)s; }
QSlider::handle:horizontal:pressed { background: %(accent)s; }

/* ---------- Cases et boutons radio ---------- */
QCheckBox, QRadioButton { spacing: 10px; padding: 3px 0; background: transparent; }
QCheckBox::indicator { width: 18px; height: 18px; border: 1.5px solid %(edge)s; border-radius: 6px; background: %(field)s; }
QCheckBox::indicator:hover { border-color: %(accent)s; }
QCheckBox::indicator:checked { background: %(accent)s; border-color: %(accent)s; image: url(%(i_check)s); }
QCheckBox::indicator:disabled { border-color: %(line)s; }
QRadioButton::indicator { width: 18px; height: 18px; border: 1.5px solid %(edge)s; border-radius: 10px; background: %(field)s; }
QRadioButton::indicator:hover { border-color: %(accent)s; }
QRadioButton::indicator:checked { border: 1.5px solid %(accent)s; background: qradialgradient(cx:.5, cy:.5, radius:.5, fx:.5, fy:.5, stop:0 %(accent)s, stop:.5 %(accent)s, stop:.56 %(field)s, stop:1 %(field)s); }

/* ---------- Barre de la session (jeu) ---------- */
QWidget#actionbar { background: %(surface)s; border-top: 1px solid %(line)s; }
QWidget#gamebar { background: %(surface)s; border-bottom: 1px solid %(line)s; }

/* ---------- Tableaux, listes, menus ---------- */
QTableWidget, QListWidget { background: %(surface)s; border: 1px solid %(line)s; border-radius: 10px; gridline-color: %(line)s; }
QListWidget::item { padding: 7px; border-radius: 8px; }
QListWidget::item:selected, QTableWidget::item:selected { background: %(accent_soft)s; color: %(text)s; }
QHeaderView::section { background: %(raised)s; color: %(muted)s; border: none; padding: 7px 9px; }
QMenu { background: %(surface)s; border: 1px solid %(line)s; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 8px 20px; border-radius: 7px; }
QMenu::item:selected { background: %(accent_soft)s; }
QMenu::separator { height: 1px; background: %(line)s; margin: 5px 8px; }
QDialogButtonBox QPushButton { min-width: 90px; }
""" % v
