import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from daw_project_cleaner.format import parse_project
from daw_project_cleaner.normalization_validation import validate_normalization_pair
from daw_project_cleaner.rewrite_profiles import RewriteAudit
from daw_project_cleaner.scanner import scan_root
from daw_project_cleaner.transaction import (
    CONTROLLED_COPY_MARKER,
    CONTROLLED_COPY_TEXT,
    CONTROL_NAME,
    SafetyError,
    purge_session,
    prepare_controlled_copy_marker,
    quarantine_backup_policy,
    quarantine_normalized_pilot,
    quarantine_normalized_batch,
    quarantine_report,
    restore_session,
    rewrite_quarantine_pilot,
)
from tests.helpers import make_project, text_field


class TransactionTests(unittest.TestCase):
    def fixture(self, root: Path):
        audio = root / "Audio"
        audio.mkdir()
        media = audio / "unused.wav"
        media.write_bytes(b"temporary generated audio bytes")
        project = root / "song.npr"
        make_project(project, unused=[media.name])
        return project, media

    def controlled_copy(self, root: Path) -> None:
        (root / CONTROLLED_COPY_MARKER).write_text(
            CONTROLLED_COPY_TEXT, encoding="utf-8"
        )

    def age_session(self, session: Path, days: int) -> None:
        """Back-date a session so the mandatory recovery window has elapsed."""
        state_path = session / "state.json"
        state = json.loads(state_path.read_text())
        created = datetime.fromisoformat(state["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        state["created_at"] = (created - timedelta(days=days)).isoformat()
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    def test_prepare_controlled_copy_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = prepare_controlled_copy_marker(root)
            self.assertEqual(marker.name, CONTROLLED_COPY_MARKER)
            self.assertEqual(marker.read_text(encoding="utf-8"), CONTROLLED_COPY_TEXT)
            self.assertEqual(prepare_controlled_copy_marker(root), marker)

    def test_daw_normalized_quarantine_and_restore_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio = root / "Audio"
            backups = root / "Auto Saves"
            audio.mkdir()
            backups.mkdir()
            active = audio / "active.wav"
            unused = audio / "unused.wav"
            active.write_bytes(b"active")
            unused.write_bytes(b"unused")
            control = root / "CONTROL.npr"
            cleaned = root / "CLEANED.npr"
            backup = backups / "old.bak"
            make_project(control, active=[active.name], unused=[unused.name])
            make_project(cleaned, active=[active.name])
            make_project(backup, active=[active.name], unused=[unused.name])
            validation = validate_normalization_pair(
                control, cleaned, root, daw_open_confirmed=True
            )
            self.controlled_copy(root)

            session = quarantine_normalized_pilot(validation)

            self.assertTrue(cleaned.is_file())
            self.assertTrue(active.is_file())
            self.assertFalse(unused.exists())
            self.assertFalse(control.exists())
            self.assertFalse(backup.exists())
            state = json.loads((session / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["mode"], "daw-normalized-pilot")
            self.assertEqual(state["status"], "complete")

            self.assertEqual(restore_session(session), 3)
            self.assertTrue(unused.is_file())
            self.assertTrue(control.is_file())
            self.assertTrue(backup.is_file())
            self.assertTrue(cleaned.is_file())

    def test_daw_normalized_interruption_rolls_everything_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio = root / "Audio"
            audio.mkdir()
            active = audio / "active.wav"
            unused = audio / "unused.wav"
            active.write_bytes(b"active")
            unused.write_bytes(b"unused")
            control = root / "CONTROL.npr"
            cleaned = root / "CLEANED.npr"
            make_project(control, active=[active.name], unused=[unused.name])
            make_project(cleaned, active=[active.name])
            validation = validate_normalization_pair(
                control, cleaned, root, daw_open_confirmed=True
            )
            self.controlled_copy(root)

            def interrupt(_done, _total, _path):
                raise RuntimeError("simulated normalized interruption")

            with self.assertRaisesRegex(
                RuntimeError, "simulated normalized interruption"
            ):
                quarantine_normalized_pilot(validation, progress=interrupt)

            self.assertTrue(control.is_file())
            self.assertTrue(cleaned.is_file())
            self.assertTrue(active.is_file())
            self.assertTrue(unused.is_file())
            sessions = list((root / CONTROL_NAME / "sessions").iterdir())
            state = json.loads(
                (sessions[0] / "state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["status"], "rolled_back")

    def normalized_fixture(self, root: Path):
        audio = root / "Audio"
        audio.mkdir(parents=True)
        active = audio / "active.wav"
        unused = audio / "unused.wav"
        active.write_bytes(b"active")
        unused.write_bytes(b"unused")
        control = root / "CONTROL.npr"
        cleaned = root / "CLEANED.npr"
        make_project(control, active=[active.name], unused=[unused.name])
        make_project(cleaned, active=[active.name])
        self.controlled_copy(root)
        return validate_normalization_pair(
            control, cleaned, root, daw_open_confirmed=True
        ), control, cleaned, active, unused

    def test_daw_normalized_batch_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            first = self.normalized_fixture(parent / "First")
            second = self.normalized_fixture(parent / "Second")

            sessions = quarantine_normalized_batch([first[0], second[0]])

            self.assertEqual(len(sessions), 2)
            self.assertFalse(first[1].exists())
            self.assertFalse(first[4].exists())
            self.assertFalse(second[1].exists())
            self.assertFalse(second[4].exists())
            self.assertEqual(restore_session(sessions[1]), 2)
            self.assertEqual(restore_session(sessions[0]), 2)
            self.assertTrue(first[1].is_file())
            self.assertTrue(first[4].is_file())
            self.assertTrue(second[1].is_file())
            self.assertTrue(second[4].is_file())

    def test_daw_normalized_preflight_refuses_cleaned_inode_alias(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            validation, control, cleaned, active, unused = self.normalized_fixture(root)
            alias = root / "CLEANED-alias.npr"
            os.link(cleaned, alias)
            validation["project_artifacts_to_quarantine"].append({
                "path": str(alias.resolve()),
                "size_bytes": alias.stat().st_size,
                "sha256": hashlib.sha256(alias.read_bytes()).hexdigest(),
                "action": "quarantine_with_original_project_state",
                "reason": "synthetic alias regression",
            })
            validation["summary"]["project_artifacts_to_quarantine"] += 1

            with self.assertRaisesRegex(
                SafetyError, "cleaned survivor may not be quarantined"
            ):
                quarantine_normalized_pilot(validation)

            self.assertTrue(cleaned.is_file())
            self.assertTrue(alias.is_file())
            self.assertTrue(control.is_file())
            self.assertTrue(active.is_file())
            self.assertTrue(unused.is_file())

    def test_daw_normalized_batch_failure_restores_prior_sessions(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            first = self.normalized_fixture(parent / "First")
            second = self.normalized_fixture(parent / "Second")
            changed = {"done": False}

            def alter_later_project(_done, _total, _path):
                if not changed["done"]:
                    second[4].write_bytes(b"changed after batch preflight")
                    changed["done"] = True

            with self.assertRaisesRegex(SafetyError, "changed after validation"):
                quarantine_normalized_batch(
                    [first[0], second[0]], progress=alter_later_project
                )

            self.assertTrue(first[1].is_file())
            self.assertTrue(first[4].is_file())
            self.assertTrue(second[1].is_file())
            self.assertTrue(second[4].is_file())
            first_sessions = list((parent / "First" / CONTROL_NAME / "sessions").iterdir())
            state = json.loads((first_sessions[0] / "state.json").read_text())
            self.assertEqual(state["status"], "restored")

    def test_prepare_controlled_copy_refuses_symlink_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "marker-target"
            target.write_text(CONTROLLED_COPY_TEXT, encoding="utf-8")
            (root / CONTROLLED_COPY_MARKER).symlink_to(target)
            with self.assertRaisesRegex(SafetyError, "Symbolic links"):
                prepare_controlled_copy_marker(root)

    def synthetic_writer(self, source: Path):
        data = source.read_bytes()
        token = text_field("unused.wav")
        self.assertIn(token, data)
        output = data.replace(token, b"\x00" * len(token), 1)
        return output, RewriteAudit(
            source_sha256=hashlib.sha256(data).hexdigest(),
            output_sha256=hashlib.sha256(output).hexdigest(),
            delete_start=0,
            delete_end=0,
            deleted_bytes=0,
            pool_only_names=["unused.wav"],
            length_fields=[],
            reference_fields=[],
            delete_ranges=[],
        )

    def test_quarantine_and_restore_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, media = self.fixture(root)
            report = scan_root(root)
            session = quarantine_report(report)
            self.assertFalse(media.exists())
            self.assertTrue((session / "backups" / project.relative_to(root)).is_file())
            self.assertEqual(restore_session(session), 1)
            self.assertEqual(media.read_bytes(), b"temporary generated audio bytes")

    def test_purge_is_blocked_without_project_rewrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project, media = self.fixture(root)
            session = quarantine_report(scan_root(root))
            with self.assertRaises(SafetyError) as caught:
                purge_session(session, "DELETE PERMANENTLY")
            self.assertIn("confirmation did not match", str(caught.exception))
            self.assertFalse(media.exists())
            self.assertTrue((session / "state.json").is_file())
            self.assertTrue((session / "audit.jsonl").is_file())

    def test_recent_project_keeps_thirty_day_recovery_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project, media = self.fixture(root)
            self.controlled_copy(root)
            session = rewrite_quarantine_pilot(
                scan_root(root), writer=self.synthetic_writer
            )
            with self.assertRaisesRegex(SafetyError, "30-day recovery window"):
                purge_session(session, "DELETE QUARANTINE PERMANENTLY")
            self.assertFalse(media.exists())
            state = json.loads((session / "state.json").read_text())
            self.assertEqual(state["status"], "complete")
            self.assertEqual(restore_session(session), 1)

    def test_old_project_also_keeps_the_recovery_window(self):
        """An archive is mostly old projects, so age must not shorten the window."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, media = self.fixture(root)
            four_years_ago = 1_640_995_200
            os.utime(project, (four_years_ago, four_years_ago))
            self.controlled_copy(root)
            session = rewrite_quarantine_pilot(
                scan_root(root), writer=self.synthetic_writer
            )
            with self.assertRaisesRegex(SafetyError, "30-day recovery window"):
                purge_session(session, "DELETE QUARANTINE PERMANENTLY")
            self.assertFalse(media.exists())
            self.assertEqual(restore_session(session), 1)

    def test_purge_succeeds_after_the_recovery_window_elapses(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project, media = self.fixture(root)
            self.controlled_copy(root)
            session = rewrite_quarantine_pilot(
                scan_root(root), writer=self.synthetic_writer
            )
            self.age_session(session, days=31)
            self.assertFalse(media.exists())
            self.assertEqual(
                purge_session(session, "DELETE QUARANTINE PERMANENTLY"), 1
            )
            state = json.loads((session / "state.json").read_text())
            self.assertEqual(state["status"], "purged")
            self.assertEqual(state["moves"][0]["status"], "purged")
            with self.assertRaisesRegex(SafetyError, "can no longer be restored"):
                restore_session(session)

    def test_restore_recovers_a_move_interrupted_after_the_rename(self):
        """SIGKILL between os.replace and the state write leaves "planned".

        Only an in-process exception runs the rollback path. A force quit or a
        power loss leaves Restore as the only route back, so Restore must
        resolve such an entry from the filesystem rather than skip it.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project, media = self.fixture(root)
            session = quarantine_report(scan_root(root))
            state_path = session / "state.json"
            state = json.loads(state_path.read_text())
            self.assertEqual(len(state["moves"]), 1)
            quarantined = Path(state["moves"][0]["quarantine"])
            self.assertTrue(quarantined.is_file())
            # Exactly the on-disk state the kill window produces.
            state["moves"][0]["status"] = "planned"
            state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

            self.assertEqual(restore_session(session), 1)
            self.assertTrue(media.is_file())
            self.assertFalse(quarantined.exists())

    def test_restore_ignores_a_planned_move_that_never_happened(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project, media = self.fixture(root)
            session = quarantine_report(scan_root(root))
            state_path = session / "state.json"
            state = json.loads(state_path.read_text())
            quarantined = Path(state["moves"][0]["quarantine"])
            os.replace(quarantined, media)          # as if the rename never ran
            state["moves"][0]["status"] = "planned"
            state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

            self.assertEqual(restore_session(session), 0)
            self.assertTrue(media.is_file())

    def test_stale_temporary_state_file_does_not_block_restore(self):
        """A killed Apply leaves its state temp behind; Restore must still run.

        With a fixed temporary name the leftover made every later state write
        refuse, and Restore failed partway through - after it had already moved
        files back - leaving the session unrecoverable through the app.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project, media = self.fixture(root)
            session = quarantine_report(scan_root(root))
            state_path = session / "state.json"
            (session / "state.json.tmp").write_text("{}", encoding="utf-8")

            self.assertEqual(restore_session(session), 1)
            self.assertTrue(media.is_file())
            self.assertEqual(json.loads(state_path.read_text())["status"], "restored")

    def test_restore_resumes_after_being_interrupted_partway(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project, media = self.fixture(root)
            session = quarantine_report(scan_root(root))
            state_path = session / "state.json"
            state = json.loads(state_path.read_text())
            move = state["moves"][0]
            # As if Restore moved this one back and died before recording it.
            os.replace(Path(move["quarantine"]), Path(move["source"]))
            self.assertEqual(move["status"], "moved")

            self.assertEqual(restore_session(session), 0)
            self.assertTrue(media.is_file())
            self.assertEqual(
                json.loads(state_path.read_text())["moves"][0]["status"], "restored"
            )

    def test_restore_refuses_when_the_file_is_in_neither_place(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project, media = self.fixture(root)
            session = quarantine_report(scan_root(root))
            state = json.loads((session / "state.json").read_text())
            Path(state["moves"][0]["quarantine"]).unlink()
            with self.assertRaisesRegex(SafetyError, "cannot be resolved"):
                restore_session(session)
            self.assertFalse(media.exists())

    def test_cli_presents_a_refusal_as_a_sentence(self):
        """Every gate fails closed and says why; the app shows that text.

        Without the handler the message reached the operator as an unhandled
        traceback, which the native app put straight into an alert.
        """
        import subprocess
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project, media = self.fixture(root)
            session = quarantine_report(scan_root(root))
            state_path = session / "state.json"
            state = json.loads(state_path.read_text())
            Path(state["moves"][0]["quarantine"]).unlink()
            state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, "run_cli.py", "restore", str(session)],
                capture_output=True, text=True,
                cwd=str(Path(__file__).resolve().parent.parent),
            )
            self.assertEqual(result.returncode, 3)
            self.assertIn("Refused:", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_cli_help_shows_only_the_documented_workflow(self):
        """The app decides what an operator sees; the CLI must not undo that."""
        import subprocess
        root = Path(__file__).resolve().parent.parent
        plain = subprocess.run(
            [sys.executable, "run_cli.py", "--help"],
            capture_output=True, text=True, cwd=str(root),
        ).stdout
        for hidden in ("apply-pilot", "remote-scan", "rewrite-validate",
                       "prepare-controlled-copy", "publish-normalized-batch"):
            self.assertNotIn(hidden, plain, f"{hidden} must not be advertised")
        for shown in ("scan", "restore", "purge", "apply-backup-policy"):
            self.assertIn(shown, plain)
        self.assertNotIn("SUPPRESS", plain)

        env = dict(os.environ, DAW_PROJECT_CLEANER_ADVANCED="1")
        full = subprocess.run(
            [sys.executable, "run_cli.py", "--help"],
            capture_output=True, text=True, cwd=str(root), env=env,
        ).stdout
        self.assertIn("apply-pilot", full)

    def test_hidden_commands_still_run(self):
        import subprocess
        root = Path(__file__).resolve().parent.parent
        for command in ("apply-pilot", "remote-scan", "rewrite-validate"):
            result = subprocess.run(
                [sys.executable, "run_cli.py", command, "--help"],
                capture_output=True, text=True, cwd=str(root),
            )
            self.assertEqual(result.returncode, 0, command)

    def test_report_and_session_record_the_producing_version(self):
        """A report authorises a destructive move; it must name the build."""
        from daw_project_cleaner import __version__
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project, _media = self.fixture(root)
            report = scan_root(root)
            self.assertEqual(report.to_dict()["tool_version"], __version__)
            session = quarantine_report(report)
            state = json.loads((session / "state.json").read_text())
            self.assertEqual(state["tool_version"], __version__)

    def test_a_build_without_purge_refuses_before_doing_anything(self):
        """The beta ships without permanent deletion; absent, not merely gated."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project, media = self.fixture(root)
            session = quarantine_report(scan_root(root))
            with patch("daw_project_cleaner.transaction.PURGE_ENABLED", False):
                with self.assertRaisesRegex(SafetyError, "no permanent deletion"):
                    purge_session(session, "DELETE QUARANTINE PERMANENTLY")
            self.assertFalse(media.exists())
            self.assertEqual(restore_session(session), 1)
            self.assertTrue(media.is_file())

    def test_recorded_path_resolves_across_unicode_normalisation(self):
        """A report written over SMB records NFD; the server may store NFC.

        On the studio archive this alone made 4,775 of 8,719 recorded backups
        unresolvable, and one unresolvable entry aborts the whole operation.
        """
        import unicodedata
        from daw_project_cleaner.transaction import _resolve_recorded_path
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            composed = "Rebib lohki".replace("o", "\u00f5")      # NFC
            decomposed = unicodedata.normalize("NFD", composed)
            self.assertNotEqual(composed, decomposed)

            folder = root / composed
            folder.mkdir()
            target = folder / "song.bak"
            target.write_bytes(b"content")

            # Ask for the other form than the one on disk.
            on_disk = next(root.iterdir()).name
            other = (
                unicodedata.normalize("NFD", on_disk)
                if unicodedata.is_normalized("NFC", on_disk)
                else unicodedata.normalize("NFC", on_disk)
            )
            asked = str(root / other / "song.bak")
            resolved = _resolve_recorded_path(asked)
            self.assertTrue(
                resolved.is_file(),
                "a recorded path must resolve whichever normalisation it carries",
            )
            self.assertEqual(resolved.read_bytes(), b"content")

    def test_shared_quarantine_location_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "Projects"
            quarantine = base / "DAW Project Cleaner Quarantine"
            root.mkdir()
            quarantine.mkdir()
            project, media = self.fixture(root)
            original = project.read_bytes()
            self.controlled_copy(root)
            session = rewrite_quarantine_pilot(
                scan_root(root), writer=self.synthetic_writer,
                quarantine_root=quarantine,
            )
            self.assertEqual(session.parent, (quarantine / "sessions").resolve())
            self.assertFalse(media.exists())
            self.assertEqual(restore_session(session), 1)
            self.assertEqual(project.read_bytes(), original)
            self.assertTrue(media.is_file())

    def test_old_classified_backup_moves_and_restores_with_media(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, media = self.fixture(root)
            autosaves = root / "Auto Saves"
            autosaves.mkdir()
            backups = []
            for index in range(6):
                backup = autosaves / f"song-{index + 1:02d}-(Autosave).bak"
                make_project(backup)
                os.utime(backup, (1_700_000_000 + index, 1_700_000_000 + index))
                backups.append(backup)
            self.controlled_copy(root)
            report = scan_root(root, backup_keep=5)
            self.assertEqual(
                sum(item.action == "quarantine" for item in report.backups), 1
            )
            session = rewrite_quarantine_pilot(
                report, writer=self.synthetic_writer
            )
            self.assertFalse(media.exists())
            self.assertFalse(backups[0].exists())
            self.assertTrue(backups[1].exists())
            state = json.loads((session / "state.json").read_text())
            self.assertEqual(
                sum(move.get("kind") == "project_backup" for move in state["moves"]),
                1,
            )
            self.assertEqual(restore_session(session), 2)
            self.assertTrue(media.is_file())
            self.assertTrue(backups[0].is_file())

    def test_backup_policy_only_session_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "Projects"
            quarantine = base / "Shared Quarantine"
            root.mkdir()
            quarantine.mkdir()
            (root / "Audio").mkdir()
            autosaves = root / "Auto Saves"
            autosaves.mkdir()
            make_project(root / "song.npr")
            backups = []
            for index in range(6):
                backup = autosaves / f"song-{index + 1:02d}-(Autosave).bak"
                make_project(backup)
                os.utime(backup, (1_700_000_000 + index, 1_700_000_000 + index))
                backups.append(backup)
            report = scan_root(root, backup_keep=5)
            session = quarantine_backup_policy(report, quarantine)
            self.assertFalse(backups[0].exists())
            self.assertTrue(backups[1].exists())
            state = json.loads((session / "state.json").read_text())
            self.assertEqual(state["mode"], "backup-policy")
            self.assertEqual(len(state["moves"]), 1)
            self.assertEqual(restore_session(session), 1)
            self.assertTrue(backups[0].is_file())

    def test_old_backup_policy_session_still_waits_out_the_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "Projects"
            quarantine = base / "Shared Quarantine"
            root.mkdir()
            quarantine.mkdir()
            (root / "Audio").mkdir()
            autosaves = root / "Auto Saves"
            autosaves.mkdir()
            project = root / "song.npr"
            make_project(project)
            old = 1_640_995_200
            os.utime(project, (old, old))
            for index in range(2):
                backup = autosaves / f"song-{index + 1:02d}.bak"
                make_project(backup)
                os.utime(backup, (old + index, old + index))
            report = scan_root(root, backup_keep=1)
            session = quarantine_backup_policy(report, quarantine)
            with self.assertRaisesRegex(SafetyError, "30-day recovery window"):
                purge_session(session, "DELETE QUARANTINE PERMANENTLY")
            self.age_session(session, days=31)
            self.assertEqual(
                purge_session(session, "DELETE QUARANTINE PERMANENTLY"), 1
            )
            state = json.loads((session / "state.json").read_text())
            self.assertEqual(state["status"], "purged")

    def test_recent_backup_policy_session_keeps_recovery_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "Projects"
            quarantine = base / "Shared Quarantine"
            root.mkdir()
            quarantine.mkdir()
            (root / "Audio").mkdir()
            autosaves = root / "Auto Saves"
            autosaves.mkdir()
            make_project(root / "song.npr")
            for index in range(2):
                make_project(autosaves / f"song-{index + 1:02d}.bak")
            session = quarantine_backup_policy(
                scan_root(root, backup_keep=1), quarantine
            )
            with self.assertRaisesRegex(SafetyError, "30-day recovery window"):
                purge_session(session, "DELETE QUARANTINE PERMANENTLY")
            self.assertEqual(restore_session(session), 1)

    def test_backup_policy_interruption_rolls_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "Projects"
            quarantine = base / "Shared Quarantine"
            root.mkdir()
            quarantine.mkdir()
            (root / "Audio").mkdir()
            autosaves = root / "Auto Saves"
            autosaves.mkdir()
            make_project(root / "song.npr")
            first = autosaves / "song-01.bak"
            second = autosaves / "song-02.bak"
            make_project(first)
            make_project(second)
            os.utime(first, (1_700_000_000, 1_700_000_000))
            os.utime(second, (1_700_000_001, 1_700_000_001))

            def interrupt(_done, _total, _path):
                raise RuntimeError("simulated backup interruption")

            with self.assertRaisesRegex(RuntimeError, "simulated backup interruption"):
                quarantine_backup_policy(
                    scan_root(root, backup_keep=1), quarantine,
                    progress=interrupt,
                )
            self.assertTrue(first.is_file())
            sessions = list((quarantine / "sessions").iterdir())
            state = json.loads((sessions[0] / "state.json").read_text())
            self.assertEqual(state["status"], "rolled_back")

    def test_changed_project_stops_before_media_move(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, media = self.fixture(root)
            report = scan_root(root)
            project.write_bytes(project.read_bytes() + b"changed")
            with self.assertRaises(SafetyError):
                quarantine_report(report)
            self.assertTrue(media.is_file())

    def test_pilot_requires_disposable_copy_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project, media = self.fixture(root)
            with self.assertRaisesRegex(SafetyError, "controlled-copy marker"):
                rewrite_quarantine_pilot(
                    scan_root(root), writer=self.synthetic_writer
                )
            self.assertTrue(media.is_file())

    def test_rewrite_quarantine_and_restore_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, media = self.fixture(root)
            original_project = project.read_bytes()
            self.controlled_copy(root)
            session = rewrite_quarantine_pilot(
                scan_root(root), writer=self.synthetic_writer
            )
            self.assertFalse(media.exists())
            self.assertNotEqual(project.read_bytes(), original_project)
            self.assertTrue(
                (session / "backups" / project.relative_to(root)).is_file()
            )
            self.assertEqual(restore_session(session), 1)
            self.assertEqual(project.read_bytes(), original_project)
            self.assertEqual(media.read_bytes(), b"temporary generated audio bytes")

    def test_pilot_applies_only_selected_independent_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "First").mkdir()
            (root / "Second").mkdir()
            first_project, first_media = self.fixture(root / "First")
            second_project, second_media = self.fixture(root / "Second")
            second_original = second_project.read_bytes()
            self.controlled_copy(root)
            report = scan_root(root)
            selected = next(
                project.path for project in report.projects
                if project.path.endswith("/First/song.npr")
            )
            session = rewrite_quarantine_pilot(
                report, writer=self.synthetic_writer,
                selected_project_paths=[selected],
            )
            self.assertFalse(first_media.exists())
            self.assertTrue(second_media.is_file())
            self.assertEqual(second_project.read_bytes(), second_original)
            self.assertEqual(restore_session(session), 1)
            self.assertTrue(first_media.is_file())

    def test_pilot_refuses_partial_shared_pool_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio = root / "Audio"
            audio.mkdir()
            media = audio / "unused.wav"
            media.write_bytes(b"temporary generated audio bytes")
            first = root / "first.npr"
            second = root / "second.npr"
            make_project(first, unused=[media.name])
            make_project(second, unused=[media.name])
            self.controlled_copy(root)
            report = scan_root(root)
            selected = next(
                project.path for project in report.projects
                if project.path.endswith("/first.npr")
            )
            with self.assertRaisesRegex(
                SafetyError, "Shared media requires selecting every"
            ):
                rewrite_quarantine_pilot(
                    report, writer=self.synthetic_writer,
                    selected_project_paths=[selected],
                )
            self.assertTrue(media.is_file())

    def test_controlled_pilot_allows_exact_writer_for_review_reader(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, media = self.fixture(root)
            original_project = project.read_bytes()
            self.controlled_copy(root)

            def review_parser(path):
                parsed = parse_project(path)
                parsed.confidence = "review"
                return parsed

            with patch(
                "daw_project_cleaner.transaction.parse_project",
                side_effect=review_parser,
            ):
                session = rewrite_quarantine_pilot(
                    scan_root(root), writer=self.synthetic_writer
                )
                self.assertFalse(media.exists())
                self.assertEqual(restore_session(session), 1)

            self.assertEqual(project.read_bytes(), original_project)
            self.assertEqual(media.read_bytes(), b"temporary generated audio bytes")

    def test_pilot_failure_rolls_back_project_and_media(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, media = self.fixture(root)
            original_project = project.read_bytes()
            self.controlled_copy(root)

            def interrupt(_done, _total, _path):
                raise RuntimeError("simulated interruption")

            with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
                rewrite_quarantine_pilot(
                    scan_root(root), progress=interrupt,
                    writer=self.synthetic_writer,
                )
            self.assertEqual(project.read_bytes(), original_project)
            self.assertEqual(media.read_bytes(), b"temporary generated audio bytes")
            sessions = list((root / CONTROL_NAME / "sessions").iterdir())
            self.assertEqual(len(sessions), 1)
            self.assertIn(
                '"status": "rolled_back"',
                (sessions[0] / "state.json").read_text(encoding="utf-8"),
            )

    def test_pilot_refuses_partial_pool_mapping(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio = root / "Audio"
            audio.mkdir()
            media = audio / "unused.wav"
            media.write_bytes(b"temporary generated audio bytes")
            project = root / "song.npr"
            make_project(project, unused=["unused.wav", "missing.wav"])
            original_project = project.read_bytes()
            self.controlled_copy(root)
            with self.assertRaisesRegex(
                SafetyError, "Every pool-only reference must map"
            ):
                rewrite_quarantine_pilot(
                    scan_root(root), writer=self.synthetic_writer
                )
            self.assertEqual(project.read_bytes(), original_project)
            self.assertTrue(media.is_file())

    def test_restore_refuses_a_modified_rewritten_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, media = self.fixture(root)
            self.controlled_copy(root)
            session = rewrite_quarantine_pilot(
                scan_root(root), writer=self.synthetic_writer
            )
            project.write_bytes(project.read_bytes() + b"changed after apply")
            with self.assertRaisesRegex(
                SafetyError, "changed after Apply"
            ):
                restore_session(session)
            self.assertFalse(media.exists())


if __name__ == "__main__":
    unittest.main()
