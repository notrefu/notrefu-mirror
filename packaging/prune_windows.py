"""Allège le dossier portable Windows (Qt) et vérifie que chaque DLL embarquée trouve ses dépendances.
Usage : prune_windows.py <dossier notrefu-mirror>"""
import os
import re
import shutil
import sys
from pathlib import Path

import pefile

root = Path(sys.argv[1])
ps = root / "python/Lib/site-packages/PySide6"
KEEP_PYD = {"QtCore", "QtGui", "QtWidgets", "QtSvg", "QtNetwork", "QtWebChannel", "QtPositioning", "QtPrintSupport",
            "QtOpenGL", "QtQml", "QtQuick", "QtQuickWidgets", "QtWebEngineCore", "QtWebEngineWidgets"}
size0 = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())

for f in list(ps.glob("*.pyd")):
    if f.name.split(".")[0] not in KEEP_PYD:
        f.unlink()
for d in ("include", "glue", "typesystems", "scripts", "examples", "support", "qml", "metatypes", "modules"):
    shutil.rmtree(ps / d, ignore_errors=True)
    shutil.rmtree(ps / "Qt" / d, ignore_errors=True)
for pat in ("*.pyi", "py.typed", "pyside6-*", "designer.exe", "uic.exe", "rcc.exe", "lupdate.exe", "lrelease.exe",
            "assistant.exe", "linguist.exe", "qmllint.exe", "qmlformat.exe", "qmlls.exe", "qsb.exe", "svgtoqml.exe",
            "balsam.exe", "balsamui.exe", "qmlimportscanner.exe"):
    for f in ps.glob(pat):
        f.unlink()
tr = ps / "translations"
if tr.is_dir():
    for f in tr.glob("*"):
        if f.is_file():
            f.unlink()
    loc = tr / "qtwebengine_locales"
    if loc.is_dir():
        for f in loc.iterdir():
            if f.name not in ("en-US.pak", "en-GB.pak", "fr.pak"):
                f.unlink()
for f in ps.glob("*.exe"):  # outils de développement Qt : seul le processus de rendu web sert
    if f.name != "QtWebEngineProcess.exe":
        f.unlink()
for f in (ps / "plugins/imageformats").glob("qpdf.dll"):
    f.unlink()
for f in (ps / "resources").glob("qtwebengine_devtools_resources.pak"):
    f.unlink()
for d in ("designer", "qmltooling", "sqldrivers", "tls", "networkinformation", "vectorimageformats", "assetimporters",
          "canbus", "geometryloaders", "geoservices", "multimedia", "position", "renderers", "renderplugins",
          "sceneparsers", "scxmldatamodel", "sensors", "texttospeech", "webview", "platforminputcontexts"):
    shutil.rmtree(ps / "plugins" / d, ignore_errors=True)
for f in (ps / "plugins/platforms").glob("*.dll"):
    if f.name not in ("qwindows.dll", "qminimal.dll", "qoffscreen.dll"):
        f.unlink()
sp = root / "python/Lib/site-packages"
for d in ("pip", "setuptools", "pkg_resources", "wheel", "_distutils_hack"):
    shutil.rmtree(sp / d, ignore_errors=True)
for d in sp.glob("pip-*"):
    shutil.rmtree(d, ignore_errors=True)
pylib = root / "python/Lib"
for d in ("test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3", "pydoc_data"):
    shutil.rmtree(pylib / d, ignore_errors=True)
shutil.rmtree(root / "python/tcl", ignore_errors=True)
for f in (root / "python/DLLs").glob("*"):
    if re.match(r"(_tkinter|tcl|tk|_test|_ctypes_test|xxlimited)", f.name):
        f.unlink()


def imports(path: Path) -> list[str]:
    pe = pefile.PE(str(path), fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
    return [e.dll.decode().lower() for e in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])]


# fermeture des Qt6*.dll nécessaires, puis suppression des autres
files = [f for f in root.rglob("*") if f.suffix.lower() in (".dll", ".pyd", ".exe") and f.is_file()]
index = {}
for f in files:
    index.setdefault(f.name.lower(), f)
