import os
import tempfile
import unittest
from pathlib import Path

from daw_project_cleaner.normalization_validation import validate_normalization_pair
from tests.helpers import make_project


class NormalizationValidationTests(unittest.TestCase):
    def test_valid_pair_builds_hashed_plan_but_awaits_daw_confirmation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Audio").mkdir()
            (root / "Audio" / "active.wav").write_bytes(b"active")
            (root / "Audio" / "unused.wav").write_bytes(b"unused")
            make_project(root / "CONTROL.npr", active=["active.wav"], unused=["unused.wav"])
            make_project(root / "CLEANED.npr", active=["active.wav"])

            report = validate_normalization_pair(
                root / "CONTROL.npr", root / "CLEANED.npr", root
            )

            self.assertTrue(report["summary"]["structural_valid"])
            self.assertFalse(report["summary"]["cleanup_authorized"])
            self.assertFalse(report["summary"]["final_gate_passed"])
            self.assertEqual(report["summary"]["candidate_files"], 1)
            self.assertEqual(report["candidates"][0]["name"], "unused.wav")
            self.assertEqual(
                report["stages"][4]["status"], "awaiting_operator"
            )

            confirmed = validate_normalization_pair(
                root / "CONTROL.npr", root / "CLEANED.npr", root,
                daw_open_confirmed=True,
            )
            self.assertTrue(confirmed["summary"]["final_gate_passed"])
            self.assertFalse(confirmed["summary"]["cleanup_authorized"])
            self.assertEqual(
                confirmed["summary"]["project_artifacts_to_quarantine"], 1
            )

    def test_removed_active_reference_blocks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Audio").mkdir()
            (root / "Audio" / "active.wav").write_bytes(b"active")
            make_project(root / "CONTROL.npr", active=["active.wav"])
            make_project(root / "CLEANED.npr", active=[])

            report = validate_normalization_pair(
                root / "CONTROL.npr", root / "CLEANED.npr", root
            )

            self.assertFalse(report["summary"]["structural_valid"])
            self.assertIn(
                "active_reference_removed",
                {item["kind"] for item in report["blockers"]},
            )

    def test_cleaned_survivor_is_excluded_by_filesystem_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Audio").mkdir()
            (root / "Audio" / "active.wav").write_bytes(b"active")
            (root / "Audio" / "unused.wav").write_bytes(b"unused")
            make_project(
                root / "CONTROL.npr",
                active=["active.wav"], unused=["unused.wav"],
            )
            make_project(root / "CLEANED.npr", active=["active.wav"])
            # A second spelling of the same inode models APFS returning a
            # Unicode-normalized directory entry that is not Path-equal to the
            # spelling supplied by the caller.
            os.link(root / "CLEANED.npr", root / "CLEANED-alias.npr")

            report = validate_normalization_pair(
                root / "CONTROL.npr", root / "CLEANED.npr", root,
                daw_open_confirmed=True,
            )

            artifacts = {
                Path(item["path"]).name
                for item in report["project_artifacts_to_quarantine"]
            }
            self.assertEqual(artifacts, {"CONTROL.npr"})

    def test_unicode_normalized_media_name_passes_final_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Audio").mkdir()
            # Disk entry is NFD while the project reference is NFC.
            (root / "Audio" / "A\u0308ike.wav").write_bytes(b"active")
            (root / "Audio" / "unused.wav").write_bytes(b"unused")
            make_project(
                root / "CONTROL.npr",
                active=["Äike.wav"], unused=["unused.wav"],
            )
            make_project(root / "CLEANED.npr", active=["Äike.wav"])

            report = validate_normalization_pair(
                root / "CONTROL.npr", root / "CLEANED.npr", root,
                daw_open_confirmed=True,
            )

            self.assertEqual(report["blockers"], [])
            self.assertTrue(report["summary"]["final_gate_passed"])

    def test_embedded_path_resolves_active_duplicate_basename(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Audio").mkdir()
            (root / "Edits").mkdir()
            (root / "Audio" / "same.wav").write_bytes(b"audio")
            (root / "Edits" / "same.wav").write_bytes(b"edit")
            (root / "Audio" / "unused.wav").write_bytes(b"unused")
            make_project(
                root / "CONTROL.npr", active=["same.wav"],
                unused=["unused.wav"], active_paths=["/old/project/Edits/"],
            )
            make_project(
                root / "CLEANED.npr", active=["same.wav"],
                active_paths=["/old/project/Edits/"],
            )

            report = validate_normalization_pair(
                root / "CONTROL.npr", root / "CLEANED.npr", root,
                daw_open_confirmed=True,
            )

            self.assertEqual(report["blockers"], [])
            self.assertTrue(report["summary"]["final_gate_passed"])
            self.assertEqual(report["summary"]["active_files"], 1)
            self.assertEqual(
                Path(report["active_media_files"][0]["path"]),
                (root / "Edits" / "same.wav").resolve(),
            )


if __name__ == "__main__":
    unittest.main()
