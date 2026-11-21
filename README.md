# notrefu-mirror

Réplication d'écran Android (USB ou Wi-Fi) en AppImage, avec une interface Qt en français.
Le jeu tourne sur le téléphone ; notrefu-mirror embarque **adb** et le serveur **scrcpy 5.0.1** et affiche le flux
directement dans sa fenêtre (client H.264 intégré, décodage PyAV/ffmpeg). Aucune émulation, aucune automatisation.

## Utilisation sur Bazzite 44 (KDE)

```bash
chmod +x notrefu-mirror-0.15.0-x86_64.AppImage
./notrefu-mirror-0.15.0-x86_64.AppImage
```

Rien à installer : Python, Qt, scrcpy et adb sont dans le fichier. Pour l'intégrer au menu KDE, utilisez
*Gear Lever* (Flatpak) ou déplacez le fichier dans `~/Applications`.

Diagnostic : `./notrefu-mirror-0.15.0-x86_64.AppImage --check` (affiche les outils trouvés et les téléphones vus par adb).
Si l'AppImage refuse de se monter : `--appimage-extract-and-run`.

### Téléphone
1. Options pour les développeurs → **Débogage USB** (7 touches sur « Numéro de build » pour les afficher).
2. Branchez, acceptez « Autoriser le débogage USB ».
3. Choisissez le téléphone → **Lancer le mirroring**.

**USB sans autorisation (« no permissions »)** : menu *Aide → Installer les règles USB*
(écrit `/etc/udev/rules.d/51-notrefu_mirror-adb.rules`, mot de passe demandé), puis rebranchez le câble.
Le Wi-Fi n'en a pas besoin.

