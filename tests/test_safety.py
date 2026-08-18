import unittest

from freecad_agent.safety import UnsafeCodeError, validate_code


class SafetyTests(unittest.TestCase):
    def test_accepts_normal_freecad_code(self):
        validate_code(
            "import FreeCAD as App\nimport Part\ndoc = App.newDocument('Box')\n"
            "obj = doc.addObject('Part::Box', 'Box')\ndoc.recompute()\n"
        )

    def test_rejects_system_import(self):
        with self.assertRaises(UnsafeCodeError):
            validate_code("import subprocess\nsubprocess.run(['thing'])\n")

    def test_rejects_file_access(self):
        with self.assertRaises(UnsafeCodeError):
            validate_code("open('secret.txt').read()\n")

    def test_accepts_part_design_and_a2plus(self):
        validate_code(
            "import FreeCAD as App\nimport PartDesign\nimport a2p_importpart\n"
            "body = App.ActiveDocument.addObject('PartDesign::Body', 'Body')\n"
        )


if __name__ == "__main__":
    unittest.main()
