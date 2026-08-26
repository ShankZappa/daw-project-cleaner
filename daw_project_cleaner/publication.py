"""Atomic publication of DAW-validated, self-contained project copies."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .format import AUDIO_EXTENSIONS, parse_project


RECEIPT = ".daw-project-cleaner-publication.json"
NORMALIZATION_SUFFIX = re.compile(
    r"(?:[ _-]+)(?:control|normalized|cleaned)$", re.IGNORECASE
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _publication_label(stem: str) -> Tuple[str, bool]:
    """Strip operator workflow suffixes regardless of common separator style."""
    stripped, count = NORMALIZATION_SUFFIX.subn("", stem)
    return stripped.strip(), bool(count)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _regular(path: Path) -> os.stat_result:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ValueError(f"Not a regular non-link file: {path}")
    return info


def _atomic_json(path: Path, value: Dict) -> None:
    # Unique per attempt: a fixed name turns an interrupted write into a
    # permanent refusal for every later write to the same path.
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise FileExistsError(f"Unsafe temporary collision: {temporary}")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _active_names(path: Path) -> List[str]:
    parsed = parse_project(path)
    return sorted(
        [
            name for name, offsets in parsed.occurrences.items()
            if offsets and any(offset < parsed.pool_offset for offset in offsets)
        ],
        key=str.casefold,
    )


def _active_files(root: Path) -> Dict[str, List[Path]]:
    found: Dict[str, List[Path]] = {}
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        dirs[:] = [
            name for name in dirs
            if not name.startswith(".daw-project-cleaner")
            and not (Path(current) / name).is_symlink()
        ]
        for name in files:
            path = Path(current) / name
            if path.is_symlink() or path.suffix.casefold() not in AUDIO_EXTENSIONS:
                continue
            found.setdefault(_key(name), []).append(path)
    return found


def build_publication_plan(validations: Iterable[Dict], destination: Path) -> Dict:
    """Build a read-only, fully hashed publication plan."""
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Publication destination already exists: {destination}")
    roots = set()
    folder_keys = set()
    operations: List[Dict] = []
    projects: List[Dict] = []
    for validation in validations:
        summary = validation.get("summary", {})
        if validation.get("validation_mode") != "read_only" or not (
            summary.get("structural_valid") is True
            and summary.get("daw_open_confirmed") is True
            and summary.get("final_gate_passed") is True
        ) or validation.get("blockers") or validation.get("remaining_pool_only"):
            raise ValueError("Every publication input must pass the final DAW gate")
        root = Path(validation["media_root"]).resolve(strict=True)
        if root.is_symlink() or not root.is_dir() or str(root) in roots:
            raise ValueError("Publication roots must be distinct non-link directories")
        roots.add(str(root))
        cleaned = Path(validation["cleaned"]["path"]).resolve(strict=True)
        _regular(cleaned)
        if not _inside(cleaned, root) or _sha256(cleaned) != validation["cleaned"]["sha256"]:
            raise ValueError("CLEANED project is outside its root or changed")
        if _active_names(cleaned) != sorted(validation.get("active_media", []), key=str.casefold):
            raise ValueError("CLEANED active references changed after validation")
        for record in validation.get("candidates", []) + validation.get(
            "project_artifacts_to_quarantine", []
        ):
            if Path(record["path"]).exists():
                raise ValueError("Publication requires completed physical quarantine")

        original_labels = []
        for record in validation.get("project_artifacts_to_quarantine", []):
            artifact = Path(record.get("path", ""))
            _, is_workflow_artifact = _publication_label(artifact.stem)
            if (
                artifact.suffix.casefold() in {".cpr", ".npr"}
                and not is_workflow_artifact
            ):
                original_labels.append(artifact.stem)
        unique_originals = {
            _key(item): item for item in original_labels
        }
        label = (
            next(iter(unique_originals.values()))
            if len(unique_originals) == 1 else cleaned.stem
        )
        label, _ = _publication_label(label)
        if not label or "/" in label or label in {".", ".."} or _key(label) in folder_keys:
            raise ValueError("Unsafe or duplicate publication project name")
        folder_keys.add(_key(label))
        project_target = Path(label) / f"{label}{cleaned.suffix.lower()}"
        project_info = _regular(cleaned)
        project_hash = _sha256(cleaned)
        operations.append({
            "kind": "project", "source": str(cleaned),
            "destination_relative": str(project_target),
            "size_bytes": project_info.st_size, "sha256": project_hash,
        })

        active_count = 0
        active_records = validation.get("active_media_files", [])
        if active_records:
            for record in active_records:
                source = Path(record["path"]).resolve(strict=True)
                info = _regular(source)
                if not _inside(source, root) or info.st_size != record["size_bytes"] or _sha256(source) != record["sha256"]:
                    raise ValueError(f"Active media changed after validation: {source}")
                relative = source.relative_to(root)
                operations.append({
                    "kind": "active_media", "source": str(source),
                    "destination_relative": str(Path(label) / relative),
                    "size_bytes": info.st_size, "sha256": record["sha256"],
                })
                active_count += 1
        else:
            files = _active_files(root)
            for name in validation.get("active_media", []):
                matches = files.get(_key(name), [])
                if len(matches) != 1:
                    raise ValueError(f"Active media must resolve uniquely: {name}")
                source = matches[0]
                info = _regular(source)
                relative = source.relative_to(root)
                operations.append({
                    "kind": "active_media", "source": str(source),
                    "destination_relative": str(Path(label) / relative),
                    "size_bytes": info.st_size, "sha256": _sha256(source),
                })
                active_count += 1
        projects.append({
            "name": label, "source_root": str(root),
            "cleaned_project": str(cleaned), "active_media": active_count,
        })
    if not projects:
        raise ValueError("Publication plan contains no projects")
    target_keys = [_key(item["destination_relative"]) for item in operations]
    if len(target_keys) != len(set(target_keys)):
        raise ValueError("Publication destination paths collide")
    return {
        "schema_version": 1,
        "plan_mode": "read_only_normalized_publication",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "publication_id": "publish-" + uuid.uuid4().hex[:12],
        "destination": str(destination),
        "projects": projects,
        "operations": operations,
        "summary": {
            "projects": len(projects), "files": len(operations),
            "bytes": sum(item["size_bytes"] for item in operations),
            "source_writes": 0, "mother_retirement_authorized": False,
        },
        "safety": {
            "source_writes": False, "source_deletes": False,
            "atomic_container_publication": True,
            "mother_retirement_authorized": False,
        },
    }


def publish_normalized_batch(
    plan: Dict, progress: Optional[Callable[[int, int, str], None]] = None,
) -> Path:
    """Copy and hash-verify a whole publication, then reveal it atomically."""
    if plan.get("plan_mode") != "read_only_normalized_publication":
        raise ValueError("Invalid publication plan mode")
    destination = Path(plan["destination"]).absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Publication destination already exists: {destination}")
    parent = destination.parent.resolve(strict=True)
    for project in plan.get("projects", []):
        root = Path(project["source_root"]).resolve(strict=True)
        if _inside(destination, root):
            raise ValueError("Publication destination may not be inside a source root")
    required = int(plan.get("summary", {}).get("bytes", 0))
    if shutil.disk_usage(parent).free < required + 64 * 1024 * 1024:
        raise OSError("Insufficient free space for verified publication")
    staging = parent / f".daw-project-cleaner-publish-{uuid.uuid4().hex}"
    if staging.exists() or staging.is_symlink():
        raise FileExistsError(f"Unsafe publication staging collision: {staging}")
    staging.mkdir(mode=0o700)
    output = staging / "output"
    output.mkdir()
    operations = list(plan.get("operations", []))
    try:
        for index, operation in enumerate(operations, 1):
            source = Path(operation["source"])
            info = _regular(source)
            if info.st_size != operation["size_bytes"] or _sha256(source) != operation["sha256"]:
                raise ValueError(f"Publication source changed after planning: {source}")
            target = output / operation["destination_relative"]
            if not _inside(target, output) or target.exists() or target.is_symlink():
                raise ValueError(f"Unsafe publication target: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target, follow_symlinks=False)
            if _sha256(target) != operation["sha256"]:
                raise OSError(f"Published copy hash mismatch: {target}")
            if progress:
                progress(index, len(operations), str(source))
        receipt = dict(plan)
        receipt["status"] = "published_verified"
        receipt["published_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_json(output / RECEIPT, receipt)
        os.replace(output, destination)
        os.rmdir(staging)
        return destination
    except Exception:
        if staging.exists() and not staging.is_symlink() and staging.parent == parent:
            shutil.rmtree(staging)
        raise


def withdraw_publication(destination_entry: Path, quarantine_entry: Path) -> Path:
    """Atomically withdraw a verified publication into same-volume quarantine."""
    destination = destination_entry.resolve(strict=True)
    quarantine = quarantine_entry.resolve(strict=True)
    if destination.is_symlink() or not destination.is_dir():
        raise ValueError("Publication is not a non-link directory")
    if quarantine.is_symlink() or not quarantine.is_dir():
        raise ValueError("Publication quarantine is not a non-link directory")
    if destination.stat().st_dev != quarantine.stat().st_dev:
        raise ValueError("Publication rollback quarantine must be on the same filesystem")
    receipt_path = destination / RECEIPT
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if Path(receipt.get("destination", "")).absolute() != destination_entry.absolute():
        raise ValueError("Publication receipt destination does not match")
    for operation in receipt.get("operations", []):
        target = destination / operation["destination_relative"]
        _regular(target)
        if _sha256(target) != operation["sha256"]:
            raise ValueError(f"Published file changed; refusing withdrawal: {target}")
    session = quarantine / f"publication-{uuid.uuid4().hex}"
    session.mkdir(mode=0o700)
    state = {
        "schema_version": 1, "kind": "publication_withdrawal",
        "status": "withdrawing", "destination": str(destination_entry.absolute()),
        "published": str(session / "published"),
    }
    _atomic_json(session / "state.json", state)
    try:
        os.replace(destination, session / "published")
        state["status"] = "withdrawn_recoverable"
        _atomic_json(session / "state.json", state)
        return session
    except Exception:
        if session.exists() and not any(session.iterdir()):
            os.rmdir(session)
        raise


def restore_publication(session_entry: Path) -> Path:
    session = session_entry.resolve(strict=True)
    state_path = session / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("kind") != "publication_withdrawal" or state.get("status") != "withdrawn_recoverable":
        raise ValueError("Publication withdrawal session is not restorable")
    published = Path(state["published"])
    destination = Path(state["destination"])
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Publication restore destination already exists")
    if published.is_symlink() or not published.is_dir() or published.stat().st_dev != destination.parent.stat().st_dev:
        raise ValueError("Publication restore paths are unsafe")
    os.replace(published, destination)
    state["status"] = "restored"
    state["restored_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(state_path, state)
    return destination
