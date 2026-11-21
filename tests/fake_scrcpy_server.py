"""Faux serveur scrcpy (TCP) : envoie un vrai flux H.264 (libx264) et enregistre les messages de contrôle."""
import time
import socket
import struct
import threading
import time
from fractions import Fraction


def make_packets(w=320, h=240, n=20, fps=30):
    import av
    ctx = av.CodecContext.create("libx264", "w")
    ctx.width, ctx.height, ctx.pix_fmt = w, h, "yuv420p"
    ctx.time_base = Fraction(1, fps)
    ctx.framerate = Fraction(fps, 1)
    ctx.options = {"preset": "ultrafast", "tune": "zerolatency", "x264-params": "repeat-headers=1:annexb=1"}
    ctx.open()
    out = []
    for i in range(n):
        f = av.VideoFrame(w, h, "yuv420p")
        for p in f.planes:
            p.update(bytes([(i * 12) % 256]) * p.buffer_size)
        f.pts = i
        out += [bytes(p) for p in ctx.encode(f)]
    out += [bytes(p) for p in ctx.encode(None)]
    return out


class FakeServer:
    def __init__(self, w=320, h=240, n=20, audio=False):
        self.w, self.h = w, h
        self.audio = audio
        self.packets = make_packets(w, h, n)
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.control_bytes = bytearray()
        self.conns = []
        self.hold = threading.Event()
        self.sessions = 0
        threading.Thread(target=self._serve_forever, daemon=True).start()

    def _serve_forever(self):
        """Une session après l'autre : permet de tester la reconnexion."""
        while True:
            try:
                self._serve()
            except OSError:
                return
            if self.sock.fileno() == -1:
                return

    def _serve(self):
        self.hold.clear()
        try:
            video, _ = self.sock.accept()
            self.sessions += 1
            video.sendall(b"\0")
            audio = None
            if self.audio:
                audio, _ = self.sock.accept()
            control, _ = self.sock.accept()
            self.conns = [video, control] + ([audio] if audio else [])
            if audio:
                audio.sendall(b"\0raw")
                for i in range(10):
                    pcm = bytes([i + 1]) * 3840
                    audio.sendall(struct.pack(">QI", i * 20000, len(pcm)) + pcm)
                    time.sleep(0.02)  # temps réel : 3840 octets = 20 ms
            threading.Thread(target=self._read_ctl, args=(control,), daemon=True).start()
            txt = "copié sur le téléphone".encode()
            control.sendall(b"\x00" + len(txt).to_bytes(4, "big") + txt + b"\x01" + (7).to_bytes(8, "big"))
            video.sendall(b"Fake Phone".ljust(64, b"\0"))
            video.sendall(b"h264")
            video.sendall(struct.pack(">III", 0x80000000, self.w, self.h))
            for i, pkt in enumerate(self.packets):
                flags = (1 << 61) if i == 0 else 0
                video.sendall(struct.pack(">QI", flags | i, len(pkt)) + pkt)
                time.sleep(0.01)
            self.hold.wait(5)
        except OSError:
            if self.sock.fileno() == -1:
                raise

    def _read_ctl(self, s):
        try:
            while True:
                d = s.recv(4096)
                if not d:
                    return
                self.control_bytes += d
        except OSError:
            pass

    def close(self):
        self.hold.set()
        for c in self.conns + [self.sock]:
            try:
                c.close()
            except OSError:
                pass
