"""Enveloppe autour de adb : localisation des outils, parsing, commandes courantes.

Tout ce module est sans dépendance Qt pour rester testable.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

# Serveur adb privé : évite les conflits de version avec un adb déjà lancé sur
# le système (qui serait tué/relancé par le nôtre).
ADB_SERVER_PORT = os.environ.get("NOTREFU_MIRROR_ADB_PORT", "5038")

_STATES = ("device", "unauthorized", "offline", "no permissions")


WINDOWS = sys.platform == "win32"


def _bundled_dir() -> Path | None:
    """Dossier des outils embarqués : AppImage (APPDIR) ou version portable Windows (NOTREFU_MIRROR_HOME)."""
    appdir = os.environ.get("APPDIR")
    if appdir:
        p = Path(appdir) / "usr" / "lib" / "scrcpy"
        if p.is_dir():
            return p
    home = os.environ.get("NOTREFU_MIRROR_HOME")
    if home:
        p = Path(home) / "tools"
        if p.is_dir():
            return p
    return None


def find_tool(name: str) -> str | None:
    """Cherche `name` : variable NOTREFU_MIRROR_<NAME>, puis AppImage, puis PATH."""
    override = os.environ.get(f"NOTREFU_MIRROR_{name.upper()}")
    if override:
        return override
    bundled = _bundled_dir()
    exe = name + ".exe" if WINDOWS else name
    if bundled and (bundled / exe).exists():
        return str(bundled / exe)
    return shutil.which(name)


def server_path() -> str | None:
    override = os.environ.get("NOTREFU_MIRROR_SCRCPY_SERVER")
    if override:
        return override
    bundled = _bundled_dir()
    if bundled and (bundled / "scrcpy-server").exists():
        return str(bundled / "scrcpy-server")
    return None


def tool_env() -> dict[str, str]:
    """Environnement pour lancer adb/scrcpy depuis l'AppImage."""
    env = dict(os.environ)
    # Ne pas faire hériter aux outils natifs le Python/Qt embarqués.
    for var in ("PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH", "QT_PLUGIN_PATH"):
        env.pop(var, None)
    adb = find_tool("adb")
    if adb:
        env["ADB"] = adb
    srv = server_path()
    if srv:
        env["SCRCPY_SERVER_PATH"] = srv
    env["ANDROID_ADB_SERVER_PORT"] = ADB_SERVER_PORT
    return env


@dataclass(frozen=True)
class Device:
    serial: str
    state: str  # device | unauthorized | offline | no permissions
    model: str = ""
    wireless: bool = False

    @property
    def label(self) -> str:
        name = self.model.replace("_", " ") or self.serial
        kind = "Wi-Fi" if self.wireless else "USB"
        suffix = "" if self.state == "device" else f" — {state_text(self.state)}"
        return f"{name} ({kind}){suffix}"


# Tous les états que `adb devices` peut annoncer : aucun appareil vu par adb ne doit disparaître de la liste.
KNOWN_STATES = ("device", "unauthorized", "offline", "no permissions", "authorizing", "connecting",
                "recovery", "sideload", "rescue", "bootloader", "host")

STATE_TEXT = {
    "unauthorized": "Non autorisé — accepte la pop-up sur l'écran",
    "offline": "Hors ligne — rebranche le câble",
    "no permissions": "Permissions USB manquantes — installe les règles USB",
    "authorizing": "Autorisation en cours — accepte la pop-up sur l'écran",
    "connecting": "Connexion en cours…",
    "recovery": "Mode récupération",
    "sideload": "Mode sideload",
    "bootloader": "Mode bootloader",
    "rescue": "Mode secours",
    "host": "Hôte",
}


def state_text(state: str) -> str:
    return STATE_TEXT.get(state, state)


_WIFI_SERIAL = re.compile(r"^(\d{1,3}(\.\d{1,3}){3}:\d+|adb-.*_adb-tls-connect\._tcp.*)$")


def parse_devices(output: str) -> list[Device]:
    """Parse la sortie de `adb devices -l`."""
    devices: list[Device] = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith(("List of devices", "*")):
            continue
        m = re.match(r"^(\S+)\s+(%s)\b(.*)$" % "|".join(KNOWN_STATES), line)
        if not m:
            continue
        serial, state, rest = m.groups()
        model = ""
        mm = re.search(r"\bmodel:(\S+)", rest)
        if mm:
            model = mm.group(1)
        devices.append(Device(serial, state, model, bool(_WIFI_SERIAL.match(serial))))
    return devices


def parse_wifi_ip(output: str) -> str | None:
    """Extrait l'IPv4 d'une sortie `ip addr` ou `ip route`."""
    m = re.search(r"\bsrc\s+(\d{1,3}(?:\.\d{1,3}){3})\b", output)
    if m:
        return m.group(1)
    m = re.search(r"\binet\s+(\d{1,3}(?:\.\d{1,3}){3})/", output)
    if m and not m.group(1).startswith("127."):
        return m.group(1)
    return None


