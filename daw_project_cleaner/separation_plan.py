"""Read-only plan for separating projects that share one legacy media tree.

The plan deliberately does not copy, move, rewrite or delete files.  It turns a
complete archive audit into explicit per-project manifests and keeps retirement
of the mother/master project behind independent evidence gates.
"""
from __future__ import annotations

import hashlib
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from .archive_audit import RESOLVED_REFERENCE_STATES


ROLE_FOLDERS = {
    "Audio": "Audio",
    "Edits": "Edits",
    "Freeze": "Freeze",
    "Images": "Images",
    "Track Pictures": "Track Pictures",
    "Mixdown": "Mixdown",
    "Other": "Media",
}


def _name_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _external_media(files: Optional[Iterable[Path]]) -> Dict[str, Dict]:
    """Validate exact-name operator resolutions without modifying any file."""
    resolved: Dict[str, Dict] = {}
    for supplied in files or []:
        path = Path(supplied).expanduser().resolve(strict=True)
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing-media resolution is not a regular file: {path}")
        key = _name_key(path.name)
        if key in resolved:
            raise ValueError(f"Duplicate missing-media resolution name: {path.name}")
        resolved[key] = {
            "path": str(path),
            "name": path.name,
            "role": "Audio",
            "size_bytes": path.stat().st_size,
            "shared_between_projects": False,
            "external_exact_name_resolution": True,
        }
    return resolved


def _plan_id(audit: Dict) -> str:
    payload = "\n".join(
        sorted(
            (project.get("sha256") or project.get("path", ""))
            for project in audit.get("projects", [])
        )
    ).encode("utf-8")
    return "separation-" + hashlib.sha256(payload).hexdigest()[:12]


def _unique_paths(project: Dict, external: Optional[Dict[str, Dict]] = None) -> Set[str]:
    paths = {
        match
        for reference in project.get("references", [])
        if reference.get("resolution") in RESOLVED_REFERENCE_STATES
        for matches in [reference.get("matches", [])]
        if matches
        for match in matches
    }
    for reference in project.get("references", []):
        if reference.get("resolution") != "missing":
            continue
        item = (external or {}).get(_name_key(reference.get("name", "")))
        if item:
            paths.add(item["path"])
    return paths


def _reference_blockers(
    project: Dict, external: Optional[Dict[str, Dict]] = None,
) -> List[Dict[str, str]]:
    if project.get("status") != "parsed":
        return [{
            "kind": "unreadable_project",
            "detail": project.get("error") or "Project could not be parsed",
        }]
    return [
        {
            "kind": f"{reference.get('resolution')}_media_reference",
            "detail": reference.get("name", "Unknown media"),
        }
        for reference in project.get("references", [])
        if reference.get("resolution") not in RESOLVED_REFERENCE_STATES
        and not (
            reference.get("resolution") == "missing"
            and _name_key(reference.get("name", "")) in (external or {})
        )
    ]


def _matches_master(project: Dict, master_project: Optional[str]) -> bool:
    if not master_project:
        return False
    requested = Path(master_project)
    actual = Path(project.get("path", ""))
    return actual == requested or actual.name.casefold() == requested.name.casefold()


