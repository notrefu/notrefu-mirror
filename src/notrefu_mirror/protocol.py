"""Protocole scrcpy 5.0.1, côté client. Sans dépendance Qt ni réseau : uniquement des octets.

Références (sources scrcpy v5.0.1) :
  - app/src/control_msg.c        sérialisation des messages de contrôle
  - app/tests/test_control_msg_serialize.c   octets attendus (repris dans tests/test_protocol.py)
  - app/src/demuxer.c, server/.../device/Streamer.java   flux vidéo
  - app/src/server.c             arguments passés au serveur
  - server/.../device/DesktopConnection.java   poignée de main des sockets

Le protocole change d'une version à l'autre : ce module n'est valable qu'avec le scrcpy-server 5.0.1
embarqué dans l'AppImage.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

SCRCPY_VERSION = "5.0.1"
DEVICE_SERVER_PATH = "/data/local/tmp/scrcpy-server.jar"
DEVICE_NAME_FIELD_LENGTH = 64

# --- types de messages client -> serveur (ControlMessage.TYPE_*) -------------
MSG_INJECT_KEYCODE = 0
MSG_INJECT_TEXT = 1
MSG_INJECT_TOUCH_EVENT = 2
MSG_INJECT_SCROLL_EVENT = 3
MSG_BACK_OR_SCREEN_ON = 4
MSG_EXPAND_NOTIFICATION_PANEL = 5
MSG_EXPAND_SETTINGS_PANEL = 6
MSG_COLLAPSE_PANELS = 7
MSG_GET_CLIPBOARD = 8
MSG_SET_CLIPBOARD = 9
MSG_SET_DISPLAY_POWER = 10
MSG_ROTATE_DEVICE = 11
MSG_START_APP = 16
MSG_RESET_VIDEO = 17

# --- constantes Android ------------------------------------------------------
KEY_DOWN = 0
KEY_UP = 1

ACTION_DOWN = 0
ACTION_UP = 1
ACTION_MOVE = 2
ACTION_HOVER_MOVE = 7

BUTTON_PRIMARY = 1 << 0
BUTTON_SECONDARY = 1 << 1
BUTTON_TERTIARY = 1 << 2
BUTTON_BACK = 1 << 3
BUTTON_FORWARD = 1 << 4

META_SHIFT_ON = 0x01
META_ALT_ON = 0x02
META_SHIFT_LEFT_ON = 0x40
META_SHIFT_RIGHT_ON = 0x80
META_ALT_LEFT_ON = 0x10
META_ALT_RIGHT_ON = 0x20
META_CTRL_ON = 0x1000
META_CTRL_LEFT_ON = 0x2000
META_CTRL_RIGHT_ON = 0x4000
META_META_ON = 0x10000
META_META_LEFT_ON = 0x20000

POINTER_ID_MOUSE = 0xFFFFFFFFFFFFFFFF  # UINT64_C(-1)
POINTER_ID_GENERIC_FINGER = 0xFFFFFFFFFFFFFFFE
POINTER_ID_VIRTUAL_FINGER = 0xFFFFFFFFFFFFFFFD

# Codes de touches Android (app/src/android/keycodes.h)
AKEYCODE_HOME = 3
AKEYCODE_BACK = 4
AKEYCODE_0 = 7
AKEYCODE_DPAD_UP = 19
AKEYCODE_DPAD_DOWN = 20
AKEYCODE_DPAD_LEFT = 21
AKEYCODE_DPAD_RIGHT = 22
AKEYCODE_VOLUME_UP = 24
AKEYCODE_VOLUME_DOWN = 25
AKEYCODE_POWER = 26
AKEYCODE_A = 29
AKEYCODE_ALT_LEFT = 57
AKEYCODE_ALT_RIGHT = 58
AKEYCODE_SHIFT_LEFT = 59
AKEYCODE_SHIFT_RIGHT = 60
AKEYCODE_TAB = 61
AKEYCODE_SPACE = 62
AKEYCODE_ENTER = 66
AKEYCODE_DEL = 67
AKEYCODE_MENU = 82
AKEYCODE_PAGE_UP = 92
AKEYCODE_PAGE_DOWN = 93
AKEYCODE_ESCAPE = 111
AKEYCODE_FORWARD_DEL = 112
AKEYCODE_CTRL_LEFT = 113
AKEYCODE_CTRL_RIGHT = 114
AKEYCODE_MOVE_HOME = 122
AKEYCODE_MOVE_END = 123
AKEYCODE_APP_SWITCH = 187

INJECT_TEXT_MAX_LENGTH = 300
MAX_PACKET_SIZE = 32 << 20  # au-delà, le flux est désynchronisé (en-tête corrompu) : on ne l'attend pas indéfiniment
CONTROL_MSG_MAX_SIZE = 1 << 18
CLIPBOARD_TEXT_MAX_LENGTH = CONTROL_MSG_MAX_SIZE - 14
COPY_KEY_NONE, COPY_KEY_COPY, COPY_KEY_CUT = 0, 1, 2

# messages serveur -> client (DeviceMessage.TYPE_*)
DEV_CLIPBOARD = 0
DEV_ACK_CLIPBOARD = 1
DEV_UHID_OUTPUT = 2

# --- flux vidéo --------------------------------------------------------------
CODEC_H264 = 0x68323634
CODEC_RAW = 0x00726177
AUDIO_RATE, AUDIO_CHANNELS = 48000, 2
PACKET_FLAG_SESSION = 1 << 63
PACKET_FLAG_CONFIG = 1 << 62
PACKET_FLAG_KEY_FRAME = 1 << 61
PACKET_PTS_MASK = PACKET_FLAG_KEY_FRAME - 1
PACKET_HEADER_SIZE = 12


# =============================================================================
# Messages de contrôle
# =============================================================================
def utf8_truncate(text: str, max_bytes: int) -> bytes:
    """Encode en UTF-8 en coupant sur une limite de caractère (comme sc_str_utf8_truncation_index)."""
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return data
    data = data[:max_bytes]
    while data:
        try:
            data.decode("utf-8")
            break
        except UnicodeDecodeError:
            data = data[:-1]
    return data


def float_to_u16fp(value: float) -> int:
    """float [0, 1] -> entier 16 bits à virgule fixe (sc_float_to_u16fp)."""
    value = min(max(value, 0.0), 1.0)
    u = int(value * 65536.0)
    return min(u, 0xFFFF)


def float_to_i16fp(value: float) -> int:
    """float [-1, 1] -> entier signé 16 bits à virgule fixe (sc_float_to_i16fp)."""
    value = min(max(value, -1.0), 1.0)
    i = int(value * 32768.0)  # troncature vers zéro, comme le cast C
    return min(i, 0x7FFF)


def inject_keycode(action: int, keycode: int, repeat: int = 0, metastate: int = 0) -> bytes:
    return struct.pack(">BBIII", MSG_INJECT_KEYCODE, action, keycode, repeat, metastate)


def inject_text(text: str) -> bytes:
    data = utf8_truncate(text, INJECT_TEXT_MAX_LENGTH)
    return struct.pack(">BI", MSG_INJECT_TEXT, len(data)) + data


def inject_touch_event(
    action: int,
    pointer_id: int,
    x: int,
    y: int,
    screen_w: int,
    screen_h: int,
    pressure: float = 1.0,
    action_button: int = 0,
    buttons: int = 0,
) -> bytes:
    return struct.pack(
        ">BBQiiHHHII",
        MSG_INJECT_TOUCH_EVENT,
        action,
        pointer_id,
        x,
        y,
        screen_w,
        screen_h,
        float_to_u16fp(pressure),
        action_button,
        buttons,
    )


def inject_scroll_event(
    x: int, y: int, screen_w: int, screen_h: int, hscroll: float, vscroll: float, buttons: int = 0
) -> bytes:
    h = float_to_i16fp(max(-1.0, min(1.0, hscroll / 16)))
    v = float_to_i16fp(max(-1.0, min(1.0, vscroll / 16)))
    return struct.pack(">BiiHHhhI", MSG_INJECT_SCROLL_EVENT, x, y, screen_w, screen_h, h, v, buttons)


def back_or_screen_on(action: int) -> bytes:
    return struct.pack(">BB", MSG_BACK_OR_SCREEN_ON, action)


def set_display_power(on: bool) -> bytes:
    return struct.pack(">BB", MSG_SET_DISPLAY_POWER, 1 if on else 0)


def start_app(name: str) -> bytes:
    data = utf8_truncate(name, 255)
    return struct.pack(">BB", MSG_START_APP, len(data)) + data


def get_clipboard(copy_key: int = COPY_KEY_NONE) -> bytes:
    return struct.pack(">BB", MSG_GET_CLIPBOARD, copy_key)


def set_clipboard(text: str, paste: bool = False, sequence: int = 0) -> bytes:
    """sequence 0 = pas d'acquittement demandé. `paste` : le téléphone appuie aussi sur « Coller »."""
    data = utf8_truncate(text, CLIPBOARD_TEXT_MAX_LENGTH)
    return struct.pack(">BQBI", MSG_SET_CLIPBOARD, sequence, 1 if paste else 0, len(data)) + data