def parse_wm(output: str, key: str) -> str | None:
    """`wm size` / `wm density` : renvoie la valeur effective (override sinon physique)."""
    override = physical = None
    for line in output.splitlines():
        line = line.strip()
        if line.lower().startswith("override"):
            override = line.split(":", 1)[1].strip()
        elif line.lower().startswith("physical"):
            physical = line.split(":", 1)[1].strip()
    return override or physical


_SIZE_RE = re.compile(r"^\d{3,5}x\d{3,5}$")


def valid_size(text: str) -> bool:
    return bool(_SIZE_RE.match(text.strip().lower().replace("×", "x")))


def valid_dpi(text: str) -> bool:
    return text.strip().isdigit() and 72 <= int(text.strip()) <= 960


class AdbError(RuntimeError):
    pass


def run_cmd(cmd: list[str], timeout: float, env: dict[str, str] | None = None) -> tuple[int, str]:
    """Lance une commande avec un délai STRICT et renvoie (code, sortie).

    Pourquoi pas `subprocess.run(capture_output=True, timeout=…)` : sous Windows, quand adb relance son serveur en
    tâche de fond (typique juste après une coupure), le démon hérite des tuyaux de sortie ; après le délai,
    `run()` tue adb puis attend la fermeture des tuyaux… qui n'arrive jamais : l'appel (et donc la reconnexion)
    restait bloqué pour toujours. Ici la sortie va dans un fichier temporaire (aucun tuyau à attendre) et le
    processus est tué à l'échéance. Lève subprocess.TimeoutExpired."""
    with tempfile.TemporaryFile() as out:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, env=env)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
            raise
        out.seek(0)
        return code, out.read().decode("utf-8", "replace")


# --- conflit de serveur adb (autre adb.exe / émulateur / Android Studio déjà sur le port 5037) ---------------------------------
CONFLICT_HINT = ("un autre adb (émulateur, Android Studio, Samsung Smart Switch…) occupe le port 5037 avec une version différente : "
                 "ferme-le, ou clique sur Actualiser pour que notrefu-mirror redémarre le serveur adb avec sa propre version.")
EVENTS: list[str] = []  # derniers événements du serveur adb (affichés par Aide → Diagnostic)
_restart_lock = threading.Lock()
_last_restart = 0.0


def server_conflict(text: str) -> bool:
    """Vrai si le texte d'erreur signale deux versions d'adb en conflit (« adb server version (41) doesn't match this client (40) »)."""
    low = (text or "").lower()
    return ("server version" in low and "doesn't match" in low) or "failed to check server version" in low \
        or "adb server is out of date" in low or "protocol fault" in low


def _event(msg: str) -> None:
    EVENTS.append(f"{time.strftime('%H:%M:%S')} {msg}")
    del EVENTS[:-20]


def restart_server(adb_path: str, env: dict[str, str] | None, note=None) -> bool:
    """Redémarre proprement le serveur adb avec l'adb embarqué (kill-server puis start-server, délais stricts).
    Au plus une fois toutes les 10 s, pour ne jamais boucler. Renvoie True si le serveur répond ensuite."""
    global _last_restart
    note = note or _event
    with _restart_lock:
        if time.monotonic() - _last_restart < 10:
            return False
        _last_restart = time.monotonic()
        note("[adb] conflit de version du serveur adb : redémarrage avec l'adb de notrefu-mirror")
        for args, tmo in ((["kill-server"], 6), (["start-server"], 12)):
            try:
                code, out = run_cmd([adb_path, *args], tmo, env)
            except (subprocess.TimeoutExpired, OSError) as exc:
                note(f"[adb] adb {args[0]} : {exc if isinstance(exc, OSError) else 'délai dépassé'}")
                continue
            if code != 0 and args[0] == "start-server":
                note(f"[adb] adb start-server a échoué : {out.strip()[:200]}")
        try:
            code, out = run_cmd([adb_path, "devices"], 8, env)
        except (subprocess.TimeoutExpired, OSError):
            code, out = 1, ""
        ok = code == 0 and not server_conflict(out)
        note("[adb] serveur adb redémarré" if ok else "[adb] " + CONFLICT_HINT)
        return ok


def run_adb(args: list[str], serial: str | None = None, timeout: float = 15.0) -> str:
    adb = find_tool("adb")
    if not adb:
        raise AdbError("adb introuvable (ni dans l'AppImage ni dans le PATH).")
    cmd = [adb] + (["-s", serial] if serial else []) + args
    for attempt in (1, 2):
        try:
            code, out = run_cmd(cmd, timeout, tool_env())
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"adb : délai dépassé après {timeout:.0f} s ({' '.join(args[:3])})") from exc
        except OSError as exc:
            raise AdbError(f"adb n'a pas pu être lancé : {exc}") from exc
        if server_conflict(out) and attempt == 1 and restart_server(adb, tool_env()):
            continue  # le serveur a été relancé avec notre version : on rejoue la commande une fois
        break
    if server_conflict(out):
        raise AdbError(f"{CONFLICT_HINT} (détail : {out.strip()[:160]})")
    if code != 0:
        raise AdbError(out.strip() or f"adb a échoué (code {code})")
    return out


