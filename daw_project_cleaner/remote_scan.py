"""Resumable metadata-only inventory for slow or intermittent archive mounts.

This scanner deliberately cannot authorize cleanup.  It inventories directory
metadata, reads only the first 4096 bytes of main CPR/NPR files to identify the
embedded product/version, and never opens backup files.  A Full Safety Scan is
required before any quarantine or project rewrite operation.
"""
from __future__ import annotations

import errno
import fnmatch
import json
import os
import re
import signal
import struct
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .format import AUDIO_EXTENSIONS


REMOTE_EXCLUSIONS = [
    ".daw-project-cleaner", ".daw-project-cleaner-quarantine",
    "DAW Project Cleaner Quarantine", ".Trash*", "#recycle",
    ".TemporaryItems", ".Spotlight-V100", ".fseventsd",
]
BACKUP_FOLDER_NAMES = {"backup", "backups", "auto saves", "autosaves"}
PRODUCT_RE = re.compile(rb"\x00\x00\x00\x07(Cubase|Nuendo)\x00")
VERSION_RE = re.compile(rb"Version\s+([0-9]+(?:\.[0-9]+){1,3})")
TRANSIENT_ERRNOS = {
    errno.ECONNABORTED, errno.ECONNRESET, errno.ENETDOWN, errno.ENETRESET,
    errno.ENETUNREACH, errno.ENOTCONN, errno.ETIMEDOUT, errno.EIO,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _excluded(name: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatch(name.casefold(), item.casefold()) for item in patterns)


def _role(path: Path, root: Path) -> str:
    parts = {part.casefold() for part in path.relative_to(root).parts[:-1]}
    if "audio" in parts:
        return "Audio"
    if "edits" in parts:
        return "Edits"
    if "freeze" in parts or "freezes" in parts:
        return "Freeze"
    if parts & {"mixdown", "mixdowns", "export", "exports", "bounces"}:
        return "Mixdown/Exports"
    if parts & BACKUP_FOLDER_NAMES:
        return "Backups"
    if "images" in parts:
        return "Images"
    return "Other"


def _is_backup(path: Path, root: Path) -> bool:
    if path.suffix.casefold() == ".bak":
        return True
    if path.suffix.casefold() not in {".cpr", ".npr"}:
        return False
    return any(
        part.casefold() in BACKUP_FOLDER_NAMES
        for part in path.relative_to(root).parts[:-1]
    )


def _light_project_identity(path: Path) -> Tuple[str, Optional[str], Optional[str], str]:
    """Read a bounded header only; do not hash or deserialize the project."""
    with path.open("rb") as handle:
        prefix = handle.read(4096)
    if len(prefix) >= 16 and prefix[:4] == b"RIF2":
        container = "RIF2"
        form = prefix[12:16]
        declared = struct.unpack(">Q", prefix[4:12])[0]
    elif len(prefix) >= 12 and prefix[:4] == b"RIFF":
        container = "RIFF"
        form = prefix[8:12]
        declared = struct.unpack(">I", prefix[4:8])[0]
    else:
        return "unknown", None, None, "Unsupported project header"
    if form != b"NUND":
        return container, None, None, "Unsupported project form"
    product_match = PRODUCT_RE.search(prefix)
    version_match = VERSION_RE.search(prefix)
    product = product_match.group(1).decode("ascii") if product_match else None
    version = version_match.group(1).decode("ascii") if version_match else None
    expected = path.stat().st_size - (16 if container == "RIF2" else 12)
    status = "Detected from bounded header"
    if declared != expected:
        status = "Header detected; outer length needs Full Safety Scan validation"
    return container, product, version, status


def _atomic_json(path: Path, value: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _new_state(root: Path, patterns: Sequence[str]) -> Dict:
    return {
        "schema_version": 1,
        "scan_kind": "remote_quick_inventory",
        "complete": False,
        "interrupted": False,
        "root": str(root),
        "created_at": _now(),
        "updated_at": _now(),
        "exclusions": list(patterns),
        "backup_keep": 0,
        "backup_protect_media": False,
        "pending_directories": [str(root)],
        "completed_directories": [],
        "directory_summaries": {},
        "projects_by_path": {},
        "backups_by_path": {},
        "warnings": [],
        "safety": {
            "server_writes": False,
            "files_hashed": False,
            "backup_files_opened": False,
            "cleanup_authorized": False,
            "full_safety_scan_required": True,
        },
    }


def _load_resume(path: Path, root: Path, patterns: Sequence[str]) -> Dict:
    if not path.is_file() or path.is_symlink():
        return _new_state(root, patterns)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return _new_state(root, patterns)
    if (
        state.get("scan_kind") != "remote_quick_inventory"
        or state.get("root") != str(root)
        or state.get("complete")
        or list(state.get("exclusions", [])) != list(patterns)
    ):
        return _new_state(root, patterns)
    state["interrupted"] = False
    state["updated_at"] = _now()
    return state


def _project_record(path: Path, info: os.stat_result) -> Dict:
    try:
        container, product, version, detail = _light_project_identity(path)
        status = "inventory"
        error = None
    except OSError as exc:
        container = "unknown"
        product = version = None
        detail = "Project header could not be read"
        status = "error"
        error = str(exc)
    return {
        "path": str(path), "status": status, "confidence": "inventory",
        "container": container, "product": product, "version": version,
        "serialization_profile": None, "sha256": None, "audio_dir": None,
        "pool_offset": None, "media": [], "warnings": [detail], "error": error,
        "rewrite_supported": False,
        "rewrite_reason": "Remote Quick Inventory cannot authorize Apply; run a Full Safety Scan",
        "reclaimable_bytes": 0, "potential_reclaimable_bytes": 0,
        "size_bytes": info.st_size, "modified_at": info.st_mtime,
    }


def _backup_record(path: Path, info: os.stat_result) -> Dict:
    return {
        "path": str(path), "status": "inventory", "action": "review",
        "reason": "Metadata only; Full Safety Scan must hash and classify this backup before Apply",
        "family": None, "confidence": "inventory", "container": None,
        "product": None, "version": None, "serialization_profile": None,
        "sha256": None, "audio_dir": None, "pool_offset": None,
        "size_bytes": info.st_size, "modified_at": info.st_mtime,
        "media": [], "warnings": [], "error": None,
    }


def _summary(state: Dict) -> Dict:
    directories = list(state["directory_summaries"].values())
    projects = list(state["projects_by_path"].values())
    backups = list(state["backups_by_path"].values())
    versions = Counter(
        f"{item.get('product') or 'Unknown'} {item.get('version') or 'Unknown'}"
        for item in projects
    )
    roles: Dict[str, Dict[str, int]] = {}
    for directory in directories:
        for role, values in directory.get("roles", {}).items():
            target = roles.setdefault(role, {"files": 0, "bytes": 0})
            target["files"] += values["files"]
            target["bytes"] += values["bytes"]
    return {
        "projects": len(projects),
        "project_errors": sum(item["status"] == "error" for item in projects),
        "backups": len(backups),
        "backup_bytes": sum(item["size_bytes"] for item in backups),
        "directories_completed": len(state["completed_directories"]),
        "directories_pending": len(state["pending_directories"]),
        "files": sum(item["files"] for item in directories),
        "bytes": sum(item["bytes"] for item in directories),
        "media_files": sum(item["media_files"] for item in directories),
        "media_bytes": sum(item["media_bytes"] for item in directories),
        "versions": dict(sorted(versions.items())),
        "roles": roles,
        # Full-scan-compatible zero values keep the GUI summary fail-closed.
        "reclaimable_bytes": 0,
        "potential_reclaimable_bytes": 0,
        "candidate_files": 0,
        "eligible_files": 0,
        "errors": sum(item["status"] == "error" for item in projects),
        "rewrite_ready_projects": 0,
        "backup_files": len(backups),
        "backup_quarantine_files": 0,
        "backup_quarantine_bytes": 0,
    }


def _public_report(state: Dict, include_resume_state: bool = False) -> Dict:
    private = {
        "pending_directories", "completed_directories", "directory_summaries",
        "projects_by_path", "backups_by_path",
    }
    report = dict(state) if include_resume_state else {
        key: value for key, value in state.items() if key not in private
    }
    report["projects"] = sorted(
        state["projects_by_path"].values(), key=lambda item: item["path"].casefold()
    )
    report["backups"] = sorted(
        state["backups_by_path"].values(), key=lambda item: item["path"].casefold()
    )
    report["summary"] = _summary(state)
    return report


def _checkpoint(
    state: Dict, report_path: Path, ui_report_path: Optional[Path] = None
) -> None:
    state["updated_at"] = _now()
    _atomic_json(
        report_path,
        state if ui_report_path is not None
        else _public_report(state, include_resume_state=True),
    )
    if ui_report_path is not None:
        _atomic_json(ui_report_path, _public_report(state))


def remote_quick_scan(
    root: Path,
    report_path: Path,
    ui_report_path: Optional[Path] = None,
    exclusions: Optional[Sequence[str]] = None,
    progress: Optional[Callable[[int, int, str], None]] = None,
    result_callback: Optional[Callable[[Dict], None]] = None,
    resume: bool = True,
    checkpoint_every: int = 25,
    directory_limit: Optional[int] = None,
) -> Dict:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")
    patterns = list(exclusions or REMOTE_EXCLUSIONS)
    resume_path = report_path
    if (
        resume and not report_path.exists() and ui_report_path is not None
        and ui_report_path.exists()
    ):
        # One-time migration from 0.5.9 development checkpoints where the
        # resumable state and UI report shared latest-quick-scan.json.
        resume_path = ui_report_path
    state = (
        _load_resume(resume_path, root, patterns)
        if resume else _new_state(root, patterns)
    )
    completed_list: List[str] = list(state["completed_directories"])
    completed = set(completed_list)
    pending: List[str] = list(dict.fromkeys(state["pending_directories"]))
    queued = set(pending)
    state["pending_directories"] = pending
    stop_requested = False

    def stop_handler(_signum, _frame) -> None:
        nonlocal stop_requested
        stop_requested = True

    previous_term = signal.getsignal(signal.SIGTERM)
    previous_int = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    processed_this_run = 0
    _checkpoint(state, report_path, ui_report_path)
    try:
        while pending and not stop_requested:
            if directory_limit is not None and processed_this_run >= directory_limit:
                stop_requested = True
                break
            current_raw = pending[0]
            current = Path(current_raw)
            directory_summary = {
                "files": 0, "bytes": 0, "media_files": 0,
                "media_bytes": 0, "roles": {},
            }
            children: List[str] = []
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        path = current / entry.name
                        try:
                            if entry.is_symlink():
                                state["warnings"].append(f"Skipped symbolic link: {path}")
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                if not _excluded(entry.name, patterns):
                                    children.append(str(path))
                                continue
                            if not entry.is_file(follow_symlinks=False):
                                continue
                            info = entry.stat(follow_symlinks=False)
                            directory_summary["files"] += 1
                            directory_summary["bytes"] += info.st_size
                            suffix = path.suffix.casefold()
                            if suffix in AUDIO_EXTENSIONS:
                                role = _role(path, root)
                                directory_summary["media_files"] += 1
                                directory_summary["media_bytes"] += info.st_size
                                role_summary = directory_summary["roles"].setdefault(
                                    role, {"files": 0, "bytes": 0}
                                )
                                role_summary["files"] += 1
                                role_summary["bytes"] += info.st_size
                            if suffix == ".bak" or suffix in {".cpr", ".npr"}:
                                if _is_backup(path, root):
                                    state["backups_by_path"][str(path)] = _backup_record(path, info)
                                elif suffix in {".cpr", ".npr"}:
                                    record = _project_record(path, info)
                                    state["projects_by_path"][str(path)] = record
                                    if result_callback:
                                        result_callback(record)
                        except OSError as exc:
                            state["warnings"].append(f"Cannot inspect {path}: {exc}")
            except OSError as exc:
                state["warnings"].append(f"Cannot enumerate {current}: {exc}")
                if exc.errno in TRANSIENT_ERRNOS:
                    stop_requested = True
                    break
            state["directory_summaries"][current_raw] = directory_summary
            pending.pop(0)
            queued.discard(current_raw)
            completed.add(current_raw)
            completed_list.append(current_raw)
            state["completed_directories"] = completed_list
            for path in sorted(children, key=str.casefold):
                if path not in completed and path not in queued:
                    pending.append(path)
                    queued.add(path)
            state["pending_directories"] = pending
            processed_this_run += 1
            total_known = len(completed) + len(pending)
            if progress:
                progress(len(completed), total_known, current_raw)
            if processed_this_run % max(1, checkpoint_every) == 0:
                _checkpoint(state, report_path, ui_report_path)
        state["complete"] = not pending and not stop_requested
        state["interrupted"] = not state["complete"]
        if state["complete"]:
            state["completed_at"] = _now()
        _checkpoint(state, report_path, ui_report_path)
        return _public_report(state)
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)
