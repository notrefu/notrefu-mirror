"""Assistant de diagnostic : vérifie les prérequis (adb, serveur scrcpy, son, téléphone) et explique quoi corriger."""

from __future__ import annotations

import os
import shutil
import sys

from . import adb, compat, report
from .wireless import device_state_hint

OK, WARN, BAD = "ok", "warn", "bad"


def _mask_line(line: str) -> str:
    """Numéro de série partiellement masqué dans la sortie brute (le rapport se copie et se partage)."""
    parts = line.split(None, 1)
    if len(parts) == 2 and not line.startswith(("List of", "*")):
        return f"{report.mask_serial(parts[0])} {parts[1]}"
    return line


def run_diagnostics() -> list[tuple[str, str, str]]:
    """Liste de (niveau, titre, détail/conseil)."""
    out: list[tuple[str, str, str]] = []
    path = adb.find_tool("adb")
    if path:
        try:
            ver = adb.run_adb(["version"], timeout=8).splitlines()[0]
        except adb.AdbError as exc:
            ver = f"erreur : {exc}"
        out.append((OK, "adb", f"{path}\n{ver}"))
    else:
        out.append((BAD, "adb", "introuvable. Utilise l'AppImage officielle ou installe android-tools."))
    if path and sys.platform == "win32":
        folder = os.path.dirname(path)
        missing = [n for n in ("AdbWinApi.dll", "AdbWinUsbApi.dll") if not os.path.isfile(os.path.join(folder, n))]
        out.append((BAD, "Pilotes adb embarqués", "fichier(s) manquant(s) à côté d'adb.exe : " + ", ".join(missing) +
                    ". Ré-extrais le zip complet de notrefu-mirror.") if missing else (OK, "Pilotes adb embarqués", "AdbWinApi.dll et AdbWinUsbApi.dll présents"))
    try:
        from . import engine

        if sys.platform == "win32":
            from av.codec.hwaccel import hwdevices_available

            avail = [d for d in engine.hw_devices() if d in set(hwdevices_available())]
            out.append((OK if avail and engine.HW_DECODE_ENABLED else WARN, "Décodage vidéo",
                        ("carte graphique : " + ", ".join(avail) if avail else "décodage logiciel (aucun décodeur GPU disponible)")
                        + ("" if engine.HW_DECODE_ENABLED else " — désactivé dans Réglages")))
    except Exception as exc:  # noqa: BLE001 - PyAV peut manquer : le diagnostic ne doit jamais planter
        out.append((WARN, "Décodage vidéo", f"état inconnu : {exc}"))
    srv = adb.server_path()
    out.append((OK, "Serveur scrcpy", srv) if srv else (BAD, "Serveur scrcpy", "scrcpy-server introuvable dans l'AppImage."))
    if sys.platform == "win32":
        out.append((OK, "Son", "lecteur audio Windows intégré (winmm)"))
    elif shutil.which("paplay") or shutil.which("pw-cat"):
        out.append((OK, "Son", "lecteur audio trouvé (" + (shutil.which("paplay") or shutil.which("pw-cat")) + ")"))
    else:
        out.append((WARN, "Son", "ni paplay ni pw-cat : pas de son. Installe pipewire-pulse / pulseaudio-utils."))
    if sys.platform == "win32":
        out.append((OK, "Pilote USB", "Si le téléphone n'apparaît pas par câble : installe le pilote USB du constructeur (Xiaomi : « Mi USB Driver », "
                                      "Samsung : « Samsung Android USB Driver ») ou le Google USB Driver. Samsung : désactive aussi le « Bloqueur automatique » "
                                      "(Paramètres → Sécurité et confidentialité). Inutile en Wi-Fi."))
    elif os.path.exists(adb.UDEV_RULE_PATH):
        try:
            current = "04e8" in open(adb.UDEV_RULE_PATH, encoding="utf-8", errors="replace").read()
        except OSError:
            current = True
        if current:
            out.append((OK, "Règles USB", "règle udev installée (constructeurs connus inclus, dont Samsung 04e8)"))
        else:
            out.append((WARN, "Règles USB", "ancienne règle udev (sans les constructeurs, dont Samsung) : menu Aide → Installer les règles USB pour la mettre à jour, "
                                            "puis rebranche le câble."))
    else:
        out.append((WARN, "Règles USB", "absente. Si le téléphone n'apparaît pas en USB : menu Aide → Installer les règles USB. Inutile en Wi-Fi."))
    if not path:
        return out
    raw, err = adb.raw_devices()
    lvl, summary = adb.analyze_adb_output(raw, err)
    if adb.EVENTS:
        summary += "\n" + "\n".join(adb.EVENTS[-6:])
    out.append((OK if lvl == "ok" else BAD if lvl == "bad" else WARN, "Serveur adb", summary))
    shown = "\n".join(_mask_line(line) for line in raw.strip().splitlines()) if raw.strip() else f"(aucune sortie){' — ' + err if err else ''}"
    out.append((OK if raw.strip() else WARN, "Sortie brute de « adb devices -l » (à copier-coller)", shown))
    if err:
        return out
    devs = adb.parse_devices(raw)
    if sys.platform.startswith("linux") and not any(d.state == "device" for d in devs):
        seen = adb.usb_vendors_seen()
        if seen:
            out.append((WARN, "USB branché", "constructeur(s) vu(s) sur le port USB : " + ", ".join(f"{n} ({v})" for v, n in seen)
                        + ". S'il n'apparaît pas dans adb : mode USB « Transfert de fichiers », débogage USB activé, règles USB à jour."))
    if not devs:
        out.append((BAD, "Téléphones", "aucun appareil. Active « Débogage USB » (Options développeur), branche le câble en mode transfert de fichiers."
                    + (" Samsung : désactive le « Bloqueur automatique » et installe le pilote « Samsung Android USB Driver »." if sys.platform == "win32" else "")))
    for d in devs:
        if d.state == "device":
            info = adb.device_info(d.serial)
            sdk = int(info.get("sdk") or 0)
            line = f"{info.get('model') or d.serial} · Android {info.get('android') or '?'} ({d.label})"
            lvl = OK
            if sdk and sdk < 30:
                lvl, line = WARN, line + "\nAndroid < 11 : le son ne peut pas être capturé."
            out.append((lvl, "Téléphone", line))
            tip = compat.brand_tip(info.get("manufacturer", ""), info.get("model", ""), sys.platform)
            if tip:
                out.append((OK, "Conseil pour ta marque", tip))
            ok_in, detail = adb.input_test(d.serial)
            if ok_in:
                out.append((OK, "Souris et clavier", "le téléphone accepte les touches et les clics envoyés par notrefu-mirror"))
            elif adb.input_blocked(detail):
                out.append((BAD, "Souris et clavier",
                            "le téléphone refuse les touches et les clics. " + (tip or (
                                "Sur Xiaomi / HyperOS : Paramètres → Paramètres supplémentaires → "
                                "Options pour les développeurs → active « Débogage USB (paramètres de sécurité) » (et « Installer via USB »). "
                                "Sur Oppo / Realme / OnePlus : « Désactiver la surveillance des autorisations ».")) +
                            " Puis débranche et rebranche le câble."))
            else:
                out.append((WARN, "Souris et clavier", f"test non concluant : {detail[:150]}"))
            try:
                users = adb.parse_users(adb.run_adb(["shell", "pm", "list", "users"], d.serial, timeout=8))
                if len(users) > 1:
                    out.append((OK, "Double application", "utilisateurs Android : " + ", ".join(f"{u}" for u, _ in users)))
            except adb.AdbError:
                pass
        else:
            label = d.label.replace(d.serial, report.mask_serial(d.serial))
            out.append((BAD, "Téléphone", f"{label}\n{device_state_hint(d.state) or 'État adb inattendu : ' + d.state}"))
    return out


def format_report(items: list[tuple[str, str, str]]) -> str:
    mark = {OK: "✔", WARN: "⚠", BAD: "✘"}
    return "\n\n".join(f"{mark[lvl]} {title}\n{detail}" for lvl, title, detail in items)
