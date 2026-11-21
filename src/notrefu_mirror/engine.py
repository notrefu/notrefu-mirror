"""Client scrcpy intégré : lance le serveur sur le téléphone, reçoit la vidéo H.264, envoie les commandes.

Pas de dépendance Qt : l'interface s'abonne via des callbacks (appelés depuis des threads du moteur).
Fonctionnement (voir protocol.py pour le détail des octets) :
  1. push de scrcpy-server sur le téléphone, redirection adb `forward`, lancement du serveur via `app_process` ;
  2. connexion TCP locale : socket vidéo (1 octet factice puis 64 octets de nom d'appareil),
     (socket audio optionnelle), socket de contrôle ;
  3. thread vidéo : paquets H.264 -> décodage PyAV -> image RGB ; thread contrôle : messages -> socket.
"""

from __future__ import annotations

import os
import queue
import random
import select
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from typing import Callable, Protocol

from . import adb, compat, power
from . import protocol as P



def remux_h264(raw: str, pts: list[int], out: str, pcm: str = "", apkts: list[tuple[int, int]] | None = None) -> None:
    """Range le flux H.264 brut (et le son PCM s16le 48 kHz stéréo, s'il y en a) dans un Matroska, horodatages d'origine."""
    import av
    from fractions import Fraction

    tb = Fraction(1, 1_000_000)
    inp = av.open(raw, format="h264")
    ins = inp.streams.video[0]
    outc = av.open(out, "w", format="matroska")
    outs = outc.add_stream_from_template(ins)
    pkts = [p for p in inp.demux(ins) if p.size]
    exact = len(pkts) == len(pts)
    base = pts[0] if pts else 0
    items: list[tuple[int, int, object, object]] = []
    for i, p in enumerate(pkts):
        t = (pts[i] - base) if exact else int(i * 1_000_000 / 30)
        items.append((t, 0, p, outs))
    if pcm and apkts:
        aout = outc.add_stream("pcm_s16le", rate=P.AUDIO_RATE)
        aout.layout = "stereo"
        with open(pcm, "rb") as f:
            for apts, size in apkts:
                data = f.read(size)
                t = apts - base
                if t < 0 or len(data) != size:
                    continue  # son d'avant la première image : ignoré
                items.append((t, 1, data, aout))
    items.sort(key=lambda x: (x[0], x[1]))
    for t, kind, obj, stream in items:
        if kind == 0:
            pk = obj
        else:
            pk = av.Packet(obj)
        pk.time_base = tb
        pk.pts = pk.dts = t
        pk.stream = stream
        outc.mux(pk)
    outc.close()
    inp.close()


class EngineError(RuntimeError):
    pass


@dataclass
class ClientParams:
    serial: str = ""
    video_bit_rate: int = 6_000_000
    max_fps: int = 60
    max_size: int = 0
    new_display: str = ""  # « 1920x1080/280 » : écran virtuel horizontal
    app_package: str = ""
    audio: bool = False
    show_touches: bool = False
    stay_awake: bool = False
    power_off_on_close: bool = False
    turn_screen_off: bool = False
    audio_latency_ms: int = 120
    game_mode: str = ""  # standard / performance / battery (mode jeu Android) ; vide = ne pas toucher
    quiet_notifications: bool = False  # « Ne pas déranger » (prioritaire) sur le téléphone pendant la session
    audio_source: str = ""  # « playback » = son du jeu seul (Android 13+) ; vide = tout le son du téléphone
    clipboard: bool = False  # synchronisation du presse-papiers téléphone -> PC (le PC -> téléphone est envoyé par la vue)
    log_level: str = "info"
    fallback: int = 0  # niveau de repli vidéo (0 = réglages demandés ; 1, 2 = profil compatible, voir compat.video_fallback)


class VideoStartError(EngineError):
    """Le flux vidéo n'a jamais démarré (encodeur refusé, serveur arrêté, aucune image) : un repli est possible."""


@dataclass
class Connection:
    video: socket.socket
    control: socket.socket
    audio: socket.socket | None
    device_name: str
    close_extra: Callable[[], None]
    notes: tuple[str, ...] = ()  # informations discrètes pour l'interface (ex. « Audio désactivé automatiquement… »)


@dataclass(frozen=True)
class Frame:
    """Image RGB888 prête à afficher (peut avoir été réduite à la taille de la vue)."""

    width: int
    height: int
    stride: int
    data: "bytes | memoryview"  # mémoire de l'image RGB (sans copie : `keep` garde la trame PyAV en vie)
    source_width: int  # taille de l'écran du téléphone (pour convertir les clics)
    source_height: int
    keep: object = None


class Transport(Protocol):
    def open(self, params: ClientParams, scid: int, stop: threading.Event, log: Callable[[str], None]) -> Connection: ...


def recv_exact(sock: socket.socket, n: int) -> bytes:
    chunks = []
    remaining = n
    while remaining:
        chunk = sock.recv(min(remaining, 1 << 20))
        if not chunk:
            raise EOFError("connexion fermée")
        chunks.append(chunk)
        remaining -= len(chunk)
    return chunks[0] if len(chunks) == 1 else b"".join(chunks)


HANDSHAKE_TIMEOUT_S = 20.0
FIRST_VIDEO_TIMEOUT_S = 10.0  # le flux vidéo doit démarrer dans ce délai, sinon repli sur un profil compatible


