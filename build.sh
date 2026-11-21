#!/usr/bin/env bash
# Construit notrefu-mirror-x86_64.AppImage
#   ./build.sh            -> build complet (télécharge puis met en cache les dépendances)
# Prérequis : bash, curl, tar, sha256sum, accès à github.com et pypi.org.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
CACHE="$ROOT/build/cache"
APPDIR="$ROOT/build/AppDir"
OUT="$ROOT/dist"

# ---- versions épinglées -----------------------------------------------------
SCRCPY_VERSION="5.0.1"
PBS_TAG="20261026"
PYTHON_VERSION="3.13.18"
PYSIDE_VERSION="6.12.0"
WEBENGINE_VERSION="6.12.0.140"
PYAV_VERSION="19.0.2"

SCRCPY_URL="https://github.com/Genymobile/scrcpy/releases/download/v${SCRCPY_VERSION}/scrcpy-linux-x86_64-v${SCRCPY_VERSION}.tar.gz"
PYTHON_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/cpython-${PYTHON_VERSION}+${PBS_TAG}-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"

# Empreintes SHA-256 des archives (vérifiées à chaque build ; laissez vide pour les recalculer).
SCRCPY_SHA256="9f969d30cc574816077edecda65719c1c70b0aee1df1ba5fa00779ac07b8fd6e"
PYTHON_SHA256="df15fe60d3ff55bf9dcf25824b5572756bb8816ff93865a273d3301d7066a8b7"

mkdir -p "$CACHE" "$OUT"

fetch() { # url dest [sha256]
    local url="$1" dest="$2" sha="${3:-}"
    if [ ! -f "$dest" ]; then
        echo ">> téléchargement $(basename "$dest")"
        curl -fsSL --retry 3 -o "$dest.part" "$url"
        mv "$dest.part" "$dest"
    fi
    local got; got="$(sha256sum "$dest" | cut -d' ' -f1)"
    if [ -n "$sha" ] && [[ "$sha" != __* ]] && [ "$got" != "$sha" ]; then
        echo "!! SHA-256 incorrect pour $dest" >&2
        echo "   attendu $sha" >&2
        echo "   obtenu  $got" >&2
        exit 1
    fi
    echo "   sha256 $(basename "$dest") = $got"
}

fetch "$SCRCPY_URL" "$CACHE/scrcpy.tar.gz" "$SCRCPY_SHA256"
fetch "$PYTHON_URL" "$CACHE/python.tar.gz" "$PYTHON_SHA256"
fetch "$APPIMAGETOOL_URL" "$CACHE/appimagetool" ""
chmod +x "$CACHE/appimagetool"

# ---- AppDir -----------------------------------------------------------------
echo ">> assemblage de l'AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib/scrcpy" "$APPDIR/usr/app" \
         "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Python relocatable
tar xzf "$CACHE/python.tar.gz" -C "$APPDIR/usr"
PY="$APPDIR/usr/python/bin/python3"

# scrcpy + adb + serveur
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
tar xzf "$CACHE/scrcpy.tar.gz" -C "$tmp"
d="$(echo "$tmp"/scrcpy-linux-x86_64-*)"
cp "$d/scrcpy" "$d/adb" "$d/scrcpy-server" "$d/LICENSE" "$APPDIR/usr/lib/scrcpy/"
chmod 755 "$APPDIR/usr/lib/scrcpy/scrcpy" "$APPDIR/usr/lib/scrcpy/adb"

# PySide6 (Qt) – uniquement les modules nécessaires
"$PY" -m pip install --quiet --no-cache-dir --break-system-packages --root-user-action=ignore \
    "PySide6-Essentials==${PYSIDE_VERSION}" "PySide6-Addons==${PYSIDE_VERSION}"
# navigateur intégré (fenêtre « Guides ») : QtWebEngine
"$PY" -m pip install --quiet --no-cache-dir --break-system-packages --root-user-action=ignore \
    --no-deps "PySide6-WebEngine==${WEBENGINE_VERSION}"
# PyAV (décodeur H.264 ffmpeg embarqué) : sans numpy, l'application n'en a pas besoin
"$PY" -m pip install --quiet --no-cache-dir --break-system-packages --root-user-action=ignore \
    --no-deps "av==${PYAV_VERSION}"

# Application
cp -r "$ROOT/src/notrefu_mirror" "$APPDIR/usr/app/"
find "$APPDIR/usr/app" -name '__pycache__' -prune -exec rm -rf {} +

