"""Interface française / anglaise, changeable à chaud (Aide → Langue).

Le texte français reste la langue d'origine du code. En mode anglais, chaque texte affiché (étiquettes, boutons, infobulles,
menus, barre d'état, boîtes de dialogue) est traduit au moment où il est posé, par remplacement de fragments : cela
marche aussi pour les messages construits avec des valeurs (« Connexion à 192.168.1.5:5555… »).
Le français d'origine est gardé dans une propriété du widget pour pouvoir rebasculer sans redémarrer.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QComboBox, QDialog, QGroupBox, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox,
    QPlainTextEdit, QStatusBar, QWidget,
)

EN = {
    "RAM : en attente du premier relevé…": "RAM: waiting for the first reading…",
    "RAM de l'appareil : ": "Device RAM: ",
    " utilisés (": " used (",
    "RAM de l'appareil : indisponible (relevé en attente ou /proc/meminfo illisible)": "Device RAM: unavailable (reading pending or /proc/meminfo unreadable)",
    "Jeu : non disponible (en attente ou dumpsys meminfo indisponible)": "Game: not available (pending or dumpsys meminfo unavailable)",
    "Jeu : ~": "Game: ~",
    "Mémoire globale de l'appareil Android (système, services, cache et jeu), pas uniquement celle du jeu. Utilisée = mémoire totale − mémoire disponible.":
        "Global memory of the Android device (system, services, cache and game), not the game alone. Used = total memory − available memory.",
    "CPU et RAM : valeurs globales de l'appareil Android (tous les processus), pas celles du jeu seul. RAM = mémoire totale − mémoire disponible ; « jeu » = mémoire de l'application seule.":
        "CPU and RAM: global values for the whole Android device (all processes), not the game alone. RAM = total memory − available memory; “jeu” (game) = the app alone.",
    "Touches personnalisées : une touche du clavier = un appui à un endroit précis de l'écran":
        "Custom keys: one keyboard key = one tap at a precise spot on the screen",
    "Modifier les touches": "Edit keys",
    "Touches actives (désactive-les pour écrire dans le chat)": "Keys active (turn off to type in the chat)",
    "Afficher les repères sur le jeu": "Show markers on the game",
    "Fermer le jeu sur le téléphone quand j'arrête ou supprime la session": "Close the game on the phone when I stop or delete the session",
    "Sinon le jeu reste ouvert en arrière-plan sur le téléphone (batterie, réseau, compte connecté).": "Otherwise the game stays open in the background on the phone (battery, network, logged-in account).",
    "Ne s'applique qu'au jeu lancé par notrefu-mirror (case « Lancer le jeu automatiquement »), jamais lors d'une reconnexion ou d'un redémarrage de la session.": "Only applies to the game launched by notrefu-mirror (\"Launch the game automatically\" box), never on a reconnection or session restart.",
    "Téléphone : chauffe et réveil": "Phone: heat and wake-up",
    "Limiter les ips de tout le téléphone s'il chauffe ou si le Wi-Fi sature (retard possible)": "Limit fps of the whole phone if it gets hot or Wi-Fi is saturated (may add delay)",
    "Réveiller le téléphone quand je clique sur une session": "Wake the phone when I click a session",
    "Copier le rapport": "Copy report",
    "⚠ Wi-Fi saturé : ips limités à ": "⚠ Wi-Fi saturated: fps limited to ",
    " pour fluidifier le flux.": " to smooth the stream.",
    "Wi-Fi redevenu stable : ips rétablis.": "Wi-Fi stable again: fps restored.",
    "Wi-Fi plus stable : limitation allégée.": "Wi-Fi more stable: limit eased.",
    "⚠ Téléphone chaud : ips limités à ": "⚠ Phone hot: fps limited to ",
    " (retour à la normale quand il refroidit).": " (back to normal when it cools down).",
    "Téléphone refroidi : limitation des ips allégée.": "Phone cooled down: fps limit eased.",
    "Téléphone refroidi : ips rétablis.": "Phone cooled down: fps restored.",
    "ips limités à ": "fps limited to ",
    " (chauffe)": " (heat)",
    "Tout effacer…": "Clear all…", "Copier ces touches vers…": "Copy these keys to…", "Toutes les autres sessions": "All other sessions",
    "Remplacer les touches de ": "Replace the keys of ", " touches copiées de ": " keys copied from ",
    "Touches personnalisées : activer / désactiver": "Custom keys: turn on / off",
    "Touches personnalisées : mode édition": "Custom keys: edit mode",
    "Démarre la session avant de placer des touches.": "Start the session before placing keys.",
    "Démarre la session pour placer des touches.": "Start the session to place keys.",
    "Mode édition : clique sur le jeu pour ajouter une touche — Échap pour terminer.":
        "Edit mode: click the game to add a key — Esc to finish.",
    "Appuie maintenant sur la touche à assigner (Échap pour annuler).": "Now press the key to assign (Esc to cancel).",
    "Annulé.": "Cancelled.",
    "Une seule touche, sans Ctrl / Alt.": "A single key, without Ctrl / Alt.",
    "Mode édition — clic : ajouter · glisser : déplacer · double-clic : changer la touche · clic droit : supprimer · Échap : terminer":
        "Edit mode — click: add · drag: move · double-click: change key · right-click: delete · Esc: finish",
    "touche invalide": "invalid key",
    "Touche {} supprimée.": "Key {} removed.",
    "Appuie sur la nouvelle touche pour ce repère (actuellement {}).": "Press the new key for this marker (currently {}).",
    "Impossible : {}.": "Not possible: {}.",
    "Touche {} assignée. Une pression = un seul appui sur l'écran.": "Key {} assigned. One press = a single tap on the screen.",
    "les combinaisons (Ctrl, Alt, Maj…) ne sont pas permises : une seule touche": "combinations (Ctrl, Alt, Shift…) are not allowed: a single key",
    "maximum 40 touches": "maximum 40 keys",
    "touches personnalisées activées.": "custom keys turned on.",
    "touches personnalisées désactivées.": "custom keys turned off.",
    "Effacer les ": "Clear the ",
    " touches de « ": " keys of « ",
    "position hors de l'écran": "position outside the screen",
    # --- barre de titre, menus -------------------------------------------------
    "Appareils": "Devices", "Raccourcis": "Shortcuts", "Espaces": "Spaces", "Thème": "Theme", "Aide": "Help",
    "Téléphones détectés, règles USB": "Detected phones, USB rules",
    "Raccourcis clavier de navigation": "Keyboard shortcuts for navigation",
    "Groupes de comptes enregistrés, style TabDesk": "Saved account groups, TabDesk style",
    "Changer l'apparence de notrefu-mirror": "Change notrefu-mirror's appearance",
    "Aide et à propos": "Help and about", "Réduire": "Minimise",
    "Guide de démarrage": "Getting started", "Diagnostic…": "Diagnostics…",
    "Installer les règles USB (Linux)…": "Install USB rules (Linux)…", "Installer les règles USB…": "Install USB rules…",
    "Langue : Français": "Language: French", "Langue : English": "Language: English",
    "À propos de ": "About ", "À propos": "About", " — clic : à propos": " — click: about",
    "Nouvelle session": "New session", "Renommer la session": "Rename session", "Renommer": "Rename",
    "Fermer cette session": "Close this session", "Fermer": "Close", "Détacher dans une fenêtre": "Detach into a window",
    "Rattacher aux onglets": "Reattach to tabs",
    "Sort une session de la barre d'onglets pour la mettre dans sa propre fenêtre (deuxième écran, par exemple).":
        "Moves a session out of the tab bar into its own window (a second screen, for example).",
    "Fenêtre indépendante qui contient une session sortie des onglets ; la fermer la remet dans les onglets.":
        "Independent window holding a session taken out of the tabs; closing it puts the session back.",
    "Aucune session ouverte.\nClique sur « Nouvelle session » pour en créer une.":
        "No session open.\nClick “New session” to create one.",
    "Prêt. Ctrl+Tab : session suivante · Alt+1…9 : aller à une session · F11 : plein écran.":
        "Ready. Ctrl+Tab: next session · Alt+1…9: go to a session · F11: full screen.",
    "Page affichée quand toutes les sessions sont fermées.": "Page shown when all sessions are closed.",
    "Barre de titre personnalisée : déplacement à la souris, double-clic = agrandir, boutons de fenêtre.":
        "Custom title bar: drag to move, double-click to maximise, window buttons.",
    # --- espaces / style / thèmes ---------------------------------------------
    "Enregistrer les sessions actuelles comme espace…": "Save current sessions as a space…",
    "Supprimer un espace": "Delete a space", "Appliquer le style TabDesk (16:9, barres réduites)": "Apply TabDesk style (16:9, slim bars)",
    "Nom de l'espace (ex. Mes 4 persos) :": "Space name (e.g. My 4 characters):",
    "Ouvrir « ": "Open “", "Supprimer l'espace « ": "Delete space “", "Espace « ": "Space “",
    " » enregistré (": "” saved (", " » ouvert : ": "” opened: ", " lancée(s).": " started.",
    " » : remplacer les sessions actuelles ou les ajouter aux onglets ?": "”: replace the current sessions or add them to the tabs?",
    "Thème : ": "Theme: ",
    "Rendu proche de TabDesk : écran 16:9, interface à 100 %, barre d'outils masquée (F10).":
        "TabDesk-like look: 16:9 screen, interface at 100 %, toolbar hidden (F10).",
    "Style TabDesk appliqué. « Appliquer et relancer » dans Réglages pour les sessions en cours (F10 : barres).":
        "TabDesk style applied. Use “Apply and restart” in Settings for running sessions (F10: bars).",
    "Zinc violet (défaut)": "Zinc violet (default)", "Bleu électrique": "Electric blue", "Clair": "Light",
    # --- réglages de la session ---------------------------------------------------
    "Réglages": "Settings", "Journal": "Log", "Adapter": "Fit", "Téléphone :": "Phone:", "Actualiser": "Refresh",
    "Audio désactivé automatiquement : Android 11+ requis": "Audio turned off automatically: Android 11+ required",
    "Vidéo : profil compatible (H.264 Baseline, débit réduit) utilisé automatiquement": "Video: compatible profile (H.264 Baseline, lower bit rate) used automatically",
    "Non autorisé — accepte la pop-up sur l'écran": "Not authorised — accept the pop-up on the screen",
    "Hors ligne — rebranche le câble": "Offline — replug the cable",
    "Permissions USB manquantes — installe les règles USB": "USB permissions missing — install the USB rules",
    "Autorisation en cours — accepte la pop-up sur l'écran": "Authorising — accept the pop-up on the screen",
    "Connexion en cours…": "Connecting…",
    "Le téléphone refuse les clics. ": "The phone refuses clicks. ",
    "Xiaomi / POCO / Redmi : active « Débogage USB (Paramètres de sécurité) » dans les Options pour les développeurs (il faut une carte SIM et un compte Mi) pour autoriser les clics et les touches.":
        "Xiaomi / POCO / Redmi: turn on “USB debugging (Security settings)” in Developer options (a SIM card and a Mi account are required) to allow clicks and keys.",
    "Oppo / Realme / OnePlus : dans les Options pour les développeurs, active « Désactiver la surveillance des autorisations » pour autoriser les clics et les touches.":
        "Oppo / Realme / OnePlus: in Developer options, turn on “Disable permission monitoring” to allow clicks and keys.",
    "Samsung : désactive le « Bloqueur automatique » (Paramètres → Sécurité et confidentialité).":
        "Samsung: turn off “Auto Blocker” (Settings → Security and privacy).",
    " Sous Windows, installe aussi le pilote officiel « Samsung Android USB Driver ».": " On Windows, also install the official “Samsung Android USB Driver”.",
    "Conseil pour ta marque": "Tip for your brand",
    "Ouvrir le diagnostic": "Open diagnostics",
    "Appareil détecté mais non autorisé — accepte la pop-up « Autoriser le débogage USB » sur l'écran du téléphone (coche « Toujours autoriser »). Elle n'apparaît pas ? Débranche/rebranche le câble, écran déverrouillé.":
        "Device detected but not authorised — accept the “Allow USB debugging” pop-up on the phone screen (tick “Always allow”). Not showing? Unplug and replug the cable with the screen unlocked.",
    "Appareil détecté mais sans permissions USB : menu Aide → « Installer les règles USB », puis rebranchez le câble.":
        "Device detected but without USB permissions: Help → “Install USB rules”, then replug the cable.",
    "Appareil détecté mais hors ligne : débranchez/rebranchez le câble ou désactivez puis réactivez le débogage USB.":
        "Device detected but offline: unplug and replug the cable, or turn USB debugging off and on.",
    "Appareil en cours d'autorisation : accepte la pop-up « Autoriser le débogage USB » sur le téléphone.":
        "Device is being authorised: accept the “Allow USB debugging” pop-up on the phone.",
    "Appareil Samsung (ex. Galaxy Tab) : désactive le « Bloqueur automatique » (Paramètres → Sécurité et confidentialité → Bloqueur automatique) et installe le pilote officiel « Samsung Android USB Driver ». Clique sur « Ouvrir le diagnostic ».":
        "Samsung device (e.g. Galaxy Tab): turn off “Auto Blocker” (Settings → Security and privacy → Auto Blocker) and install the official “Samsung Android USB Driver”. Click “Open diagnostics”.",
    "Tablette ou téléphone USB non vu ? Menu Aide → « Installer les règles USB » (Samsung et autres constructeurs inclus).":
        "Tablet or phone not seen over USB? Help → “Install USB rules” (Samsung and other makers included).",
    "Aucun téléphone détecté": "No phone detected", "Aucun téléphone sélectionné.": "No phone selected.",
    "Connecter le téléphone": "Connect the phone", "USB (câble)": "USB (cable)", "Sans fil (Wi-Fi)": "Wireless (Wi-Fi)",
    "Activez le <b>débogage USB</b> sur le téléphone, branchez-le, puis acceptez la fenêtre d'autorisation. Il apparaît alors dans la liste ci-dessus.":
        "Turn on <b>USB debugging</b> on the phone, plug it in, then accept the authorisation prompt. It then shows up in the list above.",
    "1. Première fois (et après chaque redémarrage du téléphone) : branchez-le en USB et cliquez sur <b>Activer le sans-fil</b>. L'adresse se remplit toute seule.<br>2. Débranchez le câble (même Wi-Fi sur le PC et le téléphone).<br>3. Cliquez sur <b>Connecter sans fil</b>.":
        "1. First time (and after each phone reboot): plug it in over USB and click <b>Enable wireless</b>. The address fills itself in.<br>2. Unplug the cable (same Wi-Fi on the PC and the phone).<br>3. Click <b>Connect wirelessly</b>.",
    "Adresse IP du téléphone": "Phone IP address", "Port": "Port", "Activer le sans-fil": "Enable wireless",
    "Connecter sans fil": "Connect wirelessly", "Appairer (Android 11+)…": "Pair (Android 11+)…",
    "Débogage sans fil d'Android 11+ : appairage avec un code, sans câble.": "Android 11+ wireless debugging: pair with a code, no cable.",
    "Affichage": "Display", "Nom de la fenêtre": "Window name",
    "Nom de l'onglet et de la fenêtre. Astuce : préfixez-le d'un numéro (« 1 Eniripsa », « 2 Roublard ») pour changer de fenêtre avec --focus 1, --focus 2 (voir le README).":
        "Name of the tab and the window. Tip: prefix it with a number (“1 Eniripsa”, “2 Roublard”) to switch windows with --focus 1, --focus 2 (see the README).",
    "Emblème de l'onglet": "Tab emblem", "Emblèmes": "Emblems", "Image…": "Image…", "Retirer": "Remove",
    "Choisir un emblème de classe pour l'onglet": "Pick a class emblem for the tab",
    "Utiliser une image de ton ordinateur comme icône de l'onglet (par exemple l'emblème de ta classe)":
        "Use an image from your computer as the tab icon (for example your class emblem)",
    "Choisir une image": "Pick an image", "Mode": "Mode", "Application": "Application", "Détecter…": "Detect…",
    "Nom de paquet Android de l'application à lancer (ex. com.ankama.dofustouch).":
        "Android package name of the app to launch (e.g. com.ankama.dofustouch).",
    "Cherche Dofus Touch et ses clones installés sur le téléphone.": "Looks for Dofus Touch and its clones installed on the phone.",
    "Horizontal (écran virtuel paysage)": "Horizontal (landscape virtual screen)", "Standard (sdk)": "Standard (sdk)",
    "Standard (écran du téléphone)": "Standard (phone screen)",
    "Clavier physique simulé (uhid)": "Simulated physical keyboard (uhid)",
    "Un écran virtuel horizontal est créé : le jeu s'y ouvre sans toucher à l'écran du téléphone (Android 10+, idéal Android 11+).":
        "A horizontal virtual screen is created: the game opens on it without touching the phone's screen (Android 10+, ideal Android 11+).",
    "L'écran du téléphone, tel quel.": "The phone's screen, as is.",
    "Ce téléphone est sous Android 9 ou moins : l'écran virtuel n'est pas disponible, utilisez le mode Standard.":
        "This phone runs Android 9 or older: the virtual screen is unavailable, use Standard mode.",
    "En sans fil, l'USB est conseillé à partir de la qualité « Haut » : si ça saccade, baissez le débit.":
        "Over Wi-Fi, USB is recommended from “High” quality up: if it stutters, lower the bitrate.",
    "Forme de l'écran": "Screen shape", "Suivre la fenêtre (sans bandes noires)": "Follow the window (no black bars)",
    "16:9 (téléphone classique)": "16:9 (regular phone)", "2:1 (large)": "2:1 (wide)", "21:9 (très large)": "21:9 (ultra wide)",
    "Largeur × hauteur de « Perso »": "Width × height of “Custom”",
    "Forme de l'écran virtuel du jeu. « Suivre la fenêtre » prend la forme actuelle de la fenêtre au lancement ; les autres formes sont fixes (des bandes noires peuvent apparaître si la fenêtre n'a pas la même forme).":
        "Shape of the game's virtual screen. “Follow the window” takes the window's current shape at launch; the other shapes are fixed (black bars may appear if the window has a different shape).",
    "Taille de l'interface": "Interface size",
    "Plus grand = interface du jeu plus grosse (le nombre de pixels reste celui de la qualité choisie).":
        "Larger = bigger game interface (the pixel count stays that of the chosen quality).",
    "Ouvrir l'application à la connexion": "Open the app on connect",
    "Qualité": "Quality", "Faible": "Low", "Moyen": "Medium", "Haut": "High", "Multi-compte": "Multi-account", "Perso": "Custom",
    "Réglages personnalisés.": "Custom settings.", "Débit vidéo": "Video bitrate", "Images par seconde": "Frames per second",
    "Largeur": "Width", "Hauteur": "Height", "DPI (écran virtuel)": "DPI (virtual screen)", " ips, écran ": " fps, screen ",
    "Options": "Options",
    "Éteindre l'écran du téléphone": "Turn the phone screen off",
    "Le contrôle continue, l'écran du téléphone reste noir.": "Control keeps working, the phone screen stays black.",
    "Afficher les images/s": "Show frames/s", "Afficher les touches (téléphone)": "Show touches (phone)",
    "Contrôle souris et clavier": "Mouse and keyboard control",
    "Transférer le son (Android 11+)": "Forward sound (Android 11+)",
    "Seule la session affichée joue du son.": "Only the displayed session plays sound.",
    "Son du jeu seulement": "Game sound only",
    "Ne transfère que le son des applications (jeu, musique) : pas les notifications ni les sons système. Demande Android 13+ ; sinon tout le son est transféré. S'applique après « Appliquer et relancer ».":
        "Only forwards app sound (game, music): no notifications or system sounds. Needs Android 13+; otherwise all sound is forwarded. Applies after “Apply and restart”.",
    "Synchroniser le presse-papiers": "Sync clipboard", "Copier/coller entre le PC et le téléphone.": "Copy/paste between the PC and the phone.",
    "Empêcher la mise en veille (USB)": "Keep awake (USB)", "Éteindre le téléphone en quittant": "Turn the phone off on exit",
    "Afficher le journal technique": "Show technical log", "Reconnexion automatique": "Automatic reconnection",
    "Rétablit la session si le câble ou le Wi-Fi coupe.": "Restores the session if the cable or Wi-Fi drops.",
    "Pixels 1:1 (image plus nette)": "1:1 pixels (sharper image)",
    "L'écran virtuel prend exactement la taille de la zone de jeu : aucun redimensionnement de l'image, donc un texte plus net et moins de travail pour le téléphone. Le préréglage de qualité reste le maximum.":
        "The virtual screen takes exactly the size of the game area: no image resizing, so sharper text and less work for the phone. The quality preset remains the maximum.",
    "Re-adapter en redimensionnant": "Re-fit when resizing",
    "Quand tu changes la taille de la fenêtre, la session est relancée pour que l'écran du jeu reprenne la nouvelle forme (le téléphone ne sait pas redimensionner l'écran virtuel en direct).":
        "When you resize the window, the session is restarted so the game screen takes the new shape (the phone cannot resize the virtual screen live).",
    "Lancer au démarrage de notrefu-mirror": "Start on notrefu-mirror launch",
    "Cette session démarre toute seule à l'ouverture de notrefu-mirror.": "This session starts by itself when notrefu-mirror opens.",
    "Latence du son": "Sound latency",
    "Son qui grésille ou saccade : augmente. Son en retard sur l'image : diminue.":
        "Crackling or stuttering sound: increase. Sound late compared to the picture: decrease.",
    "Liste des raccourcis": "Shortcut list", "Lancer le mirroring": "Start mirroring", "Arrêter": "Stop",
    "Appliquer et relancer": "Apply and restart",
    "Reprend les réglages d'une autre session (qualité, options…), en gardant son propre nom.":
        "Copies the settings of another session (quality, options…), keeping its own name.",
    # --- session en cours / états ------------------------------------------------------
    "Session en cours avec : ": "Session running with: ", "écran du téléphone": "phone screen", " Mbit/s": " Mbit/s",
    " ips": " fps", " · plafond ": " · cap ",
    ". Les changements de réglages s'appliquent après « Appliquer et relancer ».":
        ". Setting changes apply after “Apply and restart”.",
    "Connexion au téléphone…": "Connecting to the phone…", " : mirroring en cours…": ": mirroring…",
    "Réception de l'image…": "Receiving the picture…", " : connecté (": ": connected (", " : arrêté.": ": stopped.",
    " : résolution du téléphone restaurée.": ": phone resolution restored.",
    "[session terminée]": "[session ended]", "[erreur] ": "[error] ",
    "[résolution/densité du téléphone restaurées à leur état d'avant la session]": "[phone resolution/density restored to their pre-session state]",
    "[reconnexion abandonnée après 60 essais]": "[reconnection given up after 60 attempts]",
    "Connexion perdue (": "Connection lost (", "Nouvelle tentative ": "Attempt ", " dans ": " in ",
    " : connexion perdue, reconnexion…": ": connection lost, reconnecting…",
    " : fenêtre redimensionnée, adaptation de l'écran du jeu…": ": window resized, fitting the game screen…",
    " reçus · décodage ": " received · decoding ", "reçus": "received", "décodage": "decoding", "son : ": "sound: ",
    "Arrêté": "Stopped", "Connecté": "Connected", "Session ": "Session ",
    "Arrête la session puis la relance avec les réglages actuels.": "Stops the session and relaunches it with the current settings.",
    "Adapte l'écran du jeu à la taille actuelle de la fenêtre (relance la session, le jeu reste lancé sur le téléphone).":
        "Fits the game screen to the window's current size (restarts the session, the game stays open on the phone).",
    "Volume du son de cette session (0–100 %)": "Volume of this session's sound (0–100 %)",
    "Journal technique de la session (utile pour comprendre un problème).": "The session's technical log (useful to understand a problem).",
    "Applications récentes": "Recent apps", "Panneau de notifications": "Notification panel", "Accueil": "Home", "Retour": "Back",
    "Capture d'écran (dossier Images)": "Screenshot (Pictures folder)", "Éteindre / allumer l'écran du téléphone": "Phone screen on / off",
    "Enregistrer la session en vidéo avec le son du jeu (.mkv) — clic droit : choisir le dossier": "Record the session to video with game sound (.mkv) — right-click: choose the folder",
    "Écran du téléphone allumé.": "Phone screen on.", "Écran du téléphone éteint.": "Phone screen off.",
    "Aucune image à enregistrer.": "No picture to save.", "Capture enregistrée : ": "Screenshot saved: ",
    "Enregistrement terminé (conversion en cours) : ": "Recording finished (converting): ",
    "Enregistrement en cours (vidéo et son du jeu) : ": "Recording (video and game sound): ",
    "Enregistrement en cours (vidéo seule, sans le son) : ": "Recording (video only, no sound): ",
    "Dossier des enregistrements…": "Recordings folder…", "Choisir le dossier des enregistrements": "Choose the recordings folder",
    "Dossier des enregistrements : ": "Recordings folder: ", "Dossier par défaut (Vidéos)": "Default folder (Videos)",
    "Ouvrir le dossier des enregistrements": "Open the recordings folder",
    "Choisir le dossier d'enregistrement": "Choose the recording folder",
    "Garde barre de titre et onglets mais libère la barre d'outils et la barre d'état pour le jeu.":
        "Keeps the title bar and tabs but frees the toolbar and status bar for the game.",
    "Taille de la zone de jeu. Les onglets masqués n'ont pas la bonne taille : on mesure l'onglet visible.":
        "Size of the game area. Hidden tabs don't have the right size: the visible tab is measured.",
    # --- appareils / sans fil ----------------------------------------------------------------
    "Téléphones vus par adb :": "Phones seen by adb:", "État": "State",
    "Aucun téléphone : activez le débogage USB et branchez le câble (voir Aide).":
        "No phone: turn on USB debugging and plug in the cable (see Help).",
    "Téléphone non autorisé : acceptez la fenêtre « Autoriser le débogage USB » sur le téléphone.":
        "Phone not authorised: accept the “Allow USB debugging” prompt on the phone.",
    "Permissions USB manquantes : menu Aide → « Installer les règles USB », puis rebranchez le câble.":
        "Missing USB permissions: Help menu → “Install USB rules”, then replug the cable.",
    "Téléphone hors ligne : débranchez/rebranchez le câble ou redémarrez le débogage USB.":
        "Phone offline: unplug/replug the cable or restart USB debugging.",
    "Sélectionnez un téléphone USB et un port valide.": "Select a USB phone and a valid port.",
    "Activation du sans-fil…": "Enabling wireless…", "Échec : ": "Failed: ",
    "Impossible d'activer le sans-fil :\n": "Could not enable wireless:\n", "Sans-fil activé sur ": "Wireless enabled on ",
    ". Vous pouvez débrancher le câble puis cliquer « Connecter sans fil ».": ". You can unplug the cable, then click “Connect wirelessly”.",
    "Sans-fil activé, mais l'adresse IP n'a pas été trouvée : saisissez-la à la main.":
        "Wireless enabled, but the IP address was not found: type it in by hand.",
    "Connexion à ": "Connecting to ", "Échec de la connexion sans fil.": "Wireless connection failed.",
    "Connexion impossible :\n": "Connection failed:\n",
    "\n\nVérifiez que le PC et le téléphone sont sur le même Wi-Fi et que « Activer le sans-fil » a été fait en USB depuis le dernier redémarrage du téléphone.":
        "\n\nCheck that the PC and the phone are on the same Wi-Fi and that “Enable wireless” was done over USB since the phone last rebooted.",
    "Sur le téléphone : Options pour les développeurs → Débogage sans fil → « Associer avec un code ».\nSaisissez l'adresse IP:port affichée :":
        "On the phone: Developer options → Wireless debugging → “Pair with code”.\nEnter the IP:port shown:",
    "Code d'association à 6 chiffres :": "6-digit pairing code:", "Appairage échoué :\n": "Pairing failed:\n",
    "Appairage réussi. Saisissez maintenant le port affiché sur l'écran principal « Débogage sans fil » (différent de celui de l'appairage), puis « Connecter sans fil ».":
        "Pairing succeeded. Now enter the port shown on the main “Wireless debugging” screen (different from the pairing one), then “Connect wirelessly”.",
    "Recherche des applications Dofus Touch…": "Looking for Dofus Touch apps…", "Applications trouvées": "Apps found",
    "Lecture des applications impossible :\n": "Could not read the apps:\n",
    "Aucune application trouvée sur ce téléphone.": "No app found on this phone.", "Application : ": "Application: ",
    "Afficher toutes les applications (clone dont le nom ne contient pas « Dofus »)": "Show all apps (clone whose name doesn't contain “Dofus”)",
    "Nom de paquet invalide (ex. com.ankama.dofustouch).": "Invalid package name (e.g. com.ankama.dofustouch).",
    "adb ou scrcpy-server est introuvable (ni dans l'AppImage ni sur le PC).": "adb or scrcpy-server not found (neither in the AppImage nor on the PC).",
    "Icône indisponible : ": "Icon unavailable: ",
    "Icône indisponible (aucune image d'icône trouvée dans l'application)": "Icon unavailable (no icon image found in the app)",
    # --- raccourcis ------------------------------------------------------------------------------
    "Raccourcis de la fenêtre de mirroring": "Mirroring window shortcuts",
    "MOD = la touche choisie dans « Touche des raccourcis » (par défaut Alt gauche ou Super gauche).":
        "MOD = the key chosen in “Shortcut key” (left Alt or left Super by default).",
    "Action": "Action", "Plein écran": "Full screen", "Fenêtre à la taille 1:1": "Window at 1:1 size",
    "Retirer les bandes noires": "Remove black bars", "clic molette": "middle click", "clic droit": "right click",
    "Bouton marche/arrêt": "Power button", "Rallumer l'écran du téléphone": "Turn the phone screen back on",
    "Coller le presse-papiers du PC": "Paste the PC clipboard", "Afficher/masquer les images par seconde": "Show/hide frames per second",
    "Naviguez entre les sessions depuis le clavier.<br>Format : <b>Ctrl+Tab</b>, <b>Alt+1</b>, <b>F11</b>, <b>Ctrl+Shift+Tab</b>… Laissez vide pour désactiver. Ces touches ne sont actives que lorsque notrefu-mirror est la fenêtre active (elles ne sont pas envoyées au jeu).":
        "Navigate between sessions from the keyboard.<br>Format: <b>Ctrl+Tab</b>, <b>Alt+1</b>, <b>F11</b>, <b>Ctrl+Shift+Tab</b>… Leave empty to disable. These keys only work when notrefu-mirror is the active window (they are not sent to the game).",
    "Session suivante": "Next session", "Session précédente": "Previous session", "Aller à la session ": "Go to session ",
    "Plein écran (masquer les barres)": "Full screen (hide the bars)",
    "Mode compact (masquer barre d'outils et d'état)": "Compact mode (hide toolbar and status bar)",
    "Capture d'écran de la session": "Session screenshot", "Détacher / rattacher la session": "Detach / reattach the session",
    "(aucun)": "(none)", "Valeurs par défaut": "Defaults", "Raccourcis de scrcpy…": "scrcpy shortcuts…",
    "Journal technique — ": "Technical log — ",
    "Journal technique d'une session, mis à jour en direct (partage le document du journal de la session).":
        "A session's technical log, updated live (shares the session log's document).",
    "Les lignes « [app] » disent si l'application a pu être lancée.": "“[app]” lines say whether the app could be launched.",
    # --- boîtes de dialogue -----------------------------------------------------------------------------
    "Vérification en cours…": "Checking…", "Erreur : ": "Error: ",
    " » est en cours. L'arrêter et fermer l'onglet ?": "” is running. Stop it and close the tab?",
    "Relancer ": "Relaunch ", " session(s) qui tournaient à la dernière fermeture ?\n": " session(s) that were running when notrefu-mirror last closed?\n",
    "Au démarrage : propose de relancer les sessions qui tournaient à la fermeture (une seule fois).":
        "On start: offers to relaunch the sessions that were running when it closed (once).",
    "Cette règle autorise l'accès USB aux téléphones en mode débogage (adb) pour l'utilisateur connecté. Elle n'est utile que pour la connexion par câble ; le Wi-Fi n'en a pas besoin.\n\n":
        "This rule grants USB access to phones in debugging mode (adb) for the signed-in user. It is only needed for cable connections; Wi-Fi doesn't need it.\n\n",
    "pkexec est absent. Dans un terminal :\n\n": "pkexec is missing. In a terminal:\n\n",
    " (mot de passe administrateur demandé) ?": " (administrator password required)?", "Écrire ": "Write ", "annulé": "cancelled",
    "Installation échouée :\n": "Installation failed:\n", "\n\nEn terminal :\n\n": "\n\nIn a terminal:\n\n",
    "Règle installée. Débranchez puis rebranchez le téléphone.": "Rule installed. Unplug and replug the phone.",
    "1. Sur le téléphone : Paramètres → À propos → touchez 7 fois « Numéro de build », puis Options pour les développeurs → activez « Débogage USB ».\n2. Branchez le câble, acceptez « Autoriser le débogage USB ».\n3. Dans une session : choisissez le téléphone, réglez la qualité, puis « Lancer le mirroring ». Le jeu s'affiche dans l'onglet.\n\nPlusieurs comptes : bouton « Nouvelle session » (réglages copiés de la session courante), double-clic sur un onglet pour le renommer.\n\nNaviguer : Ctrl+Tab / Ctrl+Maj+Tab, Alt+1…9, F11 pour le plein écran (modifiables dans « Raccourcis »).\n\nSans fil : section « Connecter le téléphone » des réglages de la session.":
        "1. On the phone: Settings → About → tap “Build number” 7 times, then Developer options → turn on “USB debugging”.\n2. Plug in the cable, accept “Allow USB debugging”.\n3. In a session: pick the phone, set the quality, then “Start mirroring”. The game appears in the tab.\n\nSeveral accounts: “New session” button (settings copied from the current session), double-click a tab to rename it.\n\nNavigate: Ctrl+Tab / Ctrl+Shift+Tab, Alt+1…9, F11 for full screen (editable in “Shortcuts”).\n\nWireless: “Connect the phone” section of the session settings.",
    "</b><br>Interface de réplication d'écran Android.<br><br>Moteur : ": "</b><br>Android screen mirroring interface.<br><br>Engine: ",
    " et adb (Android SDK Platform-Tools).<br>Interface : Qt for Python (LGPL).<br><br>Projet indépendant, sans lien avec Ankama ni avec un site tiers. Aucune émulation, aucune automatisation : le jeu tourne sur le téléphone et vous le pilotez vous-même.":
        " and adb (Android SDK Platform-Tools).<br>Interface: Qt for Python (LGPL).<br><br>Independent project, not affiliated with Ankama or any third-party site. No emulation, no automation: the game runs on the phone and you play it yourself.",
    # --- diagnostic -------------------------------------------------------------------------------------------
    "Son": "Sound", "lecteur audio trouvé": "audio player found", "Règles USB": "USB rules", "règle udev installée": "udev rule installed",
    "absente. Si le téléphone n'apparaît pas en USB : menu Aide → Installer les règles USB. Inutile en Wi-Fi.":
        "missing. If the phone doesn't show up over USB: Help menu → Install USB rules. Not needed over Wi-Fi.",
    "Téléphones": "Phones", "adb ne répond pas : ": "adb is not responding: ",
    "aucun appareil. Active « Débogage USB » (Options développeur), branche le câble en mode transfert de fichiers.":
        "no device. Turn on “USB debugging” (Developer options), plug the cable in file-transfer mode.",
    "Android < 11 : le son ne peut pas être capturé.": "Android < 11: sound cannot be captured.",
    "Téléphone": "Phone",
    "Accepte la fenêtre « Autoriser le débogage USB » sur le téléphone (coche « Toujours autoriser »).":
        "Accept the “Allow USB debugging” prompt on the phone (tick “Always allow”).",
    "Débranche et rebranche le câble, ou désactive/réactive le Débogage USB.": "Unplug and replug the cable, or toggle USB debugging off and on.",
    "Permissions USB manquantes : menu Aide → Installer les règles USB.": "Missing USB permissions: Help menu → Install USB rules.",
    # --- divers ---------------------------------------------------------------------------------------------------------
    "Filet de sécurité": "Safety net",
    "Batterie critique (": "Critical battery (", "): branche le chargeur.": "): plug in the charger.",
    "Batterie faible (": "Low battery (", "Le téléphone chauffe beaucoup (": "The phone is getting very hot (",
    "): baisse la qualité ou fais une pause.": "): lower the quality or take a break.", "Le téléphone chauffe (": "The phone is getting warm (",
    "Le téléphone bride ses performances à cause de la chauffe : le jeu risque de ralentir.": "The phone is throttling its performance because of heat: the game may slow down.",
    "Stockage presque plein (": "Storage almost full (", " Go libres).": " GB free).",
    "Mémoire du téléphone presque saturée (": "Phone memory almost full (", " Mo disponibles) : trop de comptes ?": " MB available): too many accounts?",
    "Jusqu'à ": "Up to ", " Mbit/s pour cette fenêtre": " Mbit/s for this window", " Mbit/s au total pour ": " Mbit/s in total for ",
    " sessions sur ce téléphone": " sessions on this phone",
    ". En Wi-Fi, au-delà de ": ". On Wi-Fi, above ", " Mbit/s ça saccade souvent : baisse le débit ou branche le câble.": " Mbit/s it often stutters: lower the bitrate or plug in the cable.",
    ". C'est beaucoup, même pour de l'USB : baisse le débit.": ". That's a lot, even for USB: lower the bitrate.",
    "Vue en grille (sessions en cours)": "Grid view (running sessions)",
    "Guides (Papycha, Almanax)…": "Guides (Papycha, Almanax)…",
    "Guides (Papycha, Almanax)": "Guides (Papycha, Almanax)",
    "Page précédente": "Previous page",
    "Réglages": "Settings",
    "Ouvrir la page dans le navigateur du système": "Open the page in the system browser",
    "Sites": "Sites",
    "Téléphones, raccourcis, thème, langue, export des réglages": "Phones, shortcuts, theme, language, settings export",
    "Téléphones détectés et règles USB…": "Detected phones and USB rules…",
    "Raccourcis clavier…": "Keyboard shortcuts…",
    "Disposition du panneau": "Panel layout",
    "Ajuster : le jeu sans bandes noires, les guides le reste": "Fit: game without black bars, guides get the rest",
    "Téléphone": "Phone",
    "Jeu": "Game",
    "Réglages avancés": "Advanced settings",
    "Nom de la session": "Session name",
    "Format de la fenêtre": "Window format",
    "Taille de l'interface du jeu": "Game interface size",
    "Priorité au jeu (Android)": "Game priority (Android)",
    "Lancer le jeu automatiquement à la connexion": "Launch the game automatically on connection",
    "Éteindre l'écran du téléphone pendant la session": "Turn the phone screen off during the session",
    "Afficher la fluidité (images/s)": "Show smoothness (frames/s)",
    "Montrer les appuis sur l'écran du téléphone": "Show touches on the phone screen",
    "Empêcher la mise en veille du téléphone (USB)": "Keep the phone awake (USB)",
    "Éteindre l'écran du téléphone en quittant": "Turn the phone screen off on exit",
    "Image nette (peut ralentir)": "Sharp image (may slow down)",
    "Adapter le jeu quand je redimensionne la fenêtre": "Fit the game when I resize the window",
    "Démarrer cette session à l'ouverture de notrefu-mirror": "Start this session when notrefu-mirror opens",
    "Empêcher le jeu de s'endormir…": "Keep the game from sleeping…",
    "Son": "Sound",
    "Contrôle": "Control",
    "Session": "Session",
    "Aucune session ouverte.": "No session open.",
    "Impossible de lire les téléphones :": "Cannot read the phones:",
    "Aucun téléphone détecté. Active le débogage USB, branche le câble et accepte la fenêtre d'autorisation, puis clique sur Actualiser.": "No phone detected. Turn on USB debugging, plug in the cable and accept the authorisation prompt, then click Refresh.",
    "Réglages de cette session (qualité, affichage, options)": "Session settings (quality, display, options)",
    "Adapter l'écran du jeu à la taille de la fenêtre (relance la session, le jeu reste lancé sur le téléphone)": "Fit the game screen to the window size (restarts the session, the game stays running on the phone)",
    "Panneau de notifications du téléphone": "Phone notification panel",
    "Journal technique de la session (utile pour comprendre un problème)": "Session technical log (useful to understand a problem)",
    "Arrêter cette session": "Stop this session",
    "Autres actions": "More actions",
    "Relancer le jeu (ferme puis rouvre l'application, sans couper la session)": "Relaunch the game (closes and reopens the app without ending the session)",
    "Au démarrage : ouvrir un espace": "At startup: open a space",
    "Ranger les fenêtres détachées côte à côte": "Arrange detached windows side by side",
    "Ranger les fenêtres détachées en pile": "Arrange detached windows stacked",
    "Démarre d'abord la session et indique l'application du jeu dans les réglages.": "Start the session first and set the game app in the settings.",
    "relance du jeu": "relaunching the game",
    "jeu relancé": "game relaunched",
    "relance impossible": "relaunch failed",
    "Dézoomer (Ctrl+-)": "Zoom out (Ctrl+-)",
    "Zoomer (Ctrl++)": "Zoom in (Ctrl++)",
    "Adapter la page à la largeur du panneau (évite le défilement horizontal)": "Fit the page to the panel width (avoids horizontal scrolling)",
    "Ajuster : le jeu prend la place sans bandes noires, les guides le reste": "Auto-fit: the game fills its space with no black bars, the guides get the rest",
    "Le navigateur intégré n'est pas disponible.": "The built-in browser is not available.",
    "Mettre les guides de l'autre côté des sessions": "Move the guides to the other side of the sessions",
    "Fermer les guides": "Close the guides",
    "Page suivante": "Next page",
    "Recharger": "Reload",
    "Navigateur": "Browser",
    "Sites…": "Sites…",
    "Ouvrir la page actuelle dans le navigateur du système": "Open the current page in the system browser",
    "Ajouter ou retirer un site de la liste": "Add or remove a site from the list",
    "Ajouter un site…": "Add a site…",
    "Ajouter un site": "Add a site",
    "Retirer un site": "Remove a site",
    "Rétablir la liste d'origine": "Restore the default list",
    "Nom du bouton :": "Button name:",
    "Adresse (ex. papycha.fr) :": "Address (e.g. papycha.fr):",
    "Adresse non valide.": "Invalid address.",
    "Vue en grille : lance au moins 2 sessions pour les voir côte à côte.": "Grid view: start at least 2 sessions to see them side by side.",
    "Vue en grille : clique sur une cellule pour entendre son son, sur son titre pour l'ouvrir en grand.": "Grid view: click a cell to hear its sound, its title to open it full size.",
    "Ouvrir cette session en grand": "Open this session full size",
    "Qualité 1 : Faible": "Quality 1: Low", "Qualité 2 : Moyen": "Quality 2: Medium", "Qualité 3 : Haut": "Quality 3: High", "Qualité 4 : Ultra": "Quality 4: Ultra",
    " : qualité ": ": quality ", ", relance de la session…": ", restarting the session…", " (appliquée au prochain lancement).": " (applied at next launch).",
    "Clique ici puis appuie sur la combinaison de touches voulue. Retour arrière ou Suppr : aucun raccourci.": "Click here then press the key combination you want. Backspace or Delete: no shortcut.",
    "Appuyez sur la nouvelle combinaison…": "Press the new combination…",
    "» est déjà utilisé par : ": "” is already used by: ",
    "Un même raccourci est donné à plusieurs actions : corrige-le avant de valider.": "The same shortcut is assigned to several actions: fix it before confirming.",
    "Exporter les réglages…": "Export settings…", "Importer des réglages…": "Import settings…",
    "Exporter les réglages": "Export settings", "Importer des réglages": "Import settings", "Réglages notrefu-mirror (*.json)": "notrefu-mirror settings (*.json)",
    " réglages exportés dans ": " settings exported to ", "Export impossible : ": "Export failed: ", "Import impossible : ": "Import failed: ",
    "Réglages importés : ferme puis relance notrefu-mirror pour les appliquer.": "Settings imported: close and relaunch notrefu-mirror to apply them.",
    "Remplacer toutes les sessions, espaces et réglages par ceux du fichier (": "Replace all sessions, spaces and settings with those from the file (",
    " valeurs) ?\nLes changements s'appliquent au prochain démarrage de notrefu-mirror.": " values)?\nChanges apply the next time notrefu-mirror starts.",
    "Demander à Android de ne pas endormir « ": "Ask Android not to put “", " » quand sa fenêtre est en arrière-plan ?\n\nC'est réversible (réglage de batterie de l'application sur le téléphone) et ne change rien aux tours de jeu.": "” to sleep when its window is in the background?\n\nIt is reversible (the app's battery setting on the phone) and changes nothing about the game turns.",
    "\n\nSur Xiaomi / HyperOS, ouvre aussi la page de l'application et règle « Économiseur de batterie » sur « Aucune restriction » et active « Démarrage automatique ». Ouvrir cette page sur le téléphone maintenant ?": "\n\nOn Xiaomi / HyperOS, also open the app page and set “Battery saver” to “No restrictions” and turn on “Autostart”. Open that page on the phone now?",
    "Impossible d'ouvrir la page : ": "Could not open the page: ",
    "Échec : ": "Failed: ",
    "Statut : ": "Status: ",

    "Mode jeu Android": "Android game mode", "Ne pas changer": "Don't change", "Économie de batterie": "Battery saver",
    "Anti-gel en arrière-plan…": "Background anti-freeze…",
    "Souris et clavier": "Mouse and keyboard",
    "Mode jeu d'Android pour Dofus Touch : « Performance » donne plus de puissance au jeu (le téléphone chauffe davantage), « Économie de batterie » en donne moins. Appliqué au lancement de la session ; sans effet si le téléphone n'a pas de mode jeu.": "Android game mode for Dofus Touch: “Performance” gives the game more power (the phone gets hotter), “Battery saver” gives it less. Applied when the session starts; no effect if the phone has no game mode.",
    "À utiliser seulement si la fenêtre d'un compte se fige au bout d'un moment : demande à Android de ne pas endormir le jeu. Ne change rien au jeu lui-même ni aux tours ; le téléphone consomme juste un peu plus de batterie.": "Only use this if an account's window freezes after a while: asks Android not to put the game to sleep. It changes nothing in the game itself or in the turns; the phone just uses a little more battery.",
    "Choisis d'abord un téléphone et l'application du jeu.": "First pick a phone and the game app.",
    "Exclure de l'économie de batterie": "Exclude from battery saving", "Autoriser l'activité en arrière-plan": "Allow background activity",
    "Autoriser l'activité longue en arrière-plan": "Allow long background activity",
    "le téléphone accepte les touches et les clics envoyés par notrefu-mirror": "the phone accepts the keys and clicks sent by notrefu-mirror",
    "le téléphone refuse les touches et les clics. Sur Xiaomi / HyperOS : Paramètres → Paramètres supplémentaires → Options pour les développeurs → active « Débogage USB (paramètres de sécurité) » (et « Installer via USB »), puis débranche et rebranche le câble.": "the phone refuses keys and clicks. On Xiaomi / HyperOS: Settings → Additional settings → Developer options → turn on “USB debugging (Security settings)” (and “Install via USB”), then unplug and replug the cable.",
    "Batterie": "Battery", "Temps de jeu : ": "Play time: ", " Go libres": " GB free",

    "Couper les notifications du téléphone": "Mute the phone's notifications",
    "Active « Ne pas déranger » (prioritaire) sur le téléphone pendant la session, puis le rétablit à l'arrêt : plus de sons de notification dans le jeu ni sur le PC. Le son du jeu n'est pas touché.": "Turns on “Do Not Disturb” (priority) on the phone during the session, then restores it on stop: no more notification sounds in the game or on the PC. Game sound is not affected.",
    "Au démarrage : rouvrir les dernières sessions": "On startup: reopen the last sessions",
    "Au démarrage : ne rien ouvrir": "On startup: open nothing",
    "Au démarrage : notrefu-mirror rouvrira les dernières sessions.": "On startup: notrefu-mirror will reopen the last sessions.",
    "Au démarrage : notrefu-mirror s'ouvrira sans aucune session.": "On startup: notrefu-mirror will open with no session.",
    "Alt gauche ou Super gauche (défaut)": "Left Alt or left Super (default)", "Alt gauche": "Left Alt", "Ctrl gauche": "Left Ctrl",
    "Alt droit (AltGr)": "Right Alt (AltGr)", "Touche des raccourcis": "Shortcut key", "Diagnostic": "Diagnostics",
    "Qualité, affichage, options de cette session.": "Quality, display and options of this session.",
    "Qualité, écran, options : les changements ne comptent qu'au prochain lancement.": "Quality, screen, options: changes only count at the next launch.",
    "Raccourci": "Shortcut", "Valeurs par défaut": "Defaults",

    "Féca": "Feca", "Xélor": "Xelor", "Écaflip": "Ecaflip", "Steamer": "Steamer",
}

_lang = "fr"
_keys: list[str] = []
_rx: re.Pattern | None = None
_cache: dict[str, str] = {}


def _build() -> None:
    global _rx, _keys
    # en fragment, seules les clés longues ou délimitées (espace, ponctuation) : « Mode » ne doit pas toucher « Modèle »
    _keys = sorted((k for k in EN if k and (len(k) >= 12 or k[0] in " :(…»“[]<\n" or k[-1] in " :(…»“[]>\n")),
                   key=len, reverse=True)
    _rx = re.compile("|".join(re.escape(k) for k in _keys))
    _cache.clear()


_build()


def lang() -> str:
    return _lang


def tr(text: str) -> str:
    """Traduit `text` (français) dans la langue courante ; renvoie `text` tel quel en français."""
    if _lang != "en" or not isinstance(text, str) or not text:
        return text
    hit = _cache.get(text)
    if hit is not None:
        return hit
    out = EN.get(text)
    if out is None:
        out = _rx.sub(lambda m: EN[m.group(0)], text) if _rx else text
    if len(_cache) > 4000:
        _cache.clear()
    _cache[text] = out
    return out


# --- méthodes d'origine (avant remplacement) -------------------------------------------------------------------------
_O: dict[str, object] = {}


def _orig_text(w: QWidget, original: str) -> None:
    if isinstance(w, QGroupBox):
        _O["gb.setTitle"](w, original)  # type: ignore[operator]
    elif isinstance(w, QLabel):
        _O["lb.setText"](w, original)  # type: ignore[operator]
    elif isinstance(w, QAbstractButton):
        _O["bt.setText"](w, original)  # type: ignore[operator]


def install() -> None:
    """Fait passer les textes affichés par `tr()` (à appeler une fois, avant de créer les fenêtres)."""
    if _O:
        return

    def wrap_text(key: str, cls, name: str):
        orig = getattr(cls, name)
        _O[key] = orig

        def f(self, text, *a, **k):
            if isinstance(text, str):
                self.setProperty("_fr", text)
                text = tr(text)
            return orig(self, text, *a, **k)

        setattr(cls, name, f)

    for _cls, _names in ((QDialog, ("show", "exec", "open")), (QMenu, ("exec", "popup"))):
        for _n in _names:
            _wrap_show(_cls, _n)
    wrap_text("lb.setText", QLabel, "setText")
    wrap_text("bt.setText", QAbstractButton, "setText")
    wrap_text("gb.setTitle", QGroupBox, "setTitle")

    o_tip = QWidget.setToolTip

    def set_tip(self, text):
        if isinstance(text, str):
            self.setProperty("_fr_tip", text)
            text = tr(text)
        return o_tip(self, text)

    QWidget.setToolTip = set_tip  # type: ignore[method-assign]
    _O["w.setToolTip"] = o_tip

    o_wt = QWidget.setWindowTitle

    def set_wt(self, text):
        if isinstance(text, str):
            self.setProperty("_fr_wt", text)
            text = tr(text)
        return o_wt(self, text)

    QWidget.setWindowTitle = set_wt  # type: ignore[method-assign]
    _O["w.setWindowTitle"] = o_wt

    o_ph = QLineEdit.setPlaceholderText

    def set_ph(self, text):
        if isinstance(text, str):
            self.setProperty("_fr_ph", text)
            text = tr(text)
        return o_ph(self, text)

    QLineEdit.setPlaceholderText = set_ph  # type: ignore[method-assign]

    o_sb = QStatusBar.showMessage

    def show_msg(self, text, *a):
        return o_sb(self, tr(text) if isinstance(text, str) else text, *a)

    QStatusBar.showMessage = show_msg  # type: ignore[method-assign]

    o_ppt = QPlainTextEdit.setPlainText

    def set_ppt(self, text):
        return o_ppt(self, tr(text) if isinstance(text, str) else text)

    QPlainTextEdit.setPlainText = set_ppt  # type: ignore[method-assign]

    # menus : addAction("texte", ...) et addMenu("titre")
    o_aa = QMenu.addAction

    def add_action(self, *args, **kw):
        args = list(args)
        i = 1 if args and isinstance(args[0], QIcon) else 0
        fr_text = args[i] if len(args) > i and isinstance(args[i], str) else ""
        if fr_text:
            args[i] = tr(fr_text)
        res = o_aa(self, *args, **kw)
        if fr_text and hasattr(res, "setProperty"):
            res.setProperty("_fr", fr_text)
        return res

    QMenu.addAction = add_action  # type: ignore[method-assign]
    o_am = QMenu.addMenu

    def add_menu(self, *args):
        args = list(args)
        i = 1 if args and isinstance(args[0], QIcon) else 0
        if len(args) > i and isinstance(args[i], str):
            args[i] = tr(args[i])
        return o_am(self, *args)

    QMenu.addMenu = add_menu  # type: ignore[method-assign]

    # listes déroulantes : le français d'origine est gardé par entrée
    o_ai = QComboBox.addItem
    o_sit = QComboBox.setItemText
    o_clear = QComboBox.clear

    def add_item(self, *args, **kw):
        args = list(args)
        i = 1 if args and isinstance(args[0], QIcon) else 0
        if len(args) > i and isinstance(args[i], str):
            fr = self.property("_fr_items") or []
            fr = list(fr) + [args[i]]
            self.setProperty("_fr_items", fr)
            args[i] = tr(args[i])
        return o_ai(self, *args, **kw)

    def set_item_text(self, index, text):
        if isinstance(text, str):
            fr = list(self.property("_fr_items") or [])
            while len(fr) <= index:
                fr.append("")
            fr[index] = text
            self.setProperty("_fr_items", fr)
            text = tr(text)
        return o_sit(self, index, text)

    def clear(self):
        self.setProperty("_fr_items", [])
        return o_clear(self)

    QComboBox.addItem = add_item  # type: ignore[method-assign]
    QComboBox.setItemText = set_item_text  # type: ignore[method-assign]
    QComboBox.clear = clear  # type: ignore[method-assign]
    _O["cb.setItemText"] = o_sit

    # boîtes de dialogue
    for name in ("information", "warning", "critical", "question"):
        orig = getattr(QMessageBox, name)

        def make(orig):
            def f(parent, title, text, *a, **k):
                return orig(parent, tr(title), tr(text), *a, **k)
            return staticmethod(f)

        setattr(QMessageBox, name, make(orig))
    for name in ("getText", "getInt", "getItem"):
        orig = getattr(QInputDialog, name)

        def make2(orig):
            def f(parent, title, label, *a, **k):
                return orig(parent, tr(title), tr(label), *a, **k)
            return staticmethod(f)

        setattr(QInputDialog, name, make2(orig))


def _apply(w: QWidget) -> None:
    """Pose sur `w` la langue courante ; le français d'origine est repris du texte actuel s'il n'a pas été mémorisé
    (widgets créés avec le texte dans le constructeur : QLabel("..."), QCheckBox("...")…)."""
    if isinstance(w, (QLabel, QAbstractButton, QGroupBox)):
        fr = w.property("_fr")
        if fr is None:
            fr = w.title() if isinstance(w, QGroupBox) else w.text()
            if _lang != "en" and not fr:
                fr = None
            if fr is not None:
                w.setProperty("_fr", fr)
        if fr:
            _orig_text(w, tr(fr))
    tip = w.property("_fr_tip")
    if tip is None and w.toolTip():
        tip = w.toolTip()
        w.setProperty("_fr_tip", tip)
    if tip:
        _O["w.setToolTip"](w, tr(tip))  # type: ignore[operator]
    wt = w.property("_fr_wt")
    if wt is not None:
        _O["w.setWindowTitle"](w, tr(wt))  # type: ignore[operator]
    if isinstance(w, QLineEdit):
        ph = w.property("_fr_ph")
        if ph is None and w.placeholderText():
            ph = w.placeholderText()
            w.setProperty("_fr_ph", ph)
        if ph:
            w.setPlaceholderText(ph)
    if isinstance(w, QComboBox):
        items = w.property("_fr_items")
        if items is None or len(items) != w.count():
            items = [w.itemText(i) for i in range(w.count())]
            w.setProperty("_fr_items", items)
        for i, t in enumerate(items):
            if i < w.count() and t:
                _O["cb.setItemText"](w, i, tr(t))  # type: ignore[operator]
    for a in w.actions():
        a_fr = a.property("_fr")
        if a_fr is None:
            a_fr = a.text()
            a.setProperty("_fr", a_fr)
        a.setText(tr(a_fr))


def translate(root: QWidget) -> None:
    """Traduit `root` et ses enfants (à appeler après la création d'une page en anglais)."""
    if not _O or _lang != "en":
        return
    for w in [root] + root.findChildren(QWidget):
        _apply(w)


def _wrap_show(cls, name: str) -> None:
    """Traduit une fenêtre au moment de l'afficher. (Un filtre d'événements Python sur toute l'application
    ferait planter le navigateur intégré : ses objets internes ne peuvent pas être enveloppés par PySide.)"""
    orig = getattr(cls, name)

    def f(self, *a, **k):
        if _lang == "en":
            translate(self)
        return orig(self, *a, **k)

    setattr(cls, name, f)


_filter = None


def set_lang(lang: str) -> None:
    """Change la langue et retraduit tout ce qui est déjà affiché."""
    global _lang
    _lang = "en" if lang == "en" else "fr"
    _cache.clear()
    global _filter
    app = QApplication.instance()
    if app is None or not _O:
        return
    for w in app.allWidgets():
        _apply(w)
