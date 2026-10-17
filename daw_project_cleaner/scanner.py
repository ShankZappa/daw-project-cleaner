from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import time
from dataclasses import dataclass
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .format import AUDIO_EXTENSIONS, ProjectFormatError, parse_project
from .model import BackupResult, MediaItem, ProjectResult, ScanReport
from .rewrite_profiles import (
    ExperimentalRewriteError,
    application_validated_shape_label,
    rewrite_for_exact_profile,
)


DEFAULT_EXCLUSIONS = [
    "Backups", "Backup", "Auto Saves", "Autosaves", "Edits", "Mixdown", "Mixdowns", "Exports",
    "Export", "Bounces", "Freeze", ".daw-project-cleaner",
    ".daw-project-cleaner-quarantine", "DAW Project Cleaner Quarantine", ".Trash*",
    # A deleted project keeps its .npr but loses its Audio folder, so every
    # reference in it reads as missing media. Scanning a Synology share without
    # these found 354 deleted projects against 702 real ones - a third of the
    # results were the recycle bin, and each one looked alarming.
    "#recycle", "#snapshot", "@eaDir", ".@__thumb",
]
BACKUP_FOLDER_NAMES = {"backup", "backups", "auto saves", "autosaves"}


def _excluded(name: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatch(name.casefold(), p.casefold()) for p in patterns)


def discover_projects(
    root: Path, exclusions: Sequence[str],
    discovery_progress: Optional[Callable[[int, int, str], None]] = None,
) -> Tuple[List[Path], List[str]]:
    projects: List[Path] = []
    warnings: List[str] = []

    def onerror(error: OSError) -> None:
        warnings.append(f"Cannot read {error.filename}: {error.strerror}")

    seen_dirs = 0
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False, onerror=onerror):
        seen_dirs += 1
        if discovery_progress and seen_dirs % 100 == 0:
            discovery_progress(seen_dirs, len(projects), current)
        kept = []
        for name in dirs:
            path = Path(current) / name
            if name.casefold() in BACKUP_FOLDER_NAMES or _excluded(name, exclusions):
                continue
            try:
                if path.is_symlink():
                    warnings.append(f"Skipped symbolic-link directory: {path}")
                    continue
            except OSError as exc:
                warnings.append(f"Cannot inspect {path}: {exc}")
                continue
            kept.append(name)
        dirs[:] = kept
        for name in files:
            if Path(name).suffix.casefold() not in {".npr", ".cpr"}:
                continue
            path = Path(current) / name
            if path.is_symlink():
                warnings.append(f"Skipped symbolic-link project: {path}")
            else:
                projects.append(path)
    return sorted(projects, key=lambda p: str(p).casefold()), warnings


def discover_backups(
    root: Path, exclusions: Sequence[str],
    discovery_progress: Optional[Callable[[int, int, str], None]] = None,
) -> Tuple[List[Path], List[str]]:
    backups: List[Path] = []
    warnings: List[str] = []

    def onerror(error: OSError) -> None:
        warnings.append(f"Cannot read {error.filename}: {error.strerror}")

    blocked = {".daw-project-cleaner", ".daw-project-cleaner-quarantine"}
    seen_dirs = 0
    for current, dirs, files in os.walk(
        root, topdown=True, followlinks=False, onerror=onerror
    ):
        seen_dirs += 1
        if discovery_progress and seen_dirs % 100 == 0:
            discovery_progress(seen_dirs, len(backups), current)
        kept = []
        for name in dirs:
            path = Path(current) / name
            if (
                name.casefold() in blocked
                or fnmatch.fnmatch(name.casefold(), ".trash*")
                or (
                    name.casefold() not in BACKUP_FOLDER_NAMES
                    and _excluded(name, exclusions)
                )
            ):
                continue
            if path.is_symlink():
                warnings.append(f"Skipped symbolic-link directory: {path}")
                continue
            kept.append(name)
        dirs[:] = kept
        in_backup_folder = any(
            part.casefold() in BACKUP_FOLDER_NAMES
            for part in Path(current).relative_to(root).parts
        )
        for name in files:
            suffix = Path(name).suffix.casefold()
            if suffix != ".bak" and not (
                in_backup_folder and suffix in {".npr", ".cpr"}
            ):
                continue
            path = Path(current) / name
            if path.is_symlink():
                warnings.append(f"Skipped symbolic-link backup: {path}")
            else:
                backups.append(path)
    return sorted(backups, key=lambda p: str(p).casefold()), warnings


