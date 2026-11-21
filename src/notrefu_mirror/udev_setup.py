"""Règle udev pour l'accès USB (adb), sans Qt : commandes et installation. Les boîtes de dialogue restent dans l'interface."""

from __future__ import annotations

import os
import subprocess
import tempfile

from . import adb


def manual_command() -> str:
    return (
        f"sudo tee {adb.UDEV_RULE_PATH} <<'EOF'\n{adb.UDEV_RULE}EOF\n"
        "sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=usb"
    )


def install_shell(tmp: str) -> str:
    return (f'install -m 0644 "{tmp}" {adb.UDEV_RULE_PATH} && udevadm control --reload-rules '
            "&& udevadm trigger --subsystem-match=usb")


def install_rule(pkexec: str) -> None:
    """Écrit la règle avec les droits administrateur ; lève RuntimeError si refusé ou en échec."""
    with tempfile.NamedTemporaryFile("w", suffix=".rules", delete=False) as f:
        f.write(adb.UDEV_RULE)
        tmp = f.name
    try:
        res = subprocess.run([pkexec, "sh", "-c", install_shell(tmp)], capture_output=True, text=True, timeout=120)
        if res.returncode != 0:
            raise RuntimeError((res.stderr or res.stdout or "annulé").strip())
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
