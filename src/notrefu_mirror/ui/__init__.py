"""Interface Qt de notrefu-mirror, découpée en modules.

common        : constantes, exécuteur asynchrone, signaux, étiquette tronquée
dialogs       : fenêtres de dialogue (apps, raccourcis, appareils, journal)
phone_panel   : réglages et pilotage d'une session (un téléphone)
session_page  : page d'une session (barre, jeu, réglages)
titlebar      : barre de titre personnalisée
main_window   : fenêtre principale, fenêtres détachées, point d'entrée `run`
"""

from .common import CLASS_EMBLEMS, CLASS_NAMES, RESOURCES, SESSION_COLORS  # noqa: F401  (installe aussi la traduction)
from .dialogs import AppPickerDialog, DevicesDialog, HotkeysDialog, JournalDialog, KeyCaptureEdit, ShortcutsDialog  # noqa: F401
from .main_window import MainWindow, run  # noqa: F401
from .phone_panel import PhonePanel  # noqa: F401
from .session_page import SessionPage  # noqa: F401
from .titlebar import TitleBar  # noqa: F401
