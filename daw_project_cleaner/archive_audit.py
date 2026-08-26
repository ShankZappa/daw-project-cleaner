"""Read-only archive topology audit for shared and nested DAW project folders."""
from __future__ import annotations

import fnmatch
import json
import os
import random
import re
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .format import AUDIO_EXTENSIONS, ProjectFormatError, parse_project


MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | {
    ".mov", ".mp4", ".m4v", ".avi", ".mxf", ".dv", ".jpg", ".jpeg",
    ".png", ".tif", ".tiff", ".bmp",
}
AUXILIARY_EXTENSIONS = {".bak", ".peak"}
AUDIT_EXCLUSIONS = [
    ".daw-project-cleaner-quarantine", ".nuendo-cleaner", ".Trash*",
    ".Spotlight-V100", ".fseventsd",
]
RESOLVED_REFERENCE_STATES = {"unique", "path_evidenced"}
PATH_ROLE_RE = re.compile(rb"/(Audio|Edits|Freeze|Freezes)/", re.IGNORECASE)


def _name_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _path_roles(data: bytes, offsets: Sequence[int]) -> List[str]:
    roles = set()
    for offset in offsets:
        # Inspected Steinberg objects store the source directory immediately
        # after the media filename. Keep the window tight so evidence from a
        # neighboring object cannot leak into this reference.
        window = data[offset:min(len(data), offset + 384)]
        for match in PATH_ROLE_RE.finditer(window):
            raw = match.group(1).decode("ascii").casefold()
            roles.add("Freeze" if raw in {"freeze", "freezes"} else raw.title())
    return sorted(roles)


def _excluded(name: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatch(name.casefold(), pattern.casefold()) for pattern in patterns)


def _role(path: Path, root: Path) -> str:
    parts = {part.casefold() for part in path.relative_to(root).parts[:-1]}
    if "audio" in parts:
        return "Audio"
    if "edits" in parts:
        return "Edits"
    if "freeze" in parts or "freezes" in parts:
        return "Freeze"
    if "mixdown" in parts or "mixdowns" in parts or "exports" in parts:
        return "Mixdown"
    if "auto saves" in parts or "autosaves" in parts or "backups" in parts:
        return "Auto Saves"
    if "images" in parts:
        return "Images"
    if "track pictures" in parts:
        return "Track Pictures"
    return "Other"


