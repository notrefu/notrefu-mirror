#!/usr/bin/env bash
# Construit notrefu-mirror-<version>-windows-portable.zip (dossier à dézipper, sans installation) depuis Linux.
# Rien n'est exécuté sous Windows ici : Python, Qt, PyAV et adb sont des binaires Windows téléchargés puis assemblés.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
CACHE="$ROOT/build/wincache"; STAGE="$ROOT/build/winstage"; OUT="$ROOT/dist"
SCRCPY_VERSION="5.0.1"; PBS_TAG="20261026"; PYTHON_VERSION="3.13.18"
PYSIDE_VERSION="6.12.0"; WEBENGINE_VERSION="6.12.0.140"; PYAV_VERSION="19.0.2"
mkdir -p "$CACHE" "$OUT"
fetch() { [ -f "$2" ] || { echo ">> téléchargement $(basename "$2")"; curl -fsSL --retry 3 -o "$2.part" "$1" && mv "$2.part" "$2"; }; }
fetch "https://github.com/Genymobile/scrcpy/releases/download/v${SCRCPY_VERSION}/scrcpy-win64-v${SCRCPY_VERSION}.zip" "$CACHE/scrcpy-win.zip"
fetch "https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/cpython-${PYTHON_VERSION}+${PBS_TAG}-x86_64-pc-windows-msvc-install_only_stripped.tar.gz" "$CACHE/python-win.tar.gz"
if ! ls "$CACHE"/wheels/*.whl >/dev/null 2>&1; then
    mkdir -p "$CACHE/wheels"
    python3 -m pip download --quiet --platform win_amd64 --python-version 3.13 --only-binary=:all: --no-deps -d "$CACHE/wheels" \
        "PySide6-Essentials==${PYSIDE_VERSION}" "PySide6-Addons==${PYSIDE_VERSION}" "shiboken6==${PYSIDE_VERSION}" \
        "PySide6-WebEngine==${WEBENGINE_VERSION}" "av==${PYAV_VERSION}"
fi

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/src/notrefu_mirror/__init__.py")"
NAME="notrefu-mirror-${VERSION}-windows"
D="$STAGE/$NAME"
rm -rf "$STAGE"; mkdir -p "$D/tools" "$D/app"
tar xzf "$CACHE/python-win.tar.gz" -C "$D"
SP="$D/python/Lib/site-packages"; mkdir -p "$SP"
for w in "$CACHE"/wheels/*.whl; do python3 -c "import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$w" "$SP"; done
t="$(mktemp -d)"; unzip -q "$CACHE/scrcpy-win.zip" -d "$t"
cp "$t"/scrcpy-win64-*/{adb.exe,scrcpy.exe,scrcpy-server} "$t"/scrcpy-win64-*/*.dll "$D/tools/"  # scrcpy.exe sert à lister les applications
cp "$t"/scrcpy-win64-*/LICENSE.txt "$D/tools/LICENSE-scrcpy.txt"; rm -rf "$t"
for f in adb.exe AdbWinApi.dll AdbWinUsbApi.dll libusb-1.0.dll scrcpy-server scrcpy.exe; do  # adb sans ses DLL = tablettes USB invisibles
    [ -s "$D/tools/$f" ] || { echo "!! $f manquant dans tools/ (archive scrcpy incomplète)" >&2; exit 1; }
done
cp -r "$ROOT/src/notrefu_mirror" "$D/app/"; find "$D/app" -name '__pycache__' -prune -exec rm -rf {} +
cp "$ROOT/packaging/NOTICE.txt" "$D/NOTICE.txt"
python3 "$ROOT/packaging/prune_windows.py" "$D"

# lanceur notrefu-mirror.exe (petit programme C compilé pour Windows avec zig : pip install ziglang)
L="$(mktemp -d)"; cp "$ROOT/packaging/launcher_windows.c" "$ROOT/packaging/notrefu_mirror.ico" "$L/"; echo '1 ICON "notrefu_mirror.ico"' > "$L/res.rc"
(cd "$L" && python3 -m ziglang cc -target x86_64-windows-gnu -O2 -Wl,--subsystem,windows -o notrefu-mirror.exe launcher_windows.c res.rc)
cp "$L/notrefu-mirror.exe" "$D/notrefu-mirror.exe"; rm -rf "$L"
# lanceur de diagnostic (console visible)
printf '@echo off\r\nset "NOTREFU_MIRROR_HOME=%%~dp0"\r\nset "PYTHONPATH=%%~dp0app"\r\nset PYTHONNOUSERSITE=1\r\nset PYTHONDONTWRITEBYTECODE=1\r\n"%%~dp0python\\python.exe" -m notrefu_mirror --check\r\necho.\r\npause\r\n' > "$D/Diagnostic.bat"
cp "$ROOT/packaging/LISEZMOI-windows.txt" "$D/LISEZMOI.txt"
sed -i 's/$/\r/' "$D/LISEZMOI.txt"
(cd "$STAGE" && rm -f "$OUT/$NAME-portable.zip" && zip -qr -9 "$OUT/$NAME-portable.zip" "$NAME")
ls -lh "$OUT/$NAME-portable.zip"
