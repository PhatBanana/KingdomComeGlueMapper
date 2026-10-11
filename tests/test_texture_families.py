"""The indexed DDS family lookup must select exactly what the old per-texture scan did."""
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from audit_maps import texture_families


def scanned(index, texture):
    """The previous linear scan, kept as the reference behaviour."""
    found = []
    for member in index:
        suffix = member[len(texture):] if member.startswith(texture) else "INVALID"
        if suffix == "" or re.fullmatch(r"\.(?:a|[0-9]+a?)", suffix):
            found.append((member, suffix))
    return found


class TextureFamilyTests(unittest.TestCase):
    def test_matches_linear_scan_in_index_order(self):
        index = dict.fromkeys([
            "objects/tree/bark.dds.2", "objects/tree/bark.dds", "objects/tree/bark.dds.a",
            "objects/tree/bark.dds.1a", "objects/tree/bark.dds.10", "objects/tree/bark.dds.mtl",
            "objects/tree/bark.ddsa", "objects/tree/bark_ddna.dds", "objects/tree/bark_ddna.dds.1",
            "objects/tree/bark.dds.dds", "objects/tree/bark.dds.1b", "objects/tree/bark.mtl",
            "objects/tree/bark2.dds", "textures/a.dds.dds.1", "textures/a.dds.dds",
            "%level%/textures/a.dds", "%level%/textures/a.dds.3a"])
        families = texture_families(index)
        for texture in [n for n in index if n.endswith(".dds")]:
            self.assertEqual(families.get(texture, []), scanned(index, texture), texture)
        self.assertEqual([m for m, _ in families["objects/tree/bark.dds"]],
                         ["objects/tree/bark.dds.2", "objects/tree/bark.dds", "objects/tree/bark.dds.a",
                          "objects/tree/bark.dds.1a", "objects/tree/bark.dds.10"])
        self.assertNotIn("objects/tree/bark.mtl", families)


if __name__ == "__main__":
    unittest.main()
