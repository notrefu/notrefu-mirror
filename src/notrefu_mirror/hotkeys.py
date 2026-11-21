"""Raccourcis clavier de navigation entre les sessions (raccourcis Qt, actifs quand notrefu-mirror a le focus)."""

from __future__ import annotations

from PySide6.QtGui import QKeySequence

# action -> (libellé, raccourci par défaut)
ACTIONS: dict[str, tuple[str, str]] = {
    "next": ("Session suivante", "Ctrl+Tab"),
    "prev": ("Session précédente", "Ctrl+Shift+Tab"),
    **{f"goto{i}": (f"Aller à la session {i}", f"Alt+{i}") for i in range(1, 10)},
    "fullscreen": ("Plein écran (masquer les barres)", "F11"),
    "compact": ("Mode compact (masquer barre d'outils et d'état)", "F10"),
    "screenshot": ("Capture d'écran de la session", "Ctrl+Shift+S"),
    "detach": ("Détacher / rattacher la session", "Ctrl+Shift+D"),
    "grid": ("Vue en grille (sessions en cours)", "Ctrl+Shift+G"),
    "guides": ("Guides (Papycha, Almanax)", "Ctrl+Shift+J"),
    "keymap": ("Touches personnalisées : activer / désactiver", "Ctrl+Shift+K"),
    "keymap_edit": ("Touches personnalisées : mode édition", "Ctrl+Shift+E"),
    "size1": ("Qualité 1 : Faible", "Ctrl+Alt+1"),
    "size2": ("Qualité 2 : Moyen", "Ctrl+Alt+2"),
    "size3": ("Qualité 3 : Haut", "Ctrl+Alt+3"),
    "size4": ("Qualité 4 : Ultra", "Ctrl+Alt+4"),
}
SIZE_PRESETS = {"size1": "faible", "size2": "moyen", "size3": "haut", "size4": "ultra"}


def default_bindings() -> dict[str, str]:
    return {k: v[1] for k, v in ACTIONS.items()}


def validate_combo(combo: str) -> str | None:
    """Message d'erreur si `combo` n'est pas un raccourci valide, sinon None (vide = désactivé)."""
    if not combo.strip():
        return None
    if QKeySequence(combo).isEmpty():
        return f"raccourci invalide : {combo}"
    return None


def normalize(combo: str) -> str:
    """Forme canonique d'un raccourci (« ctrl+tab » et « Ctrl+Tab » sont les mêmes)."""
    return QKeySequence(combo.strip()).toString(QKeySequence.SequenceFormat.PortableText) if combo.strip() else ""


def find_conflicts(bindings: dict[str, str]) -> dict[str, list[str]]:
    """Raccourcis utilisés par plusieurs actions : {combinaison: [actions]}."""
    seen: dict[str, list[str]] = {}
    for name, combo in bindings.items():
        key = normalize(combo)
        if key:
            seen.setdefault(key, []).append(name)
    return {k: v for k, v in seen.items() if len(v) > 1}
