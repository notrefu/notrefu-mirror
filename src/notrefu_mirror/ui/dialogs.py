"""Interface Qt de notrefu-mirror : dialogs."""

from __future__ import annotations

import sys


from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QTextDocument, QGuiApplication, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QPlainTextDocumentLayout,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, adb, i18n
from ..hotkeys import ACTIONS, default_bindings, find_conflicts, validate_combo

from ..scrcpy_cmd import (
    SHORTCUTS,
)


class AppPickerDialog(QDialog):
    """Applications Dofus Touch (clones compris) trouvées sur le téléphone, avec leur nom et leur icône."""

    def __init__(self, runner, serial: str, apps: list[tuple[str, str]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Applications trouvées")
        self.resize(520, 440)
        self.runner, self.serial, self._all = runner, serial, apps
        self._icons: dict[str, bytes] = {}
        self._queue: list = []
        self._alive = True
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Quelle application lancer dans cette session ?"))
        self.list = QListWidget()
        self.list.setIconSize(QSize(48, 48))
        self.list.setSpacing(2)
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        v.addWidget(self.list, 1)
        self.show_all = QCheckBox("Afficher toutes les applications (clone dont le nom ne contient pas « Dofus »)")
        self.show_all.toggled.connect(self._fill)
        v.addWidget(self.show_all)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.finished.connect(lambda _r: setattr(self, "_alive", False))
        self._fill()

    def _fill(self) -> None:
        self.list.clear()
        every = self.show_all.isChecked()
        rows = [(n, p) for n, p in self._all if every or "dofus" in n.lower() or "dofus" in p.lower()]
        placeholder = self.style().standardIcon(self.style().StandardPixmap.SP_FileIcon)
        self._queue = []
        for name, pkg in rows:
            item = QListWidgetItem(placeholder, f"{name}\n{pkg}")
            item.setData(Qt.ItemDataRole.UserRole, pkg)
            self.list.addItem(item)
            self._queue.append((item, pkg))
        if self.list.count():
            self.list.setCurrentRow(0)
        # Icônes chargées 2 par 2, dans l'ordre d'affichage (la liste complète peut compter des centaines d'applications)
        self._gen = getattr(self, "_gen", 0) + 1
        for _ in range(2):
            self._next_icon(self._gen)

    def _next_icon(self, gen: int) -> None:
        if not self._alive or gen != self._gen or not self._queue:
            return
        item, pkg = self._queue.pop(0)
        cached = self._icons.get(pkg)
        if cached is not None:
            self._set_icon(item, cached)
            self._next_icon(gen)
            return

        def done(data, err, it=item, pkg=pkg) -> None:
            if data:
                self._icons[pkg] = data
            self._set_icon(it, data, err)
            self._next_icon(gen)

        self.runner.run(lambda pkg=pkg: adb.app_icon(self.serial, pkg), done)

    def _set_icon(self, item: QListWidgetItem, data, err=None) -> None:
        if not self._alive:
            return
        if not data:
            try:
                item.setToolTip(f"Icône indisponible : {err}" if err else "Icône indisponible (aucune image d'icône trouvée dans l'application)")
            except RuntimeError:
                pass
            return
        pm = QPixmap()
        if pm.loadFromData(data):
            try:
                item.setIcon(QIcon(pm))
            except RuntimeError:  # élément supprimé (liste rechargée)
                pass

    def package(self) -> str:
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else ""


# --------------------------------------------------------------------------
class ShortcutsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Raccourcis de la fenêtre de mirroring")
        self.resize(520, 420)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("MOD = la touche choisie dans « Touche des raccourcis » (par défaut Alt gauche ou Super gauche)."))
        t = QTableWidget(len(SHORTCUTS), 2)
        t.setHorizontalHeaderLabels([i18n.tr("Raccourci"), i18n.tr("Action")])
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for i, (k, a) in enumerate(SHORTCUTS):
            t.setItem(i, 0, QTableWidgetItem(i18n.tr(k)))
            t.setItem(i, 1, QTableWidgetItem(i18n.tr(a)))
        v.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)


