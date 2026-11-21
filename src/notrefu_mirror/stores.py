"""Persistance de l'application sans Qt : espaces, démarrage, restauration, panneau Guides.

Extrait de `MainWindow`, qui lisait et écrivait QSettings partout. Chaque classe prend un « magasin »
(QSettings, ou n'importe quel objet avec `value`, `setValue`, `remove`, `allKeys`) : les clés restent celles d'avant.
"""

from __future__ import annotations

from typing import Any, Protocol

from .session_config import SessionConfig


class Store(Protocol):
    def value(self, key: str, default: Any = None) -> Any: ...
    def setValue(self, key: str, value: Any) -> None: ...
    def remove(self, key: str) -> None: ...
    def allKeys(self) -> list[str]: ...


def as_bool(v: Any, default: bool = False) -> bool:
    return default if v is None else str(v).lower() in ("true", "1")


def as_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def space_name(raw: str) -> str:
    """Nom d'espace utilisable comme clé (pas de « / », 40 caractères au plus)."""
    return raw.strip().replace("/", "-")[:40]


class WorkspaceStore:
    """Espaces = groupes de sessions enregistrés sous « ws/<nom>/<n> »."""

    def __init__(self, qs: Store) -> None:
        self.qs = qs

    def names(self) -> list[str]:
        found = {k.split("/")[1] for k in self.qs.allKeys() if k.startswith("ws/") and k.count("/") >= 2}
        return sorted(found)

    def count(self, name: str) -> int:
        return as_int(self.qs.value(f"ws/{name}/count", 0) or 0)

    def prefix(self, name: str, index: int) -> str:
        return f"ws/{name}/{index}"

    def save(self, name: str, configs: list[SessionConfig]) -> None:
        self.delete(name)
        for i, cfg in enumerate(configs):
            cfg.save(self.qs, self.prefix(name, i))
        self.qs.setValue(f"ws/{name}/count", len(configs))

    def delete(self, name: str) -> None:
        self.qs.remove(f"ws/{name}")


class StartupStore:
    """Que faire au lancement, et dernier état des onglets."""

    def __init__(self, qs: Store) -> None:
        self.qs = qs

    def raw(self) -> str:
        v = str(self.qs.value("startup", "restore"))
        return v if v in ("restore", "empty") or v.startswith("space:") else "restore"

    def mode(self) -> str:
        """« restore » rouvre les dernières sessions ; sinon on part sans session."""
        return "restore" if self.raw() == "restore" else "empty"

    def set(self, mode: str) -> None:
        self.qs.setValue("startup", mode)

    def tab_count(self) -> int:
        v = self.qs.value("tabs")
        n = 1 if v is None else as_int(v, 1)
        return max(0, min(n, 8))

    def set_tab_count(self, n: int) -> None:
        self.qs.setValue("tabs", n)

    def restore_policy(self) -> str:
        """Relancer les sessions qui tournaient à la fermeture : « ask », « always » ou « never »."""
        return str(self.qs.value("restore", "ask"))

    def set_restore_always(self) -> None:
        self.qs.setValue("restore", "always")


class GuidesStore:
    """Réglages du panneau Guides (les sites et zooms sont gérés par guides.py)."""

    def __init__(self, qs: Store) -> None:
        self.qs = qs

    @property
    def auto(self) -> bool:
        return as_bool(self.qs.value("guides/auto", "true"), True)

    @auto.setter
    def auto(self, on: bool) -> None:
        self.qs.setValue("guides/auto", on)

    @property
    def width(self) -> int:
        return as_int(self.qs.value("guides/width", 0) or 0) or 480

    @width.setter
    def width(self, w: int) -> None:
        self.qs.setValue("guides/width", w)

    @property
    def side(self) -> str:
        return "left" if str(self.qs.value("guides/side", "right")) == "left" else "right"

    @side.setter
    def side(self, s: str) -> None:
        self.qs.setValue("guides/side", "left" if s == "left" else "right")
