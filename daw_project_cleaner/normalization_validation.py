"""Validate a DAW-created control/Pool-cleaned pair without moving media."""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

from .format import AUDIO_EXTENSIONS, parse_project


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _active(parsed) -> Set[str]:
    return {
        name for name, offsets in parsed.occurrences.items()
        if offsets and any(offset < parsed.pool_offset for offset in offsets)
    }


def _pool_only(parsed) -> Set[str]:
    return {
        name for name, offsets in parsed.occurrences.items()
        if offsets and all(offset > parsed.pool_offset for offset in offsets)
    }


def _name_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


PATH_ROLE_RE = re.compile(rb"/(Audio|Edits|Freeze|Freezes)/", re.IGNORECASE)


def _path_roles(data: bytes, offsets: List[int]) -> Set[str]:
    roles: Set[str] = set()
    for offset in offsets:
        window = data[offset:min(len(data), offset + 384)]
        for match in PATH_ROLE_RE.finditer(window):
            raw = match.group(1).decode("ascii").casefold()
            roles.add("Freeze" if raw in {"freeze", "freezes"} else raw.title())
    return roles


def _media_role(path: Path, root: Path) -> str:
    parts = {part.casefold() for part in path.relative_to(root).parts[:-1]}
    if "audio" in parts:
        return "Audio"
    if "edits" in parts:
        return "Edits"
    if "freeze" in parts or "freezes" in parts:
        return "Freeze"
    return "Other"


def _resolve_media_paths(
    name: str, offsets: List[int], project_data: bytes,
    media: Dict[str, List[Path]], root: Path,
) -> List[Path]:
    matches = list(media.get(_name_key(name), []))
    if len(matches) <= 1:
        return matches
    roles = _path_roles(project_data, offsets)
    if not roles:
        return matches
    by_role = {
        role: [path for path in matches if _media_role(path, root) == role]
        for role in roles
    }
    if by_role and all(len(paths) == 1 for paths in by_role.values()):
        return [by_role[role][0] for role in sorted(by_role)]
    return matches


def _media_by_name(root: Path) -> Dict[str, List[Path]]:
    found: Dict[str, List[Path]] = {}
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        dirs[:] = [
            name for name in dirs
            if not (Path(current) / name).is_symlink()
        ]
        for name in files:
            path = Path(current) / name
            if path.is_symlink() or path.suffix.casefold() not in AUDIO_EXTENSIONS:
                continue
            found.setdefault(_name_key(name), []).append(path)
    return found


