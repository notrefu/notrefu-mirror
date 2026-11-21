"""Réglages propres à Windows (sans effet ailleurs) : pas de fenêtre de console qui clignote pour adb, sorties valides."""

from __future__ import annotations

import os
import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000


def apply() -> None:
    if sys.platform != "win32":
        return
    for name in ("stdout", "stderr"):  # pythonw.exe : pas de console, donc pas de flux
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    if getattr(subprocess.Popen, "_notrefu_mirror_patched", False):
        return
    original = subprocess.Popen.__init__

    def init(self, *args, **kwargs):  # noqa: ANN001
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | CREATE_NO_WINDOW
        original(self, *args, **kwargs)

    subprocess.Popen.__init__ = init  # type: ignore[method-assign]
    subprocess.Popen._notrefu_mirror_patched = True  # type: ignore[attr-defined]
