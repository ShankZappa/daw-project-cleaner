import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from daw_project_cleaner.rewrite_profiles import ExperimentalRewriteError, RewriteAudit
from daw_project_cleaner.scanner import scan_root
from tests.helpers import make_project


class ScannerTests(unittest.TestCase):
    def test_scan_reports_application_validated_rewrite_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "Audio"
            audio.mkdir()
            (audio / "used.wav").write_bytes(b"used")
            (audio / "unused.wav").write_bytes(b"unused")
            make_project(
                root / "song.npr", active=["used.wav"], unused=["unused.wav"]
            )
            audit = RewriteAudit(
                source_sha256="a", output_sha256="b", delete_start=0,
                delete_end=1, deleted_bytes=1,
                pool_only_names=["unused.wav"], length_fields=[],
                reference_fields=[], delete_ranges=[(0, 1)],
            )
            with patch(
                "daw_project_cleaner.scanner.rewrite_for_exact_profile",
                return_value=(b"rewritten", audit),
            ), patch(
                "daw_project_cleaner.scanner.application_validated_shape_label",
                return_value="generated test shape",
            ):
                report = scan_root(root)
            self.assertTrue(report.projects[0].rewrite_supported)
            self.assertIn("generated test shape", report.projects[0].rewrite_reason)
            self.assertEqual(report.to_dict()["summary"]["rewrite_ready_projects"], 1)
    def test_scan_and_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            song = root / "Song"
            audio = song / "Audio"
            audio.mkdir(parents=True)
            (audio / "used.wav").write_bytes(b"used")
            (audio / "unused.wav").write_bytes(b"unused")
            (audio / "orphan.wav").write_bytes(b"orphan")
            make_project(song / "song.npr", ["used.wav"], ["unused.wav"])
            backup = song / "Backups"
            backup.mkdir()
            make_project(backup / "old.npr", unused=["orphan.wav"])

            report = scan_root(root, workers=2)
            self.assertEqual(len(report.projects), 1)
            project = report.projects[0]
            by_name = {x.name: x for x in project.media}
            self.assertFalse(by_name["used.wav"].eligible)
            self.assertTrue(by_name["unused.wav"].candidate)
            self.assertFalse(by_name["unused.wav"].eligible)
            self.assertEqual(by_name["orphan.wav"].classification, "unreferenced_on_disk")
            self.assertFalse(by_name["orphan.wav"].eligible)

    def test_scan_streams_each_completed_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("One", "Two"):
                folder = root / name
                audio = folder / "Audio"
                audio.mkdir(parents=True)
                (audio / "used.wav").write_bytes(b"used")
                make_project(folder / f"{name}.npr", active=["used.wav"])
            streamed = []
            report = scan_root(
                root, workers=2, result_callback=lambda result: streamed.append(result.path)
            )
            self.assertEqual(len(report.projects), 2)
            self.assertEqual(set(streamed), {project.path for project in report.projects})

    def test_scan_progress_announces_total_then_each_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("One", "Two"):
                folder = root / name
                (folder / "Audio").mkdir(parents=True)
                make_project(folder / f"{name}.npr")
            events = []
            scan_root(root, workers=1, progress=lambda done, total, path: events.append(
                (done, total, path)
            ))
            self.assertEqual(events[0], (0, 2, ""))
            self.assertEqual([event[0] for event in events], [0, 1, 2])
            self.assertTrue(events[-1][2].endswith(".npr"))

    def test_shared_active_media_is_globally_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "Audio"
            audio.mkdir()
            (audio / "shared.wav").write_bytes(b"x")
            make_project(root / "a.npr", active=["shared.wav"])
            make_project(root / "b.npr", unused=["shared.wav"])
            report = scan_root(root)
            candidate = next(x for p in report.projects if p.path.endswith("b.npr") for x in p.media if x.name == "shared.wav")
            self.assertFalse(candidate.candidate)
            self.assertIn("another discovered project", candidate.reason)

    def test_shared_pool_media_requires_every_owner_to_be_rewrite_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "Audio"
            audio.mkdir()
            (audio / "shared.wav").write_bytes(b"shared")
            ready = root / "ready.npr"
            report_only = root / "report-only.npr"
            make_project(ready, unused=["shared.wav"])
            make_project(report_only, unused=["shared.wav"])
            audit = RewriteAudit(
                source_sha256="a", output_sha256="b", delete_start=0,
                delete_end=1, deleted_bytes=1, pool_only_names=["shared.wav"],
                length_fields=[], reference_fields=[], delete_ranges=[(0, 1)],
            )

            def writer(path):
                if path.name == "report-only.npr":
                    raise ExperimentalRewriteError("unsupported test shape")
                return b"rewritten", audit

            with patch(
                "daw_project_cleaner.scanner.rewrite_for_exact_profile",
                side_effect=writer,
            ), patch(
                "daw_project_cleaner.scanner.application_validated_shape_label",
                return_value="generated test shape",
            ):
                report = scan_root(root)
            self.assertFalse(any(project.rewrite_supported for project in report.projects))
            self.assertEqual(report.to_dict()["summary"]["candidate_files"], 1)

    def test_any_unreadable_project_fail_closes_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "Audio"
            audio.mkdir()
            (audio / "unused.wav").write_bytes(b"x")
            make_project(root / "good.npr", unused=["unused.wav"])
            (root / "unknown.cpr").write_bytes(b"not a project")
            report = scan_root(root)
            candidate = next(x for p in report.projects for x in p.media if x.name == "unused.wav")
            self.assertFalse(candidate.candidate)
            self.assertIn("scan contains", candidate.reason)

    def test_shared_pool_only_path_is_counted_once_in_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "Audio"
            audio.mkdir()
            (audio / "shared.wav").write_bytes(b"12345")
            make_project(root / "a.npr", unused=["shared.wav"])
            make_project(root / "b.npr", unused=["shared.wav"])
            report = scan_root(root)
            self.assertEqual(report.potential_reclaimable_bytes, 5)
            self.assertEqual(report.to_dict()["summary"]["candidate_files"], 1)

    def test_retained_backup_protects_referenced_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "Audio"
            autosaves = root / "Auto Saves"
            audio.mkdir()
            autosaves.mkdir()
            (audio / "unused.wav").write_bytes(b"audio")
            make_project(root / "song.npr", unused=["unused.wav"])
            make_project(
                autosaves / "song-01-(Autosave).bak", active=["unused.wav"]
            )
            report = scan_root(
                root, backup_keep=5, backup_protect_media=True
            )
            item = next(
                item for item in report.projects[0].media
                if item.name == "unused.wav"
            )
            self.assertFalse(item.candidate)
            self.assertIn("retained project backup", item.reason)
            self.assertEqual(len(report.backups), 1)
            self.assertEqual(report.backups[0].action, "keep")

    def test_archive_mode_does_not_parse_or_protect_backup_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "Audio"
            autosaves = root / "Auto Saves"
            audio.mkdir()
            autosaves.mkdir()
            (audio / "unused.wav").write_bytes(b"audio")
            make_project(root / "song.npr", unused=["unused.wav"])
            make_project(
                autosaves / "song-01-(Autosave).bak", active=["unused.wav"]
            )
            report = scan_root(
                root, backup_keep=0, backup_protect_media=False
            )
            item = next(
                item for item in report.projects[0].media
                if item.name == "unused.wav"
            )
            self.assertTrue(item.candidate)
            self.assertEqual(report.backups[0].status, "indexed")
            self.assertEqual(report.backups[0].action, "quarantine")
            self.assertEqual(report.backups[0].media, [])

    def test_backup_policy_keeps_newest_five(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Audio").mkdir()
            autosaves = root / "Auto Saves"
            autosaves.mkdir()
            make_project(root / "song.npr")
            for index in range(6):
                backup = autosaves / f"song-{index + 1:02d}-(Autosave).bak"
                make_project(backup)
                os.utime(backup, (1_700_000_000 + index, 1_700_000_000 + index))
            report = scan_root(root, backup_keep=5)
            self.assertEqual(len(report.backups), 6)
            quarantined = [
                backup for backup in report.backups
                if backup.action == "quarantine"
            ]
            self.assertEqual(len(quarantined), 1)
            self.assertIn("song-01-", quarantined[0].path)
            summary = report.to_dict()["summary"]
            self.assertEqual(summary["backup_files"], 6)
            self.assertEqual(summary["backup_quarantine_files"], 1)

    def test_ambiguous_backup_family_is_always_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Audio").mkdir()
            make_project(root / "first.npr")
            make_project(root / "second.npr")
            backup = root / "unknown-01.bak"
            make_project(backup)
            report = scan_root(root, backup_keep=0)
            self.assertEqual(report.backups[0].action, "keep")
            self.assertIn("ambiguous", report.backups[0].reason)

    def test_backup_of_unreadable_project_is_kept_beside_a_readable_one(self):
        """A backup may be the last readable copy of the project it belongs to.

        An unreadable project is excluded from family matching, so a folder
        holding one corrupt and one healthy project used to adopt the corrupt
        project's backup into the healthy family and select it for quarantine.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Audio").mkdir()
            (root / "Audio" / "take.wav").write_bytes(b"take")
            (root / "corrupt.npr").write_bytes(b"")
            make_project(root / "healthy.npr", active=["take.wav"])
            make_project(root / "corrupt-01.bak", active=["take.wav"])
            report = scan_root(root, backup_keep=0)
            self.assertEqual(len(report.backups), 1)
            self.assertEqual(report.backups[0].action, "keep")
            self.assertIn("could not be read", report.backups[0].reason)

    def test_numbered_failed_save_protects_every_backup_in_the_folder(self):
        """The shape found in the real archive: a 0-byte numbered save.

        Steinberg numbers saved versions and auto-backups independently, and
        `_backup_stem` strips that number, so `song-02.bak` matches `song.cpr`
        by name even when the unreadable project is `song-01.cpr`. Name
        evidence therefore cannot protect this case; folder evidence must.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Audio").mkdir()
            (root / "Audio" / "take.wav").write_bytes(b"take")
            make_project(root / "song.npr", active=["take.wav"])
            (root / "song-01.npr").write_bytes(b"")
            for index in (2, 3):
                make_project(root / f"song-{index:02d}.bak", active=["take.wav"])
            report = scan_root(root, backup_keep=0)
            self.assertEqual(len(report.backups), 2)
            for backup in report.backups:
                self.assertEqual(backup.action, "keep")
                self.assertIn("could not be read", backup.reason)

    def test_backup_belongs_to_the_project_in_its_own_folder(self):
        """Found in the real archive: a backup beside an unclassifiable project.

        `find_backup_audio_dir` resolves the Audio folder by walking upward, so
        a backup in a subfolder could be adopted by the project one directory
        up - which its name happened to match - while the project sitting right
        next to it was never considered.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Audio").mkdir()
            (root / "Audio" / "take.wav").write_bytes(b"take")
            make_project(root / "Podcast.npr", active=["take.wav"])
            nested = root / "Podcast subfolder"
            nested.mkdir()
            make_project(nested / "Podcast.npr", active=["take.wav"])
            make_project(nested / "Podcast.bak", active=["take.wav"])

            report = scan_root(root, backup_keep=0)
            self.assertEqual(len(report.backups), 1)
            backup = report.backups[0]
            self.assertEqual(backup.action, "keep")
            self.assertIn("its own folder", backup.reason)

    def test_backup_in_a_subfolder_without_a_project_still_uses_the_parent(self):
        """Auto Saves and Backups folders must keep working."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Audio").mkdir()
            (root / "Audio" / "take.wav").write_bytes(b"take")
            make_project(root / "song.npr", active=["take.wav"])
            saves = root / "Auto Saves"
            saves.mkdir()
            make_project(saves / "song-01.bak", active=["take.wav"])

            report = scan_root(root, backup_keep=0)
            self.assertEqual(report.backups[0].action, "quarantine")

    def test_sole_readable_project_still_adopts_an_unmatched_backup(self):
        """The name-free fallback stays available when nothing can be confused."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Audio").mkdir()
            (root / "Audio" / "take.wav").write_bytes(b"take")
            make_project(root / "healthy.npr", active=["take.wav"])
            make_project(root / "unrelated-name-01.bak", active=["take.wav"])
            report = scan_root(root, backup_keep=0)
            self.assertEqual(report.backups[0].action, "quarantine")


if __name__ == "__main__":
    unittest.main()