def validate_normalization_pair(
    control_path: Path,
    cleaned_path: Path,
    media_root: Path,
    daw_open_confirmed: bool = False,
) -> Dict:
    control_path = control_path.resolve(strict=True)
    cleaned_path = cleaned_path.resolve(strict=True)
    media_root = media_root.resolve(strict=True)
    if any(path.is_symlink() for path in (control_path, cleaned_path, media_root)):
        raise ValueError("Normalization inputs may not be symbolic links")
    if not media_root.is_dir():
        raise ValueError("Media root is not a directory")

    control = parse_project(control_path)
    cleaned = parse_project(cleaned_path)
    control_data = control_path.read_bytes()
    cleaned_data = cleaned_path.read_bytes()
    control_active = _active(control)
    cleaned_active = _active(cleaned)
    control_pool = _pool_only(control)
    cleaned_pool = _pool_only(cleaned)
    removed_pool = control_pool - cleaned_pool
    media = _media_by_name(media_root)

    blockers: List[Dict[str, str]] = []
    identity = (
        control.product, control.version, control.container,
        control.serialization_profile,
    )
    cleaned_identity = (
        cleaned.product, cleaned.version, cleaned.container,
        cleaned.serialization_profile,
    )
    if identity != cleaned_identity:
        blockers.append({"kind": "format_changed", "detail": str(cleaned_identity)})
    for name in sorted(control_active - cleaned_active, key=str.casefold):
        blockers.append({"kind": "active_reference_removed", "detail": name})
    for name in sorted(cleaned_active - control_active, key=str.casefold):
        blockers.append({"kind": "active_reference_added", "detail": name})
    for name in sorted(cleaned_pool, key=str.casefold):
        blockers.append({"kind": "pool_only_reference_remains", "detail": name})
    active_media_files = []
    active_seen = set()
    for name in sorted(control_active | cleaned_active, key=str.casefold):
        offsets = cleaned.occurrences.get(name) or control.occurrences.get(name, [])
        data = cleaned_data if cleaned.occurrences.get(name) else control_data
        matches = _resolve_media_paths(name, offsets, data, media, media_root)
        roles = _path_roles(data, offsets)
        resolved = len(matches) == 1 or (
            bool(roles)
            and len({_media_role(path, media_root) for path in matches}) == len(roles)
            and all(_media_role(path, media_root) in roles for path in matches)
        )
        if not resolved:
            blockers.append({
                "kind": "active_media_missing" if not matches else "active_media_ambiguous",
                "detail": name,
            })
            continue
        for path in matches:
            key = (path.stat().st_dev, path.stat().st_ino)
            if key in active_seen:
                continue
            active_seen.add(key)
            info = path.stat()
            active_media_files.append({
                "name": name, "path": str(path), "role": _media_role(path, media_root),
                "size_bytes": info.st_size, "sha256": _sha256(path),
            })

    candidates = []
    for name in sorted(removed_pool, key=str.casefold):
        offsets = control.occurrences.get(name, [])
        matches = _resolve_media_paths(
            name, offsets, control_data, media, media_root
        )
        roles = _path_roles(control_data, offsets)
        resolved = len(matches) == 1 or (
            bool(roles)
            and len({_media_role(path, media_root) for path in matches}) == len(roles)
            and all(_media_role(path, media_root) in roles for path in matches)
        )
        if not resolved:
            blockers.append({
                "kind": "candidate_media_missing" if not matches else "candidate_media_ambiguous",
                "detail": name,
            })
            continue
        for path in matches:
            info = path.stat()
            candidates.append({
                "name": name,
                "path": str(path),
                "role": _media_role(path, media_root),
                "size_bytes": info.st_size,
                "sha256": _sha256(path),
                "action": "quarantine_after_final_gate",
            })

    project_artifacts = []
    for path in sorted(media_root.rglob("*"), key=lambda item: str(item).casefold()):
        if not path.is_file() or path.is_symlink():
            continue
        # APFS may return a directory entry using a different Unicode
        # normalization form than the spelling supplied to resolve().  String
        # equality is therefore not a safe identity check for the CLEANED
        # survivor.  Compare the existing filesystem objects themselves.
        if os.path.samefile(path, cleaned_path):
            continue
        if path.suffix.casefold() not in {".cpr", ".npr", ".bak"}:
            continue
        project_artifacts.append({
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "action": "quarantine_with_original_project_state",
            "reason": (
                "Backup project is rollback state"
                if path.suffix.casefold() == ".bak" else
                "Non-surviving project may retain removed Pool references"
            ),
        })

    structural_valid = not blockers and bool(removed_pool)
    final_gate_passed = structural_valid and daw_open_confirmed
    stages = [
        {"name": "normalize_in_matching_daw", "status": "completed"},
        {
            "name": "remove_unused_media_from_pool",
            "status": "completed" if structural_valid else "blocked",
        },
        {
            "name": "create_self_contained_archive",
            "status": "completed" if structural_valid else "blocked",
        },
        {
            "name": "validate_all_references_exist",
            "status": "completed" if structural_valid else "blocked",
        },
        {
            "name": "validate_open_in_matching_daw",
            "status": "completed" if daw_open_confirmed else "awaiting_operator",
        },
        {"name": "quarantine_original", "status": "pending"},
    ]
    return {
        "schema_version": 1,
        "validation_mode": "read_only",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "media_root": str(media_root),
        "control": {"path": str(control_path), "sha256": control.sha256},
        "cleaned": {"path": str(cleaned_path), "sha256": cleaned.sha256},
        "format": {
            "product": cleaned.product, "version": cleaned.version,
            "container": cleaned.container,
            "serialization_profile": cleaned.serialization_profile,
        },
        "active_media": sorted(cleaned_active, key=str.casefold),
        "active_media_files": active_media_files,
        "removed_pool_only": sorted(removed_pool, key=str.casefold),
        "remaining_pool_only": sorted(cleaned_pool, key=str.casefold),
        "candidates": candidates,
        "project_artifacts_to_quarantine": project_artifacts,
        "blockers": blockers,
        "stages": stages,
        "summary": {
            "active_references": len(cleaned_active),
            "active_files": len(active_media_files),
            "removed_pool_references": len(removed_pool),
            "remaining_pool_references": len(cleaned_pool),
            "candidate_files": len(candidates),
            "candidate_bytes": sum(item["size_bytes"] for item in candidates),
            "structural_valid": structural_valid,
            "daw_open_confirmed": daw_open_confirmed,
            "final_gate_passed": final_gate_passed,
            "project_artifacts_to_quarantine": len(project_artifacts),
            "cleanup_authorized": False,
        },
        "safety": {
            "media_moves": False,
            "media_deletes": False,
            "project_writes": False,
            "cleanup_authorized": False,
            "reason": (
                "Read-only validation never moves or deletes files; a separate "
                "transaction must revalidate this report and quarantine the "
                "original project state with candidate media."
            ),
        },
    }


def save_normalization_validation(report: Dict, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)
