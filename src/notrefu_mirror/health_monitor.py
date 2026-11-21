"""Suivi de la santé du téléphone et état des onglets, sans Qt.

Extrait de `MainWindow` (_poll_health, _health_done, _tick) : qui interroger, quelles alertes envoyer (et pas trop souvent),
quel texte afficher dans l'info-bulle d'un onglet.
"""

from __future__ import annotations

from . import phonehealth

LIGHT_POLL_S = 5  # relevé léger (CPU/RAM par /proc)
FULL_EVERY_S = 60  # relevé complet (batterie, chauffe, stockage) : change lentement
GAME_RAM_EVERY_S = 120  # `dumpsys meminfo <paquet>` : la commande la plus lourde, donc la plus espacée
HIDDEN_POLL_S = 15  # session non visible (onglet inactif, fenêtre réduite) : relevé léger plus rare
ALERT_GRAVE_S = 300  # une alerte grave peut revenir au bout de 5 min
ALERT_OTHER_S = 900  # les autres au bout de 15 min


class HealthMonitor:
    def __init__(self) -> None:
        self.health: dict[str, phonehealth.Health] = {}
        self._busy: set[str] = set()
        self._alerted: dict[tuple[str, str], float] = {}
        self._last_full: dict[str, float] = {}
        self._last_game: dict[str, float] = {}
        self._last_poll: dict[str, float] = {}

    def wants_full(self, serial: str, now: float) -> bool:
        """Relevé complet si aucun n'a eu lieu depuis FULL_EVERY_S (ou jamais) ; sinon relevé léger."""
        last = self._last_full.get(serial)
        return last is None or now - last >= FULL_EVERY_S - 0.5

    def wants_game(self, serial: str, now: float) -> bool:
        """RAM du jeu seul : au plus toutes les GAME_RAM_EVERY_S (et pas à chaque relevé complet)."""
        last = self._last_game.get(serial)
        return last is None or now - last >= GAME_RAM_EVERY_S - 0.5

    def game_read(self, serial: str, now: float) -> None:
        self._last_game[serial] = now

    def due(self, serial: str, now: float, visible: bool) -> bool:
        """Faut-il relever ce téléphone maintenant ? Visible : à chaque tick (5 s) ; masqué : toutes les 15 s."""
        last = self._last_poll.get(serial)
        return visible or last is None or now - last >= HIDDEN_POLL_S - 0.5

    def forget(self, serial: str) -> None:
        self._last_game.pop(serial, None)
        self._last_poll.pop(serial, None)
        self._last_full.pop(serial, None)
        self.health.pop(serial, None)
        self._busy.discard(serial)

    def to_poll(self, serials, now: float | None = None, visible=None) -> list[str]:
        """Téléphones à interroger maintenant (ceux dont une lecture n'est pas déjà en cours) ; les marque occupés.
        `visible` : ensemble des téléphones dont une session est à l'écran (None = tous)."""
        out = []
        for s in sorted(set(serials)):
            if s in self._busy:
                continue
            if now is not None and not self.due(s, now, visible is None or s in visible):
                continue
            self._busy.add(s)
            if now is not None:
                self._last_poll[s] = now
            out.append(s)
        return out

    def failed(self, serial: str) -> None:
        self._busy.discard(serial)

    def finish(self, serial: str, h: phonehealth.Health, now: float, full: bool = True) -> tuple[str, list[str]]:
        """Enregistre une lecture ; renvoie (résumé, alertes à montrer maintenant)."""
        self._busy.discard(serial)
        if full:
            self._last_full[serial] = now
            h = phonehealth.merge_full(self.health.get(serial), h)
        else:
            h = phonehealth.merge_light(self.health.get(serial), h)
        h.stamp = now
        self.health[serial] = h
        msgs = []
        for key, msg, grave in phonehealth.alerts(h):
            last = self._alerted.get((serial, key))
            if last is not None and now - last < (ALERT_GRAVE_S if grave else ALERT_OTHER_S):
                continue
            self._alerted[(serial, key)] = now
            msgs.append(msg)
        return h.summary(), msgs


def tab_status(reconnecting: bool, running: bool, health_text: str, play_seconds: float) -> tuple[str, str]:
    """(état, info-bulle) d'un onglet ; état = « warn » (reconnexion), « ok » (en cours) ou « muted » (arrêté)."""
    state = "warn" if reconnecting else "ok" if running else "muted"
    tip = "Reconnexion en cours…" if reconnecting else "Connecté" if running else "Arrêté"
    if running and health_text:
        tip += f" · {health_text}"
    if play_seconds >= 60:
        tip += f" · Temps de jeu : {phonehealth.format_duration(play_seconds)}"
    return state, tip


def audio_note(state: str) -> str:
    """Texte court pour la barre : rien quand tout va bien ; « silence » quand le jeu est muet (voulu ou non)."""
    if not state or state == "actif":
        return ""
    if state.startswith("silence"):
        return "son : silence"
    return f"son : {state}"


def stats_text(perf: str, audio_state: str, health: str, show_perf: bool, show_audio: bool, note: str = "") -> str:
    """Ligne d'état de la barre de session : le téléphone (batterie, température) d'abord, car c'est ce qu'on veut
    garder visible quand la place manque ; l'image par seconde et le son ensuite."""
    parts = [health] if health else []
    if note:  # limitation automatique des ips : toujours visible, c'est elle qui explique un jeu moins fluide
        parts.append(note)
    if show_perf and perf:
        parts.append(perf)
    note = audio_note(audio_state) if show_audio else ""
    if note:
        parts.append(note)
    return "  ·  ".join(parts)
