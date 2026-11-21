"""Protection du téléphone (chauffe, Wi-Fi saturé) et réveil, sans Qt.

scrcpy ne permet pas de changer les images par seconde en cours de route, et relancer une session détruirait l'écran
virtuel du jeu. Le levier est donc côté PC : une session « freinée » lit son flux vidéo à au plus N images par seconde.
Le serveur du téléphone ne peut alors plus écrire dans la connexion (les tampons se remplissent), l'encodeur ralentit.
Attention : le miroir prend du retard (les images en attente sont rejouées ensuite). C'est pourquoi aucune session n'est
JAMAIS freinée parce qu'elle n'a pas le focus, et pourquoi la limitation chauffe / Wi-Fi est désactivée par défaut.
"""

from __future__ import annotations

import threading
from collections import deque

LEVEL_CAPS: dict[int, int | None] = {0: None, 1: 30, 2: 20}
WAKE_MIN_INTERVAL_S = 20.0

# Chauffe : seuils avec hystérésis (on monte vite, on ne redescend que quand c'est vraiment frais).
THERMAL_UP = {1: (41.0, 2), 2: (44.0, 3)}  # niveau visé : (température °C, état « thermalservice » minimal)
THERMAL_DOWN = {1: (39.0, 2), 2: (42.0, 3)}  # on quitte le niveau si température <= seuil ET état < minimal


def thermal_level(prev: int, temp_c: float | None, thermal: int | None) -> int:
    """Niveau de limitation (0 = aucune, 1 = 30 ips, 2 = 20 ips) d'après la température et l'état thermique Android."""
    t = temp_c if temp_c is not None else 0.0
    s = thermal if thermal is not None else 0
    level = prev
    for target in (2, 1):
        limit, status = THERMAL_UP[target]
        if t >= limit or s >= status:
            level = max(level, target)
            break
    while level > 0:
        limit, status = THERMAL_DOWN[level]
        if temp_c is None and thermal is None:
            break  # aucune mesure : on ne change rien
        if t <= limit and s < status:
            level -= 1
        else:
            break
    return level


class FpsCaps:
    """Plafonds d'images par seconde demandés par plusieurs sources (chaleur, Wi-Fi) : le plus bas gagne."""

    def __init__(self) -> None:
        self._caps: dict[str, int] = {}
        self._lock = threading.Lock()

    def set(self, source: str, fps: int | None) -> bool:
        """Renvoie True si le plafond effectif de cette source a changé."""
        with self._lock:
            new = max(1, int(fps)) if fps else None
            if self._caps.get(source) == new:
                return False
            if new is None:
                self._caps.pop(source, None)
            else:
                self._caps[source] = new
            return True

    def effective(self) -> int | None:
        with self._lock:
            return min(self._caps.values()) if self._caps else None

    def get(self, source: str) -> int | None:
        with self._lock:
            return self._caps.get(source)


class StallGuard:
    """Détecte un Wi-Fi saturé : des « blocages » répétés du flux (silence puis rafale d'images d'un coup).

    `update(nouveaux_blocages, maintenant)` renvoie le niveau de limitation (0, 1 ou 2). On monte après 3 blocages en
    10 s, on redescend d'un cran après 30 s calmes ; jamais plus d'un changement toutes les 8 s."""

    def __init__(self) -> None:
        self._events: deque[float] = deque()
        self.level = 0
        self._changed = -1e9

    def update(self, new_stalls: int, now: float) -> int:
        for _ in range(max(0, new_stalls)):
            self._events.append(now)
        while self._events and now - self._events[0] > 10:
            self._events.popleft()
        if len(self._events) >= 3 and now - self._changed >= 8 and self.level < 2:
            self.level += 1
            self._changed = now
            self._events.clear()
        elif self.level > 0 and not self._events and now - self._changed >= 30:
            self.level -= 1
            self._changed = now
        return self.level


def should_wake(last_wake: float | None, now: float, enabled: bool, screen_off_mode: bool) -> bool:
    """Réveil du téléphone quand on clique une session : pas si c'est voulu éteint, et pas plus d'une fois par 20 s."""
    if not enabled or screen_off_mode:
        return False
    return last_wake is None or now - last_wake >= WAKE_MIN_INTERVAL_S


def throttle_note(thermal: int, wifi: int) -> str:
    """Texte court pour la barre de session quand les ips sont limitées automatiquement."""
    parts = []
    if thermal:
        parts.append(f"ips limités à {LEVEL_CAPS[thermal]} (chauffe)")
    if wifi:
        parts.append(f"ips limités à {LEVEL_CAPS[wifi]} (Wi-Fi)")
    return " · ".join(parts)
