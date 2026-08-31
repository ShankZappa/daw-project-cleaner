"""Build a fail-closed Nuendo 15 archive-normalization queue.

The queue is planning data only. It never launches a DAW and never writes to an
archive. Projects that resolve to any of the same media files are kept in one
family so a later cleanup cannot make a decision from only one version.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set

from .archive_audit import RESOLVED_REFERENCE_STATES


WORKFLOW_STAGES = [
    "normalize_in_nuendo_15",
    "remove_unused_media_from_pool",
    "create_self_contained_archive",
    "validate_all_references_exist",
    "validate_open_in_nuendo_15",
    "quarantine_original",
]


def _family_id(paths: List[str]) -> str:
    canonical = "\n".join(sorted(paths, key=str.casefold)).encode("utf-8")
    return "family-" + hashlib.sha256(canonical).hexdigest()[:12]


def _project_paths(project: Dict) -> Set[str]:
    paths: Set[str] = set()
    for reference in project.get("references", []):
        if reference.get("resolution") == "unique":
            matches = reference.get("matches", [])
            if len(matches) == 1:
                paths.add(matches[0])
    return paths


def _dependency_paths(project: Dict) -> Set[str]:
    """Return every possible media match, including ambiguous protected ones."""
    return {
        match
        for reference in project.get("references", [])
        for match in reference.get("matches", [])
    }


def _project_blockers(project: Dict) -> List[Dict[str, str]]:
    blockers: List[Dict[str, str]] = []
    if project.get("status") != "parsed":
        blockers.append({
            "kind": "unreadable_project",
            "project": project.get("path", ""),
            "detail": project.get("error") or "Project could not be parsed",
        })
        return blockers
    for reference in project.get("references", []):
        resolution = reference.get("resolution")
        # A path-evidenced reference is resolved, not a blocker. This used a
        # narrower hardcoded set than the audit and the separation planner,
        # so every successfully resolved path-evidenced reference was reported
        # as blocking: 179,355 of the 191,413 blockers on the studio archive.
        if resolution is not None and resolution not in RESOLVED_REFERENCE_STATES:
            blockers.append({
                "kind": f"{resolution}_media_reference",
                "project": project.get("path", ""),
                "detail": reference.get("name", "Unknown media"),
            })
    return blockers


def build_archive_queue(audit: Dict, target: str = "Nuendo 15") -> Dict:
    """Convert a complete read-only archive audit into dependency families."""
    if audit.get("audit_mode") != "read_only":
        raise ValueError("Archive queue requires a read-only archive audit")
    projects = list(audit.get("projects", []))
    if audit.get("sample", {}).get("requested") is not None:
        raise ValueError("A sampled audit cannot produce an archive queue")
    if len(projects) != audit.get("summary", {}).get("projects_discovered"):
        raise ValueError("Archive audit is incomplete")

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

    media_sets = [_project_paths(project) for project in projects]
    dependency_sets = [_dependency_paths(project) for project in projects]
    media_owner: Dict[str, int] = {}
    directory_owner: Dict[str, int] = {}
    for index, paths in enumerate(dependency_sets):
        for path in paths:
            if path in media_owner:
                union(index, media_owner[path])
            else:
                media_owner[path] = index
        # Multiple CPR/NPR files beside the same conventional Audio/Edits tree
        # are versions of one archive unit even when their active media do not
        # overlap. This deliberately makes large legacy parent layouts advance
        # through normalization together.
        project_path = projects[index].get("path")
        if project_path:
            directory = str(Path(project_path).parent)
            if directory in directory_owner:
                union(index, directory_owner[directory])
            else:
                directory_owner[directory] = index

    groups: Dict[int, List[int]] = {}
    for index in range(len(projects)):
        groups.setdefault(find(index), []).append(index)

    families = []
    for indexes in groups.values():
        members = [projects[index] for index in indexes]
        member_paths = sorted(
            (member.get("path", "") for member in members), key=str.casefold
        )
        referenced_media = sorted(
            set().union(*(media_sets[index] for index in indexes)),
            key=str.casefold,
        )
        blockers = [
            blocker
            for member in members
            for blocker in _project_blockers(member)
        ]
        products = sorted({
            " ".join(
                part for part in (member.get("product"), member.get("version"))
                if part
            ) or "Unknown"
            for member in members
        })
        families.append({
            "id": _family_id(member_paths),
            "name": Path(member_paths[0]).stem if member_paths else "Unknown",
            "status": "blocked" if blockers else "ready_for_operator",
            "target_application": target,
            "members": member_paths,
            "source_formats": products,
            "referenced_media": referenced_media,
            "referenced_media_files": len(referenced_media),
            "blockers": blockers,
            "stages": [
                {"name": name, "status": "pending"} for name in WORKFLOW_STAGES
            ],
            "cleanup_authorized": False,
            "operator_note": (
                "Resolve every blocker before normalization."
                if blockers else
                "Open every member in Nuendo 15 and save a normalized copy."
            ),
        })
    families.sort(key=lambda family: family["members"][0].casefold())

    return {
        "schema_version": 1,
        "queue_mode": "planning_only",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "audit_root": audit.get("root"),
        "target_application": target,
        "summary": {
            "families": len(families),
            "projects": len(projects),
            "ready_for_operator": sum(
                family["status"] == "ready_for_operator" for family in families
            ),
            "blocked": sum(family["status"] == "blocked" for family in families),
            "cleanup_authorized": 0,
        },
        "families": families,
        "safety": {
            "archive_writes": False,
            "daw_automation_enabled": False,
            "cleanup_authorized": False,
            "required_final_gate": (
                "All surviving normalized projects reopen in Nuendo 15 with "
                "every referenced media file present."
            ),
        },
    }