def recv_handshake(sock: socket.socket, n: int, stop: threading.Event, timeout_s: float = HANDSHAKE_TIMEOUT_S) -> bytes:
    """Comme recv_exact, mais pour la poignée de main : s'interrompt dès que `stop` est levé et abandonne après
    `timeout_s`. Sans cela, un serveur qui accepte la connexion (le tunnel adb accepte toujours) sans jamais répondre
    bloquait la session pour toujours, et « Arrêter » restait sans effet car les sockets n'étaient pas encore connus."""
    deadline = time.monotonic() + timeout_s
    chunks: list[bytes] = []
    remaining = n
    sock.settimeout(1.0)
    try:
        while remaining:
            if stop.is_set():
                raise EOFError("arrêt demandé")
            if time.monotonic() > deadline:
                raise EOFError(f"pas de réponse du téléphone en {timeout_s:.0f} s")
            try:
                chunk = sock.recv(remaining)
            except socket.timeout:
                continue
            if not chunk:
                raise EOFError("connexion fermée")
            chunks.append(chunk)
            remaining -= len(chunk)
    finally:
        try:
            sock.settimeout(None)
        except OSError:
            pass
    return b"".join(chunks)


# =============================================================================
# Transports
# =============================================================================
HW_DECODE_ENABLED = True  # décodage matériel du GPU quand c'est possible (Windows : d3d11va/dxva2 ; Linux : vaapi/cuda) ; la fenêtre principale le pilote (menu Réglages)
HW_DEVICES_WIN = ("d3d11va", "dxva2")  # ordre d'essai sous Windows
HW_DEVICES_LINUX = ("vaapi", "cuda")  # VAAPI (Intel/AMD) puis NVDEC (NVIDIA)


def hw_devices() -> tuple[str, ...]:
    return HW_DEVICES_WIN if sys.platform == "win32" else HW_DEVICES_LINUX if sys.platform.startswith("linux") else ()


HW_DEVICES = hw_devices()

STALE_CONTROL_S = 1.0  # une action en attente depuis plus longtemps n'est plus envoyée (sauf relâchement)
CONNECT_TIMEOUT_S = 12.0  # le serveur du téléphone doit répondre dans ce délai (avant : jusqu'à ~7 minutes)


def _connect_first(host: str, port: int, stop: threading.Event, alive: Callable[[], bool], timeout_s: float = CONNECT_TIMEOUT_S) -> socket.socket:
    """Se connecte et lit l'octet factice (la connexion adb réussit même si le serveur n'écoute pas encore)."""
    last: Exception | None = None
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if stop.is_set():
            raise EngineError("arrêt demandé")
        if not alive():
            raise EngineError("le serveur scrcpy s'est arrêté pendant le démarrage")
        try:
            sock = socket.create_connection((host, port), timeout=2)
            sock.settimeout(2)
            if sock.recv(1) == b"\0":
                sock.settimeout(None)
                return sock
            sock.close()
        except OSError as exc:
            last = exc
        time.sleep(0.1)
    raise EngineError(f"délai dépassé : le serveur scrcpy n'a pas répondu en {timeout_s:.0f} s ({last or 'aucune réponse'})")


def _open_sockets(host: str, port: int, params: ClientParams, stop, alive) -> tuple[socket.socket, socket.socket | None, socket.socket]:
    video = _connect_first(host, port, stop, alive)
    audio = control = None
    try:
        if params.audio:
            audio = socket.create_connection((host, port), timeout=5)
            audio.settimeout(None)
        control = socket.create_connection((host, port), timeout=5)
        control.settimeout(None)
        control.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except OSError:
        for s in (video, audio, control):
            if s:
                s.close()
        raise
    return video, audio, control


class TcpTransport:
    """Serveur déjà en écoute sur host:port (tests, ou `adb forward` fait à la main)."""

    def __init__(self, host: str = "127.0.0.1", port: int = 27183) -> None:
        self.host, self.port = host, port

    def open(self, params, scid, stop, log) -> Connection:
        video, audio, control = _open_sockets(self.host, self.port, params, stop, lambda: True)
        name = P.parse_device_name(recv_handshake(video, P.DEVICE_NAME_FIELD_LENGTH, stop))
        return Connection(video, control, audio, name, lambda: None)