def find_audio_dir(project: Path) -> Optional[Path]:
    try:
        children = list(project.parent.iterdir())
    except OSError:
        return None
    matches = [p for p in children if p.is_dir() and not p.is_symlink() and p.name.casefold() == "audio"]
    return matches[0] if len(matches) == 1 else None


def find_backup_audio_dir(backup: Path, root: Path) -> Optional[Path]:
    current = backup.parent
    while current == root or root in current.parents:
        try:
            matches = [
                child for child in current.iterdir()
                if child.is_dir() and not child.is_symlink()
                and child.name.casefold() == "audio"
            ]
        except OSError:
            return None
        if len(matches) == 1:
            return matches[0]
        if current == root:
            break
        current = current.parent
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_backup(
    backup: Path, root: Path, exclusions: Sequence[str], protect_media: bool
) -> BackupResult:
    result = BackupResult(
        path=str(backup), status="scanned" if protect_media else "indexed"
    )
    try:
        info = backup.stat()
        result.sha256 = _sha256(backup)
        result.size_bytes = info.st_size
        result.modified_at = info.st_mtime
        audio_dir = find_backup_audio_dir(backup, root)
        if audio_dir is not None:
            result.audio_dir = str(audio_dir.resolve())
        if not protect_media:
            result.reason = (
                "Archive mode: backup content is not parsed and does not protect media"
            )
            return result

        parsed = parse_project(backup)
        result.confidence = parsed.confidence
        result.container = parsed.container
        result.product = parsed.product
        result.version = parsed.version
        result.serialization_profile = parsed.serialization_profile
        if result.sha256 != parsed.sha256:
            raise ValueError("Backup hash changed while it was being parsed")
        result.pool_offset = parsed.pool_offset
        result.warnings.extend(parsed.warnings)
        if audio_dir is None:
            result.status = "review"
            result.reason = "Backup is kept: a unique ancestor Audio folder was not found"
            result.warnings.append(result.reason)
            return result
        result.audio_dir = str(audio_dir.resolve())
        disk, disk_warnings = _disk_audio(audio_dir, exclusions)
        result.warnings.extend(disk_warnings)
        for name, offsets in sorted(
            parsed.occurrences.items(), key=lambda item: item[0].casefold()
        ):
            paths = disk.get(name.casefold(), [])
            classification = (
                "active" if any(offset < parsed.pool_offset for offset in offsets)
                else "pool_only"
            )
            disk_path = str(paths[0].absolute()) if len(paths) == 1 else None
            size = paths[0].stat().st_size if len(paths) == 1 else None
            reason = "Retained backup protects this media"
            if not paths:
                reason = "Backup-referenced media is missing"
            elif len(paths) > 1:
                reason = "Backup media mapping is ambiguous"
            result.media.append(MediaItem(
                name, classification, offsets, disk_path, size,
                False, False, reason,
            ))
    except (OSError, ProjectFormatError, ValueError) as exc:
        result.status = "error"
        result.error = str(exc)
        result.reason = "Unreadable backup is kept for safety"
    return result


def _backup_stem(path: Path) -> str:
    stem = path.stem
    stem = re.sub(r"[-_ ]\d+(?:[-_ ]*\(.*\))?$", "", stem)
    return stem.strip().casefold()


