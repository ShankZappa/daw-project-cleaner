import tempfile
import unittest
from pathlib import Path

from daw_project_cleaner.format import ProjectFormatError, parse_project
from tests.helpers import make_project


class FormatTests(unittest.TestCase):
    def test_active_and_pool_side_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "song.npr"
            make_project(project, active=["used.wav"], unused=["take.wav"])
            parsed = parse_project(project)
            self.assertLess(parsed.occurrences["used.wav"][0], parsed.pool_offset)
            self.assertTrue(all(x > parsed.pool_offset for x in parsed.occurrences["take.wav"]))

    def test_riff_profile_is_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "song.cpr"
            make_project(project, active=["used.wav"], version="12.0.70", container="RIFF")
            parsed = parse_project(project)
            self.assertEqual(parsed.container, "RIFF")
            self.assertEqual(parsed.product, "Nuendo")
            self.assertEqual(parsed.version, "12.0.70")

    def test_invalid_outer_length_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "bad.npr"
            make_project(project)
            data = bytearray(project.read_bytes())
            data[11] ^= 1
            project.write_bytes(data)
            with self.assertRaises(ProjectFormatError):
                parse_project(project)


if __name__ == "__main__":
    unittest.main()