class AdbTransport:
    def __init__(self, adb: str, server_path: str, env: dict[str, str]) -> None:
        self.adb, self.server_path, self.env = adb, server_path, env
        self.note: Callable[[str], None] = lambda _m: None  # journal de la session (posé par open)

    def _run(self, args: list[str], timeout: float = 10) -> str:
        """Commande adb à délai strict (voir adb.run_cmd) ; toute erreur devient une EngineError lisible."""
        what = " ".join(a for a in args if a != "-s")[:60]
        for attempt in (1, 2):
            try:
                code, out = adb.run_cmd([self.adb, *args], timeout, self.env)
            except subprocess.TimeoutExpired:
                raise EngineError(f"délai dépassé après {timeout:.0f} s : adb {what}") from None
            except OSError as exc:
                raise EngineError(f"adb n'a pas pu être lancé : {exc}") from exc
            # un autre adb (émulateur…) tient le port 5037 avec une autre version : on relance le serveur avec le nôtre, une fois
            if adb.server_conflict(out) and attempt == 1 and adb.restart_server(self.adb, self.env, self.note):
                continue
            break
        if adb.server_conflict(out):
            raise EngineError(f"adb : {adb.CONFLICT_HINT}")
        if code != 0:
            raise EngineError(out.strip() or f"adb {what} a échoué")
        return out.strip()

    # Sessions vivantes de cette application (scid) : tout serveur/tunnel scrcpy qui n'en fait pas partie est un reste
    # d'une session coupée à nettoyer avant de réessayer.
    _live_scids: set[int] = set()
    _live_lock = threading.Lock()

    def preflight(self, serial: str, log: Callable[[str], None], stop: threading.Event) -> None:
        """Avant de relancer le serveur : l'appareil doit être « device ». En Wi-Fi, `adb disconnect` puis `adb connect`
        remettent à neuf une liaison fantôme ; en USB on demande à adb de reconnecter. Lève EngineError avec la raison."""
        target = adb.wifi_target(serial)

        def state() -> str:
            try:
                return adb.parse_device_state(self._run(["devices"], timeout=5), serial)
            except EngineError as exc:
                log(f"[connexion] liste des appareils impossible : {exc}")
                return "inconnu"

        def alive() -> bool:
            try:
                return self._run(["-s", serial, "shell", "echo", "ok"], timeout=5) == "ok"
            except EngineError as exc:
                log(f"[connexion] l'appareil ne répond pas : {exc}")
                return False

        st = state()
        if st == "device" and alive():
            return
        log(f"[connexion] état de l'appareil {serial} : {st}")
        if st in ("unauthorized", "no permissions"):
            raise EngineError(f"appareil non autorisé ({st}) : accepte le débogage sur le téléphone")
        for attempt in (1, 2):
            if stop.is_set():
                raise EngineError("arrêt demandé")
            if target:
                log(f"[connexion] Wi-Fi : adb disconnect puis adb connect {target[0]}:{target[1]} (essai {attempt}/2)")
                try:
                    self._run(["disconnect", f"{target[0]}:{target[1]}"], timeout=5)
                except EngineError as exc:
                    log(f"[connexion] adb disconnect : {exc}")
                try:
                    res = self._run(["connect", f"{target[0]}:{target[1]}"], timeout=8)
                    log(f"[connexion] adb connect : {res}")
                except EngineError as exc:
                    log(f"[connexion] adb connect a échoué : {exc}")
            elif st != "missing":
                try:
                    self._run(["-s", serial, "reconnect"], timeout=6)
                except EngineError as exc:
                    log(f"[connexion] adb reconnect : {exc}")
            for _ in range(6):  # l'appareil met un instant à repasser « device »
                if stop.wait(0.5):
                    raise EngineError("arrêt demandé")
                st = state()
                if st == "device":
                    break
            if st == "device" and alive():
                log("[connexion] appareil de nouveau joignable")
                return
        reason = {"offline": "hors ligne (offline)", "missing": "introuvable (absent de adb devices)",
                  "unauthorized": "non autorisé"}.get(st, f"injoignable (état adb : {st})")
        raise EngineError(f"appareil {reason}")

    def cleanup_strays(self, serial: str, log: Callable[[str], None]) -> None:
        """Supprime les tunnels `adb forward` et les serveurs scrcpy laissés par une session coupée (hors sessions vivantes)."""
        with self._live_lock:
            live = set(self._live_scids)
        try:
            for spec, scid in adb.parse_scrcpy_forwards(self._run(["-s", serial, "forward", "--list"], timeout=5)):
                if scid not in live:
                    self._run(["-s", serial, "forward", "--remove", spec], timeout=5)
                    log(f"[nettoyage] tunnel orphelin {spec} supprimé")
            self.kill_servers(serial, lambda scid: scid not in live, log)
        except EngineError as exc:
            log(f"[nettoyage] ignoré : {exc}")

    def kill_servers(self, serial: str, which: Callable[[int], bool], log: Callable[[str], None]) -> None:
        for pid, scid in adb.parse_scrcpy_servers(self._run(["-s", serial, "shell", "ps", "-A", "-o", "PID,ARGS"], timeout=5)):
            if which(scid):
                self._run(["-s", serial, "shell", "kill", str(pid)], timeout=4)
                log(f"[nettoyage] serveur scrcpy {scid:08x} (pid {pid}) arrêté sur le téléphone")

    # « Ne pas déranger » : partagé entre les sessions d'un même téléphone (le premier l'active, le dernier le rétablit)
    _dnd: dict[str, list] = {}
    _dnd_lock = threading.Lock()
    _ZEN = {"0": "off", "1": "priority", "2": "none", "3": "alarms"}

    def _dnd_acquire(self, serial: str, log: Callable[[str], None]) -> bool:
        with self._dnd_lock:
            entry = self._dnd.get(serial)
            if entry:
                entry[0] += 1
                return True
            try:
                prev = self._run(["-s", serial, "shell", "settings", "get", "global", "zen_mode"], timeout=8).strip()
                self._run(["-s", serial, "shell", "cmd", "notification", "set_dnd", "priority"], timeout=8)
            except (EngineError, subprocess.SubprocessError):
                log("[notifications] impossible de passer le téléphone en « Ne pas déranger » (ignoré)")
                return False
            self._dnd[serial] = [1, self._ZEN.get(prev, "off") if prev != "1" else None]
            log("[notifications] « Ne pas déranger » activé pendant la session (rétabli à l'arrêt)")
            return True

    def _dnd_release(self, serial: str, log: Callable[[str], None]) -> None:
        with self._dnd_lock:
            entry = self._dnd.get(serial)
            if not entry:
                return
            entry[0] -= 1
            if entry[0] > 0:
                return
            del self._dnd[serial]
            if entry[1]:
                try:
                    self._run(["-s", serial, "shell", "cmd", "notification", "set_dnd", entry[1]], timeout=8)
                    log("[notifications] « Ne pas déranger » rétabli")
                except (EngineError, subprocess.SubprocessError):
                    log("[notifications] impossible de rétablir « Ne pas déranger » : à régler à la main sur le téléphone")

    def open(self, params: ClientParams, scid: int, stop: threading.Event, log: Callable[[str], None]) -> Connection:
        serial = params.serial
        self.note = log
        self.preflight(serial, log, stop)  # appareil « device » ? sinon reconnexion adb (Wi-Fi : disconnect puis connect)
        self.cleanup_strays(serial, log)  # restes (tunnels, serveurs) d'une session coupée
        notes: list[str] = []
        try:
            sdk = int(self._run(["-s", serial, "shell", "getprop", "ro.build.version.sdk"], timeout=5).strip() or 0)
        except (EngineError, ValueError):
            sdk = 0
        if params.audio and not compat.audio_supported(sdk):
            params = replace(params, audio=False)  # Android 10 et moins : pas de capture du son ; sans cela le serveur plante au démarrage
            notes.append(compat.AUDIO_OFF_NOTE)
            log(f"[audio] {compat.AUDIO_OFF_NOTE} (Android SDK {sdk})")
        bit_rate, fps, max_size, codec_opts = compat.video_fallback(
            params.fallback, params.video_bit_rate, params.max_fps, params.max_size, "i-frame-interval:int=2")
        new_display = params.new_display
        if params.fallback > 0:
            new_display = compat.shrink_display(new_display, max_size or 1280)
            notes.append("Vidéo : profil compatible (H.264 Baseline, débit réduit)")
            log(f"[vidéo] repli niveau {params.fallback} : {bit_rate // 1000} kbit/s, {fps} ips, "
                f"{new_display or ('≤ ' + str(max_size) + ' px')}, {codec_opts}")
        sp = P.ServerParams(
            scid=scid,
            video_bit_rate=bit_rate,
            max_fps=fps,
            max_size=max_size,
            new_display=new_display,
            audio=params.audio,
            show_touches=params.show_touches,
            stay_awake=params.stay_awake,
            power_off_on_close=params.power_off_on_close,
            log_level=params.log_level,
            clipboard_autosync=params.clipboard,
            video_codec_options=codec_opts,
        )
        if params.audio and params.audio_source:
            if sdk >= 33:
                sp.audio_source = params.audio_source
            else:
                log("[audio] « son du jeu seul » demande Android 13+ : tout le son du téléphone est transféré")
        args = P.build_server_args(sp)  # lève ValueError si un paramètre est suspect
        log(f"[audio] source : {sp.audio_source or 'tout le son du téléphone'}" if params.audio else "[audio] désactivé")
        dnd_held = False

        log("Envoi du serveur scrcpy sur le téléphone…")
        self._run(["-s", serial, "push", self.server_path, P.DEVICE_SERVER_PATH], timeout=30)
        socket_name = f"localabstract:scrcpy_{scid:08x}"
        port_text = self._run(["-s", serial, "forward", "tcp:0", socket_name], timeout=8)
        try:
            port = int(port_text.splitlines()[-1])
        except (ValueError, IndexError) as exc:
            raise EngineError(f"port adb inattendu : {port_text!r}") from exc
        with self._live_lock:
            self._live_scids.add(scid)
        server: subprocess.Popen | None = None

        def remove_forward() -> None:
            try:
                self._run(["-s", serial, "forward", "--remove", f"tcp:{port}"], timeout=5)
            except EngineError:
                pass

        def close_extra() -> None:
            """Nettoyage complet, identique pour « Arrêter » et pour chaque tentative de reconnexion : « Ne pas déranger »,
            tunnel adb, processus adb du serveur, puis serveur scrcpy resté sur le téléphone. Chaque étape est bornée."""
            nonlocal dnd_held
            if dnd_held:
                dnd_held = False
                self._dnd_release(serial, log)
            remove_forward()
            if server is not None and server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    server.kill()
            try:
                self.kill_servers(serial, lambda s: s == scid, log)
            except EngineError as exc:
                log(f"[nettoyage] serveur du téléphone non vérifié : {exc}")
            with self._live_lock:
                self._live_scids.discard(scid)

        try:
            if params.quiet_notifications:
                dnd_held = self._dnd_acquire(serial, log)
            server = subprocess.Popen(
                [self.adb, "-s", serial, "shell", f"CLASSPATH={P.DEVICE_SERVER_PATH}", "app_process", "/",
                 "com.genymobile.scrcpy.Server", P.SCRCPY_VERSION, *args],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=self.env,
            )
            srv = server

            def pump() -> None:
                assert srv.stdout is not None
                for line in srv.stdout:
                    line = line.rstrip()
                    if line:
                        log(line)

            threading.Thread(target=pump, name="scrcpy-server-log", daemon=True).start()

            log("Connexion au serveur…")
            video, audio, control = _open_sockets("127.0.0.1", port, params, stop, lambda: srv.poll() is None)
            remove_forward()  # le tunnel n'est plus utile une fois les sockets ouvertes
            try:
                name = P.parse_device_name(recv_handshake(video, P.DEVICE_NAME_FIELD_LENGTH, stop))
            except (OSError, EOFError) as exc:
                for sk in (video, audio, control):
                    if sk:
                        sk.close()
                raise EngineError(f"délai dépassé ou coupure : le serveur n'a pas envoyé les informations de l'appareil ({exc})") from exc
        except BaseException:
            close_extra()
            raise
        return Connection(video, control, audio, name, close_extra, tuple(notes))


