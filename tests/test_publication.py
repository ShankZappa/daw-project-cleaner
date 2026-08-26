import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daw_project_cleaner.normalization_validation import validate_normalization_pair
from daw_project_cleaner.publication import (
    RECEIPT,
    build_publication_plan,
    publish_normalized_batch,
    restore_publication,
    withdraw_publication,
)
from tests.helpers import make_project


class PublicationTests(unittest.TestCase):
    def fixture(self, parent: Path, name: str = "Song"):
        root = parent / name
        audio = root / "Audio"
        audio.mkdir(parents=True)
        active = audio / "active.wav"
        unused = audio / "unused.wav"
        active.write_bytes(b"active media")
        unused.write_bytes(b"unused media")
        control = root / f"{name}_CONTROL.cpr"
        cleaned = root / f"{name}_CLEANED.cpr"
        make_project(control, active=[active.name], unused=[unused.name])
        make_project(cleaned, active=[active.name])
        validation = validate_normalization_pair(
            control, cleaned, root, daw_open_confirmed=True
        )
        held = parent / f"{name}-held"
        held.mkdir()
        for record in validation["candidates"] + validation["project_artifacts_to_quarantine"]:
            source = Path(record["path"])
            os.replace(source, held / source.name)
        return root, active, cleaned, validation

    def test_atomic_publication_keeps_sources_and_writes_verified_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root, active, cleaned, validation = self.fixture(parent)
            destination = parent / "Published"
            plan = build_publication_plan([validation], destination)

            result = publish_normalized_batch(plan)

            self.assertEqual(result, destination.absolute())
            self.assertEqual((destination / "Song" / "Audio" / "active.wav").read_bytes(), b"active media")
            self.assertTrue((destination / "Song" / "Song.cpr").is_file())
            self.assertFalse((destination / "Song" / "Audio" / "unused.wav").exists())
            self.assertTrue(active.is_file())
            self.assertTrue(cleaned.is_file())
            receipt = json.loads((destination / RECEIPT).read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "published_verified")
            self.assertFalse(receipt["safety"]["mother_retirement_authorized"])

    def test_existing_destination_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            _, _, _, validation = self.fixture(parent)
            destination = parent / "Published"
            destination.mkdir()
            with self.assertRaisesRegex(FileExistsError, "already exists"):
                build_publication_plan([validation], destination)

    def test_space_separated_workflow_suffix_is_not_published(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "Linda Itk"
            audio = root / "Audio"
            audio.mkdir(parents=True)
            active = audio / "active.wav"
            unused = audio / "unused.wav"
            active.write_bytes(b"active")
            unused.write_bytes(b"unused")
            original = root / "Linda Itk.cpr"
            control = root / "Linda Itk CONTROL.cpr"
            cleaned = root / "Linda Itk CLEANED.cpr"
            make_project(original, active=[active.name], unused=[unused.name])
            make_project(control, active=[active.name], unused=[unused.name])
            make_project(cleaned, active=[active.name])
            validation = validate_normalization_pair(
                control, cleaned, root, daw_open_confirmed=True
            )
            held = parent / "held"
            held.mkdir()
            for record in validation["candidates"] + validation["project_artifacts_to_quarantine"]:
                source = Path(record["path"])
                os.replace(source, held / source.name)

            plan = build_publication_plan([validation], parent / "Published")

            project = next(op for op in plan["operations"] if op["kind"] == "project")
            self.assertEqual(project["destination_relative"], "Linda Itk/Linda Itk.cpr")

    def test_changed_source_fails_without_visible_or_staging_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            _, active, _, validation = self.fixture(parent)
            destination = parent / "Published"
            plan = build_publication_plan([validation], destination)
            active.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "changed after planning"):
                publish_normalized_batch(plan)
            self.assertFalse(destination.exists())
            self.assertEqual(list(parent.glob(".daw-project-cleaner-publish-*")), [])

    def test_copy_interruption_removes_generated_staging_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            _, active, cleaned, validation = self.fixture(parent)
            destination = parent / "Published"
            plan = build_publication_plan([validation], destination)
            from daw_project_cleaner import publication
            real_copy = publication.shutil.copy2
            calls = {"count": 0}

            def interrupted(*args, **kwargs):
                calls["count"] += 1
                if calls["count"] == 2:
                    raise OSError("simulated publish interruption")
                return real_copy(*args, **kwargs)

            with patch.object(publication.shutil, "copy2", side_effect=interrupted):
                with self.assertRaisesRegex(OSError, "simulated publish interruption"):
                    publish_normalized_batch(plan)
            self.assertFalse(destination.exists())
            self.assertEqual(list(parent.glob(".daw-project-cleaner-publish-*")), [])
            self.assertTrue(active.is_file())
            self.assertTrue(cleaned.is_file())

    def test_publication_withdraw_and_restore_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            _, _, _, validation = self.fixture(parent)
            destination = parent / "Published"
            plan = build_publication_plan([validation], destination)
            publish_normalized_batch(plan)
            quarantine = parent / "Publication Quarantine"
            quarantine.mkdir()

            session = withdraw_publication(destination, quarantine)

            self.assertFalse(destination.exists())
            self.assertTrue((session / "published" / RECEIPT).is_file())
            restored = restore_publication(session)
            self.assertEqual(restored, destination.absolute())
            self.assertTrue((destination / RECEIPT).is_file())
            state = json.loads((session / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "restored")


if __name__ == "__main__":
    unittest.main()
