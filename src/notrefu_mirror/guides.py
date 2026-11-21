"""Fenêtre « Guides » : sites de guides (Papycha, Almanax…) affichés dans un navigateur intégré (QtWebEngine).

Les sites s'affichent tels quels, comme dans un navigateur : notrefu-mirror n'en extrait rien et n'utilise aucune API privée.
Si QtWebEngine est absent, les liens s'ouvrent dans le navigateur du système.
"""

from __future__ import annotations

import json
import os

from PySide6.QtCore import QSettings, QStandardPaths, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox, QToolButton, QVBoxLayout, QWidget
from .appsettings import app_settings

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")

_PROBE = (
    "import sys\n"
    "from PySide6.QtWebEngineWidgets import QWebEngineView\n"
    "from PySide6.QtWidgets import QApplication\n"
    "from PySide6.QtCore import QTimer, QUrl\n"
    "app = QApplication(sys.argv)\n"
    "from PySide6.QtCore import Qt\n"
    "app.setApplicationName('notrefu-mirror (vérification)')\n"
    "v = QWebEngineView(); v.setWindowTitle('notrefu-mirror'); v.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowDoesNotAcceptFocus)\n"
    "v.setWindowOpacity(0.0); v.resize(2, 2); v.setUrl(QUrl('about:blank')); v.show()\n"
    "QTimer.singleShot(1500, app.quit)\n"
    "app.exec()\n"
)


def web_engine_ok(version: str) -> bool:
    """Essaie le navigateur intégré dans un processus à part : s'il plante sur cette machine, on s'en passe.

    Le résultat est mémorisé par version (NOTREFU_MIRROR_PROBE=1 force un nouvel essai).
    """
    import subprocess
    import sys

    if os.environ.get("NOTREFU_MIRROR_NO_WEB"):
        return False
    qs = app_settings()
    key = "guides/probe"
    saved = str(qs.value(key, "") or "")
    try:  # le résultat dépend de la machine et de la version de Qt, pas de celle de notrefu-mirror : un seul essai par version de Qt
        import PySide6

        version = "qt" + PySide6.__version__
    except Exception:
        pass
    if saved.startswith(version + ":") and not os.environ.get("NOTREFU_MIRROR_PROBE"):
        return saved.endswith(":ok")
    try:
        r = subprocess.run([sys.executable, "-c", _PROBE], timeout=40, capture_output=True)
        ok = r.returncode == 0
    except Exception:
        ok = False
    qs.setValue(key, f"{version}:{'ok' if ok else 'fail'}")
    qs.sync()
    return ok


HAS_WEB = False  # devient vrai au premier chargement réussi (voir load_web)
_WEB: tuple | None = None
_WEB_TRIED = False


def load_web():
    """Charge QtWebEngine à la demande (premier affichage du panneau Guides) et renvoie (Page, Profil, Vue, PageSilencieuse) ou None.

    QtWebEngine est volumineux (plus de 100 Mo de bibliothèques) : l'importer au démarrage coûtait de la mémoire et du temps même
    quand les guides ne sont jamais ouverts. L'essai isolé (web_engine_ok) n'est lui aussi fait qu'à ce moment-là."""
    global HAS_WEB, _WEB, _WEB_TRIED
    if _WEB_TRIED:
        return _WEB
    _WEB_TRIED = True
    try:  # QtWebEngine dépend de la machine : essai isolé avant de l'utiliser
        from . import __version__ as version

        if not web_engine_ok(version):
            raise ImportError("navigateur intégré indisponible")
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
        from PySide6.QtWebEngineWidgets import QWebEngineView

        class QuietPage(QWebEnginePage):
            """Page web qui n'affiche pas dans le terminal les messages de console des sites."""

            def javaScriptConsoleMessage(self, level, message, line, source) -> None:  # noqa: N802
                return

        _WEB = (QWebEnginePage, QWebEngineProfile, QWebEngineView, QuietPage)
        HAS_WEB = True
    except Exception:  # pragma: no cover - dépend de l'environnement
        _WEB = None
    return _WEB


DEFAULT_SITES = [
    {"name": "Papycha", "url": "https://www.papycha.fr/"},
    {"name": "Almanax", "url": "https://www.krosmoz.com/fr/almanax"},
    {"name": "Lomitall", "url": "https://lomitall.fr/#outils/touch/almanax"},
]


def load_sites(qs: QSettings) -> list[dict]:
    try:
        data = json.loads(str(qs.value("guides/sites", "") or ""))
        sites = [s for s in data if isinstance(s, dict) and s.get("name") and str(s.get("url", "")).startswith(("http://", "https://"))]
        if sites:
            return sites
    except Exception:
        pass
    return [dict(s) for s in DEFAULT_SITES]


