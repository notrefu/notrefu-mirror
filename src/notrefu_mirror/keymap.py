"""Touches personnalisées : une touche du clavier = UN appui tactile à un endroit précis de l'écran du jeu.

Ce module ne dépend pas de Qt (testable seul). Il contient :
  - `KeyMap`        : le modèle, des ratios (0..1) de l'image du téléphone, donc justes à toute taille de fenêtre ;
  - `KeyTranslator` : le traducteur « touche pressée -> un toucher », avec ses garde-fous.

Règle fondamentale (conditions d'utilisation du jeu : un clic physique = une action, sur un seul compte) :
  * une touche ne déclenche QU'UN toucher, jamais plusieurs (pas de macro, pas de séquence) ;
  * aucune répétition : la répétition automatique du clavier est ignorée, et la touche doit être relâchée
    avant de pouvoir agir de nouveau ;
  * aucune diffusion : le traducteur n'écrit que dans la session à laquelle il est rattaché (celle qui a le focus).
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import protocol as P

MAX_BINDINGS = 40
RESERVED_KEYS = frozenset({"Esc"})  # Échap quitte le mode édition / annule une saisie
MIN_PRESS_GAP_S = 0.06  # deux appuis de la même touche plus proches que ça = répétition parasite, pas un humain
MAX_HOLD_S = 3.0  # un relâchement perdu ne doit pas laisser un « doigt » posé sur l'écran
_POINTER_BASE = 0x4D440000  # identifiants de doigts réservés à cette fonction (distincts de la souris)


def _ratio(v: object) -> float | None:
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and 0.0 <= f <= 1.0 else None


def check_key_name(name: str, reserved: frozenset[str] | set[str] = RESERVED_KEYS) -> str | None:
    """Message d'erreur si `name` ne peut pas être une touche assignée, sinon None."""
    if not name or len(name) > 24 or not name.isprintable():
        return "touche invalide"
    if "+" in name.strip("+") or name in ("Ctrl", "Alt", "Shift", "Meta"):
        return "les combinaisons (Ctrl, Alt, Maj…) ne sont pas permises : une seule touche"
    if name in reserved:
        return f"la touche {name} est réservée"
    return None


@dataclass
class KeyMap:
    """Touche -> (x, y) en ratios de l'image du téléphone (0 = bord gauche/haut, 1 = bord droit/bas)."""

    keys: dict[str, tuple[float, float]]
    active: bool = True  # le mode jeu traduit les touches
    show: bool = True  # repères visibles sur le jeu

    def __init__(self) -> None:
        self.keys = {}
        self.active = True
        self.show = True

    def __len__(self) -> int:
        return len(self.keys)

    def set(self, name: str, x: float, y: float, reserved=RESERVED_KEYS) -> str | None:
        """Assigne (ou remplace) une touche ; renvoie un message d'erreur, ou None si c'est fait."""
        err = check_key_name(name, reserved)
        if err:
            return err
        rx, ry = _ratio(x), _ratio(y)
        if rx is None or ry is None:
            return "position hors de l'écran"
        if name not in self.keys and len(self.keys) >= MAX_BINDINGS:
            return f"maximum {MAX_BINDINGS} touches"
        self.keys[name] = (rx, ry)
        return None

    def remove(self, name: str) -> None:
        self.keys.pop(name, None)

    def clear(self) -> None:
        self.keys.clear()

    def key_at(self, x: float, y: float, radius: float) -> str | None:
        """Touche dont le repère est le plus proche de (x, y) à moins de `radius` (même unité que x, y)."""
        best, best_d = None, radius
        for name, (kx, ky) in self.keys.items():
            d = math.hypot(kx - x, ky - y)
            if d <= best_d:
                best, best_d = name, d
        return best

    # ---- sauvegarde (texte JSON, rangé dans les réglages de la session) ----
    def copy_keys_from(self, other: "KeyMap") -> int:
        """Recopie les touches d'une autre disposition (positions seulement : « actives » et « repères » ne changent pas).
        Chaque touche est revalidée. Ne fait que recopier : rien n'est envoyé à aucune session."""
        keep = (self.active, self.show)
        self.load_json(other.to_json())
        self.active, self.show = keep
        return len(self.keys)

    def to_json(self) -> str:
        return json.dumps({"v": 1, "active": self.active, "show": self.show,
                           "keys": {k: [round(x, 5), round(y, 5)] for k, (x, y) in sorted(self.keys.items())}},
                          ensure_ascii=False, separators=(",", ":"))

    def load_json(self, text: object) -> None:
        """Charge un texte JSON ; tout ce qui est abîmé est ignoré (jamais d'exception)."""
        self.keys.clear()
        self.active = self.show = True
        try:
            doc = json.loads(str(text)) if text else {}
        except (ValueError, RecursionError):
            return
        if not isinstance(doc, dict):
            return
        self.active = bool(doc.get("active", True))
        self.show = bool(doc.get("show", True))
        raw = doc.get("keys")
        if not isinstance(raw, dict):
            return
        for name, pos in raw.items():
            if isinstance(name, str) and isinstance(pos, (list, tuple)) and len(pos) == 2:
                self.set(name, pos[0], pos[1])  # set() revalide : touche et position


