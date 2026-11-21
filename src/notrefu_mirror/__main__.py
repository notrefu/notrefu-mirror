import sys

from . import APP_NAME, __version__

USAGE = f"""{APP_NAME} {__version__}
  (sans option)          ouvre l'application
  --check                auto-diagnostic (outils, téléphones vus par adb)
  --icon-debug PAQUET    diagnostic des icônes d'une application du téléphone (ex. com.ankama.dofustouch)
  --users-debug          liste les utilisateurs du téléphone et les doubles applications (clones au même nom de paquet)
  --version
"""


def check() -> int:
    """Auto-diagnostic : `notrefu-mirror.AppImage --check`."""
    from . import adb

    print(f"{APP_NAME} {__version__}")
    ok = True
    path = adb.find_tool("adb")
    print(f"{'adb':8} {path or 'INTROUVABLE'}")
    ok &= bool(path)
    srv = adb.server_path()
    print(f"{'server':8} {srv or 'INTROUVABLE'}")
    ok &= bool(srv)
    try:
        import av

        print(f"{'decodeur':8} PyAV {av.__version__}")
    except ImportError as exc:
        print(f"decodeur INTROUVABLE ({exc})")
        ok = False
    try:
        devs = adb.list_devices()
        print(f"adb OK, {len(devs)} appareil(s) :")
        for d in devs:
            print(f"  - {d.label} [{d.serial}]")
    except adb.AdbError as exc:
        print(f"adb : {exc}")
        ok = False
    return 0 if ok else 1


def main() -> int:
    from . import winfix

    winfix.apply()
    args = sys.argv[1:]
    if "--version" in args:
        print(f"{APP_NAME} {__version__}")
        return 0
    if "--help" in args or "-h" in args:
        print(USAGE)
        return 0
    if "--icon-debug" in args:
        from . import adb

        i = args.index("--icon-debug")
        if i + 1 >= len(args):
            print(USAGE)
            return 2
        devs = [d for d in adb.list_devices() if d.state == "device"]
        if not devs:
            print("Aucun téléphone autorisé détecté.")
            return 1
        print(adb.icon_debug(devs[0].serial, args[i + 1]))
        return 0
    if "--users-debug" in args:
        from . import adb

        devs = [d for d in adb.list_devices() if d.state == "device"]
        if not devs:
            print("Aucun téléphone autorisé détecté.")
            return 1
        ser = devs[0].serial
        print("pm list users :")
        try:
            print(adb.run_adb(["shell", "pm", "list", "users"], ser))
        except adb.AdbError as exc:
            print(f"ERREUR : {exc}")
        for uid, name in adb.parse_users(adb.run_adb(["shell", "pm", "list", "users"], ser)):
            print(f"--- applications tierces de l'utilisateur {uid} ({name}) ---")
            try:
                print(adb.run_adb(["shell", "pm", "list", "packages", "-3", "--user", str(uid)], ser))
            except adb.AdbError as exc:
                print(f"ERREUR : {exc}")
        print("--- entrées de la liste notrefu-mirror ---")
        for name, pkg in adb.list_apps(ser):
            if "dofus" in name.lower() or "dofus" in pkg.lower():
                print(f"{name}  ->  {pkg}")
        return 0
    if "--check" in args:
        return check()
    from .ui import run

    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