def _assign_backup_policy(
    backups: List[BackupResult], projects: List[ProjectResult], backup_keep: Optional[int]
) -> None:
    main_by_root: Dict[str, List[ProjectResult]] = {}
    # Every discovered project, including ones that could not be read or that
    # have no unique Audio folder. A backup may belong to one of those, so
    # their presence has to block the name-free fallback below.
    discovered_by_root: Dict[str, int] = {}
    # Folders holding a project we could not read at all. Steinberg numbers
    # saved versions and auto-backups independently, and `_backup_stem` strips
    # that number, so a backup can match an unrelated sibling by name alone.
    # When one project in the folder is unreadable - a 0-byte failed save is the
    # common case - a backup there may be the only copy of the work that was
    # open at that moment, so nothing in the folder may be selected.
    unreadable_roots = {
        str(Path(project.path).parent)
        for project in projects
        if project.status == "error"
    }
    projects_by_folder: Dict[str, List[ProjectResult]] = {}
    for project in projects:
        folder = str(Path(project.path).parent)
        discovered_by_root[folder] = discovered_by_root.get(folder, 0) + 1
        projects_by_folder.setdefault(folder, []).append(project)
        if not project.audio_dir:
            continue
        project_root = str(Path(project.audio_dir).parent)
        main_by_root.setdefault(project_root, []).append(project)
    families: Dict[str, List[BackupResult]] = {}
    for backup in backups:
        if backup.status not in {"scanned", "indexed"} or not backup.audio_dir:
            backup.action = "keep"
            if not backup.reason:
                backup.reason = "Backup is kept because it could not be classified safely"
            continue
        project_root = str(Path(backup.audio_dir).parent)
        backup_folder = str(Path(backup.path).parent)
        if project_root in unreadable_roots or backup_folder in unreadable_roots:
            backup.action = "keep"
            backup.reason = (
                "Backup is kept: a project in this folder could not be read, so "
                "this backup may be its only readable copy"
            )
            continue
        own = projects_by_folder.get(backup_folder, [])
        if own:
            # A project sits in the backup's own folder. find_backup_audio_dir
            # resolves the Audio folder by walking upward, so without this the
            # backup could be adopted by a project one directory up while the
            # sibling it actually belongs to is ignored entirely.
            mains = [project for project in own if project.audio_dir]
            if not mains:
                backup.action = "keep"
                backup.reason = (
                    "Backup is kept: the project in its own folder could not be "
                    "classified, so this backup's family is unknown"
                )
                continue
        else:
            mains = main_by_root.get(project_root, [])
        backup_name = _backup_stem(Path(backup.path))
        matches = [
            project for project in mains
            if backup_name == Path(project.path).stem.casefold()
            or backup_name.startswith(Path(project.path).stem.casefold() + "-")
            or backup_name.startswith(Path(project.path).stem.casefold() + "_")
        ]
        if len(matches) == 1:
            family = matches[0].path
        elif len(mains) == 1 and discovered_by_root.get(project_root, 0) == 1:
            # No name evidence, but the folder holds exactly one project and we
            # read it, so there is no other candidate parent to confuse it with.
            family = mains[0].path
        elif len(mains) == 1:
            backup.action = "keep"
            backup.reason = (
                "Backup is kept: its name matches no readable project and this "
                "folder holds another project that could not be classified"
            )
            continue
        else:
            backup.action = "keep"
            backup.reason = "Backup is kept: its main project family is ambiguous"
            continue
        backup.family = family
        families.setdefault(family, []).append(backup)
    for family_backups in families.values():
        ordered = sorted(
            family_backups,
            key=lambda item: (item.modified_at or 0, item.path.casefold()),
            reverse=True,
        )
        keep_count = len(ordered) if backup_keep is None else max(0, backup_keep)
        for index, backup in enumerate(ordered):
            if index < keep_count:
                backup.action = "keep"
                backup.reason = "Retained by the backup policy; its media remains protected"
            else:
                backup.action = "quarantine"
                backup.reason = "Older backup selected for recoverable quarantine"


def _disk_audio(audio_dir: Path, exclusions: Sequence[str]) -> Tuple[Dict[str, List[Path]], List[str]]:
    by_name: Dict[str, List[Path]] = {}
    warnings: List[str] = []
    def onerror(error: OSError) -> None:
        warnings.append(f"Cannot read {error.filename}: {error.strerror}")

    for current, dirs, files in os.walk(audio_dir, topdown=True, followlinks=False, onerror=onerror):
        dirs[:] = [
            d for d in dirs
            if not _excluded(d, exclusions) and not (Path(current) / d).is_symlink()
        ]
        for name in files:
            path = Path(current) / name
            if path.suffix.casefold() not in AUDIO_EXTENSIONS:
                continue
            if path.is_symlink():
                warnings.append(f"Skipped symbolic-link media: {path}")
                continue
            by_name.setdefault(name.casefold(), []).append(path)
    return by_name, warnings