class HotkeysDialog(QDialog):
    def __init__(self, bindings: dict[str, str], enabled: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Raccourcis")
        self.resize(480, 520)
        v = QVBoxLayout(self)
        text = (
            "Naviguez entre les sessions depuis le clavier.<br>"
            "Format : <b>Ctrl+Tab</b>, <b>Alt+1</b>, <b>F11</b>, <b>Ctrl+Shift+Tab</b>… "
            "Laissez vide pour désactiver. Ces touches ne sont actives que lorsque notrefu-mirror est la fenêtre active (elles ne sont pas envoyées au jeu)."
        )
        info = QLabel(text)
        info.setWordWrap(True)
        v.addWidget(info)
        form = QFormLayout()
        self.edits: dict[str, KeyCaptureEdit] = {}
        for name, (label, _default) in ACTIONS.items():
            e = KeyCaptureEdit(bindings.get(name, ""))
            e.setEnabled(enabled)
            e.changed.connect(self._check_conflicts)
            self.edits[name] = e
            form.addRow(i18n.tr(label), e)
        host = QWidget()
        host.setLayout(form)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setWidget(host)
        v.addWidget(area, 1)
        self.conflict_label = QLabel("")
        self.conflict_label.setWordWrap(True)
        self.conflict_label.setStyleSheet("color: #ef4444;")
        v.addWidget(self.conflict_label)
        row = QHBoxLayout()
        reset = QPushButton("Valeurs par défaut")
        reset.clicked.connect(self._reset)
        scrcpy = QPushButton("Raccourcis de scrcpy…")
        scrcpy.clicked.connect(lambda: ShortcutsDialog(self).exec())
        row.addWidget(reset)
        row.addWidget(scrcpy)
        row.addStretch(1)
        v.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _reset(self) -> None:
        for name, combo in default_bindings().items():
            self.edits[name].setText(combo)

    def _check_conflicts(self) -> None:
        conflicts = find_conflicts({n: e.text() for n, e in self.edits.items()})
        bad = {n for names in conflicts.values() for n in names}
        for n, e in self.edits.items():
            e.setStyleSheet("border: 1px solid #ef4444;" if n in bad else "")
        self.conflict_label.setText("".join(
            f"« {k} » est déjà utilisé par : " + ", ".join(i18n.tr(ACTIONS[n][0]) for n in names) + "\n"
            for k, names in conflicts.items()).strip())

    def accept(self) -> None:
        conflicts = find_conflicts({n: e.text() for n, e in self.edits.items()})
        if conflicts:
            self._check_conflicts()
            QMessageBox.warning(self, APP_NAME, "Un même raccourci est donné à plusieurs actions : corrige-le avant de valider.")
            return
        for name, e in self.edits.items():
            err = validate_combo(e.text())
            if err:
                QMessageBox.warning(self, APP_NAME, f"{ACTIONS[name][0]} : {err}")
                return
        super().accept()

    def values(self) -> dict[str, str]:
        return {name: e.text().strip() for name, e in self.edits.items()}


class KeyCaptureEdit(QLineEdit):
    """Champ de raccourci : on clique dedans puis on appuie sur la combinaison voulue (Retour arrière = vider)."""

    changed = Signal()

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setReadOnly(True)
        self.setPlaceholderText("(aucun)")
        self.setToolTip("Clique ici puis appuie sur la combinaison de touches voulue. Retour arrière ou Suppr : aucun raccourci.")

    def focusInEvent(self, ev) -> None:  # noqa: N802
        super().focusInEvent(ev)
        if not self.text():
            self.setPlaceholderText("Appuyez sur la nouvelle combinaison…")

    def focusOutEvent(self, ev) -> None:  # noqa: N802
        super().focusOutEvent(ev)
        self.setPlaceholderText("(aucun)")

    def event(self, ev) -> bool:
        if ev.type() == QEvent.Type.KeyPress and ev.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.keyPressEvent(ev)  # Tab / Ctrl+Tab sont des raccourcis possibles : ne pas les laisser changer le focus
            return True
        return super().event(ev)

    def keyPressEvent(self, ev) -> None:  # noqa: N802
        key = ev.key()
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta, Qt.Key.Key_AltGr, Qt.Key.Key_unknown):
            return  # un modificateur seul n'est pas un raccourci : on attend la touche
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete) and not ev.modifiers():
            self.setText("")
        else:
            self.setText(QKeySequence(ev.keyCombination()).toString(QKeySequence.SequenceFormat.PortableText))
        self.changed.emit()
        ev.accept()


class DevicesDialog(QDialog):
    def __init__(self, devices: list[adb.Device], on_udev, on_refresh, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Appareils")
        self.resize(460, 320)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Téléphones vus par adb :"))
        table = QTableWidget(len(devices), 3)
        table.setHorizontalHeaderLabels(["Appareil", "Connexion", "État"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for i, d in enumerate(devices):
            table.setItem(i, 0, QTableWidgetItem(d.model.replace("_", " ") or d.serial))
            table.setItem(i, 1, QTableWidgetItem("Wi-Fi" if d.wireless else "USB"))
            table.setItem(i, 2, QTableWidgetItem(d.state))
        v.addWidget(table, 1)
        if not devices:
            v.addWidget(QLabel("Aucun téléphone : activez le débogage USB et branchez le câble (voir Aide)."))
        row = QHBoxLayout()
        b1 = QPushButton("Actualiser")
        b1.clicked.connect(on_refresh)
        b2 = QPushButton("Installer les règles USB…")
        b2.clicked.connect(on_udev)
        row.addWidget(b1)
        if sys.platform.startswith("linux"):  # les règles udev n'existent que sous Linux
            row.addWidget(b2)
        else:
            b2.deleteLater()
        row.addStretch(1)
        v.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)


class JournalDialog(QDialog):
    """Journal technique d'une session, mis à jour en direct (partage le document du journal de la session)."""

    def __init__(self, title: str, source: QPlainTextEdit, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Journal technique — {title}")
        self.resize(820, 440)
        v = QVBoxLayout(self)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setDocument(source.document())
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())
        v.addWidget(self.view, 1)
        row = QHBoxLayout()
        copy = QPushButton("Copier tout")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(source.toPlainText()))
        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        row.addWidget(QLabel("Les lignes « [app] » disent si l'application a pu être lancée."))
        row.addStretch(1)
        row.addWidget(copy)
        row.addWidget(close)
        v.addLayout(row)

    def done(self, r: int) -> None:
        try:
            self._own = QTextDocument(self)  # détache le document partagé avant fermeture (il appartient à la session)
            self._own.setDocumentLayout(QPlainTextDocumentLayout(self._own))
            self.view.setDocument(self._own)
        except RuntimeError:
            pass
        super().done(r)
