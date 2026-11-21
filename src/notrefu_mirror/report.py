"""Rapport de diagnostic complet à copier-coller (sans Qt) : versions, système, sessions, derniers journaux.

Les adresses IP et numéros de série sont masqués : le rapport peut être partagé sans révéler le réseau ni l'appareil."""

from __future__ import annotations

import re

_IP = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.\d{1,3}\.\d{1,3}\b")
_HOST_PORT = re.compile(r"\b(\d{1,3}\.\d{1,3}\.)\d{1,3}\.\d{1,3}(:\d+)?\b")


def mask_ip(text: str) -> str:
    """192.168.1.42:5555 -> 192.168.x.x:5555"""
    return _HOST_PORT.sub(lambda m: f"{m.group(1)}x.x{m.group(2) or ''}", text)


def mask_serial(serial: str) -> str:
    if not serial:
        return "—"
    if re.search(r"\d+\.\d+\.\d+\.\d+", serial):
        return mask_ip(serial)
    return serial[:3] + "…" + serial[-2:] if len(serial) > 6 else "…"


def session_block(info: dict) -> str:
    lines = [f"- {info.get('title', '?')} : {info.get('state', '?')}"]
    for key, label in (("phone", "téléphone"), ("link", "liaison"), ("quality", "qualité"), ("fps_cap", "plafond d'ips"),
                       ("health", "santé"), ("perf", "flux"), ("audio", "son")):
        if info.get(key):
            lines.append(f"    {label} : {info[key]}")
    tail = info.get("log") or []
    if tail:
        lines.append("    derniers messages :")
        lines += [f"      {mask_ip(str(x))[:200]}" for x in tail[-12:]]
    return "\n".join(lines)


def build_report(app: dict, diagnostic: str, sessions: list[dict]) -> str:
    head = "\n".join(f"{k} : {v}" for k, v in app.items())
    body = "\n".join(session_block(s) for s in sessions) or "(aucune session)"
    return f"=== notrefu-mirror : rapport ===\n{head}\n\n=== Diagnostic ===\n{mask_ip(diagnostic)}\n\n=== Sessions ===\n{body}\n"