def inspect_project(project: Path, exclusions: Sequence[str]) -> ProjectResult:
    result = ProjectResult(path=str(project), status="scanned")
    try:
        parsed = parse_project(project)
        result.confidence = parsed.confidence
        result.container = parsed.container
        result.product = parsed.product
        result.version = parsed.version
        result.serialization_profile = parsed.serialization_profile
        result.sha256 = parsed.sha256
        result.pool_offset = parsed.pool_offset
        result.warnings.extend(parsed.warnings)
        audio_dir = find_audio_dir(project)
        if audio_dir is None:
            result.status = "review"
            result.warnings.append("A unique sibling Audio folder was not found")
            disk: Dict[str, List[Path]] = {}
        else:
            result.audio_dir = str(audio_dir.resolve())
            disk, disk_warnings = _disk_audio(audio_dir, exclusions)
            result.warnings.extend(disk_warnings)

        project_names = {name.casefold() for name in parsed.occurrences}
        for name, offsets in sorted(parsed.occurrences.items(), key=lambda x: x[0].casefold()):
            paths = disk.get(name.casefold(), [])
            classification = "active" if any(x < parsed.pool_offset for x in offsets) else "pool_only"
            reason = ""
            candidate = False
            disk_path = None
            size = None
            if len(paths) == 1:
                disk_path = str(paths[0].absolute())
                try:
                    size = paths[0].stat().st_size
                except OSError as exc:
                    reason = f"Cannot stat media: {exc}"
            elif len(paths) > 1:
                reason = "Duplicate filename in Audio tree; path mapping is ambiguous"
            else:
                reason = "Referenced media is missing from Audio tree"
            if classification == "pool_only" and len(paths) == 1 and size is not None:
                candidate = True
                reason = "Potential candidate: only appears on the pool side; verify in the DAW"
            elif classification == "pool_only" and not reason:
                reason = "Parser profile requires manual review"
            result.media.append(MediaItem(
                name, classification, offsets, disk_path, size, candidate, False, reason
            ))

        for key, paths in disk.items():
            if key in project_names:
                continue
            for path in paths:
                try:
                    size = path.stat().st_size
                except OSError:
                    size = None
                result.media.append(MediaItem(
                    path.name, "unreferenced_on_disk", [], str(path.absolute()), size,
                    False, False, "Absence from one project is not sufficient evidence",
                ))

        pool_items = [item for item in result.media if item.classification == "pool_only"]
        if pool_items:
            try:
                _output, audit = rewrite_for_exact_profile(project)
                shape = application_validated_shape_label(parsed, audit)
                mapped = {
                    item.name.casefold() for item in pool_items
                    if item.candidate and item.disk_path and item.size_bytes is not None
                }
                expected = {name.casefold() for name in audit.pool_only_names}
                if shape is None:
                    result.rewrite_reason = (
                        "The exact version is readable, but this Pool topology "
                        "has not passed application validation"
                    )
                elif mapped != expected:
                    result.rewrite_reason = (
                        "Every Pool-only reference must map to one local Audio file"
                    )
                else:
                    result.rewrite_supported = True
                    result.rewrite_reason = f"Validated controlled-copy shape: {shape}"
            except (OSError, ProjectFormatError, ExperimentalRewriteError, ValueError) as exc:
                result.rewrite_reason = f"No validated exact writer: {exc}"
        else:
            result.rewrite_reason = "No Pool-only media records were found"
    except (OSError, ProjectFormatError, ValueError) as exc:
        result.status = "error"
        result.error = str(exc)
    return result


def _inside_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _is_uncertain(project: ProjectResult) -> bool:
    """A project whose media evidence we do not have."""
    return project.status == "error" or (
        project.status == "review" and not project.media and project.warnings
    )


def _uncertainty_scopes(
    projects: List[ProjectResult], root: Optional[Path]
) -> Optional[Set[str]]:
    """Folders an unreadable project could plausibly reference media in.

    A project that failed to parse says nothing about media in an unrelated
    part of the archive. Scanning one project folder and scanning a 2 TB
    archive are the same code path, and treating one corrupt file as doubt
    over everything makes cleanup unavailable for the whole archive - which is
    what happened on the studio server: one 0-byte failed save disabled 81,216
    candidates across 1,725 projects.

    The bound is the nearest ancestor holding a unique Audio folder, the same
    rule find_backup_audio_dir uses. Returns None when the doubt cannot be
    bounded, and then it stays global.
    """
    if root is None:
        return None
    scopes: Set[str] = set()
    for project in projects:
        if not _is_uncertain(project):
            continue
        audio = find_backup_audio_dir(Path(project.path), root)
        if audio is not None:
            scopes.add(os.path.normcase(os.path.normpath(str(audio.parent))))
            continue
        # No Audio folder anywhere above it. Falling back to global doubt made
        # 28 old Cubase projects, whose media names this reader cannot extract,
        # suppress 296 GB of evidence across 953 readable ones. A project with
        # no Audio folder maps no media, so its own folder is the honest bound:
        # whatever it references is not something this scan resolved.
        folder = Path(project.path).parent
        if not _inside_root(folder, root):
            return None
        scopes.add(os.path.normcase(os.path.normpath(str(folder))))
    return scopes