def parse_device_state(output: str, serial: str) -> str:
    """État adb d'un appareil d'après `adb devices` : device, offline, unauthorized, no permissions ou missing."""
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == serial:
            return " ".join(parts[1:3]) if parts[1] == "no" else parts[1]
    return "missing"


def wifi_target(serial: str) -> tuple[str, int] | None:
    """(hôte, port) si le numéro de série est une adresse Wi-Fi « hôte:port », sinon None."""
    if ":" not in serial:
        return None
    host, _, port = serial.rpartition(":")
    return (host, int(port)) if port.isascii() and port.isdigit() else None


_SERVER_LINE = re.compile(r"^\s*(\d+)\s+.*com\.genymobile\.scrcpy\.Server\b.*?\bscid=([0-9a-fA-F]{1,8})\b")
_FORWARD_LINE = re.compile(r"^\S+\s+(tcp:\d+)\s+localabstract:scrcpy_([0-9a-fA-F]{1,8})\s*$")


def parse_scrcpy_servers(ps_output: str) -> list[tuple[int, int]]:
    """[(pid, scid)] des serveurs scrcpy trouvés dans la sortie de `ps -A -o PID,ARGS` du téléphone."""
    found = []
    for line in ps_output.splitlines():
        m = _SERVER_LINE.match(line)
        if m:
            found.append((int(m.group(1)), int(m.group(2), 16)))
    return found


def parse_scrcpy_forwards(forward_list: str) -> list[tuple[str, int]]:
    """[(« tcp:PORT », scid)] des tunnels scrcpy d'après `adb forward --list`."""
    found = []
    for line in forward_list.splitlines():
        m = _FORWARD_LINE.match(line.strip())
        if m:
            found.append((m.group(1), int(m.group(2), 16)))
    return found


def device_state(serial: str, timeout: float = 5.0) -> str:
    return parse_device_state(run_adb(["devices"], timeout=timeout), serial)


def list_devices() -> list[Device]:
    return parse_devices(run_adb(["devices", "-l"]))


def device_info(serial: str) -> dict[str, str]:
    info = {}
    for key, prop in (("model", "ro.product.model"), ("android", "ro.build.version.release"), ("sdk", "ro.build.version.sdk"),
                       ("manufacturer", "ro.product.manufacturer")):
        try:
            info[key] = run_adb(["shell", "getprop", prop], serial).strip()
        except AdbError:
            info[key] = ""
    return info


def wifi_ip(serial: str) -> str | None:
    for cmd in (["shell", "ip", "-f", "inet", "addr", "show", "wlan0"], ["shell", "ip", "route"]):
        try:
            ip = parse_wifi_ip(run_adb(cmd, serial))
        except AdbError:
            continue
        if ip:
            return ip
    return None


def enable_tcpip(serial: str, port: int = 5555) -> str:
    return run_adb(["tcpip", str(port)], serial, timeout=20).strip()


def connect(ip: str, port: int, timeout: float = 8.0) -> str:
    out = run_adb(["connect", f"{ip}:{port}"], timeout=timeout).strip()
    if "connected to" not in out.lower() or "cannot" in out.lower() or "failed" in out.lower():
        raise AdbError(out)
    return out


def disconnect(ip: str, port: int, timeout: float = 5.0) -> str:
    return run_adb(["disconnect", f"{ip}:{port}"], timeout=timeout).strip()


def pair(address: str, code: str) -> str:
    out = run_adb(["pair", address, code], timeout=20).strip()
    if "successfully paired" not in out.lower():
        raise AdbError(out)
    return out


def parse_display_on(output: str) -> bool | None:
    """État réel de l'écran d'après `dumpsys power` (« Display Power: state=ON/OFF »)."""
    m = re.search(r"Display Power: state=(\w+)", output)
    if m:
        return m.group(1).upper() == "ON"
    m = re.search(r"mWakefulness=(\w+)", output)
    if m:
        return m.group(1).lower() == "awake"
    return None


def display_is_on(serial: str) -> bool | None:
    try:
        return parse_display_on(run_adb(["shell", "dumpsys", "power"], serial, timeout=6))
    except AdbError:
        return None


def wake_up(serial: str) -> None:
    """Réveille vraiment le téléphone (KEYCODE_WAKEUP) : le message scrcpy seul ne suffit pas sur certaines surcouches."""
    try:
        run_adb(["shell", "input", "keyevent", "224"], serial, timeout=6)
    except AdbError:
        pass


def current_wm(serial: str) -> tuple[str | None, str | None]:
    size = parse_wm(run_adb(["shell", "wm", "size"], serial), "size")
    dens = parse_wm(run_adb(["shell", "wm", "density"], serial), "density")
    return size, dens


def parse_wm_override(output: str) -> str | None:
    """Valeur « Override » de `wm size` / `wm density` (None = réglage d'origine)."""
    for line in output.splitlines():
        if line.strip().lower().startswith("override"):
            return line.split(":", 1)[1].strip()
    return None


