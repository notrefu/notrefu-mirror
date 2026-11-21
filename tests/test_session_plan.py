import unittest
from notrefu_mirror.session_plan import DisplayRequest, plan_display


def req(**k):
    base = dict(mode="horizontal", width=1920, height=1080, dpi=320, shape="16:9", area_w=1200, area_h=700,
                native=False, pixel_ratio=1.0, zoom_percent=100)
    base.update(k)
    return DisplayRequest(**base)


class PlanDisplay(unittest.TestCase):
    def test_phone_mode(self):
        p = plan_display(req(mode="phone", width=1280, height=720))
        self.assertEqual((p.new_display, p.max_size, p.ratio), ("", 1280, None))

    def test_fixed_shape(self):
        p = plan_display(req())
        self.assertEqual(p.new_display, "1920x1080/320")
        self.assertAlmostEqual(p.ratio, 1920 / 1080)

    def test_auto_follows_area_and_clamps(self):
        p = plan_display(req(shape="auto", area_w=3000, area_h=500))
        self.assertAlmostEqual(p.ratio, 1920 / (1920 // 2.4 // 8 * 8), places=1)
        self.assertTrue(p.new_display.startswith("1920x"))

    def test_native_shrinks_and_scales_dpi(self):
        p = plan_display(req(native=True, area_w=960, area_h=540))
        self.assertTrue(p.new_display.startswith("960x"))
        self.assertEqual(p.new_display.split("/")[1], "160")

    def test_zoom_and_dpi_clamp(self):
        self.assertTrue(plan_display(req(zoom_percent=400)).new_display.endswith("/640"))
        self.assertTrue(plan_display(req(zoom_percent=10)).new_display.endswith("/120"))


if __name__ == "__main__":
    unittest.main()
