import tempfile
import unittest
from pathlib import Path

from daw_project_cleaner.archive_audit import audit_archive
from daw_project_cleaner.separation_plan import build_separation_plan
from tests.helpers import make_project


class SeparationPlanTests(unittest.TestCase):
    def test_shared_media_is_planned_for_each_child_without_authorizing_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Mother"
            audio = root / "Audio"
            audio.mkdir(parents=True)
            (audio / "shared.wav").write_bytes(b"shared")
            (audio / "one.wav").write_bytes(b"one")
            (audio / "two.wav").write_bytes(b"two")
            make_project(root / "One.cpr", active=["shared.wav", "one.wav"])
            make_project(root / "Two.cpr", active=["shared.wav", "two.wav"])

            plan = build_separation_plan(audit_archive(root), root.parent / "Separated")

            self.assertEqual(plan["summary"]["projects"], 2)
            self.assertEqual(plan["summary"]["copy_manifest_ready"], 2)
            self.assertGreater(plan["summary"]["shared_media_duplication_bytes"], 0)
            self.assertFalse(plan["safety"]["copy_execution_enabled"])
            for project in plan["projects"]:
                destinations = {item["destination_relative"] for item in project["media"]}
                self.assertIn("Audio/shared.wav", destinations)

    def test_missing_reference_blocks_only_the_affected_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Mother"
            (root / "Audio").mkdir(parents=True)
            (root / "Audio" / "ok.wav").write_bytes(b"ok")
            make_project(root / "Good.cpr", active=["ok.wav"])
            make_project(root / "Broken.cpr", active=["missing.wav"])

            plan = build_separation_plan(audit_archive(root), root.parent / "Separated")
            by_name = {Path(item["project"]).name: item for item in plan["projects"]}

            self.assertTrue(by_name["Good.cpr"]["copy_manifest_ready"])
            self.assertFalse(by_name["Broken.cpr"]["copy_manifest_ready"])
            self.assertEqual(plan["summary"]["blocked"], 1)

    def test_exact_name_external_file_resolves_missing_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "Mother"
            root.mkdir()
            make_project(root / "Song.cpr", active=["Äike.mp3"])
            found = base / "Other" / "A\u0308ike.mp3"
            found.parent.mkdir()
            found.write_bytes(b"exact external media")

            plan = build_separation_plan(
                audit_archive(root), root.parent / "Separated",
                missing_media_files=[found],
            )

            manifest = plan["projects"][0]
            self.assertTrue(manifest["copy_manifest_ready"])
            self.assertEqual(manifest["media_files"], 1)
            self.assertEqual(manifest["media"][0]["destination_relative"], "Audio/A\u0308ike.mp3")
            self.assertTrue(manifest["media"][0]["external_exact_name_resolution"])

    def test_external_file_with_unmatched_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "Mother"
            root.mkdir()
            make_project(root / "Song.cpr", active=["missing.mp3"])
            wrong = base / "wrong.mp3"
            wrong.write_bytes(b"wrong")

            with self.assertRaisesRegex(ValueError, "does not match"):
                build_separation_plan(
                    audit_archive(root), root.parent / "Separated",
                    missing_media_files=[wrong],
                )

    def test_master_without_supported_references_can_never_be_retired(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Mother"
            (root / "Audio").mkdir(parents=True)
            (root / "Audio" / "song.wav").write_bytes(b"song")
            make_project(root / "Song.cpr", active=["song.wav"])
            make_project(root / "Master.cpr", active=[])

            plan = build_separation_plan(
                audit_archive(root), root.parent / "Separated",
                master_project="Master.cpr",
            )

            gate = plan["master_retirement_gate"]
            self.assertEqual(gate["status"], "unverifiable_no_supported_references")
            self.assertFalse(gate["retirement_authorized"])
            master = next(item for item in plan["projects"] if item["is_master"])
            self.assertFalse(master["copy_manifest_ready"])

    def test_unknown_master_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Mother"
            root.mkdir()
            make_project(root / "Song.cpr", active=[])
            with self.assertRaisesRegex(ValueError, "exactly one"):
                build_separation_plan(
                    audit_archive(root), root.parent / "Separated",
                    master_project="Unknown.cpr",
                )


if __name__ == "__main__":
    unittest.main()
