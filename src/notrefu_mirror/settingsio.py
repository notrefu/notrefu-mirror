"""Export / import des réglages de notrefu-mirror dans un fichier JSON (sessions, espaces, raccourcis, thème…)."""

from __future__ import annotations

import json
from typing import Any

MARKER = "notrefu-mirror-settings"
SKIP_PREFIXES = ("geometry", "detached/")  # propres à l'écran de ce PC : on ne les exporte pas


def _plain(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return None  # QByteArray et autres : non exportables


def collect(qs, version: str) -> dict:
    data: dict[str, Any] = {}
    for key in qs.allKeys():
        if key.startswith(SKIP_PREFIXES):
            continue
        v = _plain(qs.value(key))
        if v is not None:
            data[key] = v
    return {"app": MARKER, "version": version, "settings": data}


def export_to(qs, path: str, version: str) -> int:
    doc = collect(qs, version)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
    return len(doc["settings"])


class SettingsFileError(ValueError):
    pass


def read_file(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError, RecursionError) as exc:  # RecursionError : JSON imbriqué à l'extrême
        raise SettingsFileError(f"fichier illisible : {exc}") from exc
    if not isinstance(doc, dict) or doc.get("app") != MARKER or not isinstance(doc.get("settings"), dict):
        raise SettingsFileError("ce n'est pas un fichier de réglages notrefu-mirror")
    return doc["settings"]


def apply_to(qs, settings: dict[str, Any]) -> int:
    """Remplace les sessions, espaces et réglages par ceux du fichier (la géométrie de la fenêtre est conservée)."""
    for key in list(qs.allKeys()):
        if not key.startswith(SKIP_PREFIXES):
            qs.remove(key)
    n = 0
    for key, value in settings.items():
        if not isinstance(key, str) or not key.strip("/") or key.startswith(SKIP_PREFIXES) or ".." in key or "//" in key:
            continue
        qs.setValue(key, value)
        n += 1
    qs.sync()
    return n