def wm_overrides(serial: str) -> tuple[str | None, str | None]:
    size = parse_wm_override(run_adb(["shell", "wm", "size"], serial))
    dens = parse_wm_override(run_adb(["shell", "wm", "density"], serial))
    return size, dens


def set_size(serial: str, size: str | None) -> None:
    """`size=None` remet la résolution d'origine."""
    arg = "reset" if size is None else size.strip().lower().replace("×", "x")
    run_adb(["shell", "wm", "size", arg], serial)


def set_density(serial: str, dpi: int | None) -> None:
    run_adb(["shell", "wm", "density", "reset" if dpi is None else str(dpi)], serial)


_APP_LINE = re.compile(r"^\s*[-*]\s+(.+?)\s+([A-Za-z]\w*(?:\.[A-Za-z]\w*)+)(?:\s+\(.*\))?\s*$")


def parse_list_apps(output: str) -> list[tuple[str, str]]:
    """Parse `scrcpy --list-apps` : lignes « - Nom   com.exemple.paquet »."""
    apps = []
    for line in output.splitlines():
        m = _APP_LINE.match(line)
        if m:
            apps.append((m.group(1).strip(), m.group(2)))
    return apps


_USER_RE = re.compile(r"UserInfo\{(\d+):([^:}]*)")


def parse_users(output: str) -> list[tuple[int, str]]:
    """Sortie de `pm list users` : (identifiant, nom). Les « doubles applications » Xiaomi/HyperOS sont l'utilisateur 999."""
    return [(int(m.group(1)), m.group(2)) for m in _USER_RE.finditer(output)]


def split_package(spec: str) -> tuple[str, int | None]:
    """« com.x.y » -> (paquet, None) ; « com.x.y@999 » -> (paquet, 999) : copie installée pour un autre utilisateur."""
    pkg, sep, user = spec.strip().partition("@")
    return pkg, (int(user) if sep and user.isdigit() else None)