def simple_message(msg_type: int) -> bytes:
    """Messages sans données : panneaux de notification, rotation, reset vidéo…"""
    return bytes([msg_type])


def is_droppable_move(msg: bytes) -> bool:
    """Un MOVE tactile peut être abandonné si le réseau est en retard (comme scrcpy)."""
    return len(msg) >= 2 and msg[0] == MSG_INJECT_TOUCH_EVENT and msg[1] == ACTION_MOVE


def is_stale_droppable(msg: bytes) -> bool:
    """Entrée tactile/clavier/molette qui ne doit JAMAIS être rejouée en retard (réseau bloqué, onglet masqué) : tout sauf
    les relâchements (UP) qu'il faut toujours livrer pour ne pas laisser un doigt ou une touche coincé."""
    if not msg:
        return False
    kind = msg[0]
    if kind in (MSG_INJECT_TOUCH_EVENT, MSG_INJECT_KEYCODE):
        return len(msg) >= 2 and msg[1] != ACTION_UP
    return kind == MSG_INJECT_SCROLL_EVENT


# =============================================================================
# Flux vidéo
# =============================================================================
def parse_device_name(buf: bytes) -> str:
    """Les 64 premiers octets : nom de l'appareil, terminé par un NUL."""
    return buf.split(b"\0", 1)[0].decode("utf-8", errors="replace")


