"""Lecteur audio pour Windows : flux PCM brut (s16, 48 kHz, stéréo) joué par l'API « waveOut » de winmm.dll.

Aucun module externe : seulement ctypes. L'objet imite assez un processus pour que `audio.run_audio` l'utilise comme
`paplay` sous Linux (`stdin.write`, `stdin.flush`, `stdin.close`, `wait`, `kill`)."""

from __future__ import annotations

import ctypes
import subprocess
import sys
import time

CHUNK_MS = 20
WHDR_DONE, WHDR_PREPARED, WHDR_INQUEUE = 0x1, 0x2, 0x10
WAVE_MAPPER = 0xFFFFFFFF
WAVE_FORMAT_PCM = 1


class WinAudioError(RuntimeError):
    pass


def _structures():
    from ctypes import wintypes as w

    class WAVEFORMATEX(ctypes.Structure):
        _fields_ = [("wFormatTag", w.WORD), ("nChannels", w.WORD), ("nSamplesPerSec", w.DWORD),
                    ("nAvgBytesPerSec", w.DWORD), ("nBlockAlign", w.WORD), ("wBitsPerSample", w.WORD),
                    ("cbSize", w.WORD)]

    class WAVEHDR(ctypes.Structure):
        _fields_ = [("lpData", ctypes.c_void_p), ("dwBufferLength", w.DWORD), ("dwBytesRecorded", w.DWORD),
                    ("dwUser", ctypes.c_size_t), ("dwFlags", w.DWORD), ("dwLoops", w.DWORD),
                    ("lpNext", ctypes.c_void_p), ("reserved", ctypes.c_size_t)]

    return WAVEFORMATEX, WAVEHDR


class WavePlayer:
    """Joue du PCM s16le au fil de l'eau. `write` ne bloque jamais plus de ~50 ms : au-delà, le morceau est abandonné."""

    def __init__(self, latency_ms: int = 120, rate: int = 48000, channels: int = 2) -> None:
        if sys.platform != "win32":
            raise WinAudioError("réservé à Windows")
        self.stdin = self
        self.closed = False
        self._winmm = ctypes.WinDLL("winmm")
        fmt_t, hdr_t = _structures()
        m = self._winmm
        for name in ("waveOutPrepareHeader", "waveOutWrite", "waveOutUnprepareHeader"):
            fn = getattr(m, name)
            fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(hdr_t), ctypes.c_uint]
            fn.restype = ctypes.c_uint
        m.waveOutOpen.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint, ctypes.POINTER(fmt_t),
                                  ctypes.c_size_t, ctypes.c_size_t, ctypes.c_uint32]
        m.waveOutOpen.restype = ctypes.c_uint
        m.waveOutReset.argtypes = m.waveOutClose.argtypes = [ctypes.c_void_p]
        m.waveOutReset.restype = m.waveOutClose.restype = ctypes.c_uint
        block = channels * 2
        fmt = fmt_t(WAVE_FORMAT_PCM, channels, rate, rate * block, block, 16, 0)
        self._h = ctypes.c_void_p()
        res = m.waveOutOpen(ctypes.byref(self._h), WAVE_MAPPER, ctypes.byref(fmt), 0, 0, 0)
        if res != 0:
            raise WinAudioError(f"waveOutOpen a échoué (code {res}) : aucune sortie audio disponible ?")
        self._chunk = rate * block * CHUNK_MS // 1000
        count = max(4, latency_ms // CHUNK_MS + 2)
        self._bufs = [ctypes.create_string_buffer(self._chunk) for _ in range(count)]
        self._hdrs = []
        for b in self._bufs:
            h = hdr_t(ctypes.cast(b, ctypes.c_void_p), self._chunk, 0, 0, 0, 0, None, 0)
            if m.waveOutPrepareHeader(self._h, ctypes.byref(h), ctypes.sizeof(h)) != 0:
                self.close()
                raise WinAudioError("waveOutPrepareHeader a échoué")
            self._hdrs.append(h)
        self._next = 0
        self._block = block

    def _free_slot(self) -> int | None:
        deadline = time.monotonic() + 0.05
        while True:
            n = len(self._hdrs)
            for k in range(n):
                i = (self._next + k) % n
                if not self._hdrs[i].dwFlags & WHDR_INQUEUE:
                    self._next = (i + 1) % n
                    return i
            if time.monotonic() > deadline:
                return None
            time.sleep(0.004)

    def write(self, data: bytes) -> int:
        if self.closed:
            raise OSError("lecteur fermé")
        data = bytes(data[: len(data) // self._block * self._block])
        for off in range(0, len(data), self._chunk):
            piece = data[off: off + self._chunk]
            i = self._free_slot()
            if i is None:
                continue  # le lecteur n'avance pas : on saute ce morceau plutôt que de bloquer le flux
            h = self._hdrs[i]
            ctypes.memmove(self._bufs[i], piece, len(piece))
            h.dwBufferLength = len(piece)
            if self._winmm.waveOutWrite(self._h, ctypes.byref(h), ctypes.sizeof(h)) != 0:
                raise OSError("waveOutWrite a échoué")
        return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        m = self._winmm
        try:
            m.waveOutReset(self._h)
            for h in self._hdrs:
                m.waveOutUnprepareHeader(self._h, ctypes.byref(h), ctypes.sizeof(h))
            m.waveOutClose(self._h)
        except Exception:  # noqa: BLE001 - fermeture : rien à faire de plus
            pass

    def wait(self, timeout: float | None = None) -> int:
        self.close()
        return 0

    def kill(self) -> None:
        self.close()

    def poll(self) -> int | None:
        return 0 if self.closed else None


__all__ = ["WavePlayer", "WinAudioError", "subprocess"]