def _within_scope(disk_path: Optional[str], scopes: Set[str]) -> bool:
    if not disk_path:
        return True
    normalised = os.path.normcase(os.path.normpath(disk_path))
    return any(
        normalised == scope or normalised.startswith(scope + os.sep)
        for scope in scopes
    )


def _apply_global_guards(
    projects: List[ProjectResult], backups: Optional[List[BackupResult]] = None,
    backup_protect_media: bool = True, root: Optional[Path] = None,
) -> None:
    backups = backups or []
    uncertain_backups = backup_protect_media and any(
        backup.action != "quarantine" and backup.status in {"error", "review"}
        for backup in backups
    )
    scopes = None if uncertain_backups else _uncertainty_scopes(projects, root)
    if uncertain_backups or scopes is None:
        if any(_is_uncertain(p) for p in projects) or uncertain_backups:
            for project in projects:
                for item in project.media:
                    if item.candidate:
                        item.candidate = False
                        item.reason = "Candidate disabled because the scan contains unreadable projects"
                if project.rewrite_supported:
                    project.rewrite_supported = False
                    project.rewrite_reason = "Rewrite disabled because the scan contains unreadable projects"
            return
    elif scopes:
        for project in projects:
            touched = False
            for item in project.media:
                if item.candidate and _within_scope(item.disk_path, scopes):
                    item.candidate = False
                    item.reason = (
                        "Candidate disabled: a project in this folder could not "
                        "be read, so its media evidence is unknown"
                    )
                    touched = True
            if touched and project.rewrite_supported:
                project.rewrite_supported = False
                project.rewrite_reason = (
                    "Rewrite disabled: a project in this folder could not be read"
                )
    protected_by_backup: Dict[str, BackupResult] = {}
    for backup in backups if backup_protect_media else []:
        if backup.action == "quarantine":
            continue
        for item in backup.media:
            if item.disk_path:
                protected_by_backup[
                    os.path.normcase(os.path.realpath(item.disk_path))
                ] = backup
    for project in projects:
        for item in project.media:
            if not item.candidate or not item.disk_path:
                continue
            key = os.path.normcase(os.path.realpath(item.disk_path))
            if key in protected_by_backup:
                item.candidate = False
                item.reason = "The media is referenced by a retained project backup"
    uses: Dict[str, Set[str]] = {}
    owners: Dict[str, List[MediaItem]] = {}
    for project in projects:
        for item in project.media:
            if not item.disk_path:
                continue
            key = os.path.normcase(os.path.realpath(item.disk_path))
            uses.setdefault(key, set()).add(item.classification)
            owners.setdefault(key, []).append(item)
    for key, items in owners.items():
        kinds = uses[key]
        if "active" in kinds:
            for item in items:
                if item.candidate:
                    item.candidate = False
                    item.reason = "The same media path is active in another discovered project"
        if any(x.classification not in {"active", "pool_only"} for x in items):
            for item in items:
                if item.candidate:
                    item.candidate = False
                    item.reason = "The media path has conflicting scan evidence"
    for project in projects:
        if not project.rewrite_supported:
            continue
        expected = {
            item.name.casefold() for item in project.media
            if item.classification == "pool_only"
        }
        candidates = {
            item.name.casefold() for item in project.media if item.candidate
        }
        if candidates != expected:
            project.rewrite_supported = False
            backup_protected = sum(
                "retained project backup" in item.reason
                for item in project.media
            )
            project.rewrite_reason = (
                f"Project cleanup is blocked by retained backups "
                f"({backup_protected} protected media references)"
                if backup_protected
                else "Rewrite disabled by shared, conflicting or incomplete media evidence"
            )

    # A shared pool-only file can be quarantined only when every project that
    # remembers it can be rewritten in the same selected dependency group.
    # Propagate an unsupported owner until the complete group fails closed.
    pool_owners: Dict[str, List[Tuple[ProjectResult, MediaItem]]] = {}
    for project in projects:
        for item in project.media:
            if item.classification != "pool_only" or not item.disk_path:
                continue
            key = os.path.normcase(os.path.realpath(item.disk_path))
            pool_owners.setdefault(key, []).append((project, item))
    changed = True
    while changed:
        changed = False
        for owners_for_path in pool_owners.values():
            owner_projects = {id(project): project for project, _item in owners_for_path}
            if len(owner_projects) < 2 or all(
                project.rewrite_supported for project in owner_projects.values()
            ):
                continue
            for project, _item in owners_for_path:
                if project.rewrite_supported:
                    project.rewrite_supported = False
                    project.rewrite_reason = (
                        "Rewrite disabled because shared Pool media is also "
                        "owned by a project without validated rewrite support"
                    )
                    changed = True


