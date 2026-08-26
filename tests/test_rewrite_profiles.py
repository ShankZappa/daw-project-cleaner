import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from daw_project_cleaner.rewrite_profiles import (
    ExperimentalRewriteError,
    NUENDO_14_PROFILE,
    RewriteAudit,
    _require_trailing_unused_branch,
    _text_field_token,
    application_validated_shape_label,
    rewrite_for_exact_profile,
)
from tests.helpers import make_project


class RewriteProfileGateTests(unittest.TestCase):
    def test_application_validated_shape_requires_exact_topology(self):
        parsed = SimpleNamespace(
            product="Nuendo", version="14.0.41", container="RIF2",
            serialization_profile=NUENDO_14_PROFILE, pool_offset=100,
            occurrences={
                "ACTIVE.wav": [10, 120],
                "UNUSED_A.wav": [200],
                "UNUSED_B.wav": [300],
            },
        )
        audit = RewriteAudit(
            source_sha256="a", output_sha256="b", delete_start=200,
            delete_end=400, deleted_bytes=200,
            pool_only_names=["UNUSED_A.wav", "UNUSED_B.wav"],
            length_fields=list(range(8)), reference_fields=list(range(3)),
            delete_ranges=[(200, 300), (300, 400)],
        )
        self.assertEqual(
            application_validated_shape_label(parsed, audit),
            "Nuendo 14 native two-unused",
        )
        parsed.occurrences["ACTIVE_2.wav"] = [20, 130]
        self.assertIsNone(application_validated_shape_label(parsed, audit))
    def test_unknown_profile_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "unknown.npr"
            make_project(project, active=["active.wav"], unused=["unused.wav"], version="15.0.20")
            with self.assertRaises(ExperimentalRewriteError):
                rewrite_for_exact_profile(project)

    def test_trailing_unused_branch_accepts_retained_labels_before_boundary(self):
        active = _text_field_token("ACTIVE")
        unused = _text_field_token("UNUSED")
        data = b"P" * 32 + active + b"X" * 32 + unused + b"C" * 32
        boundary = data.find(unused) - 4
        _require_trailing_unused_branch(
            data, 0, len(data), boundary, ["ACTIVE.wav"]
        )

    def test_trailing_branch_gate_refuses_interleaved_layout(self):
        first = _text_field_token("ACTIVE_FIRST")
        unused = _text_field_token("UNUSED")
        retained = _text_field_token("ACTIVE_LATER")
        data = b"P" * 32 + first + b"X" * 32 + unused + b"Y" * 32 + retained
        boundary = data.find(unused) - 4
        with self.assertRaisesRegex(
            ExperimentalRewriteError, "interleaved with retained entries"
        ):
            _require_trailing_unused_branch(
                data, 0, len(data), boundary,
                ["ACTIVE_FIRST.wav", "ACTIVE_LATER.wav"],
            )


if __name__ == "__main__":
    unittest.main()
