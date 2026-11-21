"""Réglages enregistrés (QSettings), avec reprise automatique de ceux de l'ancien nom de l'application (MirrorDeck)."""

from __future__ import annotations

from PySide6.QtCore import QSettings

ORG = "notrefu"
APP = "notrefu-mirror"
LEGACY = ("MirrorDeck", "MirrorDeck")  # ancien nom : organisation, application
_FLAG = "_migrated_from_legacy"
_checked = False


def migrate_legacy(new: QSettings, old: QSettings) -> int:
    """Copie les réglages de l'ancien nom vers le nouveau, une seule fois. Renvoie le nombre de clés copiées."""
    if new.contains(_FLAG):
        return 0
    n = 0
    if not new.allKeys():  # nouvelle installation uniquement : on ne mélange jamais deux jeux de réglages
        for k in old.allKeys():
            new.setValue(k, old.value(k))
            n += 1
    new.setValue(_FLAG, True)
    new.sync()
    return n


def app_settings() -> QSettings:
    global _checked
    qs = QSettings(ORG, APP)
    if not _checked:
        _checked = True
        try:
            migrate_legacy(qs, QSettings(*LEGACY))
        except Exception:  # la reprise est un confort : jamais bloquante
            pass
    return qs
