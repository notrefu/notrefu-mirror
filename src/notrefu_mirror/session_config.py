"""Réglages d'une session, sans Qt : lecture/écriture dans un magasin de type QSettings.

Avant, `PhonePanel.save/load` lisaient et écrivaient les widgets et les clés en même temps. Maintenant les clés et les
règles de compatibilité (anciens réglages) vivent ici ; le panneau ne fait que remplir un `SessionConfig` ou l'appliquer.
Le « magasin » est tout objet avec `value(key, default=None)` et `setValue(key, v)` : QSettings, ou un faux dans les tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .scrcpy_cmd import DOFUS_TOUCH_PACKAGE as DEFAULT_APP

EMBLEMS = 15  # nombre d'emblèmes intégrés (CLASS_EMBLEMS dans ui/common.py)
SPINS = ("br", "fps", "w", "h", "dpi", "alat")


class Store(Protocol):
    def value(self, key: str, default: Any = None) -> Any: ...
    def setValue(self, key: str, value: Any) -> None: ...


def _bool(v: Any) -> bool:
    return str(v).lower() in ("true", "1")


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError, OverflowError):  # OverflowError : « inf »
        return None


@dataclass
class SessionConfig:
    """None = « non enregistré » : le widget garde alors sa valeur par défaut."""

    mode: Any = None
    shape: Any = None
    zoom: int | None = None
    quality: Any = None
    spins: dict[str, int] = field(default_factory=dict)  # br, fps, w, h, dpi, alat
    checks: dict[str, bool] = field(default_factory=dict)
    app: str = DEFAULT_APP
    playtime: int = 0
    gamemode: Any = None
    name: str = ""
    ip: str = ""
    port: str = "5555"
    kb: Any = None
    mod: Any = None
    serial: str = ""
    color: str = ""
    icon: str = ""
    volume: int = 100
    was_running: bool = False
    keymap: str = ""  # touches personnalisées (JSON, voir keymap.KeyMap)

    # ---- écriture ------------------------------------------------------
    def save(self, qs: Store, prefix: str, emblem_count: int = EMBLEMS) -> None:
        put = lambda k, v: qs.setValue(f"{prefix}/{k}", v)  # noqa: E731
        put("mode", self.mode)
        put("shape", self.shape)
        put("zoom", self.zoom)
        put("quality", self.quality)
        for n, v in self.spins.items():
            put(f"{n}_v", v)  # « fps » est déjà pris par la case à cocher du même nom
        for n, v in self.checks.items():
            put(n, v)
        put("app", self.app)
        put("playtime", int(self.playtime))
        put("gamemode", self.gamemode)
        put("name", self.name)
        put("ip", self.ip)
        put("port", self.port)
        put("kb", self.kb)
        put("mod", self.mod)
        put("serial", self.serial)
        put("color", self.color)
        put("icon", self.icon)
        put("volume", self.volume)
        put("was_running", self.was_running)
        put("keymap", self.keymap)

    # ---- lecture -------------------------------------------------------
    @classmethod
    def load(cls, qs: Store, prefix: str, check_names=(), emblem_count: int = EMBLEMS) -> "SessionConfig":
        get = lambda k, d=None: qs.value(f"{prefix}/{k}", d)  # noqa: E731
        c = cls()
        c.playtime = _int(get("playtime", 0) or 0) or 0
        c.mode, c.gamemode, c.kb, c.mod = get("mode"), get("gamemode"), get("kb"), get("mod")
        c.shape = get("shape")
        if c.shape is None and str(get("fit", "true")).lower() in ("false", "0"):
            c.shape = "perso"  # ancien réglage « adapter » décoché
        c.zoom = _int(get("zoom")) if get("zoom") is not None else None
        c.quality = get("quality")
        for n in SPINS:
            v = get(f"{n}_v")
            if v is None:
                v = get(n)
            iv = _int(v)
            if iv is not None:  # ancienne valeur illisible (ex. « false ») : on l'ignore
                c.spins[n] = iv
        for n in check_names:
            v = get(n)
            if v is not None:
                c.checks[n] = _bool(v)
        c.app = get("app", DEFAULT_APP) or DEFAULT_APP
        c.name = str(get("name", "") or "")
        c.ip = get("ip", "") or ""
        c.port = get("port", "5555") or "5555"
        c.serial = get("serial", "") or ""
        c.color = str(get("color", "") or "")
        ic = get("icon")
        if ic is None:  # jamais choisi : emblème par défaut selon le numéro de la session
            digits = "".join(ch for ch in prefix if ch.isdigit())
            ic = f"builtin:{int(digits or 0) % emblem_count + 1:02d}"
        c.icon = str(ic or "")
        vol = get("volume")
        c.volume = 100 if vol is None else (_int(vol or 0) or 0)
        c.was_running = _bool(get("was_running", "false"))
        c.keymap = str(get("keymap", "") or "")
        return c
