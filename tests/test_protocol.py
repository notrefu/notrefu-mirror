"""Vérifie protocol.py contre les octets attendus de la suite de tests officielle de scrcpy 5.0.1
(app/tests/test_control_msg_serialize.c) et contre le format de flux de Streamer.java."""

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from notrefu_mirror import protocol as P  # noqa: E402


class ControlVectors(unittest.TestCase):
    def test_inject_keycode(self):
        got = P.inject_keycode(P.KEY_UP, P.AKEYCODE_ENTER, 5, P.META_SHIFT_ON | P.META_SHIFT_LEFT_ON)
        self.assertEqual(got, bytes([0, 0x01, 0, 0, 0, 0x42, 0, 0, 0, 0x05, 0, 0, 0, 0x41]))
        self.assertEqual(len(got), 14)

    def test_inject_text(self):
        got = P.inject_text("hello, world!")
        self.assertEqual(got, bytes([1, 0, 0, 0, 0x0D]) + b"hello, world!")
        self.assertEqual(len(got), 18)

    def test_inject_text_long_is_truncated_to_300(self):
        got = P.inject_text("a" * 500)
        self.assertEqual(len(got), 5 + 300)
        self.assertEqual(got[:5], bytes([1, 0, 0, 0x01, 0x2C]))
        self.assertEqual(got[5:], b"a" * 300)

    def test_inject_text_utf8_boundary(self):
        # 'é' = 2 octets : 299 'a' + 'é' dépasse 300 octets, le 'é' doit être retiré en entier
        got = P.inject_text("a" * 299 + "é")
        self.assertEqual(got[5:], b"a" * 299)
        self.assertEqual(struct.unpack(">I", got[1:5])[0], 299)
        got = P.inject_text("é")
        self.assertEqual(got, bytes([1, 0, 0, 0, 2]) + "é".encode())

    def test_inject_touch_event(self):
        got = P.inject_touch_event(
            P.ACTION_DOWN, 0x1234567887654321, 100, 200, 1080, 1920, 1.0, P.BUTTON_PRIMARY, P.BUTTON_PRIMARY
        )
        expected = bytes(
            [2, 0x00]
            + [0x12, 0x34, 0x56, 0x78, 0x87, 0x65, 0x43, 0x21]
            + [0, 0, 0, 0x64, 0, 0, 0, 0xC8]
            + [0x04, 0x38, 0x07, 0x80]
            + [0xFF, 0xFF]
            + [0, 0, 0, 1]
            + [0, 0, 0, 1]
        )
        self.assertEqual(got, expected)
        self.assertEqual(len(got), 32)

    def test_inject_touch_pressure_zero_and_move(self):
        got = P.inject_touch_event(P.ACTION_UP, P.POINTER_ID_MOUSE, 1, 2, 3, 4, 0.0)
        self.assertEqual(got[1], 1)
        self.assertEqual(got[2:10], b"\xff" * 8)
        self.assertEqual(got[22:24], b"\x00\x00")

    def test_inject_scroll_event(self):
        got = P.inject_scroll_event(260, 1026, 1080, 1920, 16, -16, 1)
        expected = bytes(
            [3]
            + [0, 0, 0x01, 0x04, 0, 0, 0x04, 0x02]
            + [0x04, 0x38, 0x07, 0x80]
            + [0x7F, 0xFF]
            + [0x80, 0x00]
            + [0, 0, 0, 1]
        )
        self.assertEqual(got, expected)
        self.assertEqual(len(got), 21)

    def test_get_clipboard(self):
        self.assertEqual(P.get_clipboard(P.COPY_KEY_COPY), bytes([8, 1]))

    def test_set_clipboard(self):
        got = P.set_clipboard("hello, world!", paste=True, sequence=0x0102030405060708)
        exp = bytes([9, 1, 2, 3, 4, 5, 6, 7, 8, 1, 0, 0, 0, 13]) + b"hello, world!"
        self.assertEqual(got, exp)
        self.assertEqual(len(got), 27)
        big = P.set_clipboard("a" * 400000)
        self.assertEqual(len(big), P.CONTROL_MSG_MAX_SIZE)

    def test_back_or_screen_on(self):
        self.assertEqual(P.back_or_screen_on(P.KEY_UP), bytes([4, 1]))

    def test_set_display_power(self):
        self.assertEqual(P.set_display_power(True), bytes([10, 1]))
        self.assertEqual(P.set_display_power(False), bytes([10, 0]))

    def test_start_app(self):
        got = P.start_app("firefox")
        self.assertEqual(got, bytes([16, 7]) + b"firefox")
        self.assertEqual(len(got), 9)

    def test_simple_messages(self):
        self.assertEqual(P.simple_message(P.MSG_RESET_VIDEO), bytes([17]))
        self.assertEqual(P.simple_message(P.MSG_EXPAND_NOTIFICATION_PANEL), bytes([5]))

    def test_fixed_point(self):
        self.assertEqual(P.float_to_u16fp(1.0), 0xFFFF)
        self.assertEqual(P.float_to_u16fp(0.0), 0)
        self.assertEqual(P.float_to_u16fp(0.5), 0x8000)
        self.assertEqual(P.float_to_i16fp(1.0), 0x7FFF)
        self.assertEqual(P.float_to_i16fp(-1.0), -0x8000)
        self.assertEqual(P.float_to_i16fp(0.0), 0)

    def test_droppable(self):
        move = P.inject_touch_event(P.ACTION_MOVE, 1, 0, 0, 10, 10)
        down = P.inject_touch_event(P.ACTION_DOWN, 1, 0, 0, 10, 10)
        self.assertTrue(P.is_droppable_move(move))
        self.assertFalse(P.is_droppable_move(down))
        self.assertFalse(P.is_droppable_move(P.inject_text("x")))


