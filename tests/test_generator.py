import unittest

from pathlib import Path

from freecad_agent.generator import _clean_code, _normalize_images


class GeneratorTests(unittest.TestCase):
    def test_removes_markdown_fence(self):
        self.assertEqual(_clean_code("```python\nimport Part\n```"), "import Part\n")

    def test_rejects_empty_output(self):
        with self.assertRaises(ValueError):
            _clean_code("  ")

    def test_normalizes_multiple_images(self):
        images = [Path("one.png"), Path("two.png")]
        self.assertEqual(_normalize_images(images), images)

    def test_normalizes_legacy_single_image(self):
        image = Path("one.png")
        self.assertEqual(_normalize_images(image), [image])


if __name__ == "__main__":
    unittest.main()
