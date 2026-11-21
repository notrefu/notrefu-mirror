"""Petites règles de connexion sans fil, sans Qt."""

from __future__ import annotations

import ipaddress


def parse_port(text: str) -> int | None:
    t = text.strip()
    if not (t.isascii() and t.isdigit()):  # « ² » ou « ٣ » passent isdigit() mais pas int()
        return None
    return int(t) if 1 <= int(t) <= 65535 else None


def valid_ip(text: str) -> bool:
    """Adresse IPv4 écrite en chiffres ASCII (ni « 999.1.1.1 », ni chiffres arabes, ni retour à la ligne)."""
    t = text.strip()
    if not (t.isascii() and t.count(".") == 3):
        return False
    try:
        return isinstance(ipaddress.ip_address(t), ipaddress.IPv4Address)
    except ValueError:
        return False


def pair_ip(addr: str) -> str:
    """Adresse IP d'une saisie « ip:port » d'appairage."""
    return addr.strip().split(":")[0]


DEVICE_HINTS = {
    "unauthorized": "Appareil détecté mais non autorisé — accepte la pop-up « Autoriser le débogage USB » sur l'écran du téléphone "
                    "(coche « Toujours autoriser »). Elle n'apparaît pas ? Débranche/rebranche le câble, écran déverrouillé.",
    "no permissions": "Appareil détecté mais sans permissions USB : menu Aide → « Installer les règles USB », puis rebranchez le câble.",
    "offline": "Appareil détecté mais hors ligne : débranchez/rebranchez le câble ou désactivez puis réactivez le débogage USB.",
    "authorizing": "Appareil en cours d'autorisation : accepte la pop-up « Autoriser le débogage USB » sur le téléphone.",
    "connecting": "Appareil en cours de connexion : patiente quelques secondes puis clique sur Actualiser.",
    "recovery": "Appareil en mode récupération : redémarre-le normalement.",
    "sideload": "Appareil en mode sideload : redémarre-le normalement.",
    "bootloader": "Appareil en mode bootloader : redémarre-le normalement.",
}

SAMSUNG_WINDOWS_TIP = (
    "Appareil Samsung (ex. Galaxy Tab) : désactive le « Bloqueur automatique » (Paramètres → Sécurité et confidentialité → "
    "Bloqueur automatique) et installe le pilote officiel « Samsung Android USB Driver ». Clique sur « Ouvrir le diagnostic »."
)


def device_state_hint(state: str) -> str | None:
    return DEVICE_HINTS.get(state)


def devices_banner(states: list[str], adb_error: str, platform: str) -> str:
    """Texte du bandeau d'aide de la liste des téléphones (vide = tout va bien : au moins un appareil prêt).
    Un appareil vu par adb mais pas prêt n'est jamais présenté comme « Aucun téléphone détecté »."""
    if adb_error:
        return f"Impossible de lire les téléphones : {adb_error}"
    if not states:
        text = "Aucun téléphone détecté. Active le débogage USB, branche le câble et accepte la fenêtre d'autorisation, puis clique sur Actualiser."
        if platform == "win32":
            text += " " + SAMSUNG_WINDOWS_TIP
        elif platform.startswith("linux"):
            text += " Tablette ou téléphone USB non vu ? Menu Aide → « Installer les règles USB » (Samsung et autres constructeurs inclus)."
        return text
    if "device" in states:
        return ""
    hints = []
    for st in states:
        h = DEVICE_HINTS.get(st)
        if h and h not in hints:
            hints.append(h)
    return " ".join(hints) or f"Appareil détecté mais pas prêt (état adb : {states[0]}). Ouvre le diagnostic."
