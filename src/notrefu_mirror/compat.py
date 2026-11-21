"""Compatibilité multi-appareils, sans Qt : anciens Android, marques, repli vidéo. Testable sans téléphone ni fenêtre."""

from __future__ import annotations

import re

MIN_AUDIO_SDK = 30  # scrcpy ne capture le son qu'à partir d'Android 11
AUDIO_OFF_NOTE = "Audio désactivé automatiquement : Android 11+ requis"


def audio_supported(sdk: int) -> bool:
    """SDK inconnu (0) : on tente quand même ; sinon Android 11 (SDK 30) minimum."""
    return sdk == 0 or sdk >= MIN_AUDIO_SDK


# --- aide selon la marque -----------------------------------------------------------------------------------------------
_BRANDS = {
    "xiaomi": "xiaomi", "poco": "xiaomi", "redmi": "xiaomi", "blackshark": "xiaomi",
    "oppo": "oppo", "realme": "oppo", "oneplus": "oppo",
    "samsung": "samsung",
}

_TIPS = {
    "xiaomi": "Xiaomi / POCO / Redmi : active « Débogage USB (Paramètres de sécurité) » dans les Options pour les développeurs "
              "(il faut une carte SIM et un compte Mi) pour autoriser les clics et les touches.",
    "oppo": "Oppo / Realme / OnePlus : dans les Options pour les développeurs, active « Désactiver la surveillance des autorisations » "
            "pour autoriser les clics et les touches.",
    "samsung": "Samsung : désactive le « Bloqueur automatique » (Paramètres → Sécurité et confidentialité).",
}
_SAMSUNG_WINDOWS = " Sous Windows, installe aussi le pilote officiel « Samsung Android USB Driver »."


def brand_of(manufacturer: str, model: str = "") -> str:
    """Famille de marque (« xiaomi », « oppo », « samsung ») ou « » si inconnue. Se base sur le fabricant, puis le modèle."""
    for text in (manufacturer, model):
        low = (text or "").strip().lower()
        for key, fam in _BRANDS.items():
            if low.startswith(key) or re.search(rf"\b{key}\b", low):
                return fam
    return ""


def brand_tip(manufacturer: str, model: str = "", platform: str = "") -> str:
    fam = brand_of(manufacturer, model)
    tip = _TIPS.get(fam, "")
    if fam == "samsung" and platform == "win32":
        tip += _SAMSUNG_WINDOWS
    return tip


# --- repli vidéo (encodeur ou débit trop exigeant : tablettes MediaTek / Unisoc…) ---------------------------------------
MAX_FALLBACK = 2
_BASELINE = "profile:int=1"  # H.264 Baseline : accepté par tous les encodeurs matériels


def video_fallback(level: int, bit_rate: int, fps: int, max_size: int, options: str) -> tuple[int, int, int, str]:
    """(débit, ips, taille max, options du codec) pour le niveau de repli (0 = réglages demandés, inchangés).
    1 : H.264 Baseline, débit ≤ 8 Mbit/s, ≤ 30 ips, ≤ 1280 px ; 2 : débit ≤ 3 Mbit/s, ≤ 30 ips, ≤ 960 px."""
    if level <= 0:
        return bit_rate, fps, max_size, options
    cap_br, cap_size = (8_000_000, 1280) if level == 1 else (3_000_000, 960)
    size = min(max_size, cap_size) if max_size else cap_size
    return min(bit_rate, cap_br), min(fps, 30), size, _BASELINE


def shrink_display(spec: str, max_side: int) -> str:
    """« 1920x1080/280 » -> « 1280x720/187 » : écran virtuel réduit proportionnellement (densité comprise)."""
    m = re.fullmatch(r"(\d+)x(\d+)(?:/(\d+))?", spec or "")
    if not m:
        return spec
    w, h, dpi = int(m.group(1)), int(m.group(2)), m.group(3)
    big = max(w, h)
    if big <= max_side:
        return spec
    k = max_side / big
    nw, nh = max(2, int(w * k) // 8 * 8), max(2, int(h * k) // 8 * 8)
    return f"{nw}x{nh}" + (f"/{max(120, int(int(dpi) * k))}" if dpi else "")

