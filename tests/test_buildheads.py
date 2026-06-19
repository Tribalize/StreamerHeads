import importlib.util
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "buildheads.py"


def load_buildheads():
    spec = importlib.util.spec_from_file_location("buildheads_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BuildHeadsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.buildheads = load_buildheads()

    def test_loads_heads_from_comma_separated_input(self):
        heads = self.buildheads.heads_from_names("Grian, MumboJumbo, GeminiTay")

        self.assertEqual(list(heads), ["Grian", "MumboJumbo", "GeminiTay"])
        self.assertEqual(heads["Grian"], {"model": None})

    def test_loads_heads_from_json_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            heads_file = Path(tmp) / "heads.json"
            heads_file.write_text(
                json.dumps(
                    {
                        "heads": [
                            "Grian",
                            {"name": "GoodTimeWithScar", "model": "head"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            heads = self.buildheads.load_heads_file(str(heads_file))

        self.assertEqual(heads["Grian"], {"model": None})
        self.assertEqual(heads["GoodTimeWithScar"], {"model": "head"})

    def test_manifests_link_behavior_and_resource_packs(self):
        bp_manifest = self.buildheads.build_bp_manifest()
        rp_manifest = self.buildheads.build_rp_manifest()

        self.assertEqual(rp_manifest["header"]["name"], "StreamerheadsResources")
        self.assertIn("pbr", rp_manifest["capabilities"])
        self.assertTrue(
            any(
                dep.get("uuid") == rp_manifest["header"]["uuid"]
                for dep in bp_manifest["dependencies"]
            )
        )
        self.assertTrue(
            any(
                dep.get("uuid") == bp_manifest["header"]["uuid"]
                for dep in rp_manifest["dependencies"]
            )
        )

    def test_mcaddon_uses_resource_folder_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bp_dir = tmp_path / "BPH_BP"
            rp_dir = tmp_path / "BPH_RP"
            bp_dir.mkdir()
            rp_dir.mkdir()
            (bp_dir / "manifest.json").write_text("{}", encoding="utf-8")
            (rp_dir / "manifest.json").write_text("{}", encoding="utf-8")

            old_bp_dir = self.buildheads.BP_DIR
            old_rp_dir = self.buildheads.RP_DIR
            try:
                self.buildheads.BP_DIR = str(bp_dir)
                self.buildheads.RP_DIR = str(rp_dir)
                output = tmp_path / "test.mcaddon"
                self.buildheads.build_mcaddon(str(output))
            finally:
                self.buildheads.BP_DIR = old_bp_dir
                self.buildheads.RP_DIR = old_rp_dir

            with zipfile.ZipFile(output) as zf:
                names = zf.namelist()

        self.assertIn("StreamerHeads_BP/manifest.json", names)
        self.assertIn("StreamerheadsResources/manifest.json", names)
        self.assertFalse(any(name.startswith("behavior_packs/") for name in names))
        self.assertFalse(any(name.startswith("resource_packs/") for name in names))

    def test_missing_texture_check_reports_block_and_item_pngs(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_rp_dir = self.buildheads.RP_DIR
            try:
                self.buildheads.RP_DIR = str(Path(tmp) / "BPH_RP")
                missing = self.buildheads.missing_texture_paths(["Grian"])
            finally:
                self.buildheads.RP_DIR = old_rp_dir

        self.assertEqual(len(missing), 2)
        self.assertTrue(any("textures/blocks/skulls/grian.png" in path.replace("\\", "/") for path in missing))
        self.assertTrue(any("textures/items/skulls/grian.png" in path.replace("\\", "/") for path in missing))


if __name__ == "__main__":
    unittest.main()
