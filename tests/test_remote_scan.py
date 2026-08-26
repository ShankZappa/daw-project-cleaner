import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daw_project_cleaner.model import report_from_dict
from daw_project_cleaner.remote_scan import remote_quick_scan
from daw_project_cleaner.transaction import SafetyError, quarantine_report
from tests.helpers import make_project


class RemoteQuickScanTests(unittest.TestCase):
    def test_inventory_reads_bounded_main_header_but_never_opens_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "Audio"
            backups = root / "Backups"
            audio.mkdir()
            backups.mkdir()
            make_project(root / "song.npr", active=["used.wav"])
            (audio / "used.wav").write_bytes(b"audio")
            backup = backups / "song-01.bak"
            backup.write_bytes(b"backup bytes that must not be opened")
            inspected = []

            def identity(path):
                inspected.append(path)
                return "RIF2", "Nuendo", "15.0.30", "bounded test header"

            report_path = root / "quick.json"
            with patch(
                "daw_project_cleaner.remote_scan._light_project_identity",
                side_effect=identity,
            ):
                report = remote_quick_scan(root, report_path, checkpoint_every=1)

            self.assertTrue(report["complete"])
            self.assertEqual(inspected, [(root / "song.npr").resolve()])
            self.assertEqual(report["summary"]["projects"], 1)
            self.assertEqual(report["summary"]["backups"], 1)
            self.assertEqual(report["summary"]["media_files"], 1)
            self.assertIsNone(report["backups"][0]["sha256"])
            self.assertEqual(report["backups"][0]["status"], "inventory")
            self.assertFalse(report["safety"]["backup_files_opened"])

    def test_interrupted_inventory_resumes_without_double_counting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("One", "Two"):
                folder = root / name
                folder.mkdir()
                make_project(folder / f"{name}.npr")
            report_path = root / "quick.json"

            partial = remote_quick_scan(
                root, report_path, checkpoint_every=1, directory_limit=1
            )
            self.assertFalse(partial["complete"])
            self.assertTrue(partial["interrupted"])
            self.assertGreater(partial["summary"]["directories_pending"], 0)

            complete = remote_quick_scan(root, report_path, checkpoint_every=1)
            self.assertTrue(complete["complete"])
            self.assertEqual(complete["summary"]["projects"], 2)
            self.assertEqual(len(complete["projects"]), 2)
            self.assertEqual(complete["summary"]["directories_pending"], 0)

    def test_quick_inventory_report_cannot_authorize_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_project(root / "song.npr")
            report_path = root / "quick.json"
            remote_quick_scan(root, report_path)
            raw = json.loads(report_path.read_text(encoding="utf-8"))
            report = report_from_dict(raw)
            with self.assertRaisesRegex(SafetyError, "Full Safety Scan"):
                quarantine_report(report)

    def test_ui_snapshot_is_compact_and_migrates_legacy_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "Nested"
            folder.mkdir()
            make_project(folder / "song.npr")
            ui_report = root / "latest-quick-scan.json"
            state_report = root / "latest-quick-scan-state.json"

            legacy = remote_quick_scan(
                root, ui_report, checkpoint_every=1, directory_limit=1
            )
            self.assertFalse(legacy["complete"])
            self.assertIn("pending_directories", json.loads(
                ui_report.read_text(encoding="utf-8")
            ))

            complete = remote_quick_scan(
                root, state_report, ui_report_path=ui_report,
                checkpoint_every=1,
            )
            self.assertTrue(complete["complete"])
            state = json.loads(state_report.read_text(encoding="utf-8"))
            snapshot = json.loads(ui_report.read_text(encoding="utf-8"))
            self.assertIn("pending_directories", state)
            self.assertIn("projects_by_path", state)
            self.assertNotIn("pending_directories", snapshot)
            self.assertNotIn("directory_summaries", snapshot)
            self.assertEqual(snapshot["summary"]["projects"], 1)


if __name__ == "__main__":
    unittest.main()
