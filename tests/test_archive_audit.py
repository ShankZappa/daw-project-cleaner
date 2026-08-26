import tempfile
import unittest
from pathlib import Path

from daw_project_cleaner.archive_audit import audit_archive
from tests.helpers import make_project


class ArchiveAuditTests(unittest.TestCase):
    def test_shared_parent_layout_and_media_roles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio = root / "Audio"
            edits = root / "Edits"
            freezes = root / "Freezes"
            audio.mkdir()
            edits.mkdir()
            freezes.mkdir()
            mixdown = root / "Mixdown"
            autosaves = root / "Auto Saves"
            mixdown.mkdir()
            autosaves.mkdir()
            (audio / "one.wav").write_bytes(b"one")
            (edits / "two.wav").write_bytes(b"two")
            (freezes / "orphan.wav").write_bytes(b"orphan")
            (mixdown / "master.wav").write_bytes(b"master")
            (autosaves / "song.bak").write_bytes(b"backup")
            make_project(root / "Song One.npr", active=["one.wav"])
            make_project(root / "Song Two.npr", active=["two.wav"])

            report = audit_archive(root, workers=2)
            self.assertEqual(report["summary"]["projects_audited"], 2)
            self.assertEqual(report["summary"]["separation_copy_test_ready_projects"], 2)
            self.assertEqual(report["roles"]["Audio"]["files"], 1)
            self.assertEqual(report["roles"]["Edits"]["files"], 1)
            self.assertEqual(report["roles"]["Freeze"]["unreferenced_files"], 1)
            self.assertEqual(report["roles"]["Mixdown"]["unreferenced_files"], 0)
            self.assertEqual(report["summary"]["preserved_mixdown_files"], 1)
            self.assertEqual(report["summary"]["auxiliary_files"], 1)
            self.assertFalse(report["safety"]["cleanup_authorized"])

    def test_duplicate_basename_blocks_separation_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Audio").mkdir()
            (root / "Edits").mkdir()
            (root / "Audio" / "same.wav").write_bytes(b"a")
            (root / "Edits" / "same.wav").write_bytes(b"b")
            make_project(root / "song.npr", active=["same.wav"])
            report = audit_archive(root)
            plan = report["projects"][0]["separation_plan"]
            self.assertFalse(plan["ready_for_copy_test"])
            self.assertEqual(plan["blockers"][0]["reason"], "ambiguous")
            self.assertEqual(report["summary"]["ambiguous_protected_media_files"], 2)
            self.assertEqual(report["summary"]["unreferenced_media_files"], 0)
            self.assertEqual(report["roles"]["Audio"]["ambiguous_files"], 1)

    def test_versions_with_same_media_form_one_family(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Audio").mkdir()
            (root / "Audio" / "shared.wav").write_bytes(b"shared")
            make_project(root / "Song.npr", active=["shared.wav"])
            make_project(root / "Song ATMOS.npr", active=["shared.wav"])
            report = audit_archive(root)
            self.assertEqual(report["summary"]["proposed_project_families"], 1)
            self.assertEqual(report["summary"]["multi_project_families"], 1)
            self.assertEqual(len(report["project_families"][0]["members"]), 2)
            self.assertEqual(report["project_families"][0]["proposed_folder"], "Song")

    def test_unicode_normalized_exact_name_resolves(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Audio").mkdir()
            # NFD filename on disk, NFC reference in the project.
            (root / "Audio" / "A\u0308ike.wav").write_bytes(b"audio")
            make_project(root / "Song.npr", active=["Äike.wav"])

            report = audit_archive(root)
            reference = report["projects"][0]["references"][0]
            self.assertEqual(reference["resolution"], "unique")
            self.assertEqual(
                reference["resolution_evidence"], "unicode_normalized_exact_name"
            )
            self.assertTrue(
                report["projects"][0]["separation_plan"]["ready_for_copy_test"]
            )

    def test_embedded_path_role_resolves_duplicate_basename(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Audio").mkdir()
            (root / "Edits").mkdir()
            (root / "Audio" / "same.wav").write_bytes(b"audio")
            (root / "Edits" / "same.wav").write_bytes(b"edit")
            make_project(
                root / "Song.npr", active=["same.wav"],
                active_paths=["/legacy/project/Edits/"],
            )

            report = audit_archive(root)
            reference = report["projects"][0]["references"][0]
            self.assertEqual(reference["resolution"], "path_evidenced")
            self.assertEqual(reference["resolution_evidence"], "embedded_source_directory")
            self.assertEqual(
                reference["matches"],
                [str((root / "Edits" / "same.wav").resolve())],
            )
            self.assertTrue(
                report["projects"][0]["separation_plan"]["ready_for_copy_test"]
            )


if __name__ == "__main__":
    unittest.main()
