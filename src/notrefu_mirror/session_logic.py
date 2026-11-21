"""Règles de session sans Qt : paramètres du client, politique de reconnexion, filet de sécurité de la résolution.

Extrait de `PhonePanel` (start, _schedule_retry, _restore_wm_if_changed). Le panneau ne garde que l'affichage
(textes, boutons, minuteur) ; les décisions sont ici et se testent sans fenêtre ni téléphone.
"""

from __future__ import annotations

from dataclasses import dataclass

from .adb import wifi_target  # noqa: F401  (réexporté : utilisé par le panneau et les tests)
from .engine import ClientParams
from .scrcpy_cmd import Settings

MAX_ATTEMPTS = 60
ATTEMPT_TIMEOUT_S = 45  # une tentative (démarrage complet) qui dépasse ce délai est abandonnée puis recommencée


def build_client_params(s: Settings, *, max_size: int, new_display: str, audio_latency_ms: int,
                        game_audio: bool, quiet_notifications: bool, game_mode: str) -> ClientParams:
    return ClientParams(
        serial=s.serial, video_bit_rate=int(s.bitrate_mbps) * 1_000_000, max_fps=int(s.fps), max_size=max_size,
        new_display=new_display, app_package=s.app_package.strip() if s.reopen_app else "",
        audio=s.audio, show_touches=s.show_touches, stay_awake=s.stay_awake,
        power_off_on_close=s.power_off_on_close, turn_screen_off=s.screen_off, clipboard=s.clipboard,
        audio_latency_ms=audio_latency_ms, audio_source="playback" if game_audio else "",
        quiet_notifications=quiet_notifications, game_mode=game_mode,
    )


@dataclass(frozen=True)
class RetryDecision:
    attempt: int
    delay_s: int


NOT_READY_STATES = ("offline", "unauthorized")
NOT_READY_DELAYS_S = (3, 5, 8)  # appareil en veille profonde / pas encore autorisé : on espace, plafonné à 8 s


class ReconnectPolicy:
    """Quand et combien de temps attendre avant de rétablir une session dont la connexion a sauté."""

    def __init__(self) -> None:
        self.user_stop = False
        self.chain = False  # la session a été connectée au moins une fois
        self.attempts = 0
        self.gave_up = False
        self.not_ready = 0  # essais consécutifs alors que l'appareil est « offline » / « unauthorized »

    def reset(self) -> None:
        """Démarrage voulu par l'utilisateur."""
        self.user_stop, self.chain, self.attempts, self.gave_up = False, False, 0, False
        self.not_ready = 0

    def device_ready(self) -> None:
        """L'appareil est repassé à « device » : le délai progressif repart de zéro."""
        self.not_ready = 0

    def connected(self) -> None:
        self.chain, self.attempts, self.not_ready = True, 0, 0

    def next_retry(self, enabled: bool, device_state: str | None = None) -> RetryDecision | None:
        self.gave_up = False
        if self.user_stop or not self.chain or not enabled:
            return None
        if self.attempts >= MAX_ATTEMPTS:
            self.gave_up = True
            return None
        self.attempts += 1
        if device_state in NOT_READY_STATES:
            self.not_ready += 1
            return RetryDecision(self.attempts, NOT_READY_DELAYS_S[min(self.not_ready, len(NOT_READY_DELAYS_S)) - 1])
        self.not_ready = 0
        return RetryDecision(self.attempts, min(2 + self.attempts, 8))


@dataclass(frozen=True)
class WmFix:
    size: str | None = None  # valeur à remettre (None = ne pas toucher)
    density: int | None = None
    fix_size: bool = False
    fix_density: bool = False

    def __bool__(self) -> bool:
        return self.fix_size or self.fix_density


def wm_fix(base: tuple[str | None, str | None], now: tuple[str | None, str | None]) -> WmFix:
    """Compare la résolution/densité d'avant la session et d'après ; dit ce qu'il faut remettre."""
    fix_size, fix_density = now[0] != base[0], now[1] != base[1]
    dens = int(base[1]) if base[1] and base[1].isdigit() else None
    return WmFix(base[0], dens, fix_size, fix_density)


def stop_clients(clients, timeout_s: float, clock=None) -> int:
    """Arrête plusieurs sessions EN PARALLÈLE : on demande l'arrêt à toutes, puis on attend leur nettoyage
    avec un délai total (et non 4 s par session les unes après les autres). Renvoie le nombre de sessions
    qui n'avaient pas fini à l'échéance."""
    import time

    now = clock or time.monotonic
    clients = [c for c in clients if c is not None]
    for c in clients:
        try:
            c.stop(wait=0)
        except Exception:  # noqa: BLE001  une session récalcitrante ne doit pas empêcher d'arrêter les autres
            pass
    deadline = now() + timeout_s
    late = 0
    for c in clients:
        if not c.wait_stopped(deadline - now()):
            late += 1
    return late


_REASONS = (
    (("délai dépassé", "timed out", "pas de réponse"), "délai dépassé"),
    (("address already in use", "already in use", "cannot bind", "port occupé", "bind failed"), "port occupé"),
    (("unauthorized", "non autoris"), "appareil non autorisé (accepter le débogage sur le téléphone)"),
    (("offline", "hors ligne"), "appareil hors ligne"),
    (("not found", "introuvable", "no devices", "missing", "absent"), "appareil introuvable"),
    (("refused", "refusée", "connection reset", "connexion fermée"), "connexion refusée ou coupée"),
)


def failure_reason(detail: str) -> str:
    """Raison courte et stable d'un échec de tentative (pour la ligne de journal « [reconnexion] … »)."""
    low = (detail or "").lower()
    for needles, label in _REASONS:
        if any(n in low for n in needles):
            return label
    return "erreur"