need = set()
todo = [f for f in files if f.suffix.lower() == ".pyd" or f.name.lower() in ("python.exe", "pythonw.exe", "qtwebengineprocess.exe")
        or f.name.lower() in ("qwindows.dll", "adb.exe")]
todo += [index[n] for n in ("qt6core.dll", "qt6gui.dll", "qt6widgets.dll", "qt6webenginecore.dll", "qt6webenginewidgets.dll") if n in index]
need |= {f.name.lower() for f in todo}
seen = set()
while todo:
    f = todo.pop()
    if f in seen:
        continue
    seen.add(f)
    for dep in imports(f):
        if dep in index and index[dep] not in seen:
            need.add(dep)
            todo.append(index[dep])
for plug in (ps / "plugins").rglob("*.dll"):
    for dep in imports(plug):
        if dep in index and index[dep] not in seen:
            need.add(dep)
            todo.append(index[dep])
    seen.add(plug)
while todo:
    f = todo.pop()
    if f in seen:
        continue
    seen.add(f)
    for dep in imports(f):
        if dep in index:
            need.add(dep)
            todo.append(index[dep])
for f in ps.glob("Qt6*.dll"):
    if f.name.lower() not in need and not f.name.lower().startswith(("qt6core", "qt6gui", "qt6widgets", "qt6svg")):
        f.unlink()

# vérification : toute dépendance non système doit exister dans le dossier
SYSTEM = re.compile(r"^(avicap32|bthprops|fontsub|mscms|icuuc|icu|winusb|api-ms-|ext-ms-|kernel32|user32|gdi32|advapi32|shell32|ole32|oleaut32|ws2_32|winmm|ntdll|msvcrt|"
                    r"comctl32|comdlg32|shlwapi|version|imm32|dwmapi|uxtheme|d3d|dxgi|dxcore|opengl32|glu32|crypt32|"
                    r"secur32|bcrypt|ncrypt|iphlpapi|netapi32|userenv|wtsapi32|setupapi|winspool|rpcrt4|powrprof|"
                    r"psapi|dbghelp|shcore|cfgmgr32|wintrust|mpr|dnsapi|normaliz|wldap32|nsi|hid|winhttp|wininet|"
                    r"mswsock|oleacc|propsys|d2d1|dwrite|windowscodecs|dcomp|usp10|msimg32|uiautomationcore|"
                    r"authz|wevtapi|cabinet|mfplat|avrt|mmdevapi|ucrtbase|vcruntime|msvcp|vcomp|concrt|python3|"
                    r"d3dcompiler|libusb|dinput|xinput|gdiplus|dbgcore|ncryptsslp|sspicli|cryptbase|bcryptprimitives|"
                    r"wbemuuid|netapi|ntmarta|imagehlp|sensapi|wlanapi|dhcpcsvc|rtworkq|mf|evr|ksuser|dsound|msacm32|"
                    r"gdi32full|win32u|combase|kernelbase|urlmon|sxs|tbs|userenv|dpapi|apphelp|pdh|shlwapi|ndfapi)", re.I)
local = {f.name.lower() for f in root.rglob("*") if f.is_file()}
missing = {}
for f in root.rglob("*"):
    if f.is_file() and f.suffix.lower() in (".dll", ".pyd", ".exe"):
        try:
            for dep in imports(f):
                if dep not in local and not SYSTEM.match(dep):
                    missing.setdefault(dep, set()).add(f.name)
        except pefile.PEFormatError:
            pass
for dep, who in sorted(missing.items()):
    print(f"!! dépendance introuvable : {dep}  (utilisée par {', '.join(sorted(who))[:120]})")
size1 = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
print(f"allègement : {size0 / 1e6:.0f} Mo -> {size1 / 1e6:.0f} Mo ; dépendances manquantes : {len(missing)}")
sys.exit(1 if missing else 0)
