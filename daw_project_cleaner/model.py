from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__


@dataclass
class MediaItem:
    name: str
    classification: str
    offsets: List[int]
    disk_path: Optional[str] = None
    size_bytes: Optional[int] = None
    candidate: bool = False
    eligible: bool = False
    reason: str = ""


@dataclass
class ProjectResult:
    path: str
    status: str
    confidence: str = "none"
    container: Optional[str] = None
    product: Optional[str] = None
    version: Optional[str] = None
    serialization_profile: Optional[str] = None
    sha256: Optional[str] = None
    audio_dir: Optional[str] = None
    pool_offset: Optional[int] = None
    media: List[MediaItem] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None
    rewrite_supported: bool = False
    rewrite_reason: str = ""

    @property
    def reclaimable_bytes(self) -> int:
        return sum(x.size_bytes or 0 for x in self.media if x.eligible)

    @property
    def potential_reclaimable_bytes(self) -> int:
        return sum(x.size_bytes or 0 for x in self.media if x.candidate)

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["reclaimable_bytes"] = self.reclaimable_bytes
        result["potential_reclaimable_bytes"] = self.potential_reclaimable_bytes
        return result


@dataclass
class BackupResult:
    path: str
    status: str
    action: str = "keep"
    reason: str = ""
    family: Optional[str] = None
    confidence: str = "none"
    container: Optional[str] = None
    product: Optional[str] = None
    version: Optional[str] = None
    serialization_profile: Optional[str] = None
    sha256: Optional[str] = None
    audio_dir: Optional[str] = None
    pool_offset: Optional[int] = None
    size_bytes: Optional[int] = None
    modified_at: Optional[float] = None
    media: List[MediaItem] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScanReport:
    root: str
    created_at: str
    exclusions: List[str]
    projects: List[ProjectResult]
    backups: List[BackupResult] = field(default_factory=list)
    backup_keep: Optional[int] = 0
    backup_protect_media: bool = False
    scan_kind: str = "full_safety_scan"
    complete: bool = True
    schema_version: int = 2
    # A report authorises a destructive transaction, so it has to say which
    # build produced it. Without this a defect found in one version cannot be
    # traced to the reports it may have produced.
    tool_version: str = __version__

    def _unique_items(self, attribute: str) -> List[MediaItem]:
        found: Dict[str, MediaItem] = {}
        for project in self.projects:
            for item in project.media:
                if not getattr(item, attribute) or not item.disk_path:
                    continue
                key = os.path.normcase(os.path.normpath(item.disk_path))
                found.setdefault(key, item)
        return list(found.values())

    @property
    def reclaimable_bytes(self) -> int:
        return sum(x.size_bytes or 0 for x in self._unique_items("eligible"))

    @property
    def potential_reclaimable_bytes(self) -> int:
        return sum(x.size_bytes or 0 for x in self._unique_items("candidate"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tool_version": self.tool_version,
            "root": self.root,
            "created_at": self.created_at,
            "exclusions": self.exclusions,
            "backup_keep": self.backup_keep,
            "backup_protect_media": self.backup_protect_media,
            "scan_kind": self.scan_kind,
            "complete": self.complete,
            "summary": {
                "projects": len(self.projects),
                "reclaimable_bytes": self.reclaimable_bytes,
                "potential_reclaimable_bytes": self.potential_reclaimable_bytes,
                "candidate_files": len(self._unique_items("candidate")),
                "eligible_files": len(self._unique_items("eligible")),
                "errors": (
                    sum(p.status == "error" for p in self.projects)
                    + sum(backup.status == "error" for backup in self.backups)
                ),
                "rewrite_ready_projects": sum(p.rewrite_supported for p in self.projects),
                "backup_files": len(self.backups),
                "backup_quarantine_files": sum(
                    backup.action == "quarantine" for backup in self.backups
                ),
                "backup_quarantine_bytes": sum(
                    backup.size_bytes or 0 for backup in self.backups
                    if backup.action == "quarantine"
                ),
            },
            "projects": [x.to_dict() for x in self.projects],
            "backups": [x.to_dict() for x in self.backups],
        }


def report_from_dict(raw: Dict[str, Any]) -> ScanReport:
    projects = []
    for item in raw["projects"]:
        media = [MediaItem(**m) for m in item.get("media", [])]
        allowed = {k: v for k, v in item.items() if k in ProjectResult.__dataclass_fields__}
        allowed["media"] = media
        projects.append(ProjectResult(**allowed))
    backups = []
    for item in raw.get("backups", []):
        media = [MediaItem(**m) for m in item.get("media", [])]
        allowed = {
            k: v for k, v in item.items()
            if k in BackupResult.__dataclass_fields__
        }
        allowed["media"] = media
        backups.append(BackupResult(**allowed))
    return ScanReport(
        root=raw["root"],
        created_at=raw["created_at"],
        exclusions=list(raw.get("exclusions", [])),
        projects=projects,
        backups=backups,
        backup_keep=raw.get("backup_keep", 0),
        backup_protect_media=raw.get(
            "backup_protect_media", raw.get("backup_keep", 5) != 0
        ),
        scan_kind=raw.get("scan_kind", "full_safety_scan"),
        complete=bool(raw.get("complete", True)),
        schema_version=int(raw.get("schema_version", 1)),
    )