def build_separation_plan(
    audit: Dict,
    destination_root: Path,
    master_project: Optional[str] = None,
    target_application: str = "Nuendo 15",
    missing_media_files: Optional[Iterable[Path]] = None,
) -> Dict:
    """Build per-project self-contained copy manifests from a complete audit."""
    if audit.get("audit_mode") != "read_only":
        raise ValueError("Separation planning requires a read-only archive audit")
    if audit.get("sample", {}).get("requested") is not None:
        raise ValueError("A sampled audit cannot produce a separation plan")
    projects = list(audit.get("projects", []))
    if len(projects) != audit.get("summary", {}).get("projects_discovered"):
        raise ValueError("Archive audit is incomplete")
    if not projects:
        raise ValueError("Archive audit contains no projects")

    destination_root = Path(destination_root).absolute()
    external = _external_media(missing_media_files)
    media_by_path = {item["path"]: item for item in audit.get("media", [])}
    media_by_path.update({item["path"]: item for item in external.values()})
    missing_reference_keys = {
        _name_key(reference.get("name", ""))
        for project in projects
        for reference in project.get("references", [])
        if reference.get("resolution") == "missing"
    }
    unused_external = set(external) - missing_reference_keys
    if unused_external:
        names = ", ".join(external[key]["name"] for key in sorted(unused_external))
        raise ValueError(f"Resolution file does not match a missing reference: {names}")
    master_matches = [p for p in projects if _matches_master(p, master_project)]
    if master_project and len(master_matches) != 1:
        raise ValueError("Master project must identify exactly one audited project")
    master = master_matches[0] if master_matches else None
    child_projects = [project for project in projects if project is not master]
    child_union: Set[str] = set().union(*(_unique_paths(p, external) for p in child_projects))

    manifests: List[Dict] = []
    all_project_paths: List[Set[str]] = []
    for project in projects:
        source = Path(project.get("path", ""))
        folder = destination_root / source.stem
        blockers = _reference_blockers(project, external)
        resolved = _unique_paths(project, external)
        all_project_paths.append(resolved)
        files = []
        destination_seen: Dict[str, str] = {}
        for media_path in sorted(resolved, key=str.casefold):
            item = media_by_path.get(media_path)
            if item is None:
                blockers.append({
                    "kind": "media_missing_from_audit_inventory",
                    "detail": media_path,
                })
                continue
            role = item.get("role", "Other")
            relative = str(Path(ROLE_FOLDERS.get(role, "Media")) / item["name"])
            folded = relative.casefold()
            if folded in destination_seen and destination_seen[folded] != media_path:
                blockers.append({
                    "kind": "destination_collision",
                    "detail": relative,
                })
                continue
            destination_seen[folded] = media_path
            files.append({
                "source": media_path,
                "destination_relative": relative,
                "role": role,
                "size_bytes": item.get("size_bytes", 0),
                "shared_between_projects": item.get("shared_between_projects", False),
                "sha256_required_before_copy": True,
                "external_exact_name_resolution": bool(
                    item.get("external_exact_name_resolution")
                ),
            })
        no_supported_references = project.get("status") == "parsed" and not project.get("references")
        if no_supported_references:
            blockers.append({
                "kind": "no_supported_media_references",
                "detail": "Project ownership cannot be proved from the current reader",
            })
        manifests.append({
            "project": str(source),
            "project_sha256": project.get("sha256"),
            "is_master": project is master,
            "destination_folder": str(folder),
            "destination_project": str(folder / source.name),
            "media": files,
            "media_files": len(files),
            "media_bytes": sum(item["size_bytes"] for item in files),
            "blockers": blockers,
            "copy_manifest_ready": not blockers,
            "normalized_project_required": True,
            "daw_open_playback_confirmation": False,
            "published": False,
        })

    union_paths: Set[str] = set().union(*all_project_paths)
    union_bytes = sum(media_by_path[path].get("size_bytes", 0) for path in union_paths if path in media_by_path)
    copied_bytes = sum(manifest["media_bytes"] for manifest in manifests)

    if master is None:
        master_gate = {
            "status": "not_selected",
            "retirement_authorized": False,
            "reason": "Select a master project explicitly before evaluating retirement.",
        }
    else:
        master_paths = _unique_paths(master, external)
        master_blockers = _reference_blockers(master, external)
        if not master.get("references"):
            evidence = "unverifiable_no_supported_references"
            covered = False
        else:
            covered = not master_blockers and master_paths.issubset(child_union)
            evidence = "covered_by_child_union" if covered else "not_covered_by_child_union"
        master_gate = {
            "status": evidence,
            "master_project": master.get("path"),
            "master_references": len(master_paths),
            "covered_references": len(master_paths & child_union),
            "all_child_projects_normalized": False,
            "all_child_projects_daw_validated": False,
            "all_child_projects_published": False,
            "mother_folder_quarantined": False,
            "retention_period_elapsed": False,
            "retirement_authorized": False,
            "reason": (
                "Current parser cannot prove what the master project owns. Keep it."
                if evidence == "unverifiable_no_supported_references" else
                "Reference coverage is necessary but DAW validation and quarantine retention are still pending."
                if covered else
                "Child projects do not cover every resolvable master reference."
            ),
        }

    return {
        "schema_version": 1,
        "plan_mode": "read_only_separation_plan",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "id": _plan_id(audit),
        "source_root": audit.get("root"),
        "destination_root": str(destination_root),
        "target_application": target_application,
        "summary": {
            "projects": len(manifests),
            "copy_manifest_ready": sum(m["copy_manifest_ready"] for m in manifests),
            "blocked": sum(not m["copy_manifest_ready"] for m in manifests),
            "unique_media_files": len(union_paths),
            "unique_media_bytes": union_bytes,
            "planned_copy_bytes": copied_bytes,
            "shared_media_duplication_bytes": max(copied_bytes - union_bytes, 0),
            "master_retirement_authorized": False,
            "filesystem_writes": 0,
        },
        "projects": manifests,
        "external_media_resolutions": [
            external[key] for key in sorted(external)
        ],
        "master_retirement_gate": master_gate,
        "required_next_gates": [
            "fresh_complete_audit_with_stable project and media hashes",
            "copy-only same-filesystem staging session",
            "normalize each child with the target DAW into its own folder",
            "open/play/save/reopen every surviving child project",
            "quarantine the complete mother folder with exact Restore",
            "retain master until its content is proven redundant or explicitly approved",
        ],
        "safety": {
            "source_writes": False,
            "copy_execution_enabled": False,
            "mother_folder_quarantine_enabled": False,
            "master_retirement_authorized": False,
            "permanent_deletion_enabled": False,
        },
    }