def save_sites(qs: QSettings, sites: list[dict]) -> None:
    qs.setValue("guides/sites", json.dumps(sites, ensure_ascii=False))


def clean_url(text: str) -> str:
    t = text.strip()
    if t and "://" not in t:
        t = "https://" + t
    return t if t.startswith(("http://", "https://")) and "." in t else ""


class GuidesPanel(QWidget):
    """Panneau « Guides » à placer à côté des sessions (dans la fenêtre principale)."""

    close_requested = Signal()
    side_requested = Signal()
    fit_requested = Signal()

    def __init__(self, qs: QSettings) -> None:
        super().__init__()
        self.qs = qs
        self.sites = load_sites(qs)
        self.setMinimumWidth(340)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QWidget()
        bl = QVBoxLayout(bar)
        bl.setContentsMargins(6, 5, 6, 5)
        bl.setSpacing(4)
        self.row1 = QHBoxLayout()  # sites
        self.row2 = QHBoxLayout()  # navigation et zoom
        bl.addLayout(self.row1)
        bl.addLayout(self.row2)
        lay.addWidget(bar)
        self.view = None
        self.site_box = QHBoxLayout()
        self.site_box.setSpacing(4)
        self.row1.addLayout(self.site_box)
        self.row1.addStretch(1)
        web = load_web()
        if web:
            _Page, _Profile, _View, _Quiet = web
            base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation) or "/tmp"
            self.profile = _Profile("notrefu_mirror-guides")
            self.profile.setPersistentStoragePath(base + "/guides")
            self.profile.setCachePath(base + "/guides-cache")
            self.view = _View(self)
            self.page = _Quiet(self.profile)
            self.view.setPage(self.page)
            lay.addWidget(self.view, 1)
            self._tool(self.row2, "←", "Page précédente", self.view.back)
            self._tool(self.row2, "→", "Page suivante", self.view.forward)
            self._tool(self.row2, "↻", "Recharger", self.view.reload)
            self._tool(self.row2, "−", "Dézoomer (Ctrl+-)", lambda: self.zoom_by(1 / 1.1))
            self._tool(self.row2, "+", "Zoomer (Ctrl++)", lambda: self.zoom_by(1.1))
            self._tool(self.row2, "↔", "Adapter la page à la largeur du panneau (évite le défilement horizontal)", self.fit_width)
            self.view.loadFinished.connect(self._apply_zoom)
            self.view.urlChanged.connect(self._remember_url)
            self.view.urlChanged.connect(self._mark_active)
            for keys, fn in (("Ctrl++", lambda: self.zoom_by(1.1)), ("Ctrl+=", lambda: self.zoom_by(1.1)),
                             ("Ctrl+-", lambda: self.zoom_by(1 / 1.1)), ("Ctrl+0", lambda: self.set_zoom(1.0))):
                sc = QShortcut(QKeySequence(keys), self)
                sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                sc.activated.connect(fn)
        else:
            msg = QLabel("Le navigateur intégré n'est pas disponible.\nLes guides s'ouvrent dans ton navigateur.")
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(msg, 1)
        self.row2.addStretch(1)
        self.more = self._tool(self.row1, "⋯", "Disposition du panneau", self.layout_menu)
        self._tool(self.row1, "✕", "Fermer les guides", self.close_requested.emit)
        self.rebuild()
        if self.sites:
            self.open_site(self.sites[0])

    def layout_menu(self) -> None:
        m = QMenu(self)
        m.addAction("Ajuster : le jeu sans bandes noires, les guides le reste", self.fit_requested.emit)
        m.addAction("Mettre les guides de l'autre côté des sessions", self.side_requested.emit)
        m.addSeparator()
        m.addAction("Ouvrir la page dans le navigateur du système", self.open_external)
        self._fill_sites_menu(m.addMenu("Sites"))
        m.exec(self.more.mapToGlobal(self.more.rect().bottomLeft()))

    def _mark_active(self, url: QUrl) -> None:
        """Le bouton du site affiché reste enfoncé : on sait toujours où on est."""
        for b in getattr(self, "site_buttons", []):
            b.setChecked(QUrl(b.toolTip()).host() == url.host())

    def _tool(self, row, text: str, tip: str, slot) -> QToolButton:
        b = QToolButton()
        b.setObjectName("tool")
        b.setText(text)
        b.setToolTip(tip)
        b.setStyleSheet("QToolButton { padding: 4px 9px; }")
        b.setMinimumWidth(b.sizeHint().width())
        b.clicked.connect(lambda _=False: slot())
        row.addWidget(b)
        return b

    # --- zoom (mémorisé par site) ---------------------------------------------------------------------------------
    def _host(self) -> str:
        return self.view.url().host() if self.view is not None else ""

    def set_zoom(self, f: float) -> None:
        if self.view is None:
            return
        f = max(0.25, min(3.0, f))
        self.view.setZoomFactor(f)
        host = self._host()
        if host:
            self.qs.setValue(f"guides/zoom/{host}", f)

    def zoom_by(self, k: float) -> None:
        if self.view is not None:
            self.set_zoom(self.view.zoomFactor() * k)

    def _apply_zoom(self, _ok: bool = True) -> None:
        host = self._host()
        if self.view is not None and host:
            try:
                self.view.setZoomFactor(float(self.qs.value(f"guides/zoom/{host}", 1.0) or 1.0))
            except (TypeError, ValueError):
                pass

    def fit_width(self) -> None:
        """Calcule le zoom pour que toute la largeur de la page tienne dans le panneau."""
        if self.view is None:
            return
        self.view.setZoomFactor(1.0)
        js = "Math.max(document.documentElement.scrollWidth, document.body ? document.body.scrollWidth : 0)"

        def done(width) -> None:
            try:
                w = float(width)
            except (TypeError, ValueError):
                return
            avail = max(100, self.view.width() - 18)  # marge pour l'ascenseur vertical
            self.set_zoom(avail / w if w > avail else 1.0)

        self.view.page().runJavaScript(js, done)

    def rebuild(self) -> None:
        self.site_buttons = []
        while self.site_box.count():
            w = self.site_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        for s in self.sites:
            b = QToolButton()
            b.setObjectName("tool")
            b.setText(s["name"])
            b.setToolTip(s["url"])
            b.setCheckable(True)
            b.setStyleSheet("QToolButton { padding: 4px 9px; }")
            b.setMinimumWidth(b.sizeHint().width())
            b.clicked.connect(lambda _=False, s=s: self.open_site(s))
            self.site_box.addWidget(b)
            self.site_buttons.append(b)
        if self.view is not None:
            self._mark_active(self.view.url())

    def _remember_url(self, url: QUrl) -> None:
        """Retient la dernière page visitée de chaque site (rouverte au clic sur son bouton)."""
        for s in self.sites:
            if QUrl(s["url"]).host() == url.host() and url.scheme() in ("http", "https"):
                self.qs.setValue("guides/last/" + s["name"], url.toString())
                break

    def open_site(self, site: dict) -> None:
        if self.view is not None:
            last = str(self.qs.value("guides/last/" + site["name"], "") or "")
            same = last and QUrl(last).host() == QUrl(site["url"]).host()
            self.view.setUrl(QUrl(last if same else site["url"]))
        else:
            QDesktopServices.openUrl(QUrl(site["url"]))

    def open_external(self) -> None:
        url = self.view.url() if self.view is not None else QUrl(self.sites[0]["url"] if self.sites else "")
        if url.isValid() and not url.isEmpty():
            QDesktopServices.openUrl(url)

    def _fill_sites_menu(self, m: QMenu) -> None:
        m.addAction("Ajouter un site…", self.add_site)
        if self.sites:
            d = m.addMenu("Retirer un site")
            for s in self.sites:
                d.addAction(s["name"], lambda s=s: self.remove_site(s))
        m.addSeparator()
        m.addAction("Rétablir la liste d'origine", self.reset_sites)

    def add_site(self) -> None:
        name, ok = QInputDialog.getText(self, "Ajouter un site", "Nom du bouton :")
        name = name.strip()[:24]
        if not ok or not name:
            return
        text, ok = QInputDialog.getText(self, "Ajouter un site", "Adresse (ex. papycha.fr) :")
        url = clean_url(text)
        if not ok:
            return
        if not url:
            QMessageBox.warning(self, "notrefu-mirror", "Adresse non valide.")
            return
        self.sites.append({"name": name, "url": url})
        self._persist()

    def remove_site(self, site: dict) -> None:
        self.sites = [s for s in self.sites if s is not site]
        self._persist()

    def reset_sites(self) -> None:
        self.sites = [dict(s) for s in DEFAULT_SITES]
        self._persist()

    def _persist(self) -> None:
        save_sites(self.qs, self.sites)
        self.rebuild()

    def stop(self) -> None:
        if self.view is not None:
            self.view.setUrl(QUrl("about:blank"))  # coupe vidéos/sons éventuels

    def shutdown(self) -> None:
        """Libère le moteur web dans le bon ordre (vue, page, puis profil) pour éviter l'avertissement à la fermeture."""
        if self.view is None:
            return
        try:
            import shiboken6

            self.view.setUrl(QUrl("about:blank"))
            view, page, profile = self.view, self.page, self.profile
            self.view = None
            shiboken6.delete(view)
            shiboken6.delete(page)
            shiboken6.delete(profile)
        except Exception:
            pass
