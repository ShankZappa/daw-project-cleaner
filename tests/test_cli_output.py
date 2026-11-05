"""The command line as the app runs it: piped, under any locale, on macOS names.

The app launches the backend with both streams on one pipe and decodes every
line as UTF-8, dropping a line that is not. Folder and file names carry
Estonian letters, and macOS presents SMB and exFAT names decomposed (NFD), so
a combining mark such as U+0303 reaches the output as its own character.
"""
import json
import os
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

from tests.helpers import make_project


REPO = Path(__file__).resolve().parent.parent
COMPOSED = "Sõber äöüšž"
DECOMPOSED = unicodedata.normalize("NFD", "Lõpp Äike")

# Each one used to kill the backend before its first line reached the app.
HOSTILE_OUTPUT = {
    "ascii": {"PYTHONIOENCODING": "ascii:strict"},
    # An inherited ISO-8859 locale cannot encode a combining mark at all.
    "latin-1": {"PYTHONIOENCODING": "latin-1:strict"},
}
if sys.platform == "darwin":
    # The C locale with Python's UTF-8 mode and locale coercion off: an ASCII
    # stdout. Only on macOS, whose filesystem encoding stays UTF-8 regardless;
    # on Linux it would also make file names undecodable, a different fault.
    HOSTILE_OUTPUT["c-locale"] = {
        "LC_ALL": "C", "LANG": "C",
        "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0",
    }


def run_cli(arguments, extra_env):
    env = {"PATH": os.environ.get("PATH", os.defpath)}
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "daw_project_cleaner.cli", *arguments],
        cwd=str(REPO), env=env, capture_output=True,
    )


def utf8_lines(raw: bytes):
    """Decode as the app does; a line that is not UTF-8 fails the test."""
    return raw.decode("utf-8").splitlines()


class CliOutputEncodingTests(unittest.TestCase):
    def archive(self, base: Path) -> Path:
        root = base / "Archive"
        composed = root / COMPOSED
        (composed / "Audio").mkdir(parents=True)
        (composed / "Audio" / "võte üks.wav").write_bytes(b"take")
        (composed / "Audio" / "unused.wav").write_bytes(b"unused")
        make_project(
            composed / f"{COMPOSED}.npr",
            active=["võte üks.wav"], unused=["unused.wav"],
        )
        decomposed = root / DECOMPOSED
        take = unicodedata.normalize("NFD", "ään.wav")
        (decomposed / "Audio").mkdir(parents=True)
        (decomposed / "Audio" / take).write_bytes(b"take")
        make_project(decomposed / f"{DECOMPOSED}.npr", active=[take])
        saves = decomposed / "Auto Saves"
        saves.mkdir()
        for index in (1, 2):
            backup = saves / f"{DECOMPOSED}-0{index}.bak"
            make_project(backup, active=[take])
            os.utime(backup, (1_700_000_000 + index, 1_700_000_000 + index))
        return root

    def test_scan_output_is_utf8_whatever_the_locale(self):
        for label, extra_env in HOSTILE_OUTPUT.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as temporary:
                root = self.archive(Path(temporary))
                report_path = Path(temporary) / "report.json"
                result = run_cli(
                    ["scan", str(root), "--report", str(report_path),
                     "--events-jsonl", "--keep-backups", "1"],
                    extra_env,
                )
                self.assertEqual(
                    result.returncode, 0,
                    result.stderr.decode("utf-8", "backslashreplace"),
                )
                lines = utf8_lines(result.stdout)
                report = json.loads(report_path.read_text(encoding="utf-8"))
                paths = {project["path"] for project in report["projects"]}
                events = [
                    json.loads(line[len("PROJECT_EVENT "):])
                    for line in lines if line.startswith("PROJECT_EVENT ")
                ]
                self.assertEqual({event["path"] for event in events}, paths)
                # Both spellings reach the app exactly as the disk holds them.
                self.assertTrue(any(COMPOSED in path for path in paths))
                self.assertTrue(any(DECOMPOSED in path for path in paths))
                self.assertTrue(any(line.startswith("MEASURED ") for line in lines))
                self.assertTrue(any(
                    line.startswith("[") and DECOMPOSED in line for line in lines
                ))
                self.assertEqual(report["summary"]["errors"], 0)

    def test_backup_quarantine_and_restore_report_utf8(self):
        for label, extra_env in HOSTILE_OUTPUT.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                root = self.archive(base)
                quarantine = base / f"Karantiin {COMPOSED}"
                quarantine.mkdir()
                report_path = base / "report.json"
                scan = run_cli(
                    ["scan", str(root), "--report", str(report_path),
                     "--events-jsonl", "--keep-backups", "1"],
                    extra_env,
                )
                self.assertEqual(scan.returncode, 0)
                oldest = next(root.rglob(f"{DECOMPOSED}-01.bak"))

                applied = run_cli(
                    ["apply-backup-policy", str(report_path),
                     "--quarantine-root", str(quarantine),
                     "--confirm", "APPLY BACKUP POLICY"],
                    extra_env,
                )
                self.assertEqual(
                    applied.returncode, 0,
                    applied.stderr.decode("utf-8", "backslashreplace"),
                )
                lines = utf8_lines(applied.stdout)
                self.assertTrue(any(
                    line.startswith("[1/1] ") and DECOMPOSED in line
                    for line in lines
                ))
                session = next(
                    line[len("BACKUP SESSION: "):] for line in lines
                    if line.startswith("BACKUP SESSION: ")
                )
                self.assertIn(COMPOSED, session)
                self.assertFalse(oldest.exists())

                restored = run_cli(["restore", session], extra_env)
                self.assertEqual(restored.returncode, 0)
                self.assertIn("Restored files: 1", utf8_lines(restored.stdout))
                self.assertTrue(oldest.is_file())

    def test_a_refusal_naming_a_decomposed_path_reaches_the_app(self):
        """The alert shows this line; Latin-1 bytes would be dropped unseen."""
        for label, extra_env in HOSTILE_OUTPUT.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                root = self.archive(base)
                quarantine = base / "Quarantine"
                quarantine.mkdir()
                report_path = base / "report.json"
                self.assertEqual(run_cli(
                    ["scan", str(root), "--report", str(report_path),
                     "--keep-backups", "1"],
                    extra_env,
                ).returncode, 0)
                oldest = next(root.rglob(f"{DECOMPOSED}-01.bak"))
                oldest.write_bytes(oldest.read_bytes() + b"changed")

                refused = run_cli(
                    ["apply-backup-policy", str(report_path),
                     "--quarantine-root", str(quarantine),
                     "--confirm", "APPLY BACKUP POLICY"],
                    extra_env,
                )
                self.assertEqual(refused.returncode, 3)
                message = utf8_lines(refused.stderr)
                self.assertTrue(any(
                    line.startswith("Refused: ") and DECOMPOSED in line
                    for line in message
                ), message)
                self.assertTrue(oldest.is_file())


if __name__ == "__main__":
    unittest.main()
