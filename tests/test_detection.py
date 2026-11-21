"""Détection des appareils : états adb, bandeau d'aide, règle udev, diagnostic."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from notrefu_mirror import adb, diag  # noqa: E402
from notrefu_mirror.wireless import SAMSUNG_WINDOWS_TIP, devices_banner  # noqa: E402

RAW = (
    "List of devices attached\n"
    "R9TX1234ABC\tunauthorized usb:1-2 transport_id:3\n"
    "????????????\tno permissions (user in plugdev group; are your udev rules wrong?); see [http://developer.android.com/tools/device.html]\n"
    "R58M12\toffline transport_id:1\n"
    "R58M13\tauthorizing\n"
    "192.168.1.5:5555\tdevice product:a52 model:SM_A525F device:a52q transport_id:4\n"
)


class Parsing(unittest.TestCase):
    def test_every_adb_state_is_listed(self):
        devs = adb.parse_devices(RAW)
        self.assertEqual([d.state for d in devs], ["unauthorized", "no permissions", "offline", "authorizing", "device"])
        self.assertTrue(devs[-1].wireless)

    def test_tablet_model_kept(self):
        d = adb.parse_devices("List of devices attached\nR9\tdevice usb:1 product:gta9pwifi model:SM_X210 device:gta9pwifi transport_id:2\n")[0]
        self.assertEqual(d.model, "SM_X210")


class Banner(unittest.TestCase):
    def test_unauthorized_is_not_reported_as_missing(self):
        t = devices_banner(["unauthorized"], "", "linux")
        self.assertIn("non autorisé", t)
        self.assertNotIn("Aucun téléphone détecté", t)

    def test_offline_and_no_permissions(self):
        self.assertIn("hors ligne", devices_banner(["offline"], "", "win32"))
        self.assertIn("règles USB", devices_banner(["no permissions"], "", "linux"))

    def test_ready_device_means_no_banner(self):
        self.assertEqual(devices_banner(["unauthorized", "device"], "", "linux"), "")

    def test_windows_samsung_tip_only_when_nothing_found(self):
        t = devices_banner([], "", "win32")
        self.assertIn("Aucun téléphone détecté", t)
        self.assertIn(SAMSUNG_WINDOWS_TIP, t)
        self.assertIn("Bloqueur automatique", t)
        self.assertNotIn("Bloqueur", devices_banner(["unauthorized"], "", "win32"))

    def test_linux_points_to_udev(self):
        self.assertIn("Installer les règles USB", devices_banner([], "", "linux"))
        self.assertNotIn("Bloqueur", devices_banner([], "", "linux"))

    def test_adb_error(self):
        self.assertIn("boom", devices_banner([], "boom", "linux"))


class Udev(unittest.TestCase):
    def test_samsung_and_major_vendors(self):
        for vid in ("04e8", "18d1", "2717", "22b8", "12d1", "2a70", "22d9", "2d95", "0fce", "1004", "0b05", "17ef", "1949"):
            self.assertIn(f'ATTR{{idVendor}}=="{vid}"', adb.UDEV_RULE, vid)
        self.assertIn("ff4201", adb.UDEV_RULE)

    def test_every_vendor_line_is_valid(self):
        for line in adb.UDEV_RULE.splitlines():
            if line.startswith("#"):
                continue
            self.assertTrue(line.startswith('SUBSYSTEM=="usb"'), line)
            self.assertIn('TAG+="uaccess"', line)


class Analyze(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(adb.analyze_adb_output("List of devices attached\nA\tdevice\n")[0], "ok")
        self.assertEqual(adb.analyze_adb_output("List of devices attached\n")[0], "warn")
        lvl, txt = adb.analyze_adb_output("List of devices attached\nA\tunauthorized\n")
        self.assertEqual(lvl, "warn")
        self.assertIn("Non autorisé", txt)
        self.assertEqual(adb.analyze_adb_output("", "adb : délai dépassé après 12 s")[0], "bad")
        self.assertEqual(adb.analyze_adb_output("", "cannot connect to daemon at tcp:5037")[0], "bad")
        self.assertIn("vient d'être démarré",
                      adb.analyze_adb_output("* daemon not running; starting now at tcp:5037\n* daemon started successfully\nList of devices attached\n")[1])


class Diagnostic(unittest.TestCase):
    def test_raw_output_and_server_status_are_shown(self):
        with mock.patch.object(adb, "find_tool", return_value="/x/adb"), \
             mock.patch.object(adb, "server_path", return_value="/x/server"), \
             mock.patch.object(adb, "run_adb", return_value="Android Debug Bridge version 1.0.41"), \
             mock.patch.object(adb, "raw_devices", return_value=("List of devices attached\nR9TX1234ABC\tunauthorized usb:1-2\n", "")):
            items = diag.run_diagnostics()
        titles = [t for _l, t, _d in items]
        self.assertIn("Serveur adb", titles)
        raw = next(d for _l, t, d in items if t.startswith("Sortie brute"))
        self.assertIn("unauthorized usb:1-2", raw)
        self.assertNotIn("R9TX1234ABC", raw)  # numéro de série masqué
        phone = next(d for _l, t, d in items if t == "Téléphone")
        self.assertIn("non autorisé", phone)

    def test_adb_failure(self):
        with mock.patch.object(adb, "find_tool", return_value="/x/adb"), \
             mock.patch.object(adb, "server_path", return_value="/x/server"), \
             mock.patch.object(adb, "run_adb", return_value="v"), \
             mock.patch.object(adb, "raw_devices", return_value=("", "adb : délai dépassé après 12 s")):
            items = diag.run_diagnostics()
        lvl, _t, d = next(i for i in items if i[1] == "Serveur adb")
        self.assertEqual(lvl, diag.BAD)


if __name__ == "__main__":
    unittest.main()