**Sans fil** : une fois en USB, *Activer le sans-fil* (l'IP se remplit), débranchez, *Connecter sans fil*.
Android 11+ : *Appairer* permet de le faire sans câble.

## Fonctions
- Modes **Standard** et **Horizontal** (écran virtuel paysage via `--new-display`, Android 10+) avec l'app lancée dessus
  (par défaut `com.ankama.dofustouch`, modifiable).
- Qualité Faible / Moyen / Haut / Ultra / Perso (débit, ips, résolution, DPI).
- Interface sombre moderne (zinc + violet) sans bordure système : barre de titre personnalisée (déplacement, double-clic pour agrandir, réduire/agrandir/fermer), redimensionnement par les bords, ombres douces, icônes 100 % SVG nettes à toute taille. Réglages sur une colonne quand la fenêtre est étroite.
- 10 thèmes (bouton « Thème » dans la barre de titre) : Zinc violet (défaut), Bleu électrique, Clair, Bonta, Brakmar, Wabbit, Pandala (jade), Frigost, Amakna, Dofus Touch. Le choix est mémorisé.
- Options : écran éteint, ips, touches visibles, contrôle, son, presse-papiers, anti-veille, extinction en quittant,
  clavier sdk/uhid, touche des raccourcis, journal technique.
- **Une seule fenêtre, une session par onglet** : bouton ＋ pour créer une session, double-clic sur l'onglet pour la
  renommer, boutons Appareils / Raccourcis / Aide en haut à droite, ⚙ Réglages (qualité, affichage, options) et ■ Arrêter dans chaque onglet.
- **Reconnexion automatique** : si le câble ou le Wi-Fi coupe, la session est relancée toute seule (jusqu'à 60 essais, espacés de 3 à 8 s ; en Wi-Fi, `adb connect` est relancé). L'onglet passe à l'orange pendant ce temps ; ■ Arrêter annule. Désactivable dans les options.
- **Plus de bandes noires** : en mode Horizontal, l'écran virtuel prend la forme de la zone d'affichage au moment du lancement (option « Adapter l'écran du jeu… »). Si tu redimensionnes la fenêtre ensuite, relance la session pour réajuster.
- **Filet de sécurité** : si la résolution/densité du téléphone change pendant une session (notrefu-mirror ne la modifie jamais volontairement), elle est remise à l'état d'avant à la fin de la session.
- Son : **Latence du son** réglable par session (⚙ Réglages, défaut 120 ms). Grésille ou saccade → augmente (ex. 200) ; en retard sur l'image → diminue (ex. 60). Le retard qui s'accumule est rattrapé automatiquement.
- Fermer la dernière session affiche une page vide (bouton « ＋ Nouvelle session ») au lieu d'en recréer une ; les sessions sont numérotées avec le plus petit numéro libre.
- Son : le journal technique affiche toutes les 10 s une ligne `[audio]` (paquets joués/abandonnés, écart max, retard max) pour diagnostiquer un problème de son. Un retard qui s'accumule côté réception est aussi rattrapé.
- Bouton **Écran** dans la barre d'outils : éteint / rallume l'écran du téléphone (l'option « Éteindre l'écran » le fait aussi au lancement, y compris en mode Horizontal).
- **Démarrage automatique** (option par session) : au lancement de notrefu-mirror, les sessions cochées se connectent toutes seules dès que leur téléphone est détecté.
- Onglets colorés : vert = connecté, orange = reconnexion. La taille de la fenêtre est mémorisée.
- Barre d'outils de session : Accueil, Retour, Récents, Notifications, Capture d'écran (PNG dans le dossier Images).
- Clic gauche = toucher/glisser, clic droit = Retour, clic molette = Accueil, molette = défilement, clavier = texte.
- **Détecter…** : liste les applications Dofus Touch du téléphone (clones compris) avec leur **nom et leur icône** ; double-clic pour choisir. Case « Afficher toutes les applications » si un clone n'a pas « Dofus » dans son nom. Les icônes sont lues directement dans l'APK du téléphone (seule la fin du fichier et l'image choisie sont transférées, pas toute l'application) ; si ce n'est pas possible, une icône générique s'affiche et le survol de l'élément en donne la raison.
- **Presse-papiers** : ce que tu copies sur le téléphone arrive sur le PC et inversement ; dans le jeu, Ctrl+C / Ctrl+X copient côté téléphone et Ctrl+V colle le texte du PC. Désactivable dans les options.
- Réglages mémorisés.

## Raccourcis (modifiables via le bouton « Raccourcis »)
| Touche | Action |
|---|---|
| Ctrl+Tab / Ctrl+Maj+Tab | session suivante / précédente |
| Alt+1 … Alt+9 | aller à la session n° |
| F11 | plein écran (barres masquées) |

Ces touches sont lues par notrefu-mirror quand sa fenêtre est active ; elles ne sont pas envoyées au jeu.

## Limites de cette version
- Le son demande Android 11+ (le son du jeu seul : Android 13+) et un lecteur sur le PC (`paplay` ou `pw-cat` sous Linux, winmm sous Windows). Seule la session affichée joue.
- Les tests automatiques utilisent un faux adb et un flux H.264 réel ; les appareils réels (Xiaomi/Poco, Samsung) ne sont testés que par retours d'utilisation. La version Windows est portable et n'est pas signée.
- Les emblèmes de classe ne sont pas fournis : voir « Emblèmes » ci-dessous.

## Règles d'Ankama (à respecter)
D'après les règles de conduite et la page « appareils compatibles » de Dofus Touch (support.ankama.com, dofus-touch.com) :
- Le **mirroring d'écran** est cité comme possible ; le jeu reste l'application officielle, non modifiée, sur ton téléphone.
- **Interdits** : programmes tiers type « bot », client modifié, émulateurs, jouer sur un appareil non mobile avec une application non officielle,
  plus de 2 comptes par joueur en combats JcJ (percepteur, prisme, Kolizéum, AvA).
- notrefu-mirror ne fait donc **aucune automatisation** : un clic ou une touche = une action de ta part. Pas de macro, pas de clic automatique,
  pas de lecture de l'écran du jeu, pas d'envoi d'une même touche à plusieurs comptes.
- Je ne peux pas garantir l'absence de sanction : Ankama reste seul juge. En cas de doute, demande au support Ankama.

## Reconstruire
```bash
./build.sh            # Linux : télécharge (SHA-256 vérifiés) et produit dist/notrefu-mirror-*.AppImage
./build_windows.sh    # Windows portable (zip), assemblé depuis Linux
cd tests && PYTHONPATH=../src QT_QPA_PLATFORM=offscreen python3 -m unittest test_core test_protocol test_engine test_reconnect test_detection test_compat test_perf test_session_plan test_session_config test_session_logic test_stores test_logic_modules test_shutdown test_runner_qt test_qa_regressions test_keymap
```
Tests graphiques à part : `test_ratios.py`, `test_edgegrip.py`, `smoke_gui.py` et `e2e_keymap.py` (avec `xvfb-run -a` si pas d'écran).
Dépendances système attendues sur l'hôte : bibliothèques de bureau standard (Wayland/X11, Mesa, fontconfig, PipeWire/Pulse).

## Emblèmes
notrefu-mirror n'embarque aucune image de jeu. Les emblèmes d'onglet sont des pastilles colorées générées ; pour utiliser vos propres images,
déposez `01.png` … `15.png` dans `src/notrefu_mirror/resources/classes/` (voir le `LISEZMOI.txt` de ce dossier).

## Licences
Code de notrefu-mirror : MIT, auteur notrefu (fichier `LICENSE`). Composants tiers : scrcpy et adb : Apache-2.0 ; Qt for Python (PySide6) : LGPL v3 ;
PyAV / FFmpeg : BSD / LGPL ; CPython : PSF. Voir `packaging/NOTICE.txt`. notrefu-mirror n'est affilié ni à Ankama ni à un site tiers.

Si la résolution du téléphone était un jour déformée : `adb shell wm size reset` et `adb shell wm density reset`.

- Affichage : « Forme de l'écran » (suivre la fenêtre, 16:9, 2:1, 21:9, ou largeur × hauteur de Perso) et « Taille de l'interface » (curseur 60–200 %, agit sur le DPI du jeu).

- Doubles applications (Xiaomi/HyperOS « Double apps », même nom de paquet) : détectées via les autres utilisateurs du téléphone et lancées par adb. Diagnostic : `./notrefu-mirror.AppImage --users-debug`.


## 0.6.x
- Couleur d'onglet par session, relance des sessions à l'ouverture, `Ctrl+Shift+S` pour une capture.
- 0.8.1 : indicateurs en direct (ips, débit reçu, temps de décodage) ; les onglets cachés ne convertissent plus les images (déjà le cas).
- 0.8.2 : enregistrement vidéo (bouton rond, .mkv dans Vidéos, sans le son) ; clic droit sur un onglet → Détacher dans une fenêtre (la fermer remet l’onglet) ; Aide → Langue : English (traduction partielle, effective après redémarrage).
- 0.9.0 : santé du téléphone (batterie, chauffe, stockage, mémoire, alertes) ; débit estimé par fenêtre et au total ; temps de jeu par session ; anti-gel en arrière-plan (bouton manuel) ; mode jeu Android ; test souris/clavier dans le diagnostic ; vue en grille (Ctrl+Maj+G) ; raccourcis Qualité 1 à 4 (Ctrl+Alt+1…4) et saisie des touches avec détection des conflits ; export/import des réglages (Aide).
- 0.8.6 : option « Couper les notifications du téléphone » (active Ne pas déranger pendant la session, rétabli à l’arrêt, partagé entre sessions du même téléphone) ; le journal indique la source audio utilisée.
- 0.8.5 : les onglets sont enregistrés en continu (plus de perte après un plantage) ; zéro session est restauré tel quel ; Espaces → « Au démarrage : rouvrir les dernières sessions / ne rien ouvrir ».
- 0.8.4 : correctif — le journal technique se ferme (croix et bouton Fermer) et ne s’ouvre plus en plusieurs exemplaires.
- 0.8.3 : son du jeu seul (option, Android 13+) et son dans l’enregistrement ; traduction anglaise complète et immédiate (Aide → Langue) ; Ctrl+Maj+D détache/rattache la session ; fenêtres détachées mémorisées ; clic droit sur le bouton ● : dossier des enregistrements ; point rouge sur l’onglet qui enregistre ; l’adaptation à la fenêtre garde la dernière image.
- 0.8.0 : « Espaces » (enregistrer/ouvrir un groupe de comptes, relance des sessions dont le téléphone est branché) et style TabDesk en un clic.
- 0.7.8 : emblèmes nommés par classe, plus de couleurs d'onglet (emblèmes seulement).
- 0.7.7 : 15 emblèmes de classe en icône d'onglet par défaut, menu « Emblèmes » (depuis 0.14.12 : pastilles générées, images personnelles facultatives).
- 0.7.6 : suppression du tiret (barre de navigation) de l'écran virtuel ; icône d'onglet au choix (image de l'ordinateur).
- 0.7.5 : préréglages identiques à TabDesk (Ultra 16 Mbit/s, Haut 8, Moyen 4 à 45 ips, Faible 2) + préréglage « Multi-compte » (4 Mbit/s, 30 ips, 1280×720, 160 dpi) appliqué aux sessions ajoutées.
- 0.7.4 : correctif du plantage au démarrage (réglage perso : clé « fps » en double).
- 0.7.3 : rendu net (image posée pixel pour pixel, redimensionnement bicubique), image clé toutes les 2 s, préréglages dpi = largeur/8, Ultra 16 Mbit/s.
- 0.7.2 : option « Pixels 1:1 » (écran virtuel à la taille exacte de la zone de jeu, image plus nette).
- 0.7.1 : seul le logo reste dans la barre de titre (clic = à propos).
- 0.7.0 : onglets dans la barre de titre (une seule ligne).
- F10 : mode compact (masque barre d'outils et barre d'état, garde les onglets).
- Volume par session (curseur dans la barre d'outils du jeu).
- Aide → Diagnostic : vérifie adb, le serveur scrcpy, le son et le téléphone.

## 0.10.0
- Fenêtre « Guides » (menu Espaces → « Guides (Papycha, Almanax)… », ou Ctrl+Shift+J) : navigateur intégré (QtWebEngine) avec boutons de sites modifiables. Les pages s'affichent telles quelles ; notrefu-mirror n'en extrait rien.
- L'AppImage est plus volumineuse (le moteur web est embarqué).

## 0.10.1
- Les guides s'affichent maintenant dans un panneau à côté des sessions (dans la fenêtre principale), à droite par défaut ; bouton ⇄ pour passer à gauche. Largeur mémorisée.
- Correction d'un plantage (journal technique : document sans mise en page) et rendu web logiciel plus sûr.

## 0.10.2
- Correction d'un plantage au démarrage de 0.10.1 (réglage OpenGL retiré). `NOTREFU_MIRROR_NO_WEB=1` désactive le navigateur intégré en cas de souci.

## 0.10.3
- Le navigateur intégré est d'abord essayé dans un processus séparé au premier lancement : s'il plante sur la machine, notrefu-mirror démarre quand même et ouvre les guides dans le navigateur du système. `NOTREFU_MIRROR_PROBE=1` refait l'essai.

## 0.10.4
- Cause du plantage trouvée : un filtre d'événements Python posé sur toute l'application (traduction des fenêtres) faisait planter dès que le navigateur intégré s'affichait. La traduction des fenêtres se fait maintenant à leur ouverture, sans filtre global.

## 0.10.5
- Guides : Almanax (krosmoz.com) et Lomitall par défaut ; barre sur deux lignes ; zoom −/+ (Ctrl +/−/0) mémorisé par site et bouton ↔ « adapter à la largeur » (plus de défilement horizontal impossible).
- Le panneau se règle seul pour que le jeu occupe toute la hauteur sans bandes noires (bouton ⇔ pour y revenir) ; la séparation se déplace librement (cela coupe l'ajustement automatique).

## 0.10.6
- Plus de messages de console des sites dans le terminal ; le moteur web est libéré dans le bon ordre à la fermeture (fin de l'avertissement « Release of profile… »).

## 0.11.0
- Guides : le moteur web est libéré dès qu'on ferme le panneau (plusieurs centaines de Mo) ; l'ajustement se fait à chaque changement de taille au lieu d'un sondage permanent ; la dernière page de chaque site est rouverte.
- Nouveau bouton « Relancer le jeu » dans la barre de session : ferme puis rouvre l'application sans couper la session.
- Espaces : « Au démarrage : ouvrir un espace » ; « Ranger les fenêtres détachées » (côte à côte ou en pile).
- AppImage : compression plus forte.

## 0.11.1 — barre de session repensée
- Trois groupes séparés : session (réglages, relancer le jeu, adapter) · navigation Android (retour, accueil, récents — dans l'ordre d'Android) · outils (capture, enregistrement, notifications, écran du téléphone) ; volume et journal ensuite ; état et « Arrêter » à droite.
- Boutons à icône seule avec infobulle : plus de texte coupé (« J...l », « ... »).
- Barre étroite : les boutons les moins utiles passent dans un menu « ⋯ » au lieu de déborder.

## 0.11.2
- La vérification du navigateur intégré n'est plus refaite à chaque nouvelle version de notrefu-mirror (seulement si Qt change) et sa fenêtre est invisible.

## 0.12.0 — écran de réglages repensé
- Une seule colonne centrée, dans l'ordre de la tâche : Téléphone · Jeu · Qualité · Options (Son, Téléphone, Contrôle, Session) · Réglages avancés (repliés : mode, format de fenêtre, taille de l'interface, image nette, mode jeu Android, anti-gel…).
- Libellés plus clairs (« Image nette », « Priorité au jeu (Android) », « Empêcher le jeu de s'endormir »…).
- Un seul bouton principal en bas à droite : « Lancer le mirroring » ou « Arrêter » selon l'état.
- Bandeau d'aide dans le bloc Téléphone quand aucun téléphone n'est détecté ou qu'adb ne répond pas.
- Barre de session : l'état s'abrège au lieu de déborder sur « Arrêter ». Sans session : bouton « Nouvelle session » centré, plus de zone vide dans la barre de titre.

## 0.12.1 — barre de titre et Guides
- Barre de titre : trois menus au lieu de cinq — Espaces · Réglages (téléphones et règles USB, raccourcis, thème, langue, export/import des réglages) · Aide.
- Guides : le site affiché reste en surbrillance ; « Navigateur », « Sites… », « Ajuster » et « autre côté » passent dans un menu « ⋯ » ; la fermeture ✕ reste en haut à droite du panneau.

## 0.12.2 — code réorganisé (aucun changement visible)
- `ui.py` (3323 lignes) devient le paquet `ui/` : `common`, `dialogs`, `phone_panel`, `session_page`, `titlebar`, `main_window`.
- Logique sans Qt, testée à part : `session_plan` (écran virtuel), `session_config` (réglages d'une session), `session_logic` (paramètres, reconnexion, résolution), `stores` (espaces, démarrage, Guides), `health_monitor`, `guides_layout`, `udev_setup`, `wireless`.
- `_build_ui` (414 lignes) découpée en six blocs. 93 tests unitaires.

## 0.12.3 — infos du téléphone toujours visibles
- Barre de session : la batterie et la température du téléphone passent en premier, puis les images/s, puis le son. Quand le jeu est muet, la barre affiche « son : silence » (court) au lieu d'un long message qui cachait le reste ; le texte complet apparaît au survol.

## 0.12.4 — fluidité et arrêt propre
- Fermer un onglet ou l'application ne fige plus l'interface : les sessions s'arrêtent en parallèle (4 s au total au lieu de 4 s chacune).
- Ctrl+C / `kill` ferment maintenant proprement (sessions, serveur adb, lecteur audio) au lieu de laisser des processus orphelins.
- Une conversion d'enregistrement en cours est terminée avant de quitter (elle pouvait être coupée net).
- Tâches adb : pool dédié de 8 fils, résultats ignorés si l'onglet a été fermé entre-temps, file vidée à la fermeture.
- « À propos », la page batterie (anti-gel) et l'allumage de l'écran du téléphone ne bloquent plus l'interface.
- Images du jeu : un seul signal en attente à la fois (pas d'empilement quand l'interface a du retard).

## 0.12.5 — audit QA : cas limites corrigés
- **Arrêter ne fonctionnait pas** quand le téléphone acceptait la connexion sans jamais répondre (session bloquée sur « Connexion au serveur… » pour toujours, reconnexion impossible) : la poignée de main a maintenant un délai de 20 s et s'interrompt dès qu'on clique sur Arrêter.
- **Redémarrer puis Arrêter** relançait quand même la session (boucle de relance orpheline) ; des clics répétés sur Redémarrer lançaient plusieurs boucles. Corrigé.
- **Relancer le jeu** : les clics répétés sont ignorés pendant qu'une relance est en cours.
- **Nombre de sessions limité à 8** (40 onglets gelaient l'interface ~12 s) ; un espace importé ne peut plus en ouvrir davantage.
- **Saisies** : port ou adresse IP avec des chiffres exotiques (« ² », chiffres arabes) ne plante plus ; l'IP doit être une vraie IPv4 ; un nom de paquet avec retour à la ligne est refusé.
- **Import de réglages** : un fichier JSON imbriqué à l'extrême ou des clés vides ne plantent plus l'import.
- **Flux corrompu** : un paquet vidéo/audio annoncé à plus de 32 Mo coupe la session proprement au lieu d'attendre indéfiniment.
- Division par zéro évitée dans le calcul de l'écran virtuel ; valeur infinie dans les réglages ignorée ; thème inconnu ramené au thème par défaut.

## 0.13.0 — touches personnalisées (keymapping)
Une touche du clavier = **un seul appui** à un endroit précis de l'écran du jeu. Bouton clavier dans la barre de session (ou Ctrl+Maj+E pour éditer, Ctrl+Maj+K pour activer/désactiver).
- **Mode édition** : clic sur le jeu → « appuie sur la touche » ; glisser = déplacer ; double-clic = changer la touche ; clic droit ou Suppr = supprimer ; Échap = terminer. Rien n'est envoyé au téléphone pendant l'édition.
- **Mode jeu** : la touche pressée envoie un appui (doigt posé), la touche relâchée lève le doigt. Plusieurs touches enfoncées = plusieurs doigts distincts, jamais la souris.
- **Positions en pourcentages de l'image du téléphone** : elles restent justes à toute taille de fenêtre (bandes noires comprises). Enregistrées par session, copiées avec « Nouvelle session », incluses dans les espaces.
- Désactive les touches (menu du bouton ou Ctrl+Maj+K) pour écrire dans le chat du jeu. Les combinaisons avec Ctrl/Alt ne sont jamais traduites ; les touches déjà prises par un raccourci de l'application (F10, F11…) sont refusées.

**Garde-fous (règle « 1 clic physique = 1 action sur 1 seul compte »)**
- Une touche ne déclenche qu'un seul appui : pas de macro, pas de séquence, pas de délai programmé.
- Aucune répétition : la répétition automatique du clavier est ignorée, la touche doit être relâchée pour agir de nouveau, et des appuis parasites plus rapprochés que 60 ms sont écartés.
- Aucune diffusion : seule la session qui a le focus reçoit l'appui (pas de filtre global, pas de boucle sur les sessions).
- Perte du focus, session arrêtée ou 3 s sans relâchement : le doigt est levé, rien ne reste posé.

## 0.13.1 — CPU et RAM du téléphone dans la barre du haut

- La ligne d'état de la session affiche maintenant la **charge du processeur** et la **mémoire utilisée** du téléphone, en plus de la batterie et de la température : « 82 % ⚡ · 36,5 °C · CPU 23 % · RAM 64 % ».
- Le **stockage restant** n'est plus affiché dans la barre. L'alerte « stockage presque plein » reste active.
- Le CPU est mesuré par deux lectures de `/proc/stat` espacées de 0,4 s (repli sur `dumpsys cpuinfo`). La RAM est la mémoire totale moins la mémoire disponible. Si une valeur n'est pas lisible, elle est simplement omise.

## 0.13.2 — coller du texte dans le jeu

- **Ctrl+V** envoie toujours le presse-papiers du PC au téléphone puis demande « Coller » (une seule fois par pression, plus de répétition si la touche reste enfoncée).
- Nouveau : **Ctrl+Maj+V** tape le texte du presse-papiers comme au clavier. À utiliser quand « Coller » est ignoré par le champ du jeu (cas fréquent avec Unity / Dofus Touch). Les retours à la ligne deviennent des espaces et certains accents peuvent être ignorés par le clavier Android.

## 0.13.3 — copier la disposition des touches vers d'autres sessions

- Menu clavier de la barre de session → **« Copier ces touches vers… »** : recopie les emplacements vers une autre session (ou toutes les autres) pour ne pas tout refaire quand l'interface de jeu est la même.
- Seules les positions sont recopiées ; chaque session garde ensuite sa propre disposition, indépendante. Rien n'est envoyé en simultané : une touche reste un seul appui sur la seule session qui a le focus.

## Version Windows portable (0.13.3-windows, expérimentale)

- `build_windows.sh` assemble depuis Linux un dossier à dézipper : Python Windows, Qt/PySide6, PyAV, adb.exe et le serveur scrcpy. Lancer `notrefu-mirror.bat` ; `Diagnostic.bat` affiche ce que l'application voit.
- Adaptations : adb.exe, son via l'API Windows winmm (`winaudio.py`, sans module externe), pas de fenêtre de console (`winfix.py`), règles USB réservées à Linux.
- Ce build est assemblé depuis Linux (sans machine Windows) ; il est validé par retours d'utilisateurs Windows et par une vérification statique des DLL.

## 0.13.4 (Windows)

- Correctif : « Détecter… » (liste des applications du téléphone) disait « scrcpy introuvable » sous Windows. `scrcpy.exe` et ses DLL sont maintenant dans le dossier `tools`.

## 0.13.5 (Windows)

- `notrefu-mirror.exe` remplace `notrefu-mirror.bat` : petit lanceur (`packaging/launcher_windows.c`, compilé par zig depuis Linux) avec l'icône de l'application, sans fenêtre de console. `Diagnostic.bat` reste disponible.

## 0.14.0 — économie d'énergie, protection du téléphone, réveil, rapport complet

Réglages → **Téléphone : chauffe et réveil** :

- ~~Ralentir les sessions sans focus~~ : **retiré en 0.14.3** (voir plus bas).
- **Limiter les ips si le téléphone chauffe ou si le Wi-Fi sature** (désactivé par défaut depuis 0.14.3) : à partir de 41 °C (ou état thermique Android « moderate ») les ips passent à 30, à 44 °C (ou « severe ») à 20, avec retour progressif quand il refroidit. En Wi-Fi, trois « blocages » du flux en 10 s (silence puis rafale d'images) déclenchent la même limitation. Un message dans la barre de session indique « ips limités à N (chauffe / Wi-Fi) ».
- **Réveiller le téléphone quand je clique sur une session** : touche « réveil » seule (ne déverrouille pas, sans effet si l'écran est déjà allumé), au plus une fois par 20 s, jamais si « Éteindre l'écran du téléphone » est coché.
- **Aide → Diagnostic → Copier le rapport** : diagnostic + versions + état de chaque session (qualité, plafond d'ips, santé, derniers messages). Adresses IP et numéros de série masqués.

Comment ça marche : scrcpy ne permet pas de changer les ips en cours de route, et relancer une session détruirait l'écran virtuel du jeu. Une session « freinée » lit donc son flux vidéo à au plus N images/s ; le serveur du téléphone ne peut plus écrire, son encodeur ralentit et le téléphone produit moins d'images. Le jeu tourne normalement, seul le miroir est moins fluide. À l'inverse d'un compte actif, un compte en arrière-plan peut avoir ~1 s de retard d'image (rattrapé dès qu'on lui redonne le focus).

Aussi : correction d'un doublon de `changeEvent` qui empêchait la mise à jour de l'icône agrandir/restaurer.

## 0.14.1 — moins de lag en Ultra sur les longues sessions

- **Rattrapage du retard** : convertir une image en RVB coûte plus cher que la décoder. Quand le PC n'arrive pas à suivre (Ultra 1440p / 60 ips sur un processeur modeste), les images en attente sont décodées sans être converties (au moins 15 images/s restent affichées) ; le retard ne grossit plus. Mesuré avec un flux simulé et une conversion volontairement lente : 3,1 s au lieu de 8,2 s pour traiter 3 s de flux.
- Test de durée (flux 720p, 25 s) : mémoire stable (+1,9 Mo), nombre de fils constant.

## 0.14.2 — le jeu se ferme sur le téléphone quand on arrête ou supprime la session

- Avant, arrêter ou supprimer une session coupait seulement le miroir : le jeu restait ouvert en arrière-plan sur le téléphone (batterie, réseau, compte toujours connecté).
- Maintenant, **Arrêter**, **supprimer l'onglet** et **fermer notrefu-mirror** ferment aussi le jeu sur le téléphone (`am force-stop`, pour la bonne copie : double application comprise).
- Sécurités : uniquement si la session a elle-même lancé le jeu (« Lancer le jeu automatiquement » coché), jamais lors d'une coupure de connexion / reconnexion automatique ni d'un redémarrage de la session. Case à décocher : Options → Téléphone → « Fermer le jeu sur le téléphone quand j'arrête ou supprime la session ».

## 0.14.3 — curseur, faux message d'Espace, fin de l'économie d'énergie en grille

- **Curseur de redimensionnement bloqué (KDE Wayland)** : le curseur double-flèche était posé sur la fenêtre principale, donc hérité par la zone vidéo, les onglets et la barre de session, et aucun événement de sortie n'arrive tant que la souris reste dans la fenêtre. Maintenant le redimensionnement par les bords passe par 8 poignées transparentes (`ui/edgegrip.py`), chacune avec son propre curseur : il n'existe que sous la souris, sur la poignée. La fenêtre n'a plus jamais de curseur propre (`unsetCursor()` à la sortie, au relâchement et au redimensionnement par sécurité), sans filtre d'événements global. Poignées masquées en plein écran / maximisé.
- **« Aucun téléphone sélectionné. » à l'ouverture d'un Espace** : une session créée à l'instant avait une liste de téléphones vide jusqu'au rafraîchissement suivant, alors que le téléphone était connu. Elle reçoit maintenant tout de suite la liste détectée et sélectionne le téléphone enregistré (`_attach_known_devices`) ; en dernier recours `start()` utilise le numéro de série enregistré au lieu d'afficher l'alerte.
- **Économie d'énergie en grille supprimée** : plus aucune session n'est ralentie parce qu'elle n'a pas le focus (grille, onglets, fenêtre réduite) : le frein sur la lecture du flux faisait prendre du retard à la session suivante, qui rejouait ensuite les animations. Réglages et textes retirés. La limitation « chauffe / Wi-Fi saturé » a la même mécanique de frein : elle est désormais **désactivée par défaut** (Réglages → Téléphone : chauffe et réveil).

## 0.14.4 — reconnexion automatique fiabilisée (Windows + Linux)

Bug : après une coupure, l'onglet restait orange « Reconnexion en cours » sans jamais reprendre, alors qu'« Arrêter » puis relancer fonctionnait.
Cause : une tentative pouvait rester bloquée sans aucun délai maximum (sous Windows, `subprocess.run(timeout=…)` attend les tuyaux de sortie
que le serveur adb, relancé en tâche de fond, garde ouverts ; en plus la connexion au serveur pouvait durer ~7 minutes).

- **Nettoyage complet à chaque tentative** (identique à « Arrêter ») : « Ne pas déranger », tunnel `adb forward --remove`, processus adb du serveur,
  serveur scrcpy resté sur le téléphone (tué par son `scid`), plus suppression des tunnels/serveurs orphelins d'une session coupée.
- **Délais stricts** : tout appel adb passe par `adb.run_cmd` (sortie en fichier temporaire, processus tué à l'échéance) : détection 5 s, `connect` 8 s,
  `forward` 8 s, envoi du serveur 30 s ; ouverture des connexions 12 s au total ; poignée de main 20 s ; garde-fou global de 45 s par tentative
  (au-delà, la tentative est abandonnée et la suivante démarre, sans attendre « Arrêter »).
- **État de l'appareil avant relance** : `offline`/`unauthorized`/absent détectés ; en Wi-Fi `adb disconnect` puis `adb connect` ; en USB `adb reconnect`.
- **Journal technique** : `[reconnexion] tentative N/60…`, `[connexion] état de l'appareil … : offline`, `[reconnexion] échec : délai dépassé — …`,
  `[nettoyage] …`.
- Tests : `tests/test_reconnect.py` (12 tests).

## 0.14.5 — détection des tablettes (Samsung Galaxy Tab A9+ …) et aide au diagnostic

- **Aucun appareil vu par adb n'est caché** : tous les états de `adb devices -l` sont listés (`unauthorized`, `offline`, `no permissions`, `authorizing`, `connecting`, `recovery`…).
  Un appareil détecté mais pas prêt n'affiche plus « Aucun téléphone détecté » mais la marche à suivre (« Appareil détecté mais non autorisé — accepte la pop-up… »).
- **Bandeau d'aide** : bouton « Ouvrir le diagnostic ». Sous Windows, sans appareil : rappel Samsung (désactiver le « Bloqueur automatique », installer le « Samsung Android USB Driver »).
  Sous Linux : renvoi vers « Installer les règles USB ».
- **Règle udev v2** (`51-notrefu_mirror-adb.rules`) : en plus de l'interface adb, une ligne par constructeur (Samsung `04e8`, Google, Xiaomi, Motorola, Huawei, Honor, OnePlus, Oppo, vivo, Sony, LG, ASUS, Lenovo, Amazon Fire…).
  Le diagnostic signale une ancienne règle sans Samsung et propose de la mettre à jour (Aide → Installer les règles USB, puis rebrancher).
- **Aide → Diagnostic** : état du serveur adb (tourne / vient de démarrer / bloqué), sortie brute de `adb devices -l` (numéros de série masqués) à copier-coller,
  et sous Linux les constructeurs vus sur le port USB (même si adb ne voit rien).
- Tests : `tests/test_detection.py` (13 tests).

## 0.14.6 — compatibilité tablettes / anciens Android / marques

- **Anciens Android (SDK < 30)** : `ro.build.version.sdk` est lu avant chaque session ; sous Android 10 et moins le transfert audio est coupé
  automatiquement (même si la case est cochée) et une info discrète s'affiche : « Audio désactivé automatiquement : Android 11+ requis ».
- **Conflit de serveur adb** (autre `adb.exe`, émulateur, Android Studio sur le port 5037, « adb server version doesn't match ») : notrefu-mirror redémarre
  le serveur avec l'adb embarqué (kill-server puis start-server, une seule fois par 10 s) et rejoue la commande ; sinon message clair dans le journal
  et dans Aide → Diagnostic.
- **États adb lisibles** dans la liste : « Non autorisé — accepte la pop-up sur l'écran », « Hors ligne — rebranche le câble », « Permissions USB manquantes… ».
- **Conseil selon la marque** (`ro.product.manufacturer`) : Xiaomi/POCO/Redmi (Débogage USB — paramètres de sécurité), Oppo/Realme/OnePlus
  (désactiver la surveillance des autorisations), Samsung (Bloqueur automatique + pilote Samsung sous Windows). Affiché sous le téléphone, dans
  Aide → Diagnostic et quand le téléphone refuse les clics.
- **Repli vidéo automatique** : si le flux ne démarre pas (encodeur refusé, serveur arrêté, aucune image en 10 s : fréquent sur tablettes MediaTek/Unisoc),
  nouvel essai en H.264 Baseline, ≤ 8 Mbit/s / 1280 px, puis ≤ 3 Mbit/s / 960 px, au lieu d'un écran noir. L'écran virtuel est réduit proportionnellement.
- **Ratios** : la vue et le keymapping utilisent toujours la taille réelle envoyée par scrcpy (16:10, 5:3, 4:3, portrait, paysage) — vérifié par tests.
- Règle udev v2 (0.14.5) : Samsung, Xiaomi, Lenovo, Huawei/Honor, Oppo/Realme, OnePlus, Motorola, ASUS, Google, Sony, vivo, MediaTek, Qualcomm… inchangée.
- Tests : `test_compat.py` (16), `test_ratios.py` (GUI).

## 0.14.7 — mémoire, décodage GPU, QtWebEngine à la demande

- **RAM du téléphone** : toujours `MemTotal − MemAvailable` (jamais MemFree, qui compte le cache Android). La barre affiche en plus la RAM de l'application du jeu
  seule (`dumpsys meminfo <paquet>`, PSS) : « RAM 62 % (jeu 512 Mo) ». notrefu-mirror n'affiche aucune statistique CPU/RAM du PC.
- **Décodage vidéo par la carte graphique (Windows)** : d3d11va puis dxva2, avec repli automatique et définitif sur le processeur (erreurs de décodage, aucune image
  après 40 paquets, pilote absent). Le décodeur utilisé est écrit dans le journal (« [décodeur] matériel (d3d11va) » ou « logiciel »). Désactivable dans
  Réglages. Aide → Diagnostic indique les décodeurs GPU disponibles.
- **QtWebEngine n'est plus chargé au démarrage** : ni la vérification isolée, ni les bibliothèques (plus de 100 Mo) tant que le panneau Guides n'est pas ouvert.
- **Binaires Windows** : `adb.exe`, `AdbWinApi.dll`, `AdbWinUsbApi.dll`, `libusb-1.0.dll` vérifiés identiques à l'archive officielle scrcpy-win64-v5.0.1 ;
  le build échoue s'il en manque un, et Aide → Diagnostic signale un fichier manquant.
- Rendu : l'image est déjà convertie et réduite à la taille exacte de la vue (une seule conversion, posée pixel pour pixel) ; le passage à un widget OpenGL n'a pas été fait.
- Tests : `tests/test_perf.py` (11).

## 0.14.8 — audit et optimisation

- **Profils de qualité vérifiés** : Moyen = 4 Mbit/s · 45 ips · 1280 px, Ultra = 16 Mbit/s · 60 ips · 2560 px sont bien transmis au serveur scrcpy (test automatique). En mode « image nette », la taille de l'écran virtuel est plafonnée par la taille de la fenêtre : les résolutions peuvent alors coïncider, mais pas le débit ni les ips.
- **RAM / CPU** : l'info-bulle de la barre précise que ce sont les valeurs globales de l'appareil Android (RAM = total − disponible ; « jeu » = l'application seule).
- **Monitoring allégé** : relevé léger /proc (CPU + RAM) toutes les 5 s, relevé complet (batterie, chauffe, stockage, RAM du jeu) toutes les 30 s ; plus aucun `dumpsys` dans le relevé rapide.
- **Décodage matériel Linux** : VAAPI (Intel/AMD) puis NVDEC (cuda), avec repli automatique sur le logiciel (option dans Réglages).
- **Moins de copies** : l'image RGB n'est plus recopiée avant l'affichage.
- **Fermeture d'onglet** : minuteur de tentative et rappels tardifs neutralisés.

## 0.14.9
- « Éteindre l'écran du téléphone pendant la session » et « Empêcher la mise en veille du téléphone (USB) » sont activés par défaut pour les nouvelles sessions (les sessions déjà enregistrées gardent leur réglage).

## 0.14.10
- **Sessions masquées** : aucune conversion/dessin quand la session n'est pas à l'écran (le flux reste lu et décodé), dernière image réaffichée immédiatement au retour. Les actions (clic, touche, molette) en attente depuis plus d'1 s ne sont jamais rejouées en retard ; les relâchements sont toujours livrés.
- **Lectures ADB** : CPU + RAM dans une seule commande `adb shell` ; relevé complet (batterie, chauffe, stockage) toutes les 60 s ; RAM du jeu (`dumpsys meminfo`) toutes les 120 s ; téléphones sans session visible relevés toutes les 15 s ; rien pendant une reconnexion.
- **Reconnexion** : appareil `offline`/`unauthorized` → délais 3 s, 5 s, 8 s (plafond) ; remis à zéro dès que l'appareil repasse en `device`, sur « Arrêter » ou relance manuelle (et nouvel essai rapide quand il se réveille).
- **Keymapping** : toutes les touches/doigts sont relâchés à la perte d'activation de la fenêtre ou de l'application, à l'ouverture d'une boîte de dialogue, au changement d'onglet et à l'arrêt de la session.

## 0.14.11
- **Info-bulle de la barre de session** : la barre garde son texte court ; au survol, détail de la RAM de l'appareil (« 5,2 / 8,0 Go utilisés », total − disponible d'après `/proc/meminfo`), RAM du jeu seul (`Jeu : ~512 Mo`) si disponible, et rappel que c'est la mémoire globale d'Android. Valeurs absentes (premier relevé, `dumpsys meminfo` indisponible) gérées.

## 0.14.12 — préparation de la publication
- Plus aucune image de jeu dans les sources : emblèmes générés (images personnelles facultatives dans `resources/classes/`).
- Faux numéros de série des tests remplacés par `FAKESERIAL01` ; `.gitignore`, `LICENSE` (MIT) ajoutés ; `NOTICE.txt` complété (PyAV/FFmpeg, QtWebEngine).

## 0.15.0 — nouveau nom : notrefu-mirror
- L'application s'appelle désormais **notrefu-mirror** (paquet Python `notrefu_mirror`, fichiers `notrefu-mirror-<version>-…`, `notrefu-mirror.exe` sous Windows, variable `NOTREFU_MIRROR_HOME`).
- Premier lancement : vos sessions, touches personnalisées, thème et espaces enregistrés sous l'ancien nom sont repris automatiquement (copie unique, l'ancien jeu de réglages n'est pas modifié).
- Les connexions des onglets Guides (cookies) ne sont pas reprises : à refaire une fois.
