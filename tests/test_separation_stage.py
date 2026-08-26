import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daw_project_cleaner.archive_audit import audit_archive
from daw_project_cleaner.separation_plan import build_separation_plan
from daw_project_cleaner.separation_stage import stage_separation_copy
from tests.helpers import make_project


class SeparationStageTests(unittest.TestCase):
    def _plan(self, temporary):
        root = Path(temporary) / "Mother"
        audio = root / "Audio"
        audio.mkdir(parents=True)
        (audio / "shared.wav").write_bytes(b"shared")
        (audio / "one.wav").write_bytes(b"one")
        make_project(root / "One.cpr", active=["shared.wav", "one.wav"])
        return root, build_separation_plan(
            audit_archive(root), Path(temporary) / "Separated"
        )

    def test_copy_rehearsal_is_hash_verified_and_leaves_mother_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, plan = self._plan(temporary)
            before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}

            destination = stage_separation_copy(plan)

            self.assertTrue((destination / "One" / "One.cpr").is_file())
            self.assertEqual((destination / "One" / "Audio" / "shared.wav").read_bytes(), b"shared")
            state = json.loads((destination / ".separation-rehearsal.json").read_text())
            self.assertEqual(state["status"], "verified_awaiting_daw_validation")
            self.assertFalse(state["mother_folder_modified"])
            self.assertFalse(state["cleanup_authorized"])
            self.assertEqual(before, {path: path.read_bytes() for path in root.rglob("*") if path.is_file()})

    def test_blocked_project_is_refused_before_destination_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Mother"
            root.mkdir()
            make_project(root / "Broken.cpr", active=["missing.wav"])
            destination = Path(temporary) / "Separated"
            plan = build_separation_plan(audit_archive(root), destination)

            with self.assertRaisesRegex(ValueError, "Blocked projects"):
                stage_separation_copy(plan)
            self.assertFalse(destination.exists())

    def test_interruption_removes_only_generated_staging_and_keeps_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, plan = self._plan(temporary)
            original = (root / "Audio" / "shared.wav").read_bytes()
            from daw_project_cleaner import separation_stage
            real_copy = separation_stage.shutil.copy2
            calls = {"count": 0}

            def interrupted(*args, **kwargs):
                calls["count"] += 1
                if calls["count"] == 2:
                    raise OSError("simulated interruption")
                return real_copy(*args, **kwargs)

            with patch.object(separation_stage.shutil, "copy2", side_effect=interrupted):
                with self.assertRaisesRegex(OSError, "simulated interruption"):
                    stage_separation_copy(plan)

            self.assertEqual((root / "Audio" / "shared.wav").read_bytes(), original)
            self.assertFalse(Path(plan["destination_root"]).exists())
            self.assertEqual(list(Path(temporary).glob(".daw-project-cleaner-separation-*")), [])


if __name__ == "__main__":
    unittest.main()