class KeyTranslator:
    """Traduit « touche pressée / relâchée » en un seul toucher DOWN puis UP, dans UNE session.

    `send(msg)` écrit dans le canal de contrôle de cette session ; `frame_size()` donne la taille de l'écran du
    téléphone (ou None si pas d'image). Aucun fil, aucun minuteur : tout se passe dans l'appel, sans bloquer.
    """

    def __init__(self, keymap: KeyMap, send: Callable[[bytes], None], frame_size: Callable[[], tuple[int, int] | None],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.keymap, self._send, self._frame_size, self._clock = keymap, send, frame_size, clock
        self._down: dict[str, tuple[int, int, int, float]] = {}  # touche -> (identifiant de doigt, x, y, instant)
        self._last_event: dict[str, float] = {}  # dernier appui OU relâchement vu pour chaque touche

    @property
    def holding(self) -> bool:
        return bool(self._down)

    def _free_pointer(self) -> int:
        used = {p for p, *_ in self._down.values()}
        return next(_POINTER_BASE + i for i in range(MAX_BINDINGS + 1) if _POINTER_BASE + i not in used)

    def press(self, name: str, auto_repeat: bool = False) -> bool:
        """True si la touche est assignée (l'événement est alors « consommé », même s'il est ignoré)."""
        if not self.keymap.active or name not in self.keymap.keys:
            return False
        now = self._clock()
        size = self._frame_size()
        last = self._last_event.get(name)
        self._last_event[name] = now  # même un appui ignoré compte : un flux rapide d'appuis ne passe jamais
        if auto_repeat or name in self._down or not size:
            return True  # répétition automatique, ou touche déjà enfoncée : rien n'est envoyé
        if last is not None and now - last < MIN_PRESS_GAP_S:
            return True  # relâché/pressé à la même milliseconde = répétition parasite, pas un humain
        w, h = size
        rx, ry = self.keymap.keys[name]
        x, y = min(int(rx * w), w - 1), min(int(ry * h), h - 1)
        pid = self._free_pointer()
        self._down[name] = (pid, x, y, now)
        self._send(P.inject_touch_event(P.ACTION_DOWN, pid, x, y, w, h, 1.0, P.BUTTON_PRIMARY, P.BUTTON_PRIMARY))
        return True

    def release(self, name: str) -> bool:
        """Relâchement : lève le doigt posé par `press` (un seul UP par DOWN). True si la touche est assignée."""
        self._last_event[name] = self._clock()
        entry = self._down.pop(name, None)
        if entry is None:
            return name in self.keymap.keys and self.keymap.active
        self._send_up(entry)
        return True

    def _send_up(self, entry: tuple[int, int, int, float]) -> None:
        pid, x, y, _t = entry
        size = self._frame_size()
        w, h = size if size else (x + 1, y + 1)
        self._send(P.inject_touch_event(P.ACTION_UP, pid, x, y, w, h, 0.0, P.BUTTON_PRIMARY, 0))

    def release_all(self) -> None:
        """Perte du focus, session arrêtée, mode édition : plus aucun doigt ne doit rester posé."""
        entries, self._down = list(self._down.values()), {}
        for e in entries:
            self._send_up(e)

    def expire(self) -> None:
        """Relâche les touches enfoncées depuis plus de MAX_HOLD_S (relâchement perdu)."""
        now = self._clock()
        for name in [n for n, e in self._down.items() if now - e[3] > MAX_HOLD_S]:
            self._send_up(self._down.pop(name))
