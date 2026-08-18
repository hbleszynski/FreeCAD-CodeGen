import unittest

from freecad_agent.gui import _asset_path, _opposite_color


class GUIThemeTests(unittest.TestCase):
    def test_flips_black_and_white_colors(self):
        self.assertEqual(_opposite_color("white"), "black")
        self.assertEqual(_opposite_color("#FFFFFF"), "black")
        self.assertEqual(_opposite_color("black"), "white")
        self.assertEqual(_opposite_color("#000000"), "white")

    def test_leaves_non_theme_colors_unchanged(self):
        self.assertIsNone(_opposite_color("SystemButtonFace"))

    def test_app_icon_asset_is_available(self):
        self.assertTrue(_asset_path("freecad-agent.png").is_file())


if __name__ == "__main__":
    unittest.main()
