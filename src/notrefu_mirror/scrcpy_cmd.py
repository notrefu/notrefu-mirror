"""Construction de la ligne de commande scrcpy à partir des réglages. Sans Qt."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

DOFUS_TOUCH_PACKAGE = "com.ankama.dofustouch"

# nom -> (libellé, Mbit/s, ips, largeur, hauteur, dpi)
# largeur/hauteur/dpi : écran virtuel (mode horizontal) ; la plus grande
# dimension sert aussi de --max-size en mode standard.
PRESETS: dict[str, tuple[str, int, int, int, int, int]] = {
    # dpi = largeur / 8 : même taille d'interface (1280 dp de large) quelle que soit la qualité
    "faible": ("Faible", 2, 30, 960, 540, 120),
    "moyen": ("Moyen", 4, 45, 1280, 720, 160),
    "haut": ("Haut", 8, 60, 1920, 1080, 240),
    "ultra": ("Ultra", 16, 60, 2560, 1440, 320),
    # plusieurs comptes ouverts en même temps : léger pour le téléphone et le processeur
    "multi": ("Multi-compte", 4, 30, 1280, 720, 160),
}
DEFAULT_QUALITY = "moyen"

# Toutes les fenêtres de mirroring commencent par ce préfixe (sert à les retrouver).
WINDOW_PREFIX = "notrefu-mirror — "

MODES = {
    "standard": "Standard",
    "horizontal": "Horizontal (écran virtuel paysage)",
}

SHORTCUT_MODS = {
    "lalt,lsuper": "Alt gauche ou Super gauche (défaut)",
    "lalt": "Alt gauche",
    "lctrl": "Ctrl gauche",
    "ralt": "Alt droit (AltGr)",
}

_PKG_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+")


def valid_package(name: str) -> bool:
    """Nom de paquet Android, éventuellement suivi de « @utilisateur » (double application)."""
    pkg, sep, user = name.strip().partition("@")
    # fullmatch : « $ » accepterait un retour à la ligne final ; isascii : « ² » passe isdigit() mais pas int()
    return bool(_PKG_RE.fullmatch(pkg)) and (not sep or (user.isascii() and user.isdigit()))


@dataclass
class Settings:
    serial: str = ""
    mode: str = "horizontal"
    quality: str = DEFAULT_QUALITY
    # valeurs effectives (remplies depuis le préréglage ou le mode « Perso »)
    bitrate_mbps: int = 6
    fps: int = 60
    width: int = 1920
    height: int = 1080
    dpi: int = 280
    # options
    screen_off: bool = False
    reopen_app: bool = True
    app_package: str = DOFUS_TOUCH_PACKAGE
    show_fps: bool = False
    show_touches: bool = False
    control: bool = True
    audio: bool = True
    clipboard: bool = True
    stay_awake: bool = False
    power_off_on_close: bool = False
    keyboard: str = "sdk"
    shortcut_mod: str = "lalt,lsuper"
    title: str = "notrefu-mirror"
    embed: bool = False  # fenêtre intégrée dans notrefu-mirror (sans bordure)
    extra: list[str] = field(default_factory=list)

    def apply_preset(self, name: str) -> None:
        _, mbps, fps, w, h, dpi = PRESETS[name]
        self.quality = name
        self.bitrate_mbps, self.fps = mbps, fps
        self.width, self.height, self.dpi = w, h, dpi


def preset_summary(name: str) -> str:
    _, mbps, fps, w, h, dpi = PRESETS[name]
    return f"{mbps} Mbit/s, {fps} ips, écran {w}×{h} / {dpi} dpi"


def build_command(scrcpy: str, s: Settings) -> list[str]:
    """Renvoie la commande scrcpy complète (liste d'arguments)."""
    cmd = [scrcpy]
    if s.serial:
        cmd += ["-s", s.serial]
    cmd += [
        f"--video-bit-rate={int(s.bitrate_mbps)}M",
        f"--max-fps={int(s.fps)}",
        f"--window-title={s.title}",
    ]
    if s.embed:
        cmd.append("--window-borderless")

    if s.mode == "horizontal":
        w, h = max(s.width, s.height), min(s.width, s.height)  # toujours paysage
        cmd.append(f"--new-display={w}x{h}/{int(s.dpi)}")
    else:
        cmd.append(f"--max-size={max(s.width, s.height)}")

    if s.reopen_app and s.app_package and valid_package(s.app_package):
        cmd.append(f"--start-app={s.app_package.strip()}")

    if s.screen_off:
        cmd.append("--turn-screen-off")
    if s.show_fps:
        cmd.append("--print-fps")
    if s.show_touches:
        cmd.append("--show-touches")
    if not s.control:
        cmd.append("--no-control")
    if not s.audio:
        cmd.append("--no-audio")
    if not s.clipboard:
        cmd.append("--no-clipboard-autosync")
    if s.stay_awake:
        cmd.append("--stay-awake")
    if s.power_off_on_close:
        cmd.append("--power-off-on-close")
    if s.keyboard and s.keyboard != "sdk":
        cmd.append(f"--keyboard={s.keyboard}")
    if s.shortcut_mod and s.shortcut_mod != "lalt,lsuper":
        cmd.append(f"--shortcut-mod={s.shortcut_mod}")

    cmd += s.extra
    return cmd


# Raccourcis scrcpy utiles (MOD = touche choisie dans les options).
SHORTCUTS = [
    ("MOD + f", "Plein écran"),
    ("MOD + g", "Fenêtre à la taille 1:1"),
    ("MOD + w", "Retirer les bandes noires"),
    ("MOD + h  /  clic molette", "Accueil"),
    ("MOD + b  /  clic droit", "Retour"),
    ("MOD + s", "Applications récentes"),
    ("MOD + p", "Bouton marche/arrêt"),
    ("MOD + o", "Éteindre l'écran du téléphone"),
    ("MOD + Maj + o", "Rallumer l'écran du téléphone"),
    ("MOD + ↑ / ↓", "Volume + / −"),
    ("MOD + v", "Coller le presse-papiers du PC"),
    ("Ctrl + Maj + v", "Taper le texte du presse-papiers du PC (si « Coller » ne marche pas dans le jeu)"),
    ("MOD + i", "Afficher/masquer les images par seconde"),
]


def explain_failure(log: str) -> str | None:
    """Traduit les erreurs fréquentes de scrcpy/adb en conseil lisible."""
    low = log.lower()
    if "unauthorized" in low:
        return "Le téléphone n'a pas autorisé ce PC : acceptez la fenêtre « Autoriser le débogage USB » sur le téléphone."
    if "no permissions" in low or "insufficient permissions" in low:
        return "Permissions USB manquantes : menu Aide → « Installer les règles USB »."
    if "could not find any adb device" in low or "no devices/emulators found" in low or "device not found" in low:
        return "Aucun téléphone détecté : vérifiez le câble, le débogage USB, ou la connexion Wi-Fi."
    if "new-display" in low and ("not supported" in low or "requires" in low or "android" in low and "10" in low):
        return "L'écran virtuel demande Android 10 ou plus récent : passez en mode Standard."
    if "server connection failed" in low or "could not connect to" in low:
        return "Connexion au serveur scrcpy impossible : reconnectez le téléphone puis réessayez."
    if "start-app" in low and ("not found" in low or "unknown" in low):
        return "Application introuvable sur le téléphone : vérifiez le nom du paquet dans « Affichage »."
    return None
