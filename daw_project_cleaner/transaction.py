from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import unicodedata
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from . import PURGE_ENABLED, __version__
from .format import parse_project
from .model import BackupResult, MediaItem, ScanReport
from .rewrite_profiles import (
    RewriteAudit,
    application_validated_shape_label,
    rewrite_for_exact_profile,
)


CONTROL_NAME = ".daw-project-cleaner-quarantine"
CONTROLLED_COPY_MARKER = ".daw-project-cleaner-controlled-copy"
CONTROLLED_COPY_TEXT = "I CONFIRM THIS ROOT IS A DISPOSABLE COPY\n"


class SafetyError(RuntimeError):
    pass


def _require_full_scan(report: ScanReport) -> None:
    if report.scan_kind != "full_safety_scan" or not report.complete:
        raise SafetyError(
            "Remote/partial inventory reports cannot authorize Apply; "
            "run a complete Full Safety Scan"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _no_symlink_chain(path: Path, root: Path) -> None:
    if not _inside(path, root):
        raise SafetyError(f"Path is outside the selected root: {path}")
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise SafetyError(f"Symbolic links are not allowed: {current}")


def _atomic_json(path: Path, value: Dict) -> None:
    # The temporary name must be unique per attempt. With a fixed name, a
    # process killed between the create and the rename leaves the file behind,
    # and every later write to that path refuses forever - which strands
    # Restore partway through, after it has already moved files back. The
    # exclusive create below remains the real guard against two writers.
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise SafetyError(f"Atomic JSON temporary path already exists: {temporary}")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary.exists() and temporary.is_file() and not temporary.is_symlink():
            temporary.unlink()
        raise


def _audit(path: Path, event: Dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    if temporary.exists() or temporary.is_symlink():
        raise SafetyError(f"Atomic temporary path already exists: {temporary}")
    try:
        shutil.copy2(source, temporary)
        if temporary.is_symlink() or not temporary.is_file():
            raise SafetyError(f"Atomic copy did not create a regular file: {temporary}")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        if temporary.exists() and temporary.is_file() and not temporary.is_symlink():
            temporary.unlink()
        raise


def _bytes_atomic(data: bytes, destination: Path, mode: int = 0o600) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    if temporary.exists() or temporary.is_symlink():
        raise SafetyError(f"Atomic temporary path already exists: {temporary}")
    try:
        with temporary.open("xb") as handle:
            os.fchmod(handle.fileno(), stat.S_IMODE(mode))
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        if temporary.exists() and temporary.is_file() and not temporary.is_symlink():
            temporary.unlink()
        raise


def _require_controlled_copy(root: Path) -> None:
    marker = root / CONTROLLED_COPY_MARKER
    _no_symlink_chain(marker, root)
    try:
        info = marker.lstat()
    except FileNotFoundError as exc:
        raise SafetyError(
            f"Pilot Apply requires the controlled-copy marker: {marker}"
        ) from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise SafetyError(f"Unsafe controlled-copy marker: {marker}")
    if marker.read_text(encoding="utf-8") != CONTROLLED_COPY_TEXT:
        raise SafetyError("Controlled-copy marker text does not match")


def prepare_controlled_copy_marker(root_entry: Path) -> Path:
    """Create the explicit disposable-root marker without touching projects."""
    if root_entry.is_symlink():
        raise SafetyError("A controlled-copy root may not be a symbolic link")
    root = root_entry.resolve(strict=True)
    if not root.is_dir():
        raise SafetyError(f"Not a directory: {root}")
    marker = root / CONTROLLED_COPY_MARKER
    _no_symlink_chain(marker, root)
    if marker.exists():
        _require_controlled_copy(root)
        return marker
    _bytes_atomic(CONTROLLED_COPY_TEXT.encode("utf-8"), marker)
    _require_controlled_copy(root)
    return marker


def _new_session(
    root: Path, quarantine_root_entry: Optional[Path] = None
) -> Tuple[Path, str, Path]:
    if quarantine_root_entry is None:
        control = root / CONTROL_NAME
    else:
        if quarantine_root_entry.is_symlink():
            raise SafetyError("The shared quarantine folder may not be a symbolic link")
        control = quarantine_root_entry.resolve(strict=True)
        if not control.is_dir():
            raise SafetyError(f"Not a quarantine directory: {control}")
        if control == root:
            raise SafetyError("The quarantine must be a dedicated folder, not the scan root")
        if control.stat().st_dev != root.stat().st_dev:
            raise SafetyError(
                "Projects and quarantine must be on the same mounted filesystem"
            )
    if control.exists() and (control.is_symlink() or not control.is_dir()):
        raise SafetyError(f"Unsafe quarantine control path: {control}")
    sessions = control / "sessions"
    if sessions.exists() and (sessions.is_symlink() or not sessions.is_dir()):
        raise SafetyError(f"Unsafe quarantine sessions path: {sessions}")
    sessions.mkdir(parents=True, exist_ok=True)
    if quarantine_root_entry is None:
        _no_symlink_chain(sessions, root)
    else:
        _no_symlink_chain(sessions, control)
    session_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    session = sessions / session_id
    session.mkdir(exist_ok=False)
    _no_symlink_chain(session, sessions)
    return session, session_id, control


def _candidates(
    report: ScanReport,
    root: Path,
    *,
    require_high_confidence: bool = True,
    selected_projects: Optional[Set[Path]] = None,
) -> Tuple[List[Tuple[Path, MediaItem]], Set[Path]]:
    found: Dict[str, Tuple[Path, MediaItem]] = {}
    affected_projects: Set[Path] = set()

    # Every parsed project is pinned to its scan digest. This prevents stale
    # reports from acting after any project in the archive has changed.
    for scanned in report.projects:
        if not scanned.sha256:
            continue
        entry = Path(scanned.path)
        _no_symlink_chain(entry, root)
        project = entry.resolve(strict=True)
        if _sha256(project) != scanned.sha256:
            raise SafetyError(f"Project changed since scan: {project}")

    for project_result in report.projects:
        candidates = [item for item in project_result.media if item.candidate]
        if not candidates:
            continue
        if not project_result.sha256 or not project_result.audio_dir:
            raise SafetyError(f"Candidate project lacks required scan metadata: {project_result.path}")
        project_entry = Path(project_result.path)
        _no_symlink_chain(project_entry, root)
        project = project_entry.resolve(strict=True)
        if selected_projects is not None and project not in selected_projects:
            continue
        reparsed = parse_project(project)
        if (
            reparsed.sha256 != project_result.sha256
            or (require_high_confidence and reparsed.confidence != "high")
        ):
            raise SafetyError(f"Project evidence no longer validates: {project}")
        audio_entry = Path(project_result.audio_dir)
        _no_symlink_chain(audio_entry, root)
        audio_root = audio_entry.resolve(strict=True)
        affected_projects.add(project)

        for item in candidates:
            if item.classification != "pool_only" or not item.disk_path or item.size_bytes is None:
                raise SafetyError(f"Invalid candidate metadata: {item.name}")
            offsets = reparsed.occurrences.get(item.name)
            if not offsets or not all(offset > reparsed.pool_offset for offset in offsets):
                raise SafetyError(f"Pool-only evidence did not revalidate: {item.name}")
            source_entry = Path(item.disk_path)
            _no_symlink_chain(source_entry, root)
            info = source_entry.lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise SafetyError(f"Media is not a regular non-link file: {source_entry}")
            source = source_entry.resolve(strict=True)
            if not _inside(source, audio_root):
                raise SafetyError(f"Media is outside the project's Audio folder: {source}")
            if source.name.casefold() != item.name.casefold() or info.st_size != item.size_bytes:
                raise SafetyError(f"Media changed since scan: {source}")
            found.setdefault(os.path.normcase(str(source)), (source, item))
    return list(found.values()), affected_projects


def _resolve_recorded_path(raw: str) -> Path:
    """Resolve a path recorded in a report, tolerating Unicode normalization.

    macOS presents SMB names decomposed (NFD) while the server filesystem may
    store them composed (NFC), so a path written by a scan does not always
    resolve later. On the studio archive 4,775 of 8,719 recorded backups failed
    to resolve for this reason alone - every one of them a name containing a
    letter like the Estonian o-tilde. The bytes differ; the file is the same.
    """
    entry = Path(raw)
    if entry.exists() or entry.is_symlink():
        return entry
    for form in ("NFC", "NFD"):
        candidate = Path(unicodedata.normalize(form, raw))
        if candidate.exists() or candidate.is_symlink():
            return candidate
    return entry


def _backup_candidates(
    report: ScanReport, root: Path, selected_projects: Optional[Set[Path]]
) -> List[Tuple[Path, BackupResult]]:
    selected: List[Tuple[Path, BackupResult]] = []
    for backup in report.backups:
        entry = _resolve_recorded_path(backup.path)
        _no_symlink_chain(entry, root)
        info = entry.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise SafetyError(f"Backup is not a regular non-link file: {entry}")
        path = entry.resolve(strict=True)
        if not backup.sha256 or _sha256(path) != backup.sha256:
            raise SafetyError(f"Project backup changed since scan: {path}")
        if backup.size_bytes is None or info.st_size != backup.size_bytes:
            raise SafetyError(f"Project backup size changed since scan: {path}")
        if backup.action != "quarantine":
            continue
        if backup.status not in {"scanned", "indexed"} or not backup.family:
            raise SafetyError(f"Unsafe backup quarantine classification: {path}")
        family_entry = Path(backup.family)
        _no_symlink_chain(family_entry, root)
        family = family_entry.resolve(strict=True)
        if selected_projects is not None and family not in selected_projects:
            continue
        selected.append((path, backup))
    return selected


def quarantine_report(
    report: ScanReport,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> Path:
    """Atomically move scan candidates into a recoverable same-root quarantine."""
    _require_full_scan(report)
    root = Path(report.root).resolve(strict=True)
    candidates, projects = _candidates(report, root)
    if not candidates:
        raise SafetyError("The report contains no validated review candidates")

    session, session_id, control = _new_session(root)
    state_path = session / "state.json"
    audit_path = session / "audit.jsonl"
    state: Dict = {
        "schema_version": 1,
        "tool_version": __version__,
        "session_id": session_id,
        "root": str(root),
        "control_root": str(control),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "preparing",
        "project_rewrite": "disabled",
        "backups": [],
        "moves": [],
    }
    _atomic_json(state_path, state)
    _audit(audit_path, {"event": "session_started", "at": state["created_at"]})

    try:
        for project in sorted(projects):
            destination = session / "backups" / project.relative_to(root)
            _copy_atomic(project, destination)
            digest = _sha256(project)
            if _sha256(destination) != digest:
                raise SafetyError(f"Project backup verification failed: {project}")
            state["backups"].append({"project": str(project), "backup": str(destination), "sha256": digest})
            _atomic_json(state_path, state)
            _audit(audit_path, {"event": "project_backed_up", "project": str(project)})

        state["status"] = "moving"
        _atomic_json(state_path, state)
        total = len(candidates)
        for index, (source, item) in enumerate(sorted(candidates, key=lambda pair: str(pair[0]).casefold()), 1):
            destination = session / "quarantine" / source.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or source.stat().st_dev != destination.parent.stat().st_dev:
                raise SafetyError(f"Atomic same-filesystem move is not possible: {source}")
            move = {
                "source": str(source), "quarantine": str(destination),
                "size_bytes": item.size_bytes, "sha256": _sha256(source), "status": "planned",
            }
            state["moves"].append(move)
            _atomic_json(state_path, state)
            os.replace(source, destination)
            move["status"] = "moved"
            _atomic_json(state_path, state)
            _audit(audit_path, {"event": "media_quarantined", **move})
            if progress:
                progress(index, total, str(source))
        state["status"] = "complete"
        state["completed_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_json(state_path, state)
        _audit(audit_path, {"event": "session_completed", "at": state["completed_at"]})
        return session
    except Exception as exc:
        state["status"] = "interrupted"
        state["error"] = str(exc)
        _atomic_json(state_path, state)
        _audit(audit_path, {"event": "session_interrupted", "error": str(exc)})
        raise


def _rollback_pilot_session(
    session: Path,
    state_path: Path,
    audit_path: Path,
    state: Dict,
) -> List[str]:
    errors: List[str] = []
    for move in reversed(state.get("moves", [])):
        source = Path(move["source"])
        quarantine = Path(move["quarantine"])
        try:
            if quarantine.is_file() and not quarantine.is_symlink() and not source.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                os.replace(quarantine, source)
                move["status"] = "rolled_back"
                _audit(audit_path, {"event": "media_rollback", "source": str(source)})
            elif source.is_file() and not quarantine.exists():
                move["status"] = "not_moved"
            else:
                raise SafetyError(f"Ambiguous media rollback state: {source}")
        except Exception as exc:
            errors.append(str(exc))

    for change in reversed(state.get("project_changes", [])):
        project = Path(change["project"])
        backup = Path(change["backup"])
        try:
            if backup.is_symlink() or not backup.is_file():
                raise SafetyError(f"Project rollback backup is unavailable: {backup}")
            if _sha256(backup) != change["original_sha256"]:
                raise SafetyError(f"Project rollback backup changed: {backup}")
            _copy_atomic(backup, project)
            if _sha256(project) != change["original_sha256"]:
                raise SafetyError(f"Project rollback verification failed: {project}")
            change["status"] = "rolled_back"
            _audit(audit_path, {"event": "project_rollback", "project": str(project)})
        except Exception as exc:
            errors.append(str(exc))
    state["status"] = "rollback_failed" if errors else "rolled_back"
    state["rollback_at"] = datetime.now(timezone.utc).isoformat()
    if errors:
        state["rollback_errors"] = errors
    _atomic_json(state_path, state)
    return errors


def rewrite_quarantine_pilot(
    report: ScanReport,
    progress: Optional[Callable[[int, int, str], None]] = None,
    *,
    writer: Callable[[Path], Tuple[bytes, RewriteAudit]] = rewrite_for_exact_profile,
    selected_project_paths: Optional[Sequence[str]] = None,
    quarantine_root: Optional[Path] = None,
) -> Path:
    """Rewrite projects and quarantine matching media in a controlled copy.

    This pilot is intentionally gated by a marker in the selected root. It is
    not connected to the GUI or production Apply path. Every affected project
    must have exact-profile writer support and every pool-only name must map to
    a validated media candidate in the same report.
    """
    _require_full_scan(report)
    root = Path(report.root).resolve(strict=True)
    _require_controlled_copy(root)
    selected_projects: Optional[Set[Path]] = None
    if selected_project_paths is not None:
        selected_projects = set()
        report_projects = {
            str(Path(result.path).resolve(strict=True)): result
            for result in report.projects if result.sha256
        }
        for raw in selected_project_paths:
            entry = Path(raw)
            _no_symlink_chain(entry, root)
            project = entry.resolve(strict=True)
            if str(project) not in report_projects:
                raise SafetyError(f"Selected project is absent from the scan report: {project}")
            selected_projects.add(project)
        if not selected_projects:
            raise SafetyError("No projects were selected for controlled-copy Apply")
    # The controlled-copy pilot may exercise an application-validated exact
    # writer for an older profile that the general scanner still labels
    # report-only. The exact writer remains the fail-closed format gate below;
    # normal quarantine continues to require high reader confidence.
    candidates, projects = _candidates(
        report, root, require_high_confidence=False,
        selected_projects=selected_projects,
    )
    if not candidates:
        raise SafetyError("The report contains no validated review candidates")
    if selected_projects is not None and projects != selected_projects:
        missing = sorted(str(path) for path in selected_projects - projects)
        raise SafetyError(
            "Selected projects have no complete candidate set: " + ", ".join(missing)
        )
    backup_candidates = _backup_candidates(report, root, selected_projects)

    selected_media = {
        os.path.normcase(str(path)): item for path, item in candidates
    }
    for result in report.projects:
        if not result.sha256:
            continue
        project = Path(result.path).resolve(strict=True)
        if project in projects:
            continue
        for item in result.media:
            if not item.disk_path or item.classification not in {"active", "pool_only"}:
                continue
            key = os.path.normcase(os.path.realpath(item.disk_path))
            if key in selected_media:
                raise SafetyError(
                    "Shared media requires selecting every referencing project: "
                    f"{item.name} is also referenced by {project}"
                )

    result_by_project = {
        str(Path(result.path).resolve(strict=True)): result
        for result in report.projects if result.sha256
    }
    candidate_paths = {
        os.path.normcase(str(path)): item for path, item in candidates
    }
    session, session_id, control = _new_session(root, quarantine_root)
    state_path = session / "state.json"
    audit_path = session / "audit.jsonl"
    state: Dict = {
        "schema_version": 2,
        "tool_version": __version__,
        "session_id": session_id,
        "root": str(root),
        "control_root": str(control),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "preparing",
        "mode": "controlled-copy-pilot",
        "project_rewrite": "exact-profile",
        "backups": [],
        "project_changes": [],
        "moves": [],
    }
    _atomic_json(state_path, state)
    _audit(audit_path, {"event": "pilot_session_started", "at": state["created_at"]})

    try:
        for project in sorted(projects):
            result = result_by_project.get(str(project))
            if result is None:
                raise SafetyError(f"Affected project is absent from the scan report: {project}")
            project_candidates = [item for item in result.media if item.candidate]
            parsed_before = parse_project(project)
            pool_only_before = sorted(
                name for name, offsets in parsed_before.occurrences.items()
                if offsets and all(offset > parsed_before.pool_offset for offset in offsets)
            )
            candidate_names = sorted(item.name for item in project_candidates)
            if {name.casefold() for name in pool_only_before} != {
                name.casefold() for name in candidate_names
            }:
                raise SafetyError(
                    f"Every pool-only reference must map to a quarantined file: {project}"
                )
            for item in project_candidates:
                key = os.path.normcase(str(Path(item.disk_path).resolve(strict=True)))
                if key not in candidate_paths:
                    raise SafetyError(f"Project candidate is not globally validated: {item.name}")

            output, rewrite_audit = writer(project)
            if (
                writer is rewrite_for_exact_profile
                and application_validated_shape_label(
                    parsed_before, rewrite_audit
                ) is None
            ):
                raise SafetyError(
                    f"Pool topology is not application-validated: {project}"
                )
            if rewrite_audit.source_sha256 != parsed_before.sha256:
                raise SafetyError(f"Writer source audit mismatch: {project}")
            if rewrite_audit.output_sha256 != hashlib.sha256(output).hexdigest():
                raise SafetyError(f"Writer output audit mismatch: {project}")
            staged = session / "prepared" / project.relative_to(root)
            _bytes_atomic(output, staged, project.stat().st_mode)
            parsed_after = parse_project(staged)
            identity_before = (
                parsed_before.product, parsed_before.version, parsed_before.container,
                parsed_before.serialization_profile,
            )
            identity_after = (
                parsed_after.product, parsed_after.version, parsed_after.container,
                parsed_after.serialization_profile,
            )
            active_before = sorted(
                name for name, offsets in parsed_before.occurrences.items()
                if offsets and any(offset < parsed_before.pool_offset for offset in offsets)
            )
            active_after = sorted(
                name for name, offsets in parsed_after.occurrences.items()
                if offsets and any(offset < parsed_after.pool_offset for offset in offsets)
            )
            pool_only_after = sorted(
                name for name, offsets in parsed_after.occurrences.items()
                if offsets and all(offset > parsed_after.pool_offset for offset in offsets)
            )
            if identity_after != identity_before or active_after != active_before or pool_only_after:
                raise SafetyError(f"Staged project rewrite did not validate: {project}")

            backup = session / "backups" / project.relative_to(root)
            _copy_atomic(project, backup)
            if _sha256(backup) != parsed_before.sha256:
                raise SafetyError(f"Project backup verification failed: {project}")
            change = {
                "project": str(project),
                "backup": str(backup),
                "prepared": str(staged),
                "original_sha256": parsed_before.sha256,
                "rewritten_sha256": rewrite_audit.output_sha256,
                "original_mtime": project.stat().st_mtime,
                "status": "prepared",
                "rewrite_audit": asdict(rewrite_audit),
            }
            state["project_changes"].append(change)
            state["backups"].append({
                "project": str(project), "backup": str(backup),
                "sha256": parsed_before.sha256,
            })
            _atomic_json(state_path, state)
            _audit(audit_path, {"event": "project_prepared", "project": str(project)})

        state["status"] = "rewriting_projects"
        _atomic_json(state_path, state)
        for change in state["project_changes"]:
            project = Path(change["project"])
            staged = Path(change["prepared"])
            _copy_atomic(staged, project)
            if _sha256(project) != change["rewritten_sha256"]:
                raise SafetyError(f"Atomic project rewrite verification failed: {project}")
            change["status"] = "rewritten"
            _atomic_json(state_path, state)
            _audit(audit_path, {"event": "project_rewritten", "project": str(project)})

        state["status"] = "moving_media"
        _atomic_json(state_path, state)
        total = len(candidates) + len(backup_candidates)
        for index, (source, item) in enumerate(
            sorted(candidates, key=lambda pair: str(pair[0]).casefold()), 1
        ):
            destination = session / "quarantine" / source.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or source.stat().st_dev != destination.parent.stat().st_dev:
                raise SafetyError(f"Atomic same-filesystem move is not possible: {source}")
            move = {
                "source": str(source), "quarantine": str(destination),
                "size_bytes": item.size_bytes, "sha256": _sha256(source),
                "status": "planned", "kind": "media",
            }
            state["moves"].append(move)
            _atomic_json(state_path, state)
            os.replace(source, destination)
            move["status"] = "moved"
            _atomic_json(state_path, state)
            _audit(audit_path, {"event": "media_quarantined", **move})
            if progress:
                progress(index, total, str(source))

        for offset, (source, backup) in enumerate(
            sorted(backup_candidates, key=lambda pair: str(pair[0]).casefold()), 1
        ):
            destination = session / "quarantine-backups" / source.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or source.stat().st_dev != destination.parent.stat().st_dev:
                raise SafetyError(f"Atomic backup move is not possible: {source}")
            move = {
                "source": str(source), "quarantine": str(destination),
                "size_bytes": backup.size_bytes, "sha256": backup.sha256,
                "status": "planned", "kind": "project_backup",
            }
            state["moves"].append(move)
            _atomic_json(state_path, state)
            os.replace(source, destination)
            move["status"] = "moved"
            _atomic_json(state_path, state)
            _audit(audit_path, {"event": "project_backup_quarantined", **move})
            if progress:
                progress(len(candidates) + offset, total, str(source))

        state["status"] = "complete"
        state["completed_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_json(state_path, state)
        _audit(audit_path, {"event": "pilot_session_completed", "at": state["completed_at"]})
        return session
    except Exception as exc:
        state["error"] = str(exc)
        _audit(audit_path, {"event": "pilot_session_interrupted", "error": str(exc)})
        rollback_errors = _rollback_pilot_session(session, state_path, audit_path, state)
        if rollback_errors:
            raise SafetyError(
                f"Pilot failed and rollback was incomplete: {exc}; "
                + "; ".join(rollback_errors)
            ) from exc
        raise


def quarantine_backup_policy(
    report: ScanReport,
    quarantine_root: Path,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> Path:
    """Move only policy-selected project backup files into quarantine."""
    _require_full_scan(report)
    root = Path(report.root).resolve(strict=True)
    backup_candidates = _backup_candidates(report, root, None)
    if not backup_candidates:
        raise SafetyError("The report contains no classified backups to quarantine")
    session, session_id, control = _new_session(root, quarantine_root)
    state_path = session / "state.json"
    audit_path = session / "audit.jsonl"
    families = sorted({
        backup.family for _path, backup in backup_candidates if backup.family
    })
    archive_projects = []
    for raw in families:
        entry = Path(raw)
        _no_symlink_chain(entry, root)
        project = entry.resolve(strict=True)
        archive_projects.append({
            "project": str(project),
            "sha256": _sha256(project),
            "modified_at": project.stat().st_mtime,
        })
    state: Dict = {
        "schema_version": 2,
        "tool_version": __version__,
        "session_id": session_id,
        "root": str(root),
        "control_root": str(control),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "moving_backups",
        "mode": "backup-policy",
        "project_rewrite": "disabled",
        "archive_projects": archive_projects,
        "backups": [],
        "project_changes": [],
        "moves": [],
    }
    _atomic_json(state_path, state)
    _audit(audit_path, {
        "event": "backup_policy_session_started", "at": state["created_at"],
    })
    try:
        total = len(backup_candidates)
        for index, (source, backup) in enumerate(
            sorted(backup_candidates, key=lambda pair: str(pair[0]).casefold()), 1
        ):
            destination = session / "quarantine-backups" / source.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or source.stat().st_dev != destination.parent.stat().st_dev:
                raise SafetyError(f"Atomic backup move is not possible: {source}")
            move = {
                "source": str(source), "quarantine": str(destination),
                "size_bytes": backup.size_bytes, "sha256": backup.sha256,
                "status": "planned", "kind": "project_backup",
            }
            state["moves"].append(move)
            _atomic_json(state_path, state)
            os.replace(source, destination)
            move["status"] = "moved"
            _atomic_json(state_path, state)
            _audit(audit_path, {"event": "project_backup_quarantined", **move})
            if progress:
                progress(index, total, str(source))
        state["status"] = "complete"
        state["completed_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_json(state_path, state)
        _audit(audit_path, {
            "event": "backup_policy_session_completed",
            "at": state["completed_at"],
        })
        return session
    except Exception as exc:
        state["error"] = str(exc)
        _audit(audit_path, {
            "event": "backup_policy_session_interrupted", "error": str(exc),
        })
        rollback_errors = _rollback_pilot_session(
            session, state_path, audit_path, state
        )
        if rollback_errors:
            raise SafetyError(
                f"Backup cleanup failed and rollback was incomplete: {exc}; "
                + "; ".join(rollback_errors)
            ) from exc
        raise


def quarantine_normalized_pilot(
    validation: Dict,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> Path:
    """Quarantine a DAW-normalized controlled copy without deleting anything."""
    root, cleaned, cleaned_record, planned = _preflight_normalized_pilot(validation)

    session, session_id, control = _new_session(root)
    state_path = session / "state.json"
    audit_path = session / "audit.jsonl"
    state: Dict = {
        "schema_version": 3,
        "tool_version": __version__,
        "session_id": session_id,
        "root": str(root),
        "control_root": str(control),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "preparing",
        "mode": "daw-normalized-pilot",
        "project_rewrite": "daw-normalized",
        "surviving_project": {
            "path": str(cleaned),
            "sha256": cleaned_record["sha256"],
            "modified_at": cleaned.stat().st_mtime,
        },
        "validation_created_at": validation.get("created_at"),
        "backups": [],
        "project_changes": [],
        "moves": [],
    }
    _atomic_json(state_path, state)
    _audit(audit_path, {
        "event": "daw_normalized_session_started", "at": state["created_at"],
        "surviving_project": str(cleaned),
    })
    try:
        state["status"] = "moving"
        _atomic_json(state_path, state)
        for index, item in enumerate(
            sorted(planned, key=lambda value: str(value["source"]).casefold()), 1
        ):
            source = item["source"]
            destination = (
                session / "quarantine-artifacts" / source.relative_to(root)
                if item["kind"] == "project_artifact" else
                session / "quarantine" / source.relative_to(root)
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or source.stat().st_dev != destination.parent.stat().st_dev:
                raise SafetyError(f"Atomic same-filesystem move is not possible: {source}")
            move = {
                "source": str(source), "quarantine": str(destination),
                "size_bytes": item["size_bytes"], "sha256": item["sha256"],
                "status": "planned", "kind": item["kind"],
            }
            state["moves"].append(move)
            _atomic_json(state_path, state)
            os.replace(source, destination)
            move["status"] = "moved"
            _atomic_json(state_path, state)
            _audit(audit_path, {"event": "normalized_file_quarantined", **move})
            if progress:
                progress(index, len(planned), str(source))
        if _sha256(cleaned) != cleaned_record["sha256"]:
            raise SafetyError("Cleaned survivor changed during transaction")
        state["status"] = "complete"
        state["completed_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_json(state_path, state)
        _audit(audit_path, {
            "event": "daw_normalized_session_completed",
            "at": state["completed_at"],
        })
        return session
    except Exception as exc:
        state["error"] = str(exc)
        _audit(audit_path, {
            "event": "daw_normalized_session_interrupted", "error": str(exc),
        })
        rollback_errors = _rollback_pilot_session(
            session, state_path, audit_path, state
        )
        if rollback_errors:
            raise SafetyError(
                f"DAW-normalized pilot failed and rollback was incomplete: {exc}; "
                + "; ".join(rollback_errors)
            ) from exc
        raise


def _preflight_normalized_pilot(
    validation: Dict,
) -> Tuple[Path, Path, Dict, List[Dict]]:
    """Revalidate a normalized plan completely without modifying its root."""
    if validation.get("validation_mode") != "read_only":
        raise SafetyError("Normalization validation mode is invalid")
    summary = validation.get("summary", {})
    if not (
        summary.get("structural_valid") is True
        and summary.get("daw_open_confirmed") is True
        and summary.get("final_gate_passed") is True
    ):
        raise SafetyError("Normalization final gate has not passed")
    if validation.get("blockers"):
        raise SafetyError("Normalization report contains blockers")

    root_entry = Path(validation.get("media_root", ""))
    if root_entry.is_symlink():
        raise SafetyError("Normalization root may not be a symbolic link")
    root = root_entry.resolve(strict=True)
    if not root.is_dir():
        raise SafetyError("Normalization root is not a directory")
    _require_controlled_copy(root)

    cleaned_record = validation.get("cleaned", {})
    cleaned_entry = Path(cleaned_record.get("path", ""))
    _no_symlink_chain(cleaned_entry, root)
    cleaned = cleaned_entry.resolve(strict=True)
    if not cleaned.is_file() or cleaned.is_symlink():
        raise SafetyError("Cleaned project is not a regular file")
    if _sha256(cleaned) != cleaned_record.get("sha256"):
        raise SafetyError("Cleaned project changed after validation")
    parsed_cleaned = parse_project(cleaned)
    active_cleaned = sorted(
        name for name, offsets in parsed_cleaned.occurrences.items()
        if offsets and any(offset < parsed_cleaned.pool_offset for offset in offsets)
    )
    pool_only_cleaned = sorted(
        name for name, offsets in parsed_cleaned.occurrences.items()
        if offsets and all(offset > parsed_cleaned.pool_offset for offset in offsets)
    )
    if active_cleaned != sorted(validation.get("active_media", [])):
        raise SafetyError("Cleaned active references changed after validation")
    if pool_only_cleaned or validation.get("remaining_pool_only"):
        raise SafetyError("Cleaned project still contains Pool-only references")

    for record in validation.get("active_media_files", []):
        entry = Path(record.get("path", ""))
        _no_symlink_chain(entry, root)
        info = entry.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise SafetyError(f"Active media is not a regular file: {entry}")
        if info.st_size != record.get("size_bytes") or _sha256(entry) != record.get("sha256"):
            raise SafetyError(f"Active media changed after validation: {entry}")

    planned: List[Dict] = []
    seen: Set[Tuple[int, int]] = set()
    for kind, records in (
        ("media", validation.get("candidates", [])),
        ("project_artifact", validation.get("project_artifacts_to_quarantine", [])),
    ):
        for record in records:
            entry = Path(record.get("path", ""))
            _no_symlink_chain(entry, root)
            info = entry.lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise SafetyError(f"Planned source is not a regular file: {entry}")
            source = entry.resolve(strict=True)
            key = (info.st_dev, info.st_ino)
            if key in seen:
                raise SafetyError(f"Duplicate normalization source: {source}")
            seen.add(key)
            if os.path.samefile(source, cleaned):
                raise SafetyError("The cleaned survivor may not be quarantined")
            expected_size = record.get("size_bytes")
            expected_hash = record.get("sha256")
            if info.st_size != expected_size or _sha256(source) != expected_hash:
                raise SafetyError(f"Planned source changed after validation: {source}")
            planned.append({
                "source": source,
                "size_bytes": expected_size,
                "sha256": expected_hash,
                "kind": kind,
            })
    if len(planned) != summary.get("candidate_files", 0) + summary.get(
        "project_artifacts_to_quarantine", 0
    ):
        raise SafetyError("Normalization plan count does not match summary")
    if not planned:
        raise SafetyError("Normalization report contains no quarantine plan")

    return root, cleaned, cleaned_record, planned


def quarantine_normalized_batch(
    validations: Sequence[Dict],
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> List[Path]:
    """Apply several normalized plans with cross-session rollback on failure."""
    if len(validations) < 2:
        raise SafetyError("Normalized batch requires at least two projects")
    preflights = [_preflight_normalized_pilot(item) for item in validations]
    roots = [item[0] for item in preflights]
    if len({str(root) for root in roots}) != len(roots):
        raise SafetyError("Normalized batch contains a duplicate project root")
    all_sources: Set[str] = set()
    for _root, _cleaned, _record, planned in preflights:
        for item in planned:
            key = os.path.normcase(str(item["source"]))
            if key in all_sources:
                raise SafetyError("Normalized batch contains a shared planned source")
            all_sources.add(key)
    total = sum(len(item[3]) for item in preflights)
    completed: List[Path] = []
    base = 0
    try:
        for validation, preflight in zip(validations, preflights):
            planned_count = len(preflight[3])
            session = quarantine_normalized_pilot(
                validation,
                progress=(
                    lambda done, _local_total, path, offset=base: progress(
                        offset + done, total, path
                    )
                ) if progress else None,
            )
            completed.append(session)
            base += planned_count
        return completed
    except Exception as exc:
        rollback_errors = []
        for session in reversed(completed):
            try:
                restore_session(session)
            except Exception as rollback_exc:
                rollback_errors.append(f"{session}: {rollback_exc}")
        if rollback_errors:
            raise SafetyError(
                f"Normalized batch failed and rollback was incomplete: {exc}; "
                + "; ".join(rollback_errors)
            ) from exc
        raise


def _load_session(session_entry: Path) -> Tuple[Path, Path, Dict, Path]:
    if session_entry.is_symlink():
        raise SafetyError("A quarantine session may not be a symbolic link")
    session = session_entry.resolve(strict=True)
    state_path = session / "state.json"
    if state_path.is_symlink() or not state_path.is_file():
        raise SafetyError("The selected folder is not a valid quarantine session")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    root = Path(state["root"]).resolve(strict=True)
    control_entry = Path(state.get("control_root", str(root / CONTROL_NAME)))
    if control_entry.is_symlink():
        raise SafetyError("The recorded quarantine root is a symbolic link")
    control = control_entry.resolve(strict=True)
    if not control.is_dir() or control.stat().st_dev != root.stat().st_dev:
        raise SafetyError("The recorded quarantine root is unsafe or on another filesystem")
    sessions_entry = control / "sessions"
    _no_symlink_chain(sessions_entry, control)
    if sessions_entry.is_symlink() or not sessions_entry.is_dir():
        raise SafetyError("The recorded quarantine sessions path is unsafe")
    sessions_root = sessions_entry.resolve(strict=True)
    if not _inside(session, sessions_root):
        raise SafetyError("Session is outside its recorded quarantine root")
    _no_symlink_chain(session, sessions_root)
    return session, state_path, state, root


def _move_quarantine_root(session: Path, move: Dict) -> Path:
    if move.get("kind") == "project_backup":
        return session / "quarantine-backups"
    if move.get("kind") == "project_artifact":
        return session / "quarantine-artifacts"
    return session / "quarantine"


def restore_session(session_entry: Path) -> int:
    session, state_path, state, root = _load_session(session_entry)
    if state.get("status") in {"purging", "purged"}:
        raise SafetyError(
            "This session has been permanently purged and can no longer be restored"
        )
    # A move killed between os.replace and the state write that follows it stays
    # recorded as "planned" while the file already sits in quarantine. Only an
    # in-process failure runs the rollback path; SIGKILL, a force quit or a power
    # loss leave Restore as the user's only route back. Resolve those entries
    # from the filesystem, the way _rollback_pilot_session already does, instead
    # of trusting the recorded status - otherwise the file is silently left
    # behind and Restore still reports success.
    moves = []
    for move in state.get("moves", []):
        status = move.get("status")
        if status not in {"moved", "planned"}:
            continue
        source = Path(move["source"])
        quarantine = Path(move["quarantine"])
        in_quarantine = quarantine.is_file() and not quarantine.is_symlink()
        if in_quarantine and not source.exists():
            move["status"] = "moved"
            moves.append(move)
            continue
        if (
            not quarantine.exists()
            and source.is_file()
            and not source.is_symlink()
            and _sha256(source) == move["sha256"]
        ):
            # Either the rename never ran, or an earlier Restore already put
            # this one back before it was interrupted. Both mean there is
            # nothing left to move, and both must stay resumable.
            move["status"] = "restored" if status == "moved" else "not_moved"
            continue
        raise SafetyError(
            f"An interrupted move cannot be resolved from the filesystem: {source}"
        )
    for move in moves:
        source = Path(move["source"])
        quarantine = Path(move["quarantine"])
        if not _inside(source, root) or not _inside(
            quarantine, _move_quarantine_root(session, move)
        ):
            raise SafetyError("Unsafe path recorded in quarantine state")
        if source.exists() or quarantine.is_symlink() or not quarantine.is_file():
            raise SafetyError(f"Cannot safely restore: {source}")
        if quarantine.stat().st_size != move["size_bytes"] or _sha256(quarantine) != move["sha256"]:
            raise SafetyError(f"Quarantined file changed: {quarantine}")
    pending_projects = []
    for change in state.get("project_changes", []):
        project = Path(change["project"])
        backup = Path(change["backup"])
        if not _inside(project, root) or not _inside(backup, session / "backups"):
            raise SafetyError("Unsafe project path recorded in quarantine state")
        if backup.is_symlink() or not backup.is_file():
            raise SafetyError(f"Project backup is unavailable: {backup}")
        if _sha256(backup) != change["original_sha256"]:
            raise SafetyError(f"Project backup changed: {backup}")
        if project.is_symlink() or not project.is_file():
            raise SafetyError(f"Rewritten project is unavailable: {project}")
        current_hash = _sha256(project)
        if current_hash == change["original_sha256"]:
            change["status"] = "restored"
        elif current_hash == change["rewritten_sha256"]:
            pending_projects.append(change)
        else:
            raise SafetyError(f"Rewritten project changed after Apply: {project}")
    restored = 0
    for move in reversed(moves):
        source = Path(move["source"])
        quarantine = Path(move["quarantine"])
        source.parent.mkdir(parents=True, exist_ok=True)
        if source.parent.stat().st_dev != quarantine.stat().st_dev:
            raise SafetyError(f"Atomic restore is not possible: {source}")
        os.replace(quarantine, source)
        move["status"] = "restored"
        restored += 1
        _atomic_json(state_path, state)
        _audit(session / "audit.jsonl", {
            "event": (
                "project_backup_restored"
                if move.get("kind") == "project_backup"
                else "project_artifact_restored"
                if move.get("kind") == "project_artifact"
                else "media_restored"
            ),
            "source": str(source),
        })
    for change in pending_projects:
        project = Path(change["project"])
        backup = Path(change["backup"])
        _copy_atomic(backup, project)
        if _sha256(project) != change["original_sha256"]:
            raise SafetyError(f"Restored project verification failed: {project}")
        change["status"] = "restored"
        _atomic_json(state_path, state)
        _audit(session / "audit.jsonl", {
            "event": "project_restored", "project": str(project),
        })
    state["status"] = "restored"
    state["restored_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(state_path, state)
    _audit(session / "audit.jsonl", {
        "event": "session_restored", "at": state["restored_at"],
    })
    return restored


def purge_session(session_entry: Path, confirmation: str) -> int:
    """Permanently remove a fully validated quarantine session's files.

    Every session retains a mandatory 30-day recovery window regardless of how
    old the projects are, and the GUI additionally requires macOS owner
    authentication.
    Every path and digest is revalidated before the first unlink. Progress is
    persisted after each file so an interrupted purge can be resumed safely.
    """
    if not PURGE_ENABLED:
        raise SafetyError(
            "This build has no permanent deletion. Quarantined files stay "
            "recoverable and Restore returns them to their original paths."
        )
    if confirmation != "DELETE QUARANTINE PERMANENTLY":
        raise SafetyError("Permanent deletion confirmation did not match")
    session, state_path, state, root = _load_session(session_entry)
    exact_rewrite = (
        state.get("project_rewrite") == "exact-profile"
        and bool(state.get("project_changes"))
    )
    backup_policy = (
        state.get("mode") == "backup-policy"
        and state.get("project_rewrite") == "disabled"
        and bool(state.get("archive_projects"))
    )
    if not (exact_rewrite or backup_policy):
        raise SafetyError(
            "Permanent deletion requires a completed exact rewrite or backup-policy session"
        )
    if state.get("status") not in {"complete", "purging"}:
        raise SafetyError(f"Session is not purgeable: {state.get('status', 'unknown')}")

    now = datetime.now(timezone.utc)
    try:
        created = datetime.fromisoformat(state["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError) as exc:
        raise SafetyError("Session creation time is invalid") from exc
    # The recovery window is unconditional. An archive tool meets old projects
    # by definition, and those are the ones their owner is least likely to open,
    # least likely to notice damage in and least able to reconstruct. Refuse
    # before hashing anything, so an early session fails in milliseconds.
    if now - created < timedelta(days=30):
        eligible = created + timedelta(days=30)
        remaining = max(1, (eligible - now).days + 1)
        raise SafetyError(
            f"Quarantine sessions keep a mandatory 30-day recovery window "
            f"({remaining} days remaining)"
        )

    for change in state.get("project_changes", []):
        project = Path(change["project"])
        backup = Path(change["backup"])
        if not _inside(project, root) or not _inside(backup, session / "backups"):
            raise SafetyError("Unsafe project path recorded in quarantine state")
        if project.is_symlink() or not project.is_file():
            raise SafetyError(f"Rewritten project is unavailable: {project}")
        if _sha256(project) != change["rewritten_sha256"]:
            raise SafetyError(f"Rewritten project changed after Apply: {project}")
        if backup.is_symlink() or not backup.is_file():
            raise SafetyError(f"Project backup is unavailable: {backup}")
        if _sha256(backup) != change["original_sha256"]:
            raise SafetyError(f"Project backup changed: {backup}")
    for archive in state.get("archive_projects", []):
        project = Path(archive["project"])
        if not _inside(project, root) or project.is_symlink() or not project.is_file():
            raise SafetyError(f"Archive project is unavailable: {project}")
    moves = state.get("moves", [])
    if not moves:
        raise SafetyError("Session contains no quarantined files")
    for move in moves:
        source = Path(move["source"])
        quarantine = Path(move["quarantine"])
        if not _inside(source, root) or not _inside(
            quarantine, _move_quarantine_root(session, move)
        ):
            raise SafetyError("Unsafe path recorded in quarantine state")
        status = move.get("status")
        if status == "purged":
            if source.exists() or quarantine.exists() or quarantine.is_symlink():
                raise SafetyError(f"Purged media path unexpectedly exists: {source}")
            continue
        if status != "moved":
            raise SafetyError(f"Media is not in a purgeable state: {source}")
        if source.exists() or quarantine.is_symlink() or not quarantine.is_file():
            raise SafetyError(f"Cannot safely purge quarantined media: {source}")
        if (
            quarantine.stat().st_size != move["size_bytes"] or
            _sha256(quarantine) != move["sha256"]
        ):
            raise SafetyError(f"Quarantined file changed: {quarantine}")

    state["status"] = "purging"
    _atomic_json(state_path, state)
    _audit(session / "audit.jsonl", {
        "event": "permanent_purge_started", "at": now.isoformat(),
    })
    deleted = 0
    for move in moves:
        if move.get("status") == "purged":
            continue
        quarantine = Path(move["quarantine"])
        quarantine.unlink()
        move["status"] = "purged"
        move["purged_at"] = datetime.now(timezone.utc).isoformat()
        deleted += 1
        _atomic_json(state_path, state)
        _audit(session / "audit.jsonl", {
            "event": "file_permanently_deleted",
            "source": move["source"], "sha256": move["sha256"],
        })
    state["status"] = "purged"
    state["purged_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(state_path, state)
    _audit(session / "audit.jsonl", {
        "event": "permanent_purge_completed", "at": state["purged_at"],
    })
    return deleted