# Icône (PNG fourni, redimensionné à 256 px avec Qt)
QT_QPA_PLATFORM=offscreen "$PY" - "$ROOT/src/notrefu_mirror/resources/notrefu_mirror.png" \
    "$APPDIR/usr/share/icons/hicolor/256x256/apps/notrefu_mirror.png" <<'PYEOF'
import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage
app = QGuiApplication([])
img = QImage(sys.argv[1]).scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
assert not img.isNull() and img.save(sys.argv[2])
PYEOF

# ---- allègement -------------------------------------------------------------
echo ">> allègement"
SP="$APPDIR/usr/python/lib/python3.13/site-packages"
PS="$SP/PySide6"
# modules Python de PySide6 : on ne garde que ceux utilisés
for f in "$PS"/*.abi3.so; do
    case "$(basename "$f")" in
        QtCore.abi3.so|QtGui.abi3.so|QtWidgets.abi3.so|QtSvg.abi3.so) ;;
        QtNetwork.abi3.so|QtWebChannel.abi3.so|QtPositioning.abi3.so|QtPrintSupport.abi3.so|QtOpenGL.abi3.so) ;;
        QtQml.abi3.so|QtQuick.abi3.so|QtQuickWidgets.abi3.so|QtWebEngineCore.abi3.so|QtWebEngineWidgets.abi3.so) ;;
        *) rm -f "$f" ;;
    esac
done
rm -rf "$PS"/{include,glue,typesystems,scripts,examples,support} "$PS"/*.pyi "$PS"/py.typed
rm -rf "$PS"/Qt/{qml,metatypes,modules} 2>/dev/null || true
# libexec : on ne garde que le processus de rendu web ; traductions : uniquement les langues du navigateur utiles
find "$PS/Qt/libexec" -type f ! -name QtWebEngineProcess -delete
find "$PS/Qt/translations" -maxdepth 1 -type f -delete
find "$PS/Qt/translations/qtwebengine_locales" -type f ! \( -name 'en-US.pak' -o -name 'en-GB.pak' -o -name 'fr.pak' \) -delete
rm -f "$PS"/Qt/resources/qtwebengine_devtools_resources.pak
rm -f  "$PS"/{designer,uic,rcc,lupdate,lrelease,assistant,linguist,qmllint,qmlformat,qmlls,qsb,svgtoqml,balsam,balsamui,qmlimportscanner,pyside6-*}* 2>/dev/null || true
# bibliothèques Qt inutiles
cd "$PS/Qt/lib"
# on garde les bibliothèques de base + tout ce dont QtWebEngine a besoin (fermeture des dépendances Qt)
keep=" libQt6Core libQt6Gui libQt6Widgets libQt6DBus libQt6Svg libQt6OpenGL libQt6XcbQpa libQt6WaylandClient libQt6WlShellIntegration libQt6WebEngineCore libQt6WebEngineWidgets "
changed=1
while [ "$changed" = 1 ]; do
    changed=0
    for b in $keep; do
        for dep in $(readelf -d "$b.so.6" 2>/dev/null | grep -o 'libQt6[A-Za-z0-9]*'); do
            case "$keep" in *" $dep "*) ;; *) [ -e "$dep.so.6" ] && { keep="$keep$dep "; changed=1; } ;; esac
        done
    done
done
for lib in libQt6*.so*; do
    base="${lib%%.so*}"
    case "$keep" in *" $base "*) ;; *) rm -f "$lib" ;; esac
done
rm -f "$PS/Qt/lib"/libQt6FFmpegStub* "$PS/Qt/lib"/libav*.so* "$PS/Qt/lib"/libsw*.so*
cd "$PS/Qt/plugins"
rm -rf designer egldeviceintegrations qmltooling sqldrivers tls networkinformation \
       vectorimageformats wayland-graphics-integration-server assetimporters canbus geometryloaders \
       geoservices multimedia position renderers renderplugins sceneparsers scxmldatamodel sensors \
       texttospeech webview
# plugins orphelins (dépendent de modules Qt supprimés ou inutiles sur un poste de bureau)
rm -f platforms/libqeglfs.so platforms/libqvnc.so platforms/libqvkkhrdisplay.so platforms/libqminimalegl.so \
      platforms/libqlinuxfb.so generic/libqtuiotouchplugin.so platforminputcontexts/libqtvirtualkeyboardplugin.so \
      imageformats/libqpdf.so
rm -rf "$SP"/{pip,pip-*,setuptools,setuptools-*,pkg_resources,_distutils_hack,wheel,wheel-*,distutils-precedence.pth}
PYLIB="$APPDIR/usr/python/lib/python3.13"
rm -rf "$PYLIB"/{test,idlelib,tkinter,turtledemo,ensurepip,lib2to3,pydoc_data,__phello__,config-3.13-x86_64-linux-gnu}
rm -rf "$APPDIR/usr/python/share" "$APPDIR/usr/python/include" "$APPDIR/usr/python/lib/libtcl"* "$APPDIR/usr/python/lib/tk"* "$APPDIR/usr/python/lib/tcl"* 2>/dev/null || true
find "$PYLIB/lib-dynload" \( -name '_tkinter*' -o -name '_test*' -o -name '_ctypes_test*' -o -name 'xxlimited*' \) -delete 2>/dev/null || true
cd "$ROOT"

# pré-compilation (l'AppImage est en lecture seule : sans cela le démarrage recompile à chaque fois)
"$PY" -m compileall -q "$APPDIR/usr/app" "$PS" >/dev/null 2>&1 || true

# ---- garde-fous -------------------------------------------------------------
echo ">> vérification des dépendances embarquées"
missing="$(find "$PS" "$APPDIR/usr/lib/scrcpy" -type f \( -name '*.so' -o -name '*.so.*' \) -print0 \
    | xargs -0 -n1 env LD_LIBRARY_PATH="$PS/Qt/lib" ldd 2>/dev/null \
    | grep 'not found' | grep -E 'libQt6|libicu|libpyside|libshiboken' || true)"
if [ -n "$missing" ]; then
    echo "!! bibliothèques embarquées manquantes après allègement :" >&2
    echo "$missing" | sort -u >&2
    exit 1
fi
echo ">> tests (logique + interface hors écran, avec le Qt allégé)"
for t in test_core test_protocol test_engine test_reconnect test_detection test_compat test_perf test_ratios test_edgegrip; do
    "$APPDIR/usr/python/bin/python3" "$ROOT/tests/$t.py" 2>&1 | tail -3
done
rm -rf /tmp/notrefu_mirror-test-cfg
QT_QPA_PLATFORM=offscreen "$APPDIR/usr/python/bin/python3" "$ROOT/tests/smoke_gui.py" 2>&1 | tee /dev/stderr | grep "SMOKE OK" >/dev/null
QT_QPA_PLATFORM=offscreen "$APPDIR/usr/python/bin/python3" "$ROOT/tests/e2e_keymap.py" 2>&1 | tee /dev/stderr | grep "E2E KEYMAP OK" >/dev/null
rm -rf /tmp/notrefu_mirror-test-cfg

# ---- métadonnées AppImage ---------------------------------------------------
cp "$ROOT/packaging/AppRun" "$APPDIR/AppRun" && chmod 755 "$APPDIR/AppRun"
cp "$ROOT/packaging/notrefu_mirror.desktop" "$APPDIR/notrefu_mirror.desktop"
cp "$ROOT/packaging/notrefu_mirror.desktop" "$APPDIR/usr/share/applications/"
cp "$APPDIR/usr/share/icons/hicolor/256x256/apps/notrefu_mirror.png" "$APPDIR/notrefu_mirror.png"
cp "$APPDIR/usr/share/icons/hicolor/256x256/apps/notrefu_mirror.png" "$APPDIR/.DirIcon"
cp "$ROOT/packaging/NOTICE.txt" "$APPDIR/NOTICE.txt"

# ---- empaquetage ------------------------------------------------------------
echo ">> création de l'AppImage"
VERSION="$("$PY" -c 'import sys; sys.path.insert(0, "'"$APPDIR"'/usr/app"); import notrefu_mirror; print(notrefu_mirror.__version__)')"
ARCH=x86_64 "$CACHE/appimagetool" --appimage-extract-and-run --no-appstream \
    --mksquashfs-opt -b --mksquashfs-opt 1M --mksquashfs-opt -Xcompression-level --mksquashfs-opt 19 \
    "$APPDIR" "$OUT/notrefu-mirror-${VERSION}-x86_64.AppImage"
chmod +x "$OUT/notrefu-mirror-${VERSION}-x86_64.AppImage"
ls -lh "$OUT"