@dataclass(frozen=True)
class SessionPacket:
    width: int
    height: int
    client_resized: bool


@dataclass(frozen=True)
class MediaPacketHeader:
    pts: int
    config: bool
    key_frame: bool
    size: int


def parse_packet_header(header: bytes) -> SessionPacket | MediaPacketHeader:
    """Analyse un en-tête de 12 octets : paquet de session (bit de poids fort) ou paquet média."""
    if len(header) != PACKET_HEADER_SIZE:
        raise ValueError(f"en-tête de {len(header)} octets (12 attendus)")
    if header[0] & 0x80:
        width, height = struct.unpack(">II", header[4:12])
        return SessionPacket(width, height, bool(header[3] & 1))
    pts_flags, size = struct.unpack(">QI", header)
    return MediaPacketHeader(
        pts=pts_flags & PACKET_PTS_MASK,
        config=bool(pts_flags & PACKET_FLAG_CONFIG),
        key_frame=bool(pts_flags & PACKET_FLAG_KEY_FRAME),
        size=size,
    )


class ConfigMerger:
    """Les paquets de configuration (SPS/PPS H.264) sont fusionnés avec le paquet média suivant
    (app/src/packet_merger.c)."""

    def __init__(self) -> None:
        self._config: bytes | None = None

    def push(self, data: bytes, config: bool) -> bytes | None:
        """Renvoie les données à décoder, ou None si le paquet est un paquet de config mis en attente."""
        if config:
            self._config = data
            return None
        if self._config:
            data = self._config + data
            self._config = None
        return data


# =============================================================================
# Arguments du serveur (app/src/server.c)
# =============================================================================
_FORBIDDEN = " ;'\"*$?&`#\\|<>[]{}()!~\r\n"


def validate_server_string(value: str) -> str:
    """Les paramètres passent par le shell Android : le client officiel interdit ces caractères."""
    if any(c in _FORBIDDEN for c in value):
        raise ValueError(f"paramètre serveur invalide : {value!r}")
    return value


@dataclass
class ServerParams:
    scid: int
    video_bit_rate: int = 8_000_000
    max_fps: int = 0
    max_size: int = 0
    new_display: str = ""  # « 1920x1080/280 »
    audio: bool = False
    audio_codec: str = "raw"  # PCM 16 bits 48 kHz stéréo : pas de décodage côté client
    audio_source: str = ""  # « playback » : son des applications seulement (Android 13+), sans notifications
    show_touches: bool = False
    stay_awake: bool = False
    power_off_on_close: bool = False
    clipboard_autosync: bool = False
    log_level: str = "info"
    vd_system_decorations: bool = False  # False : pas de barre de navigation ni de « tiret » sur l'écran virtuel
    video_codec_options: str = ""  # « i-frame-interval:int=2 » : image clé toutes les 2 s


def build_server_args(p: ServerParams) -> list[str]:
    """Arguments `key=value` après la version, avec `tunnel_forward=true` (on se connecte à l'appareil)."""
    if not 0 <= p.scid <= 0x7FFFFFFF:
        raise ValueError("scid hors limites (31 bits)")
    args = [f"scid={p.scid:08x}", f"log_level={validate_server_string(p.log_level)}"]
    if not p.audio:
        args.append("audio=false")
    else:
        args.append(f"audio_codec={validate_server_string(p.audio_codec)}")
        if p.audio_source:
            args.append(f"audio_source={validate_server_string(p.audio_source)}")
    if p.video_bit_rate:
        args.append(f"video_bit_rate={int(p.video_bit_rate)}")
    if p.max_size:
        args.append(f"max_size={int(p.max_size)}")
    if p.max_fps:
        args.append(f"max_fps={int(p.max_fps)}")
    args.append("tunnel_forward=true")
    if p.show_touches:
        args.append("show_touches=true")
    if p.stay_awake:
        args.append("stay_awake=true")
    if p.power_off_on_close:
        args.append("power_off_on_close=true")
    if not p.clipboard_autosync:
        args.append("clipboard_autosync=false")
    if p.new_display:
        args.append(f"new_display={validate_server_string(p.new_display)}")
    if p.new_display and not p.vd_system_decorations:
        args.append("vd_system_decorations=false")
    if p.video_codec_options:
        args.append(f"video_codec_options={validate_server_string(p.video_codec_options)}")
    return args