class StreamFormat(unittest.TestCase):
    def test_session_packet(self):
        # Streamer.writeSessionMeta : (1<<63)>>32 = 0x80000000, puis largeur, hauteur
        hdr = struct.pack(">III", 0x80000000, 1920, 1080)
        s = P.parse_packet_header(hdr)
        self.assertEqual(s, P.SessionPacket(1920, 1080, False))
        hdr = struct.pack(">III", 0x80000001, 1080, 1920)
        self.assertTrue(P.parse_packet_header(hdr).client_resized)

    def test_media_packet_header(self):
        # Streamer.writeFrameMeta : pts | key frame << 61, puis taille
        hdr = struct.pack(">QI", 123456 | P.PACKET_FLAG_KEY_FRAME, 4096)
        h = P.parse_packet_header(hdr)
        self.assertEqual(h, P.MediaPacketHeader(pts=123456, config=False, key_frame=True, size=4096))
        hdr = struct.pack(">QI", P.PACKET_FLAG_CONFIG, 30)
        h = P.parse_packet_header(hdr)
        self.assertTrue(h.config)
        self.assertFalse(h.key_frame)
        self.assertEqual(h.size, 30)

    def test_bad_header_size(self):
        with self.assertRaises(ValueError):
            P.parse_packet_header(b"\x00" * 11)

    def test_device_name(self):
        buf = b"Pixel 8 Pro".ljust(64, b"\0")
        self.assertEqual(P.parse_device_name(buf), "Pixel 8 Pro")

    def test_codec_id_is_h264_ascii(self):
        self.assertEqual(P.CODEC_H264.to_bytes(4, "big"), b"h264")

    def test_config_merger(self):
        m = P.ConfigMerger()
        self.assertIsNone(m.push(b"SPSPPS", config=True))
        self.assertEqual(m.push(b"FRAME1", config=False), b"SPSPPSFRAME1")
        self.assertEqual(m.push(b"FRAME2", config=False), b"FRAME2")


class ServerArgs(unittest.TestCase):
    def test_defaults(self):
        args = P.build_server_args(P.ServerParams(scid=0x1234ABCD))
        self.assertEqual(args[0], "scid=1234abcd")
        for a in ("audio=false", "tunnel_forward=true", "clipboard_autosync=false", "video_bit_rate=8000000"):
            self.assertIn(a, args)
        self.assertFalse(any(a.startswith("new_display") for a in args))

    def test_full(self):
        p = P.ServerParams(
            scid=1, video_bit_rate=6_000_000, max_fps=60, max_size=1920, new_display="1920x1080/280",
            audio=True, show_touches=True, stay_awake=True, power_off_on_close=True,
        )
        args = P.build_server_args(p)
        for a in ("video_bit_rate=6000000", "max_fps=60", "max_size=1920", "new_display=1920x1080/280",
                  "show_touches=true", "stay_awake=true", "power_off_on_close=true"):
            self.assertIn(a, args)
        self.assertNotIn("audio=false", args)

    def test_audio_args(self):
        args = P.build_server_args(P.ServerParams(scid=1, audio=True))
        self.assertIn("audio_codec=raw", args)
        self.assertNotIn("audio=false", args)
        self.assertEqual(P.CODEC_RAW.to_bytes(4, "big"), b"\0raw")

    def test_injection_refused(self):
        for bad in ("1920x1080; reboot", "a b", "$(id)", "x'y", "a|b"):
            with self.assertRaises(ValueError):
                P.build_server_args(P.ServerParams(scid=1, new_display=bad))

    def test_scid_range(self):
        with self.assertRaises(ValueError):
            P.build_server_args(P.ServerParams(scid=-1))
        with self.assertRaises(ValueError):
            P.build_server_args(P.ServerParams(scid=0x80000000))


if __name__ == "__main__":
    unittest.main()


class AudioSourceArgs(unittest.TestCase):
    def test_audio_source_playback(self):
        args = P.build_server_args(P.ServerParams(scid=1, audio=True, audio_source="playback"))
        self.assertIn("audio_source=playback", args)

    def test_no_audio_source_by_default(self):
        self.assertFalse([a for a in P.build_server_args(P.ServerParams(scid=1, audio=True)) if a.startswith("audio_source")])
        self.assertFalse([a for a in P.build_server_args(P.ServerParams(scid=1, audio=False, audio_source="playback")) if a.startswith("audio_source")])
