"""Reproducible validation gate for exact-profile project writers.

This module never modifies a corpus input and never enables production cleanup.
It writes generated projects only into temporary directories.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .format import parse_project
from .rewrite_profiles import (
    CUBASE_12_PROFILE,
    NUENDO_14_PROFILE,
    NUENDO_15_PROFILE,
    ExperimentalRewriteError,
    RewriteAudit,
    rewrite_remove_pool_only,
    rewrite_remove_pool_only_cubase12,
)


@dataclass(frozen=True)
class ValidationCase:
    case_id: str
    source_relative: str
    official_cleaned_relative: str
    source_sha256: str
    official_cleaned_sha256: str
    product: str
    version: str
    container: str
    serialization_profile: str
    writer: Callable[[Path], Tuple[bytes, RewriteAudit]]
    application_resave_relative: Optional[str] = None
    application_resave_sha256: Optional[str] = None
    exact_pool_prefix_bytes: int = 0
    pool_prefix_ignore_ranges: Tuple[Tuple[int, int], ...] = ()
    expected_deleted_bytes: Optional[int] = None
    expected_delete_range_count: Optional[int] = None
    expected_reference_count: Optional[int] = None


@dataclass(frozen=True)
class CompatibilityCase:
    case_id: str
    source_relative: str
    resave_relative: str
    source_sha256: str
    resave_sha256: str
    source_version: str
    resave_version: str
    expected_active: Tuple[str, ...]
    expected_absent: Tuple[str, ...]


CASES = [
    ValidationCase(
        "nuendo-14.0.41-one-unused-converted", "ONE_UNUSED/CONTROL.npr",
        "ONE_UNUSED/CLEANED.npr",
        "7cb2110702143ae4105095eae3d747897bb4839d0ac67cfc58b92e3754381058",
        "119425d03cb659beccab6ea5c386ab526e2f1415cce40840329e1a940d018a79",
        "Nuendo", "14.0.41", "RIF2", NUENDO_14_PROFILE,
        rewrite_remove_pool_only,
    ),
    ValidationCase(
        "nuendo-14.0.41-two-unused-native", "TWO_UNUSED/CONTROL.npr",
        "TWO_UNUSED/CLEANED.npr",
        "520dc131dd688cb4a8e1e13887a7f51f3f0564b2d5e0b9756c3c23dc80db7990",
        "548a2dbcca86466eb9ae852e0c9671053852bbd8d9a09c7d4d1da27b39161b47",
        "Nuendo", "14.0.41", "RIF2", NUENDO_14_PROFILE,
        rewrite_remove_pool_only,
        "TWO_UNUSED/Nuendo14-TWO_UNUSED-EXPERIMENTAL-v2 RESAVE.npr",
        "c823785cd747e02728fd3b183def22c1ef48376e4054b4e6d4760c4ba0d79663",
        194,
    ),
    ValidationCase(
        "cubase-12.0.70-two-unused-native", "TWO_UNUSED_CUBASE/CONTROL.cpr",
        "TWO_UNUSED_CUBASE/CLEANED.cpr",
        "e453dbd679290fffef37c8b4616c9bd78def48dcc919750e62455e92199b4f8b",
        "49e0a0c17d045af4a7a2ced3dcb72f002ec0374f388182d86b5596ada78eb677",
        "Cubase", "12.0.70", "RIFF", CUBASE_12_PROFILE,
        rewrite_remove_pool_only_cubase12,
        "TWO_UNUSED_CUBASE/Cubase12-TWO_UNUSED-EXPERIMENTAL-v1.cpr",
        "0ae5fe4998c94d460f164cb2db61327f9768b644b35cc9c6869a789a7d85d728",
        150,
    ),
    ValidationCase(
        "nuendo-15.0.30-two-unused-native",
        "NUENDO15_VALIDATION/PROJECT/CONTROL.npr",
        "NUENDO15_VALIDATION/PROJECT/CLEAN.npr",
        "3530c3d528a500be3827e91479d8eea0303d201f07701b306256043761d37e53",
        "dea3e00a301500f38cd1b18196a076a99f9d9b772eff75256deeb6748131aab8",
        "Nuendo", "15.0.30", "RIF2", NUENDO_15_PROFILE,
        rewrite_remove_pool_only,
        "NUENDO15_VALIDATION/PROJECT/GENERATED_RESAVE.npr",
        "fda6782dd6428d9a49783fc69c35167cf60f4adcc13038e06321d8578ba7827e",
        exact_pool_prefix_bytes=194,
        # CLEAN is two characters shorter than CONTROL. Nuendo stores the
        # later Save-As name inside PPool, so the leading eight-byte PPool
        # object length differs even though the retained tree is identical.
        pool_prefix_ignore_ranges=((12, 20),),
    ),
    ValidationCase(
        "nuendo-15.0.30-multi-active-three-unused",
        "NUENDO15_MULTI_ACTIVE/PROJECT/CONTROL.npr",
        "NUENDO15_MULTI_ACTIVE/PROJECT/CLEANED.npr",
        "d69211b58915012d578cd65a093f2a9daae75adfd331543bb7c9f76756ccdfc5",
        "6cf9115960179f249dc703d1c55042d2274065bf56d55990c34ef12a43b2e182",
        "Nuendo", "15.0.30", "RIF2", NUENDO_15_PROFILE,
        rewrite_remove_pool_only,
        "NUENDO15_MULTI_ACTIVE/PROJECT/GENERATED_RESAVE.npr",
        "fd706bb258f679f0e048de01354aed7cf4a06df2aad6c6292ecd84531484a883",
        exact_pool_prefix_bytes=275,
        # Manual Pool cleanup changed one retained GTreeEntry UI-state byte
        # (CONTROL 0x60, CLEANED 0x70). It is not a length, count, media name,
        # or archive reference, so preserve the source state and mask only
        # this byte when comparing the structural prefix.
        pool_prefix_ignore_ranges=((90, 91),),
    ),
    ValidationCase(
        "nuendo-15.0.30-interleaved-three-unused",
        "NUENDO15_INTERLEAVED/PROJECT/CONTROL.npr",
        "NUENDO15_INTERLEAVED/PROJECT/CLEANED.npr",
        "905597966d2cb57fa086552a575d2432f81024106ea171091fb779395929145e",
        "1e25170e72541f14a4058e77986dc4620bd945f10a81926186c51fb5bcadda4d",
        "Nuendo", "15.0.30", "RIF2", NUENDO_15_PROFILE,
        rewrite_remove_pool_only,
        "NUENDO15_INTERLEAVED/PROJECT/GENERATED_RESAVE.npr",
        "dcf4d2136b5132880b7db263f602c13bb377b8dce8c85e368e222e147a2feb67",
        exact_pool_prefix_bytes=278,
        # Nuendo's manual cleanup reserialized the retained GTree presentation
        # flags (0x60/0x42/0x0263 -> 0x70/0x52/0x0361). The writer preserves
        # the source flags; that retained-three shape is already application-
        # validated by NUENDO15_MULTI_ACTIVE. Mask flags, not lengths/counts.
        pool_prefix_ignore_ranges=(
            (90, 91), (120, 121),
            (149, 151), (200, 202), (251, 253),
        ),
    ),
    ValidationCase(
        "nuendo-14.0.41-real-pool-six-unused",
        "NUENDO14_REAL_POOL/CONTROL.npr",
        "NUENDO14_REAL_POOL/CLEANED.npr",
        "16784c8ad15518648acea400f7f02a146c196e98f1905dfcfcaf477775e88ba2",
        "f450dd5fe550a5105677bf1d5a318b153fe43b2b4440fae79b6162df44688edf",
        "Nuendo", "14.0.41", "RIF2", NUENDO_14_PROFILE,
        rewrite_remove_pool_only,
        "NUENDO14_REAL_POOL/GENERATED_RESAVE.npr",
        "6c49a1bd5dfea8093a2834f3623fc209f1bc4c799a26aee602c8d2340014a2d9",
        expected_deleted_bytes=50197,
        expected_delete_range_count=6,
        expected_reference_count=3,
    ),
    ValidationCase(
        "nuendo-15.0.30-real-pool-six-unused",
        "NUENDO15_REAL_POOL/CONTROL.npr",
        "NUENDO15_REAL_POOL/GENERATED_RESAVE.npr",
        "20b9301282049c75d3c8418066adefa56c3a79ca9ae29e275fa333d9fe0c77cb",
        "8f3400163af09cc997adebbdf583fa9f632277b9942e93506177f199c298c967",
        "Nuendo", "15.0.30", "RIF2", NUENDO_15_PROFILE,
        rewrite_remove_pool_only,
        "NUENDO15_REAL_POOL/GENERATED_RESAVE.npr",
        "8f3400163af09cc997adebbdf583fa9f632277b9942e93506177f199c298c967",
        expected_deleted_bytes=50083,
        expected_delete_range_count=6,
        expected_reference_count=3,
    ),
]


COMPATIBILITY_CASES = [
    CompatibilityCase(
        "nuendo-15.0.30-generated-opened-and-resaved-in-15.0.20",
        "NUENDO15_INTERLEAVED/PROJECT/GENERATED.npr",
        "NUENDO15_INTERLEAVED/PROJECT/NETWORK_VALIDATION_RESAVE_N15_0_20.npr",
        "50cb13bddd2d53a2c2b3362911cc69a2915c852c98e9fdfc62126cfd1bdb5ac0",
        "f4f95a21f4de4b59a03a8672d8338331e59e77e3f49ec0569c38a0a0c4473d5d",
        "15.0.30", "15.0.20",
        ("01_ACTIVE.wav", "03_ACTIVE.wav", "05_ACTIVE.wav"),
        ("02_UNUSED.wav", "04_UNUSED.wav", "06_UNUSED.wav"),
    ),
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pool_only(parsed) -> List[str]:
    return sorted(
        name for name, offsets in parsed.occurrences.items()
        if offsets and all(offset > parsed.pool_offset for offset in offsets)
    )


def _active(parsed) -> List[str]:
    return sorted(
        name for name, offsets in parsed.occurrences.items()
        if offsets and any(offset < parsed.pool_offset for offset in offsets)
    )


def validate_case(corpus_root: Path, case: ValidationCase) -> Dict:
    source = (corpus_root / case.source_relative).resolve(strict=True)
    official = (corpus_root / case.official_cleaned_relative).resolve(strict=True)
    if source.is_symlink() or official.is_symlink():
        raise ValueError("Validation corpus entries may not be symbolic links")
    checks: Dict[str, bool] = {}
    checks["source_hash_pinned"] = _sha256(source) == case.source_sha256
    checks["official_hash_pinned"] = _sha256(official) == case.official_cleaned_sha256
    if not all(checks.values()):
        raise ValueError(f"Pinned corpus hash mismatch in {case.case_id}")

    before = parse_project(source)
    official_parsed = parse_project(official)
    expected_identity = (
        case.product, case.version, case.container, case.serialization_profile
    )
    checks["source_exact_profile"] = (
        before.product, before.version, before.container, before.serialization_profile
    ) == expected_identity
    checks["official_exact_profile"] = (
        official_parsed.product, official_parsed.version, official_parsed.container,
        official_parsed.serialization_profile
    ) == expected_identity
    input_pool_only = _pool_only(before)
    input_active = _active(before)
    checks["input_has_pool_only"] = bool(input_pool_only)

    output, audit = case.writer(source)
    with tempfile.TemporaryDirectory(prefix="daw-rewrite-validation-") as temporary:
        generated = Path(temporary) / ("generated" + source.suffix)
        generated.write_bytes(output)
        after = parse_project(generated)
    checks["generated_exact_profile"] = (
        after.product, after.version, after.container, after.serialization_profile
    ) == expected_identity
    checks["active_media_unchanged"] = _active(after) == input_active
    checks["pool_only_removed"] = not _pool_only(after)
    checks["official_media_state_matches"] = (
        _active(after) == _active(official_parsed) and
        _pool_only(after) == _pool_only(official_parsed)
    )
    checks["audit_source_hash_matches"] = audit.source_sha256 == case.source_sha256
    checks["output_hash_matches_bytes"] = audit.output_sha256 == hashlib.sha256(output).hexdigest()
    checks["removed_names_absent"] = all(name.encode("utf-8") not in output for name in input_pool_only)
    if case.expected_deleted_bytes is not None:
        checks["deleted_bytes_match"] = (
            audit.deleted_bytes == case.expected_deleted_bytes
        )
    if case.expected_delete_range_count is not None:
        checks["delete_range_count_matches"] = (
            len(audit.delete_ranges) == case.expected_delete_range_count
        )
    if case.expected_reference_count is not None:
        checks["reference_count_matches"] = (
            len(audit.reference_fields) == case.expected_reference_count
        )
    if case.exact_pool_prefix_bytes:
        start_after = after.pool_offset - 4
        start_official = official_parsed.pool_offset - 4
        generated_prefix = bytearray(output[start_after:start_after + case.exact_pool_prefix_bytes])
        official_prefix = bytearray(official.read_bytes()[start_official:start_official + case.exact_pool_prefix_bytes])
        for begin, end in case.pool_prefix_ignore_ranges:
            if begin < 0 or end < begin or end > case.exact_pool_prefix_bytes:
                raise ValueError(f"Invalid pool-prefix ignore range in {case.case_id}")
            generated_prefix[begin:end] = b"\x00" * (end - begin)
            official_prefix[begin:end] = b"\x00" * (end - begin)
        checks["official_pool_prefix_matches"] = generated_prefix == official_prefix

    application_evidence = False
    if case.application_resave_relative and case.application_resave_sha256:
        resaved = (corpus_root / case.application_resave_relative).resolve(strict=True)
        checks["application_resave_hash_pinned"] = _sha256(resaved) == case.application_resave_sha256
        resaved_parsed = parse_project(resaved)
        checks["application_resave_exact_profile"] = (
            resaved_parsed.product, resaved_parsed.version, resaved_parsed.container,
            resaved_parsed.serialization_profile
        ) == expected_identity
        checks["application_resave_media_state_matches"] = (
            _active(resaved_parsed) == input_active and not _pool_only(resaved_parsed)
        )
        application_evidence = all(
            checks[name] for name in (
                "application_resave_hash_pinned", "application_resave_exact_profile",
                "application_resave_media_state_matches",
            )
        )

    structural_pass = all(checks.values())
    promotion = "application-validated-pilot" if structural_pass and application_evidence else "structural-only"
    return {
        "case_id": case.case_id,
        "profile": {
            "product": case.product, "version": case.version,
            "container": case.container, "serialization_profile": case.serialization_profile,
        },
        "checks": checks,
        "structural_pass": structural_pass,
        "application_resave_evidence": application_evidence,
        "promotion_status": promotion,
        "input_active": input_active,
        "input_pool_only": input_pool_only,
        "rewrite_audit": asdict(audit),
    }


def validate_compatibility_case(corpus_root: Path, case: CompatibilityCase) -> Dict:
    source = (corpus_root / case.source_relative).resolve(strict=True)
    resave = (corpus_root / case.resave_relative).resolve(strict=True)
    if source.is_symlink() or resave.is_symlink():
        raise ValueError("Compatibility evidence may not be a symbolic link")
    source_parsed = parse_project(source)
    resave_parsed = parse_project(resave)
    checks = {
        "source_hash_pinned": _sha256(source) == case.source_sha256,
        "resave_hash_pinned": _sha256(resave) == case.resave_sha256,
        "source_version_pinned": source_parsed.version == case.source_version,
        "resave_version_pinned": resave_parsed.version == case.resave_version,
        "product_matches": source_parsed.product == resave_parsed.product == "Nuendo",
        "container_matches": source_parsed.container == resave_parsed.container == "RIF2",
        "serialization_profile_matches": (
            source_parsed.serialization_profile == resave_parsed.serialization_profile
        ),
        "source_active_matches": tuple(_active(source_parsed)) == case.expected_active,
        "resave_active_matches": tuple(_active(resave_parsed)) == case.expected_active,
        "source_has_no_pool_only": not _pool_only(source_parsed),
        "resave_has_no_pool_only": not _pool_only(resave_parsed),
        "removed_names_absent_from_resave": all(
            name.encode("utf-8") not in resave.read_bytes()
            for name in case.expected_absent
        ),
    }
    return {
        "case_id": case.case_id,
        "checks": checks,
        "pass": all(checks.values()),
        "scope": "exact-controlled-shape-patch-compatibility-only",
    }


def validate_corpus(corpus_root: Path) -> Dict:
    corpus_root = corpus_root.resolve(strict=True)
    results = []
    for case in CASES:
        try:
            results.append(validate_case(corpus_root, case))
        except Exception as exc:
            results.append({"case_id": case.case_id, "structural_pass": False, "error": str(exc), "promotion_status": "blocked"})
    compatibility_results = []
    for case in COMPATIBILITY_CASES:
        try:
            compatibility_results.append(validate_compatibility_case(corpus_root, case))
        except Exception as exc:
            compatibility_results.append({
                "case_id": case.case_id, "pass": False, "error": str(exc),
                "scope": "exact-controlled-shape-patch-compatibility-only",
            })
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus_root": str(corpus_root),
        "production_writer_enabled": False,
        "results": results,
        "compatibility_results": compatibility_results,
        "summary": {
            "cases": len(results),
            "structural_pass": sum(item.get("structural_pass", False) for item in results),
            "application_validated": sum(item.get("promotion_status") == "application-validated-pilot" for item in results),
            "blocked": sum(not item.get("structural_pass", False) for item in results),
            "compatibility_cases": len(compatibility_results),
            "compatibility_pass": sum(
                item.get("pass", False) for item in compatibility_results
            ),
        },
    }


def save_validation(report: Dict, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)
