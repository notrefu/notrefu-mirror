"""Son du téléphone : flux PCM brut (16 bits, 48 kHz, stéréo) envoyé à `paplay` ou `pw-cat` du système."""

from __future__ import annotations

import shutil
import sys
import time
import socket
import subprocess
import threading
from collections.abc import Callable

from . import protocol as P
from .engine import recv_exact

DEFAULT_LATENCY_MS = 120  # tampon du lecteur : trop bas = grésillements, trop haut = son en retard


def players(latency_ms: int) -> tuple[list[str], ...]:
    return (
        ["paplay", "--raw", "--format=s16le", "--rate=48000", "--channels=2", f"--latency-msec={latency_ms}"],
        ["pw-cat", "--playback", "--format", "s16", "--rate", "48000", "--channels", "2",
         "--latency", f"{latency_ms}ms", "-"],
    )


def find_player(latency_ms: int = DEFAULT_LATENCY_MS) -> list[str] | None:
    for cmd in players(latency_ms):
        path = shutil.which(cmd[0])
        if path:
            return [path, *cmd[1:]]
    return None


def apply_gain(data: bytes, percent: int) -> bytes:
    """Volume logiciel sur du PCM s16le : courbe quadratique (plus naturelle à l'oreille)."""
    if percent >= 100:
        return data
    if percent <= 0:
        return bytes(len(data))
    from array import array
    import sys

    a = array("h")
    a.frombytes(data[: len(data) // 2 * 2])
    if sys.byteorder == "big":
        a.byteswap()
    f = (percent / 100) ** 2
    a = array("h", (int(x * f) for x in a))
    if sys.byteorder == "big":
        a.byteswap()
    return a.tobytes()


def run_audio(
    sock: socket.socket,
    stop: threading.Event,
    log: Callable[[str], None],
    wants_audio: Callable[[], bool] = lambda: True,
    env: dict[str, str] | None = None,
    player: list[str] | None = None,
    latency_ms: int = DEFAULT_LATENCY_MS,
    status: Callable[[str], None] = lambda _s: None,
    gain: Callable[[], int] = lambda: 100,
    tap: Callable[[bytes, int], None] | None = None,
) -> None:
    """Lit le flux audio jusqu'à l'arrêt. Lève une exception explicite si le son est impossible."""
    codec = int.from_bytes(recv_exact(sock, 4), "big")
    if codec in (0, 1):
        raise RuntimeError("le téléphone ne peut pas capturer le son (Android 11 ou plus récent requis)")
    if codec != P.CODEC_RAW:
        raise RuntimeError(f"codec audio non géré : 0x{codec:08x}")
    cmd = player or find_player(latency_ms)
    max_backlog = latency_ms / 1000 + 0.25  # retard toléré avant d'abandonner des paquets
    if cmd:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        log(f"[audio] lecture via {cmd[0]}")
    elif sys.platform == "win32":
        from .winaudio import WavePlayer, WinAudioError

        try:
            proc = WavePlayer(latency_ms)
        except WinAudioError as exc:
            raise RuntimeError(str(exc)) from None
        log("[audio] lecture via winmm (waveOut)")
    else:
        raise RuntimeError("aucun lecteur audio (paplay / pw-cat) trouvé sur ce système")
    status("en attente du téléphone")
    got_packets = threading.Event()

    def watchdog() -> None:
        if not got_packets.wait(6) and not stop.is_set():
            status("aucun paquet reçu du téléphone")
            log("[audio] aucun paquet audio reçu en 6 s (le téléphone n'envoie rien)")

    threading.Thread(target=watchdog, name="audio-watchdog", daemon=True).start()
    loud = False  # du son réel (pas du silence) reçu depuis le dernier point
    announced = False
    bytes_per_s = P.AUDIO_RATE * P.AUDIO_CHANNELS * 2
    clock = 0.0  # instant (monotonic) où le lecteur aura fini de jouer tout ce qu'on lui a donné
    # Dérive amont : si les paquets arrivent plus tard que leur horodatage (réseau/adb/serveur en retard),
    # le retard s'accumule avant même d'arriver ici ; on le détecte avec l'horodatage du téléphone.
    pts0 = t0 = None
    played = dropped = 0
    last_arrival = time.monotonic()
    max_gap = max_lag = 0.0
    report_at = time.monotonic() + 10
    try:
        assert proc.stdin is not None
        while not stop.is_set():
            header = P.parse_packet_header(recv_exact(sock, P.PACKET_HEADER_SIZE))
            if isinstance(header, P.SessionPacket):
                continue
            if header.size > P.MAX_PACKET_SIZE:
                raise EOFError("flux audio corrompu")
            data = recv_exact(sock, header.size)
            if not header.config:
                got_packets.set()
                if data.count(0) != len(data):
                    loud = True
                    if not announced:
                        announced = True
                        status("actif")
            if tap is not None and not header.config:
                tap(data, header.pts)  # enregistrement : même si l'onglet est masqué
            if header.config or not wants_audio():
                continue  # onglet masqué : on lit le flux mais on ne le joue pas
            now = time.monotonic()
            max_gap = max(max_gap, now - last_arrival)
            last_arrival = now
            if pts0 is None:
                pts0, t0 = header.pts, now
            lag = (now - t0) - (header.pts - pts0) / 1e6  # >0 : on reçoit en retard sur le téléphone
            max_lag = max(max_lag, lag)
            if lag > max_backlog:
                dropped += 1
                if lag > 2 * max_backlog:  # très en retard : on se recale sur le flux actuel
                    pts0, t0 = header.pts, now
                continue
            if lag < 0:  # horloges légèrement décalées : on se recale
                pts0, t0 = header.pts, now
            if clock < now:
                clock = now  # le lecteur a tout joué : pas de retard
            elif clock - now > max_backlog:
                dropped += 1
                continue  # retard accumulé : on saute ce morceau plutôt que de décaler le son de plus en plus
            clock += len(data) / bytes_per_s
            played += 1
            try:
                proc.stdin.write(apply_gain(data, gain()))
                proc.stdin.flush()
            except (BrokenPipeError, OSError):
                raise RuntimeError("le lecteur audio s'est arrêté") from None
            if now >= report_at:
                status("actif" if loud else "silence reçu (jeu muet ou capture bloquée par le téléphone)")
                loud = False
                log(f"[audio] 10 s : joués={played} abandonnés={dropped} "
                    f"écart max entre paquets={max_gap * 1000:.0f} ms retard max={max_lag * 1000:.0f} ms")
                played = dropped = 0
                max_gap = max_lag = 0.0
                report_at = now + 10
    finally:
        try:
            proc.stdin.close()  # type: ignore[union-attr]
        except OSError:
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