def list_clone_apps(serial: str, known: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Applications installées pour un AUTRE utilisateur (double apps, espace secondaire) : mêmes noms de paquet
    que l'originale, donc invisibles dans la liste classique. Renvoie (nom affiché, « paquet@utilisateur »)."""
    labels = {pkg: name for name, pkg in known}
    out = []
    try:
        users = parse_users(run_adb(["shell", "pm", "list", "users"], serial, timeout=10))
    except AdbError:
        return out
    for uid, uname in users:
        if uid == 0:
            continue
        try:
            text = run_adb(["shell", "pm", "list", "packages", "-3", "--user", str(uid)], serial, timeout=15)
        except AdbError:
            continue
        for line in text.splitlines():
            if line.startswith("package:"):
                pkg = line.split(":", 1)[1].strip()
                out.append((f"{labels.get(pkg, pkg)} (double application, utilisateur {uid})", f"{pkg}@{uid}"))
    return out


def find_virtual_display_id(serial: str) -> int | None:
    """Identifiant de l'écran virtuel créé par scrcpy (nommé « scrcpy »), d'après `dumpsys display`."""
    try:
        out = run_adb(["shell", "dumpsys", "display"], serial, timeout=10)
    except AdbError:
        return None
    ids = re.findall(r'"scrcpy"[^\n]*?displayId (\d+)', out)
    return int(ids[-1]) if ids else None


_COMPONENT_RE = re.compile(r"^\s*([\w.]+/[\w.$]+)\s*$")


def parse_launcher_from_dump(dump: str, package: str) -> str | None:
    """Activité de lancement (« paquet/.Activité ») d'après `pm dump paquet` : celle dont le filtre porte la catégorie LAUNCHER."""
    last = None
    for line in dump.splitlines():
        m = re.search(r"(\S+/\S+) filter \w+", line)
        if m:
            last = m.group(1)
        elif 'android.intent.category.LAUNCHER' in line and last and last.startswith(package + "/"):
            return last
    return None


def resolve_launcher_component(serial: str, package: str, user: int) -> str | None:
    """Trouve l'activité de lancement : la résolution directe échoue souvent pour l'espace « double application »,
    alors que l'activité est la même que celle de l'application d'origine (utilisateur 0)."""
    intent = ["-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", "-p", package]
    for uid in (0, user):
        try:
            out = run_adb(["shell", "cmd", "package", "resolve-activity", "--brief", "--user", str(uid)] + intent, serial, timeout=10)
        except AdbError:
            continue
        for line in reversed(out.splitlines()):
            m = _COMPONENT_RE.match(line)
            if m and m.group(1).startswith(package + "/"):
                return m.group(1)
    for uid in (user, 0):
        try:
            dump = run_adb(["shell", "pm", "dump", package], serial, timeout=20)
        except AdbError:
            continue
        comp = parse_launcher_from_dump(dump, package)
        if comp:
            return comp
        break
    return None


def start_user_app(serial: str, package: str, user: int, display: int | None) -> str:
    """Lance l'application d'un autre utilisateur (le serveur scrcpy ne sait lancer que celles de l'utilisateur 0)."""
    comp = resolve_launcher_component(serial, package, user)
    if not comp:
        raise AdbError("activité de lancement introuvable (ni par resolve-activity ni dans pm dump)")
    cmd = ["shell", "am", "start", "--user", str(user)]
    if display is not None:
        cmd += ["--display", str(display)]
    cmd += ["-n", comp]
    out = run_adb(cmd, serial, timeout=15)
    if "Error" in out or "not started" in out.lower():
        raise AdbError(f"{comp} : {out.strip()}")
    return f"{comp} : {out.strip()}"


def list_apps(serial: str, pattern: str | None = None) -> list[tuple[str, str]]:
    """Applications installées (nom, paquet), filtrées par expression régulière."""
    scrcpy = find_tool("scrcpy")
    if not scrcpy:
        raise AdbError("scrcpy introuvable.")
    try:
        res = subprocess.run(
            [scrcpy, "-s", serial, "--list-apps"],
            capture_output=True, text=True, timeout=40, env=tool_env(),
        )
    except subprocess.TimeoutExpired as exc:
        raise AdbError("Délai dépassé pendant la lecture des applications.") from exc
    apps = parse_list_apps((res.stdout or "") + "\n" + (res.stderr or ""))
    if res.returncode != 0 and not apps:
        raise AdbError(((res.stdout or "") + (res.stderr or "")).strip() or "scrcpy --list-apps a échoué")
    apps = apps + list_clone_apps(serial, apps)
    if pattern:
        rx = re.compile(pattern, re.I)
        apps = [a for a in apps if rx.search(a[0]) or rx.search(a[1])]
    return apps


# --- icônes des applications ------------------------------------------------
_ZIP_LINE = re.compile(r"^\s*(\d+)\s+\S+\s+\S+\s+(\S.*?)\s*$")
_ICON_SKIP = re.compile(r"splash|notif|small|btn|button|background|banner|bg_|shadow|loading", re.I)


def parse_zip_listing(output: str) -> list[tuple[int, str]]:
    """Sortie de `unzip -l` : liste (taille, chemin)."""
    entries = []
    for line in output.splitlines():
        m = _ZIP_LINE.match(line)
        if m:
            entries.append((int(m.group(1)), m.group(2)))
    return entries


def rank_icon_candidates(entries: list[tuple[int, str]], limit: int = 8) -> list[str]:
    """PNG de res/ qui ont le plus de chances d'être l'icône : « launcher » / « icon » d'abord, gros fichiers ensuite."""
    scored = []
    for size, name in entries:
        low = name.lower()
        if not low.endswith((".png", ".webp")) or not low.startswith("res/") or size < 800 or size > 400_000:
            continue
        if _ICON_SKIP.search(low):
            continue
        score = 0
        if "launcher" in low:
            score += 100
        if "icon" in low:
            score += 50
        if "foreground" in low:
            score -= 30  # couche avant d'une icône adaptative : transparente, on préfère l'icône complète
        if "round" in low:
            score -= 10
        if any(d in low for d in ("xxxhdpi", "xxhdpi", "xhdpi")):
            score += 10
        scored.append((score, size, name))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    return [name for _, _, name in scored[:limit]]


def png_size(data: bytes) -> tuple[int, int] | None:
    if len(data) > 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return None


def parse_zip_central_directory(cd: bytes) -> list[dict]:
    """Entrées de l'annuaire central d'un ZIP/APK : nom, méthode, tailles, position de l'en-tête local."""
    import struct

    entries, pos = [], 0
    while pos + 46 <= len(cd) and cd[pos:pos + 4] == b"PK\x01\x02":
        method, = struct.unpack_from("<H", cd, pos + 10)
        csize, usize = struct.unpack_from("<II", cd, pos + 20)
        n, m, k = struct.unpack_from("<HHH", cd, pos + 28)
        offset, = struct.unpack_from("<I", cd, pos + 42)
        name = cd[pos + 46:pos + 46 + n].decode("utf-8", "replace")
        entries.append({"name": name, "method": method, "csize": csize, "usize": usize, "offset": offset})
        pos += 46 + n + m + k
    return entries


def read_zip_entry(read_range, size: int, entry: dict) -> bytes:
    """Lit et décompresse une entrée ; `read_range(début, longueur)` lit des octets du fichier distant."""
    import struct
    import zlib

    head = read_range(entry["offset"], 30)
    if head[:4] != b"PK\x03\x04":
        raise AdbError("en-tête ZIP local invalide")
    n, m = struct.unpack_from("<HH", head, 26)
    data = read_range(entry["offset"] + 30 + n + m, entry["csize"])
    if entry["method"] == 0:
        return data
    if entry["method"] == 8:
        return zlib.decompress(data, -15)
    raise AdbError(f"méthode de compression {entry['method']} non gérée")


def find_zip_icon(read_range, size: int) -> bytes | None:
    """Cherche l'icône d'une APK en ne lisant que sa fin (annuaire central) et l'image choisie."""
    import struct

    tail_len = min(size, 65557)
    tail = read_range(size - tail_len, tail_len)
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0 or eocd + 22 > len(tail):
        raise AdbError("fin de l'APK illisible")
    cd_size, cd_offset = struct.unpack_from("<II", tail, eocd + 12)
    if cd_offset == 0xFFFFFFFF or cd_size > 16_000_000:
        raise AdbError("APK trop grande ou ZIP64 non géré")
    entries = parse_zip_central_directory(read_range(cd_offset, cd_size))
    by_name = {e["name"]: e for e in entries}
    for name in rank_icon_candidates([(e["usize"], e["name"]) for e in entries]):
        try:
            data = read_zip_entry(read_range, size, by_name[name])
        except (AdbError, OSError, ValueError, Exception):  # noqa: BLE001  (zlib.error, etc.)
            continue
        dims = image_size(data)
        if dims and dims[0] == dims[1] and 64 <= dims[0] <= 1024:
            return data
    return None


def image_size(data: bytes) -> tuple[int, int] | None:
    """Dimensions d'une image PNG ou WebP (None sinon)."""
    dims = png_size(data)
    if dims:
        return dims
    if len(data) > 30 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        kind = data[12:16]
        if kind == b"VP8X":
            return (int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1)
        if kind == b"VP8L" and data[20] == 0x2F:
            bits = int.from_bytes(data[21:25], "little")
            return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        if kind == b"VP8 ":
            return (int.from_bytes(data[26:28], "little") & 0x3FFF, int.from_bytes(data[28:30], "little") & 0x3FFF)
    return None


def _open_apk(serial: str, package: str):
    package, user = split_package(package)
    out = run_adb(["shell", "pm", "path"] + (["--user", str(user)] if user is not None else []) + [package], serial)
    apks = [l.split(":", 1)[1].strip() for l in out.splitlines() if l.startswith("package:")]
    if not apks:
        raise AdbError("application introuvable")
    apk = next((a for a in apks if a.endswith("base.apk")), apks[0])
    # Chemins Android typiques : /data/app/~~AbC==/com.exemple-xyz==/base.apk (« ~ », « = »). Les guillemets
    # simples ci-dessous protègent le chemin ; on refuse tout caractère qui permettrait d'en sortir.
    if not re.fullmatch(r"/[\w./=+~@-]+", apk):
        raise AdbError(f"chemin d'APK inattendu : {apk!r}")
    adb = find_tool("adb")
    size_txt = run_adb(["shell", f"wc -c < '{apk}'"], serial).strip().split()
    if not size_txt or not size_txt[0].isdigit():
        raise AdbError("taille de l'APK illisible")
    size = int(size_txt[0])

    def read_range(start: int, length: int) -> bytes:
        res = subprocess.run(
            [adb, "-s", serial, "exec-out", f"tail -c +{start + 1} '{apk}' | head -c {length}"],
            capture_output=True, timeout=30, env=tool_env(),
        )
        if res.returncode != 0 or len(res.stdout) != length:
            raise AdbError(f"lecture de l'APK impossible ({len(res.stdout)}/{length} octets)")
        return res.stdout

    return apks, apk, size, read_range


def app_icon(serial: str, package: str) -> bytes | None:
    """Icône (PNG/WebP) de l'application, lue dans son APK sur le téléphone sans `unzip` ni copie complète :
    seuls la fin du fichier et l'image choisie sont transférées. None si introuvable."""
    _apks, _apk, size, read_range = _open_apk(serial, package)
    return find_zip_icon(read_range, size)


def icon_debug(serial: str, package: str) -> str:
    """Rapport de diagnostic (pour `--icon-debug`) : où l'icône est cherchée et pourquoi elle échoue."""
    import struct

    lines = [f"paquet : {package}"]
    try:
        apks, apk, size, read_range = _open_apk(serial, package)
    except AdbError as exc:
        return "\n".join(lines + [f"ERREUR : {exc}"])
    lines += [f"apk(s) : {apks}", f"choisi : {apk} ({size} octets)"]
    try:
        tail_len = min(size, 65557)
        tail = read_range(size - tail_len, tail_len)
        eocd = tail.rfind(b"PK\x05\x06")
        cd_size, cd_offset = struct.unpack_from("<II", tail, eocd + 12)
        lines.append(f"annuaire ZIP : offset={cd_offset} taille={cd_size}")
        entries = parse_zip_central_directory(read_range(cd_offset, cd_size))
    except Exception as exc:  # noqa: BLE001
        return "\n".join(lines + [f"ERREUR lecture ZIP : {exc}"])
    lines.append(f"entrées : {len(entries)}")
    imgs = [e for e in entries if e["name"].lower().endswith((".png", ".webp", ".jpg", ".jpeg", ".xml")) and e["name"].startswith("res/")]
    lines.append("--- images/xml sous res/ (60 premières, par nom contenant icon/launcher d'abord) ---")
    imgs.sort(key=lambda e: (not any(k in e["name"].lower() for k in ("launcher", "icon")), e["name"]))
    for e in imgs[:60]:
        lines.append(f"  {e['usize']:>8}  {e['name']}")
    cands = rank_icon_candidates([(e["usize"], e["name"]) for e in entries])
    lines.append(f"candidats retenus : {cands}")
    try:
        icon = find_zip_icon(read_range, size)
        lines.append("RÉSULTAT : " + (f"icône trouvée ({len(icon)} octets, {image_size(icon)})" if icon else "aucune icône valide"))
    except Exception as exc:  # noqa: BLE001
        lines.append(f"ERREUR : {exc}")
    return "\n".join(lines)


# Constructeurs Android (identifiant USB -> nom), tablettes comprises. La règle générique « interface adb ff/42/01 » ne suffit
# pas toujours (tablettes Samsung, certains modes USB) : on autorise aussi chaque constructeur par son identifiant.
USB_VENDORS = {
    "04e8": "Samsung", "18d1": "Google", "2717": "Xiaomi", "22b8": "Motorola", "12d1": "Huawei", "339b": "Honor",
    "2a70": "OnePlus", "22d9": "Oppo", "2d95": "vivo", "1d4d": "Realme/Pegatron", "0fce": "Sony", "054c": "Sony",
    "1004": "LG", "0b05": "ASUS", "17ef": "Lenovo", "0502": "Acer", "0bb4": "HTC", "19d2": "ZTE", "1bbb": "Alcatel/TCL",
    "2e04": "Nokia/HMD", "2ae5": "Fairphone", "29a9": "Meizu", "1949": "Amazon (Fire)", "0e8d": "MediaTek", "2207": "Rockchip",
    "05c6": "Qualcomm", "413c": "Dell", "109b": "Hisense", "04dd": "Sharp", "1782": "Spreadtrum/Unisoc", "2916": "Yota",
    "0489": "Foxconn", "0414": "Gigabyte", "0e79": "Archos", "091e": "Garmin", "2b4c": "Lenovo (tablettes)", "1f3a": "Allwinner",
}
UDEV_RULE = (
    "# notrefu-mirror v2 : autorise l'accès adb à l'utilisateur connecté (interface adb ff/42/01, puis constructeurs connus).\n"
    'SUBSYSTEM=="usb", ENV{ID_USB_INTERFACES}=="*:ff4201:*", TAG+="uaccess"\n'
    + "".join(f'SUBSYSTEM=="usb", ATTR{{idVendor}}=="{vid}", TAG+="uaccess"  # {name}\n' for vid, name in USB_VENDORS.items())
)
UDEV_RULE_PATH = "/etc/udev/rules.d/51-notrefu_mirror-adb.rules"


# --- anti-gel (batterie), mode jeu Android, test des entrées ---------------------------------------------------------------------
GAME_MODES = {"standard": "Standard", "performance": "Performance", "battery": "Économie de batterie"}


def parse_game_mode(text: str) -> tuple[str | None, list[str]]:
    """Sortie de `cmd game mode <paquet>` -> (mode actuel, modes proposés par le téléphone)."""
    m = re.search(r"current mode:\s*(\w+),\s*available game modes:\s*\[([^\]]*)\]", text)
    if not m:
        return None, []
    return m.group(1).lower(), [x.strip().lower() for x in m.group(2).split(",") if x.strip()]


def input_blocked(output: str) -> bool:
    """Vrai si le téléphone refuse les touches/clics venant d'adb (Xiaomi : « Débogage USB (paramètres de sécurité) »)."""
    low = output.lower()
    return "securityexception" in low or "inject_events" in low or "permission denied" in low


def input_test(serial: str) -> tuple[bool, str]:
    """Envoie une touche sans effet (KEYCODE_UNKNOWN) : (ça marche, détail)."""
    try:
        out = run_adb(["shell", "input", "keyevent", "0"], serial, timeout=8)
    except AdbError as exc:
        out = str(exc)
        if input_blocked(out):
            return False, out
        return False, out
    return (not input_blocked(out)), out.strip()


def game_mode_get(serial: str, package: str) -> tuple[str | None, list[str]]:
    try:
        return parse_game_mode(run_adb(["shell", "cmd", "game", "mode", package], serial, timeout=8))
    except AdbError:
        return None, []


def game_mode_set(serial: str, spec: str, mode: str) -> str:
    """Règle le mode jeu d'une application (« paquet » ou « paquet@utilisateur »). Renvoie la réponse du téléphone."""
    if mode not in GAME_MODES:
        raise AdbError(f"mode jeu inconnu : {mode}")
    pkg, user = split_package(spec)
    args = ["shell", "cmd", "game", "mode"] + (["--user", str(user)] if user is not None else []) + [mode, pkg]
    return run_adb(args, serial, timeout=10).strip()


def anti_freeze(serial: str, spec: str) -> list[tuple[str, bool, str]]:
    """Empêche Android d'endormir le jeu quand sa fenêtre n'est pas au premier plan.
    Renvoie [(étape, réussi, réponse)] : liste blanche d'économie d'énergie + autorisation d'activité en arrière-plan."""
    pkg, user = split_package(spec)
    uopt = ["--user", str(user)] if user is not None else []
    steps = [
        ("Exclure de l'économie de batterie", ["shell", "cmd", "deviceidle", "whitelist", f"+{pkg}"]),
        ("Autoriser l'activité en arrière-plan", ["shell", "cmd", "appops", "set", *uopt, pkg, "RUN_IN_BACKGROUND", "allow"]),
        ("Autoriser l'activité longue en arrière-plan", ["shell", "cmd", "appops", "set", *uopt, pkg, "RUN_ANY_IN_BACKGROUND", "allow"]),
    ]
    out = []
    for title, args in steps:
        try:
            out.append((title, True, run_adb(args, serial, timeout=10).strip()))
        except AdbError as exc:
            out.append((title, False, str(exc)))
    return out


def open_battery_settings(serial: str, spec: str) -> None:
    """Ouvre sur le téléphone la page de l'application (Batterie / Démarrage automatique selon la marque)."""
    pkg, user = split_package(spec)
    args = ["shell", "am", "start"] + (["--user", str(user)] if user is not None else []) + [
        "-a", "android.settings.APPLICATION_DETAILS_SETTINGS", "-d", f"package:{pkg}"]
    run_adb(args, serial, timeout=10)


def restart_game(serial: str, spec: str) -> tuple[str, int | None, int | None]:
    """Ferme l'application du jeu sur le téléphone. Renvoie (paquet, utilisateur, écran virtuel) pour la relancer."""
    pkg, user = split_package(spec)
    uopt = ["--user", str(user)] if user is not None else []
    run_adb(["shell", "am", "force-stop", *uopt, pkg], serial, timeout=10)
    time.sleep(0.8)
    return pkg, user, find_virtual_display_id(serial)


def launch_game(serial: str, pkg: str, user: int, display: int | None) -> str:
    return start_user_app(serial, pkg, user, display)


# --- diagnostic de la détection ---------------------------------------------------------------------------------------------
def raw_devices() -> tuple[str, str]:
    """(sortie brute de `adb devices -l`, erreur ou ''). Le serveur adb est démarré au besoin par cette commande."""
    try:
        return run_adb(["devices", "-l"], timeout=12), ""
    except AdbError as exc:
        return "", str(exc)


def analyze_adb_output(raw: str, error: str = "") -> tuple[str, str]:
    """(niveau « ok|warn|bad », phrase) : le serveur adb tourne-t-il, et que voit-il ? Sans Qt, testable."""
    low = (raw + " " + error).lower()
    if error and ("délai dépassé" in low or "timed out" in low):
        return "bad", "le serveur adb ne répond pas (délai dépassé) : ferme les autres outils Android (Android Studio, Samsung Smart Switch, "\
                      "autre adb) puis exécute « adb kill-server »."
    if server_conflict(low):
        return "bad", CONFLICT_HINT
    if "cannot connect to daemon" in low or "didn't ack" in low or "address already in use" in low or "failed to start daemon" in low:
        return "bad", "le serveur adb ne démarre pas (port 5037 pris par un autre adb ?). Ferme les autres adb, puis « adb kill-server »."
    if error:
        return "bad", f"adb a échoué : {error.splitlines()[0][:200]}"
    note = "le serveur adb vient d'être démarré par notrefu-mirror. " if "daemon started successfully" in low or "daemon not running" in low else ""
    devs = parse_devices(raw)
    if not devs:
        return "warn", note + "le serveur adb tourne mais ne voit AUCUN appareil (câble, mode USB, pilote ou règles USB)."
    bad = [d for d in devs if d.state != "device"]
    if not bad:
        return "ok", note + f"le serveur adb tourne ; {len(devs)} appareil(s) prêt(s)."
    return "warn", note + "le serveur adb tourne ; appareil vu mais pas prêt : " + ", ".join(f"{d.label}" for d in bad)


def usb_vendors_seen() -> list[tuple[str, str]]:
    """Linux : [(identifiant, constructeur)] des appareils USB branchés (lecture de /sys, sans lsusb). Vide ailleurs."""
    base = Path("/sys/bus/usb/devices")
    seen: dict[str, str] = {}
    try:
        for d in base.iterdir():
            f = d / "idVendor"
            if f.exists():
                vid = f.read_text().strip().lower()
                if vid in USB_VENDORS:
                    seen[vid] = USB_VENDORS[vid]
    except OSError:
        return []
    return sorted(seen.items())


def game_memory_mb(serial: str, package: str) -> int | None:
    """Mémoire (PSS) de l'application du jeu en Mo, ou None (application fermée, commande lente ou non supportée)."""
    from .phonehealth import parse_pkg_meminfo

    try:
        return parse_pkg_meminfo(run_adb(["shell", "dumpsys", "meminfo", package], serial=serial, timeout=8))
    except AdbError:
        return None
