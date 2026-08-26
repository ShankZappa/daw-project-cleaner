import tempfile
import unittest
from pathlib import Path

from daw_project_cleaner.archive_audit import audit_archive
from daw_project_cleaner.archive_queue import build_archive_queue
from tests.helpers import make_project


class ArchiveQueueTests(unittest.TestCase):
    def test_shared_media_creates_one_fail_closed_family(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Audio").mkdir()
            (root / "Audio" / "shared.wav").write_bytes(b"shared")
            (root / "Audio" / "one.wav").write_bytes(b"one")
            (root / "Audio" / "two.wav").write_bytes(b"two")
            make_project(root / "One.cpr", active=["shared.wav", "one.wav"])
            make_project(root / "Two.npr", active=["shared.wav", "two.wav"])

            queue = build_archive_queue(audit_archive(root))

            self.assertEqual(queue["summary"]["families"], 1)
            self.assertEqual(queue["summary"]["ready_for_operator"], 1)
            self.assertEqual(len(queue["families"][0]["members"]), 2)
            self.assertEqual(queue["families"][0]["target_application"], "Nuendo 15")
            self.assertFalse(queue["families"][0]["cleanup_authorized"])

    def test_missing_reference_blocks_whole_family(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Audio").mkdir()
            make_project(root / "Broken.npr", active=["missing.wav"])

            queue = build_archive_queue(audit_archive(root))

            family = queue["families"][0]
            self.assertEqual(family["status"], "blocked")
            self.assertEqual(family["blockers"][0]["kind"], "missing_media_reference")
            self.assertEqual(queue["summary"]["cleanup_authorized"], 0)

    def test_projects_in_same_legacy_parent_stay_in_one_family(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Audio").mkdir()
            (root / "Audio" / "one.wav").write_bytes(b"one")
            (root / "Audio" / "two.wav").write_bytes(b"two")
            make_project(root / "Separate Song One.npr", active=["one.wav"])
            make_project(root / "Separate Song Two.npr", active=["two.wav"])

            queue = build_archive_queue(audit_archive(root))

            self.assertEqual(queue["summary"]["families"], 1)
            self.assertEqual(len(queue["families"][0]["members"]), 2)

    def test_sampled_audit_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Audio").mkdir()
            make_project(root / "One.npr", active=[])
            make_project(root / "Two.npr", active=[])
            audit = audit_archive(root, sample_projects=1)

            with self.assertRaisesRegex(ValueError, "sampled audit"):
                build_archive_queue(audit)


if __name__ == "__main__":
    unittest.main()