def _atomic_json(path: Path, value: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _discover(
    root: Path,
    exclusions: Sequence[str],
    progress: Optional[Callable[[str], None]],
) -> Tuple[List[Path], List[Dict], List[Dict], List[str]]:
    projects: List[Path] = []
    media: List[Dict] = []
    auxiliary: List[Dict] = []
    warnings: List[str] = []
    seen = 0

    def onerror(error: OSError) -> None:
        warnings.append(f"Cannot enumerate {error.filename}: {error.strerror}")

    for current, dirs, files in os.walk(root, topdown=True, followlinks=False, onerror=onerror):
        kept = []
        for name in dirs:
            entry = Path(current) / name
            if _excluded(name, exclusions):
                continue
            try:
                if entry.is_symlink():
                    warnings.append(f"Skipped symbolic-link directory: {entry}")
                    continue
            except OSError as exc:
                warnings.append(f"Cannot inspect {entry}: {exc}")
                continue
            kept.append(name)
        dirs[:] = kept
        for name in files:
            seen += 1
            entry = Path(current) / name
            suffix = entry.suffix.casefold()
            try:
                if entry.is_symlink():
                    warnings.append(f"Skipped symbolic-link file: {entry}")
                    continue
                if suffix in {".cpr", ".npr"}:
                    projects.append(entry)
                if suffix in MEDIA_EXTENSIONS:
                    info = entry.stat()
                    media.append({
                        "path": str(entry.absolute()),
                        "name": entry.name,
                        "extension": suffix,
                        "size_bytes": info.st_size,
                        "role": _role(entry, root),
                    })
                elif suffix in AUXILIARY_EXTENSIONS:
                    info = entry.stat()
                    auxiliary.append({
                        "path": str(entry.absolute()), "name": entry.name,
                        "extension": suffix, "size_bytes": info.st_size,
                        "role": _role(entry, root),
                    })
            except OSError as exc:
                warnings.append(f"Cannot inspect file {entry}: {exc}")
            if progress and seen % 1000 == 0:
                progress(f"Discovered {seen} files, {len(projects)} projects, {len(media)} media")
    return projects, media, auxiliary, warnings


def _inspect(path: Path) -> Dict:
    try:
        parsed = parse_project(path)
        data = path.read_bytes()
        references = []
        for name, offsets in sorted(parsed.occurrences.items(), key=lambda pair: pair[0].casefold()):
            classification = "active" if any(offset < parsed.pool_offset for offset in offsets) else "pool_only"
            references.append({
                "name": name, "classification": classification,
                "offsets": offsets, "embedded_path_roles": _path_roles(data, offsets),
            })
        return {
            "path": str(path.absolute()), "status": "parsed", "sha256": parsed.sha256,
            "product": parsed.product, "version": parsed.version,
            "container": parsed.container, "serialization_profile": parsed.serialization_profile,
            "confidence": parsed.confidence, "references": references,
            "warnings": parsed.warnings,
        }
    except (OSError, ValueError, ProjectFormatError) as exc:
        return {"path": str(path.absolute()), "status": "error", "error": str(exc), "references": []}


def audit_archive(
    root: Path,
    workers: int = 4,
    exclusions: Optional[Sequence[str]] = None,
    sample_projects: Optional[int] = None,
    seed: int = 89,
    progress: Optional[Callable[[str], None]] = None,
) -> Dict:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")
    patterns = list(exclusions or AUDIT_EXCLUSIONS)
    project_paths, media, auxiliary, warnings = _discover(root, patterns, progress)
    project_paths.sort(key=lambda path: str(path).casefold())
    discovered_project_count = len(project_paths)
    if sample_projects is not None and sample_projects < len(project_paths):
        project_paths = sorted(random.Random(seed).sample(project_paths, sample_projects), key=lambda path: str(path).casefold())
    projects: List[Dict] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as pool:
        futures = {pool.submit(_inspect, path): path for path in project_paths}
        for done, future in enumerate(as_completed(futures), 1):
            projects.append(future.result())
            if progress:
                progress(f"Parsed project {done}/{len(project_paths)}: {futures[future]}")
    projects.sort(key=lambda item: item["path"].casefold())

    media_by_name: Dict[str, List[Dict]] = defaultdict(list)
    for item in media:
        media_by_name[_name_key(item["name"])].append(item)
    path_users: Dict[str, List[Dict]] = defaultdict(list)
    path_ambiguous_users: Dict[str, List[Dict]] = defaultdict(list)
    unreadable = sum(project["status"] != "parsed" for project in projects)
    for project in projects:
        blockers = []
        resolved_size = 0
        resolved_paths: List[str] = []
        for reference in project["references"]:
            matches = media_by_name.get(_name_key(reference["name"]), [])
            path_roles = set(reference.get("embedded_path_roles", []))
            if len(matches) > 1 and path_roles:
                by_role = {
                    role: [match for match in matches if match["role"] == role]
                    for role in path_roles
                }
                if by_role and all(len(items) == 1 for items in by_role.values()):
                    matches = [by_role[role][0] for role in sorted(by_role)]
            reference["matches"] = [match["path"] for match in matches]
            path_evidenced = bool(path_roles) and matches and all(
                match["role"] in path_roles for match in matches
            ) and len({match["role"] for match in matches}) == len(path_roles)
            reference["resolution"] = (
                "path_evidenced" if path_evidenced else
                "unique" if len(matches) == 1 else
                "missing" if not matches else "ambiguous"
            )
            if reference["resolution"] in RESOLVED_REFERENCE_STATES:
                for match in matches:
                    resolved_size += match["size_bytes"]
                    resolved_paths.append(match["path"])
                    path_users[match["path"]].append({
                        "project": project["path"], "classification": reference["classification"]
                    })
            if reference["resolution"] == "unique":
                reference["resolution_evidence"] = (
                    "unicode_normalized_exact_name"
                    if reference["name"].casefold() != matches[0]["name"].casefold()
                    else "exact_basename"
                )
            elif reference["resolution"] == "path_evidenced":
                reference["resolution_evidence"] = "embedded_source_directory"
            elif len(matches) > 1:
                for match in matches:
                    path_ambiguous_users[match["path"]].append({
                        "project": project["path"], "classification": reference["classification"],
                        "name": reference["name"],
                    })
            if reference["resolution"] not in RESOLVED_REFERENCE_STATES:
                blockers.append({"name": reference["name"], "reason": reference["resolution"]})
        project["separation_plan"] = {
            "proposed_folder": Path(project["path"]).stem,
            "resolved_media_bytes": resolved_size,
            "resolved_media_paths": sorted(set(resolved_paths), key=str.casefold),
            "blockers": blockers,
            "ready_for_copy_test": project["status"] == "parsed" and not blockers,
            "project_rewrite_ready": False,
        }

    referenced_paths = set(path_users)
    ambiguous_paths = set(path_ambiguous_users)
    for item in media:
        users = path_users.get(item["path"], [])
        ambiguous_users = path_ambiguous_users.get(item["path"], [])
        item["references"] = users
        item["ambiguous_references"] = ambiguous_users
        item["reference_count"] = len(users)
        item["shared_between_projects"] = len({user["project"] for user in users + ambiguous_users}) > 1
        item["cleanup_classification"] = (
            "referenced" if users else
            "protected_ambiguous_reference" if ambiguous_users else
            "preserve_mixdown_export" if item["role"] == "Mixdown" else
            "review_only_unreferenced" if unreadable == 0 and sample_projects is None else
            "protected_incomplete_evidence"
        )

    # Projects with almost complete media containment are proposed as versions
    # of one project family. This prevents needless duplication (for example a
    # main project plus an ATMOS or shortened version). It is a review proposal,
    # never an automatic filesystem action.
    parent = list(range(len(projects)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a

    family_edges: List[Dict] = []
    project_sets = [set(project["separation_plan"]["resolved_media_paths"]) for project in projects]
    for left in range(len(projects)):
        for right in range(left + 1, len(projects)):
            a, b = project_sets[left], project_sets[right]
            if not a or not b:
                continue
            intersection = len(a & b)
            containment = intersection / min(len(a), len(b))
            jaccard = intersection / len(a | b)
            if containment >= 0.90:
                union(left, right)
                family_edges.append({
                    "left": projects[left]["path"], "right": projects[right]["path"],
                    "containment": containment, "jaccard": jaccard,
                })
    grouped: Dict[int, List[int]] = defaultdict(list)
    for index in range(len(projects)):
        grouped[find(index)].append(index)
    project_families = []
    for indexes in grouped.values():
        members = [projects[index]["path"] for index in indexes]
        stems = [Path(member).stem for member in members]
        common = os.path.commonprefix(stems).rstrip(" ._-()")
        proposed = common if len(common) >= 3 else stems[0]
        project_families.append({
            "proposed_folder": proposed,
            "members": members,
            "multi_project": len(members) > 1,
            "review_required": True,
        })

    roles: Dict[str, Dict[str, int]] = defaultdict(lambda: {
        "files": 0, "bytes": 0, "unreferenced_files": 0,
        "unreferenced_bytes": 0, "ambiguous_files": 0, "ambiguous_bytes": 0,
    })
    for item in media:
        role = roles[item["role"]]
        role["files"] += 1
        role["bytes"] += item["size_bytes"]
        if item["ambiguous_references"]:
            role["ambiguous_files"] += 1
            role["ambiguous_bytes"] += item["size_bytes"]
        elif not item["references"] and item["role"] != "Mixdown":
            role["unreferenced_files"] += 1
            role["unreferenced_bytes"] += item["size_bytes"]

    return {
        "schema_version": 1,
        "audit_mode": "read_only",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "sample": {"requested": sample_projects, "seed": seed},
        "summary": {
            "projects_discovered": discovered_project_count,
            "projects_audited": len(projects),
            "projects_unreadable": unreadable,
            "media_files": len(media),
            "media_bytes": sum(item["size_bytes"] for item in media),
            "referenced_media_files": len(referenced_paths),
            "ambiguous_protected_media_files": len(ambiguous_paths),
            "unreferenced_media_files": sum(
                item["cleanup_classification"] == "review_only_unreferenced" for item in media
            ),
            "preserved_mixdown_files": sum(
                item["cleanup_classification"] == "preserve_mixdown_export" for item in media
            ),
            "auxiliary_files": len(auxiliary),
            "auxiliary_bytes": sum(item["size_bytes"] for item in auxiliary),
            "shared_media_files": sum(item["shared_between_projects"] for item in media),
            "separation_copy_test_ready_projects": sum(project["separation_plan"]["ready_for_copy_test"] for project in projects),
            "project_rewrite_ready_projects": 0,
            "proposed_project_families": len(project_families),
            "multi_project_families": sum(family["multi_project"] for family in project_families),
        },
        "roles": dict(roles),
        "projects": projects,
        "project_families": project_families,
        "project_family_edges": family_edges,
        "media": media,
        "auxiliary": auxiliary,
        "warnings": warnings,
        "safety": {
            "server_writes": False,
            "cleanup_authorized": False,
            "project_rewrite_enabled": False,
            "unreferenced_is_deletable": False,
        },
    }


def save_audit(report: Dict, path: Path) -> None:
    _atomic_json(path, report)