# =============================================================================
# Client
# =============================================================================
_BG_LOCK = threading.Lock()
_BG_THREADS: list[threading.Thread] = []  # conversions d'enregistrements en cours : à terminer avant de quitter


def join_background(timeout: float) -> bool:
    """Attend (au plus `timeout` s en tout) la fin des conversions d'enregistrement ; True si tout est fini."""
    deadline = time.monotonic() + timeout
    with _BG_LOCK:
        threads = list(_BG_THREADS)
    for t in threads:
        t.join(max(0.0, deadline - time.monotonic()))
    return not any(t.is_alive() for t in threads)


class ScrcpyClient:
    """Une session de mirroring. `start()` est non bloquant ; les événements arrivent par callbacks."""

    def __init__(
        self,
        params: ClientParams,
        transport: Transport,
        on_state: Callable[[str, str], None] | None = None,  # (état, détail) ; états : starting running stopped error
        on_log: Callable[[str], None] | None = None,
        on_frame: Callable[[], None] | None = None,
        wants_frames: Callable[[], bool] | None = None,
        on_clipboard: Callable[[str], None] | None = None,
        wants_audio: Callable[[], bool] | None = None,
        audio_gain: Callable[[], int] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.params = params
        self.transport = transport
        self._on_state = on_state or (lambda s, d: None)
        self._on_log = on_log or (lambda line: None)
        self._on_frame = on_frame or (lambda: None)
        self._wants_frames = wants_frames or (lambda: True)
        self._on_clipboard = on_clipboard or (lambda text: None)
        self._wants_audio = wants_audio or (lambda: True)
        self._audio_gain = audio_gain or (lambda: 100)
        self._env = env

        self.state = "idle"
        self.dropped_stale = 0  # actions abandonnées car trop anciennes
        self.hw_name = ""  # décodeur matériel actif (« d3d11va », « dxva2 ») ou vide = logiciel
        self._hw_failed = False
        self.auto_notes: list[str] = []  # infos discrètes pour l'interface (repli audio / vidéo automatique)
        self._abandoned = False
        self.device_name = ""
        self.source_size = (0, 0)
        self.decoded_frames = 0
        self._rec: dict | None = None
        self._rec_lock = threading.Lock()
        self.rx_bytes = 0  # octets vidéo reçus (pour le débit réel affiché)
        self.decode_ms = 0.0  # moyenne glissante du temps de décodage + conversion d'une image
        self.log_tail: deque[str] = deque(maxlen=40)
        self.caps = power.FpsCaps()  # plafonds d'ips (voir power.py) ; le plus bas s'applique
        self._last_paced = 0.0
        self._last_convert = 0.0
        self.close_app_on_stop = False  # posé par l'interface quand l'utilisateur arrête/supprime la session (pas pour un redémarrage)
        self._app_started = False
        self._cap_changed = 0.0
        self._flow = 0  # paquets vidéo consécutifs arrivés sans pause (détection de blocage réseau)
        self._burst_since = 0.0
        self._burst_n = 0
        self.stall_count = 0  # « silence puis rafale » : signe d'un Wi-Fi saturé
        self._stalls_read = 0

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._conn: Connection | None = None
        self._outbox: queue.Queue[tuple[float, bytes] | None] = queue.Queue()  # (heure d'entrée, message)
        self._frame_lock = threading.Lock()
        self._latest: Frame | None = None
        self._last_decoded = None  # dernière image décodée (av.VideoFrame), pour réafficher un onglet masqué
        self._view_size = (0, 0)
        self._finished = threading.Event()
        self.audio_state = ""  # état du son, affiché dans la barre d'outils
        self._audio_player: list[str] | None = None  # (tests) commande de lecture à la place de paplay

    # ---- API publique ---------------------------------------------------
    def start(self) -> None:
        if self._thread:
            raise EngineError("session déjà démarrée")
        self._set_state("starting", "")
        self._thread = threading.Thread(target=self._run, name="scrcpy-client", daemon=True)
        self._thread.start()

    def stop(self, wait: float = 4.0) -> None:
        self.stop_recording()
        self._stop.set()
        self._outbox.put(None)
        conn = self._conn
        if conn:
            for s in (conn.video, conn.audio, conn.control):
                if s:
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
        if self._thread and self._thread is not threading.current_thread():
            self._finished.wait(wait)

    def wait_stopped(self, timeout: float) -> bool:
        """Attend la fin du fil du client (nettoyage du serveur et du tunnel compris) ; True si terminé."""
        if not self._thread or self._thread is threading.current_thread():
            return True
        return self._finished.wait(max(0.0, timeout))

    @property
    def running(self) -> bool:
        return self.state == "running"

    def send(self, msg: bytes) -> None:
        """Envoie un message de contrôle (ignoré si la session n'est pas active)."""
        if self.state not in ("starting", "running"):
            return
        if self._outbox.qsize() > 200 and P.is_droppable_move(msg):
            return  # réseau en retard : on abandonne les déplacements (comme scrcpy)
        self._outbox.put((time.monotonic(), msg))

    def set_view_size(self, width: int, height: int) -> None:
        """Taille de la zone d'affichage (en pixels) : les images sont réduites à cette taille côté décodeur."""
        self._view_size = (max(0, int(width)), max(0, int(height)))

    def latest_frame(self) -> Frame | None:
        with self._frame_lock:
            return self._latest

    def refresh_frame(self) -> Frame | None:
        """Reconvertit la dernière image décodée (à appeler quand un onglet redevient visible)."""
        with self._frame_lock:
            decoded = self._last_decoded
        if decoded is None:
            return self.latest_frame()
        frame = self._convert(decoded)
        with self._frame_lock:
            self._latest = frame
        return frame

    @property
    def recording(self) -> bool:
        return self._rec is not None

    def start_recording(self, path: str) -> None:
        """Enregistre le flux vidéo H.264 reçu et le son du jeu ; à l'arrêt ils sont rangés dans un .mkv."""
        raw = path + ".h264.tmp"
        with self._rec_lock:
            self._rec = {"f": open(raw, "wb"), "pts": [], "raw": raw, "out": path, "started": False,
                         "af": open(path + ".pcm.tmp", "wb"), "apkts": [], "pcm": path + ".pcm.tmp"}
        self.reset_video()  # demande une image clé pour démarrer proprement

    def stop_recording(self) -> str | None:
        with self._rec_lock:
            rec, self._rec = self._rec, None
            if rec is None:
                return None
            rec["f"].close()
            rec["af"].close()

        def work() -> None:
            try:
                remux_h264(rec["raw"], rec["pts"], rec["out"], rec["pcm"], rec["apkts"])
                self._log(f"[enregistrement] terminé : {rec['out']}")
            except Exception as exc:  # noqa: BLE001
                self._log(f"[enregistrement] échec de la conversion : {exc} (flux brut conservé : {rec['raw']})")
                return
            for tmp in (rec["raw"], rec["pcm"]):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

        t = threading.Thread(target=work, name="recording-remux", daemon=True)
        with _BG_LOCK:
            _BG_THREADS[:] = [x for x in _BG_THREADS if x.is_alive()] + [t]
        t.start()
        return rec["out"]

    def _audio_tap(self, data: bytes, pts: int) -> None:
        rec = self._rec
        if rec is None or not rec["started"]:
            return
        with self._rec_lock:
            if self._rec is rec:
                rec["af"].write(data)
                rec["apkts"].append((pts, len(data)))

    def set_fps_cap(self, source: str, fps: int | None) -> None:
        """Limite la lecture du flux à `fps` images/s pour cette source (None = retire). Voir `power.py`."""
        if self.caps.set(source, fps):
            self._cap_changed = time.monotonic()

    def pop_stalls(self) -> int:
        """Nombre de blocages réseau détectés depuis le dernier appel."""
        n = self.stall_count - self._stalls_read
        self._stalls_read = self.stall_count
        return n

    def _note_arrival(self, gap: float, now: float) -> None:
        """Un long silence suivi d'une rafale de paquets d'un coup = le réseau a bloqué puis rattrapé son retard.
        (Un écran immobile donne aussi un silence, mais pas de rafale après.) Ignoré quand la lecture est freinée par nous."""
        if self.caps.effective() or now - self._cap_changed < 3.0:
            self._flow = 0
            self._burst_since = 0.0
            return
        if gap > 0.35 and self._flow >= 10:
            self._burst_since, self._burst_n = now, 0
        elif self._burst_since:
            if gap < 0.008 and now - self._burst_since < 0.25:
                self._burst_n += 1
                if self._burst_n >= 4:
                    self.stall_count += 1
                    self._burst_since = 0.0
            else:
                self._burst_since = 0.0
        self._flow = self._flow + 1 if gap < 0.1 else 0

    def reset_video(self) -> None:
        self.send(P.simple_message(P.MSG_RESET_VIDEO))

    # ---- interne --------------------------------------------------------
    def _set_state(self, state: str, detail: str = "") -> None:
        if self._abandoned:
            return  # tentative déclarée perdue : ses derniers événements ne comptent plus
        self.state = state
        self._on_state(state, detail)

    def abandon(self) -> None:
        """Tentative bloquée trop longtemps : on la déclare en erreur sur-le-champ (`running` redevient faux) et on lui
        demande de s'arrêter ; son fil termine seul le nettoyage en arrière-plan, sans plus rien signaler."""
        self._abandoned = True
        self.state = "error"
        self.stop(wait=0)

    def _log(self, line: str) -> None:
        self.log_tail.append(line)
        self._on_log(line)

    def _fail(self, detail: str) -> None:
        if self._stop.is_set():
            return
        self._set_state("error", detail)

    def _teardown(self, conn: Connection | None) -> None:
        """Ferme les sockets d'une connexion et fait le nettoyage côté téléphone (même chemin que « Arrêter »)."""
        if not conn:
            return
        for sk in (conn.video, conn.audio, conn.control):
            if sk:
                try:
                    sk.close()
                except OSError:
                    pass
        try:
            conn.close_extra()
        except Exception:  # noqa: BLE001
            pass

    def _open_with_fallback(self, scid: int) -> Connection:
        """Ouvre la session et attend le début du flux vidéo. Si l'encodeur ou le débit est trop exigeant pour l'appareil
        (tablettes MediaTek / Unisoc : le serveur s'arrête ou n'envoie aucune image), on recommence automatiquement avec
        un profil H.264 compatible plus léger plutôt que de laisser un écran noir."""
        level = self.params.fallback
        while True:
            params = replace(self.params, fallback=level)
            conn = self.transport.open(params, scid, self._stop, self._log)
            self._conn = conn
            try:
                self._await_video(conn)
            except VideoStartError as exc:
                self._conn = None
                self._teardown(conn)
                if self._stop.is_set() or level >= compat.MAX_FALLBACK:
                    raise
                level += 1
                self._log(f"[vidéo] démarrage impossible ({exc}) : nouvel essai avec un profil compatible (niveau {level}/{compat.MAX_FALLBACK})")
                continue
            if level > self.params.fallback:
                self.auto_notes.append("Vidéo : profil compatible (H.264 Baseline, débit réduit) utilisé automatiquement")
            self.auto_notes.extend(n for n in conn.notes if n not in self.auto_notes and not n.startswith("Vidéo"))
            return conn

    def _run(self) -> None:
        scid = random.getrandbits(31)
        threads: list[threading.Thread] = []
        try:
            conn = self._open_with_fallback(scid)
            self.device_name = conn.device_name
            if self._stop.is_set():
                return
            self._set_state("running", conn.device_name)
            threads.append(threading.Thread(target=self._control_writer, args=(conn,), name="scrcpy-ctl-w", daemon=True))
            threads.append(threading.Thread(target=self._control_reader, args=(conn,), name="scrcpy-ctl-r", daemon=True))
            if conn.audio:
                threads.append(threading.Thread(target=self._audio_loop, args=(conn,), name="scrcpy-audio", daemon=True))
            for t in threads:
                t.start()
            self._video_loop(conn)
        except (EngineError, ValueError) as exc:
            self._fail(str(exc))
        except Exception as exc:  # noqa: BLE001
            self._fail(f"erreur inattendue : {exc}")
        finally:
            self._stop.set()
            self._outbox.put(None)
            self._teardown(self._conn)
            self._close_app_on_phone()
            if self.state not in ("error",):
                self._set_state("stopped", "")
            self._finished.set()

    def _close_app_on_phone(self) -> None:
        """Arrêt voulu de la session : le jeu lancé par notrefu-mirror est fermé sur le téléphone (sinon il reste en arrière-plan
        et continue de consommer batterie et réseau). Jamais en cas de coupure de connexion ni de redémarrage."""
        p = self.params
        if not (self.close_app_on_stop and self._app_started and p.app_package and p.serial):
            return
        pkg, user = adb.split_package(p.app_package)
        cmd = ["shell", "am", "force-stop"] + (["--user", str(user)] if user is not None else []) + [pkg]
        try:
            adb.run_adb(cmd, p.serial, timeout=4)
            self._log(f"[app] {p.app_package} fermée sur le téléphone")
        except adb.AdbError as exc:
            self._log(f"[app] fermeture de {p.app_package} impossible : {exc}")

    # -- vidéo --
    def _new_decoder(self):
        """Décodeur H.264 : GPU (d3d11va puis dxva2) sous Windows quand c'est possible, sinon logiciel. Si le GPU échoue
        (pilote, erreurs de décodage, aucune image), `_hw_failed` bascule définitivement sur le logiciel pour cette session."""
        import av

        if HW_DECODE_ENABLED and hw_devices() and not self._hw_failed:
            try:
                from av.codec.hwaccel import HWAccel, hwdevices_available

                available = set(hwdevices_available())
                for dev in hw_devices():
                    if dev not in available:
                        continue
                    try:
                        ctx = av.CodecContext.create("h264", "r", hwaccel=HWAccel(device_type=dev, allow_software_fallback=True))
                    except Exception as exc:  # noqa: BLE001 - pilote graphique : n'importe quelle erreur
                        self._log(f"[décodeur] {dev} indisponible : {exc}")
                        continue
                    self.hw_name = dev
                    return ctx
            except Exception as exc:  # noqa: BLE001
                self._log(f"[décodeur] décodage matériel non disponible : {exc}")
        self.hw_name = ""
        ctx = av.CodecContext.create("h264", "r")
        ctx.thread_type = "SLICE"  # pas de threads par image : latence minimale
        return ctx

    def _hw_fallback(self, why: str) -> bool:
        """Le décodage matériel pose problème : on repasse au logiciel. Renvoie True si on était bien en matériel."""
        if not self.hw_name:
            return False
        self._hw_failed = True
        self._log(f"[décodeur] {self.hw_name} abandonné ({why}) : décodage logiciel")
        self.hw_name = ""
        return True

    def _await_video(self, conn: Connection, timeout_s: float = FIRST_VIDEO_TIMEOUT_S) -> None:
        """Lit l'en-tête du flux (codec) puis attend le premier paquet. Lève VideoStartError si le serveur a renoncé,
        refuse la vidéo ou n'envoie rien dans le délai : c'est le signal pour tenter un profil plus compatible."""
        sock = conn.video
        try:
            codec = int.from_bytes(recv_handshake(sock, 4, self._stop, timeout_s), "big")
        except (OSError, EOFError) as exc:
            if self._stop.is_set():
                raise EngineError("arrêt demandé") from None
            raise VideoStartError(self._server_hint(f"le serveur n'a pas envoyé de flux vidéo ({exc})")) from None
        if codec in (0, 1):
            raise VideoStartError(self._server_hint("le serveur a refusé de démarrer la vidéo"))
        if codec != P.CODEC_H264:
            raise EngineError(f"codec vidéo non géré : 0x{codec:08x}")
        deadline = time.monotonic() + timeout_s
        while not self._stop.is_set():
            ready, _, _ = select.select([sock], [], [], 0.5)
            if ready:
                return
            if time.monotonic() > deadline:
                raise VideoStartError(self._server_hint(f"aucune image reçue en {timeout_s:.0f} s"))

    def _video_loop(self, conn: Connection) -> None:
        import av

        sock = conn.video
        decoder = self._new_decoder()
        self._log(f"[décodeur] {'matériel (' + self.hw_name + ')' if self.hw_name else 'logiciel'}")
        merger = P.ConfigMerger()
        first_session = True
        errors = 0
        packets = 0
        while not self._stop.is_set():
            t_wait = time.monotonic()
            try:
                header = P.parse_packet_header(recv_exact(sock, P.PACKET_HEADER_SIZE))
            except (OSError, EOFError):
                break
            self._note_arrival(time.monotonic() - t_wait, time.monotonic())
            if isinstance(header, P.SessionPacket):
                self.source_size = (header.width, header.height)
                decoder = self._new_decoder()
                merger = P.ConfigMerger()
                if first_session:
                    first_session = False
                    self._after_first_session()
                continue
            if header.size > P.MAX_PACKET_SIZE:
                self._fail(f"flux vidéo corrompu (paquet de {header.size} octets)")
                break
            try:
                data = recv_exact(sock, header.size)
            except (OSError, EOFError):
                break
            self.rx_bytes += len(data)
            payload = merger.push(data, header.config)
            if payload is None:
                continue
            rec = self._rec
            if rec is not None:
                with self._rec_lock:
                    if self._rec is rec:
                        if not rec["started"] and header.key_frame:
                            rec["started"] = True
                        if rec["started"]:
                            rec["f"].write(payload)
                            rec["pts"].append(header.pts)
            t0 = time.monotonic()
            try:
                frames = decoder.decode(av.Packet(payload))
            except av.error.FFmpegError as exc:
                errors += 1
                self._log(f"[décodeur] {exc}")
                if errors == 3 and self._hw_fallback("erreurs de décodage"):
                    decoder = self._new_decoder()
                    merger = P.ConfigMerger()
                    self.reset_video()
                elif errors in (3, 30):
                    self.reset_video()
                continue
            packets += 1
            if self.hw_name and self.decoded_frames == 0 and packets >= 40 and not frames:
                self._hw_fallback("aucune image après 40 paquets")
                decoder = self._new_decoder()
                merger = P.ConfigMerger()
                self.reset_video()
                continue
            for frame in frames:
                errors = 0
                self.decoded_frames += 1
                if self.source_size == (0, 0):
                    self.source_size = (frame.width, frame.height)
                with self._frame_lock:
                    self._last_decoded = frame
                if self._wants_frames() and self._should_convert(sock):
                    converted = self._convert(frame)
                    self._last_convert = time.monotonic()
                    with self._frame_lock:
                        self._latest = converted
                    self._on_frame()
            dt = (time.monotonic() - t0) * 1000
            self.decode_ms = dt if self.decode_ms == 0 else self.decode_ms * 0.9 + dt * 0.1
            cap = self.caps.effective()
            if cap:  # session freinée : on lit au plus `cap` images/s, le téléphone ralentit son encodeur (voir power.py)
                delay = self._last_paced + 1.0 / cap - time.monotonic()
                if delay > 0 and self._stop.wait(delay):
                    break
                self._last_paced = time.monotonic()
        if not self._stop.is_set():
            self._fail(self._server_hint("le téléphone a fermé la connexion"))

    def _should_convert(self, sock: socket.socket) -> bool:
        """Rattrapage du retard : la conversion en RGB coûte plus que le décodage. Si d'autres images attendent déjà dans la
        connexion (le PC n'arrive pas à suivre : Ultra 1440p/60 ips sur un processeur modeste), on décode sans convertir pour
        rattraper le flux ; on convertit quand même au moins 15 fois par seconde. Sans ça, le retard grossit à chaque seconde
        de jeu. Inutile quand la lecture est déjà freinée volontairement (voir power.py)."""
        if self.caps.effective():
            return True
        if time.monotonic() - self._last_convert >= 0.066:
            return True
        try:
            return not select.select([sock], [], [], 0)[0]
        except (OSError, ValueError):
            return True

    def _convert(self, decoded) -> Frame:
        src_w, src_h = self.source_size if self.source_size != (0, 0) else (decoded.width, decoded.height)
        view_w, view_h = self._view_size
        w, h = decoded.width, decoded.height
        if view_w > 0 and view_h > 0 and (view_w < w or view_h < h):
            scale = min(view_w / w, view_h / h)
            w, h = max(2, int(w * scale) & ~1), max(2, int(h * scale) & ~1)
        rgb = decoded.reformat(width=w, height=h, format="rgb24", interpolation="BICUBIC")
        plane = rgb.planes[0]
        return Frame(rgb.width, rgb.height, plane.line_size, memoryview(plane), src_w, src_h, keep=rgb)  # pas de copie : la trame RGB est neuve

    def _start_user_app(self, pkg: str, user: int) -> None:
        p = self.params
        display = None
        if p.new_display:
            for _ in range(10):  # l'écran virtuel met un instant à apparaître dans dumpsys
                display = adb.find_virtual_display_id(p.serial)
                if display is not None or self._stop.is_set():
                    break
                time.sleep(0.5)
            if display is None:
                self._log("[app] écran virtuel introuvable : l'application sera lancée sur l'écran du téléphone")
        try:
            out = adb.start_user_app(p.serial, pkg, user, display)
            self._log(f"[app] {pkg} (utilisateur {user}) lancée sur l'écran {display if display is not None else 'principal'} : {out.strip()[:120]}")
        except adb.AdbError as exc:
            self._log(f"[app] lancement de {pkg} (utilisateur {user}) impossible : {exc}")

    def _after_first_session(self) -> None:
        """Premier flux reçu : l'écran (réel ou virtuel) existe, on peut lancer l'application."""
        p = self.params

        def later() -> None:
            if self._stop.is_set():
                return
            if p.app_package:
                pkg, user = adb.split_package(p.app_package)
                if p.game_mode:
                    try:
                        adb.game_mode_set(p.serial, p.app_package, p.game_mode)
                        self._log(f"[jeu] mode jeu Android : {adb.GAME_MODES.get(p.game_mode, p.game_mode)}")
                    except adb.AdbError as exc:
                        self._log(f"[jeu] mode jeu Android non appliqué : {exc}")
                self._app_started = True
                if user is None:
                    self.send(P.start_app(pkg))
                else:  # copie d'un autre utilisateur (double application) : lancement par adb
                    self._start_user_app(pkg, user)
            if p.turn_screen_off:
                self.send(P.set_display_power(False))

        threading.Timer(0.4, later).start()

    def _server_hint(self, base: str) -> str:
        tail = [l for l in self.log_tail if l.startswith(("[server] ERROR", "[server] WARN")) or "Exception" in l or "Error" in l]
        return base + (" : " + " | ".join(tail[-3:]) if tail else "")

    # -- contrôle --
    def _control_writer(self, conn: Connection) -> None:
        sock = conn.control
        while True:
            item = self._outbox.get()
            if item is None or self._stop.is_set():
                return
            queued_at, msg = item
            if time.monotonic() - queued_at > STALE_CONTROL_S and P.is_stale_droppable(msg):
                self.dropped_stale += 1  # trop vieux : jamais rejoué en retard (les relâchements, eux, passent toujours)
                continue
            try:
                sock.sendall(msg)
            except OSError:
                self._fail("connexion de contrôle perdue")
                return

    def _control_reader(self, conn: Connection) -> None:
        """Messages du téléphone : presse-papiers, acquittements (les autres sont lus et ignorés)."""
        sock = conn.control
        try:
            while not self._stop.is_set():
                kind = recv_exact(sock, 1)[0]
                if kind == P.DEV_CLIPBOARD:
                    n = int.from_bytes(recv_exact(sock, 4), "big")
                    if n > P.CLIPBOARD_TEXT_MAX_LENGTH:
                        raise EngineError("message de presse-papiers trop grand")
                    text = recv_exact(sock, n).decode("utf-8", errors="replace") if n else ""
                    if self.params.clipboard:
                        self._on_clipboard(text)
                elif kind == P.DEV_ACK_CLIPBOARD:
                    recv_exact(sock, 8)
                elif kind == P.DEV_UHID_OUTPUT:
                    recv_exact(sock, 2)
                    n = int.from_bytes(recv_exact(sock, 2), "big")
                    recv_exact(sock, n)
                else:
                    raise EngineError(f"message du téléphone inconnu : {kind}")
        except (OSError, EOFError):
            pass
        except EngineError as exc:
            self._fail(str(exc))

    def _set_audio_state(self, state: str) -> None:
        self.audio_state = state

    # -- audio (rempli par audio.py si disponible) --
    def _audio_loop(self, conn: Connection) -> None:
        try:
            from .audio import run_audio

            run_audio(conn.audio, self._stop, self._log, self._wants_audio, self._env, self._audio_player,
                      self.params.audio_latency_ms, self._set_audio_state, self._audio_gain, self._audio_tap)
        except Exception as exc:  # noqa: BLE001
            self._log(f"[audio] désactivé : {exc}")
            self.audio_state = f"désactivé ({exc})"
            try:
                while not self._stop.is_set() and conn.audio.recv(65536):
                    pass
            except OSError:
                pass