@dataclass
class ScanProgress:
    """What a scan is doing, in enough detail to plan a return visit.

    Counting files is misleading when they range from 500 KB to 60 MB, so the
    work measure is bytes. Discovery is reported separately because walking a
    2 TB tree over SMB takes minutes with nothing to show for it.
    """
    phase: str
    done: int
    total: int
    done_bytes: int
    total_bytes: int
    path: str
    elapsed: float

    @property
    def percent(self) -> float:
        if self.total_bytes:
            return 100.0 * self.done_bytes / self.total_bytes
        return 100.0 * self.done / self.total if self.total else 0.0

    @property
    def bytes_per_second(self) -> float:
        return self.done_bytes / self.elapsed if self.elapsed > 0 else 0.0

    @property
    def seconds_remaining(self) -> Optional[float]:
        rate = self.bytes_per_second
        if rate <= 0 or self.total_bytes <= self.done_bytes:
            return None
        return (self.total_bytes - self.done_bytes) / rate


def scan_root(
    root: Path,
    exclusions: Optional[Sequence[str]] = None,
    workers: int = 4,
    progress: Optional[Callable[["ScanProgress"], None]] = None,
    result_callback: Optional[Callable[[ProjectResult], None]] = None,
    backup_keep: Optional[int] = 0,
    backup_protect_media: bool = False,
) -> ScanReport:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")
    patterns = list(exclusions or DEFAULT_EXCLUSIONS)
    started = time.monotonic()

    def report(phase, done, total, done_bytes, total_bytes, path):
        if progress:
            progress(ScanProgress(
                phase, done, total, done_bytes, total_bytes, path,
                time.monotonic() - started,
            ))

    def walked(dirs_seen, found, current):
        report("discovering", found, 0, 0, 0, f"{dirs_seen} folders · {current}")

    paths, discovery_warnings = discover_projects(root, patterns, walked)
    backup_paths, backup_warnings = discover_backups(root, patterns, walked)
    results: List[ProjectResult] = []
    backup_results: List[BackupResult] = []
    total = len(paths) + len(backup_paths)

    # Every file is read in full, so bytes are the honest measure of the work
    # ahead and the only basis for a usable estimate.
    sizes: Dict[str, int] = {}
    for candidate in list(paths) + list(backup_paths):
        try:
            sizes[str(candidate)] = candidate.stat().st_size
        except OSError:
            sizes[str(candidate)] = 0
    total_bytes = sum(sizes.values())
    done_bytes = 0
    report("measured", 0, total, 0, total_bytes, "")
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as pool:
        futures = {
            pool.submit(inspect_project, path, patterns): ("project", path)
            for path in paths
        }
        futures.update({
            pool.submit(
                inspect_backup, path, root, patterns, backup_protect_media
            ): ("backup", path)
            for path in backup_paths
        })
        for done, future in enumerate(as_completed(futures), 1):
            result = future.result()
            kind, _path = futures[future]
            if kind == "project":
                results.append(result)
                if result_callback:
                    result_callback(result)
            else:
                backup_results.append(result)
            done_bytes += sizes.get(result.path, 0)
            report("reading", done, total, done_bytes, total_bytes, result.path)
    results.sort(key=lambda p: p.path.casefold())
    backup_results.sort(key=lambda p: p.path.casefold())
    _assign_backup_policy(backup_results, results, backup_keep)
    _apply_global_guards(results, backup_results, backup_protect_media, root)
    all_discovery_warnings = discovery_warnings + backup_warnings
    if all_discovery_warnings:
        results.insert(0, ProjectResult(
            path=str(root), status="review", warnings=all_discovery_warnings,
            error=None,
        ))
    return ScanReport(
        root=str(root),
        created_at=datetime.now(timezone.utc).isoformat(),
        exclusions=patterns,
        projects=results,
        backups=backup_results,
        backup_keep=backup_keep,
        backup_protect_media=backup_protect_media,
    )


def save_report(report: ScanReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)
