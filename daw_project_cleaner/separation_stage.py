"""Copy-only, hash-verified rehearsal for a read-only separation plan."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_source(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Source is not a regular non-link file: {path}")


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _write_state(path: Path, value: Dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def stage_separation_copy(
    plan: Dict,
    selected_projects: Optional[Iterable[str]] = None,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> Path:
    """Create an atomic, non-destructive copy rehearsal from ready manifests."""
    if plan.get("plan_mode") != "read_only_separation_plan":
        raise ValueError("Copy rehearsal requires a read-only separation plan")
    if plan.get("safety", {}).get("copy_execution_enabled"):
        raise ValueError("Unexpected mutable plan safety state")
    source_root = Path(plan["source_root"]).resolve(strict=True)
    destination = Path(plan["destination_root"]).absolute()
    if destination.exists():
        raise FileExistsError(f"Destination already exists: {destination}")
    parent = destination.parent.resolve(strict=True)
    if _inside(destination, source_root):
        raise ValueError("Destination must not be inside the mother folder")
    selected = set(selected_projects or [])
    manifests = [
        item for item in plan.get("projects", [])
        if not selected or item.get("project") in selected
    ]
    if not manifests:
        raise ValueError("No projects selected for copy rehearsal")
    unknown = selected - {item.get("project") for item in manifests}
    if unknown:
        raise ValueError("Selection contains a project outside the plan")
    blocked = [item.get("project") for item in manifests if not item.get("copy_manifest_ready")]
    if blocked:
        raise ValueError("Blocked projects cannot enter copy rehearsal: " + ", ".join(blocked))

    required = sum(
        int(item.get("media_bytes", 0))
        + Path(item["project"]).stat().st_size
        for item in manifests
    )
    if shutil.disk_usage(parent).free < required + 64 * 1024 * 1024:
        raise OSError("Insufficient free space for hash-verified staging copy")
    staging = parent / f".daw-project-cleaner-separation-{uuid.uuid4().hex}"
    if staging.exists() or staging.is_symlink():
        raise FileExistsError(f"Unsafe staging collision: {staging}")
    staging.mkdir(mode=0o700)
    output = staging / "output"
    output.mkdir()
    operations: List[Dict] = []
    sources = sum((1 + len(item.get("media", [])) for item in manifests), 0)
    done = 0
    state = {
        "schema_version": 1,
        "kind": "separation_copy_rehearsal",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(source_root),
        "destination": str(destination),
        "status": "copying",
        "operations": operations,
        "mother_folder_modified": False,
        "cleanup_authorized": False,
    }
    _write_state(staging / "state.json", state)
    try:
        for manifest in manifests:
            project = Path(manifest["project"])
            _regular_source(project)
            expected_project_hash = manifest.get("project_sha256")
            current_project_hash = _sha256(project)
            if expected_project_hash and current_project_hash != expected_project_hash:
                raise ValueError(f"Project changed since audit: {project}")
            project_output = output / Path(manifest["destination_folder"]).name
            project_output.mkdir()
            targets = [(project, project_output / project.name, current_project_hash, "project")]
            for item in manifest.get("media", []):
                source = Path(item["source"])
                _regular_source(source)
                targets.append((source, project_output / item["destination_relative"], None, "media"))
            for source, target, known_hash, kind in targets:
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() or target.is_symlink():
                    raise FileExistsError(f"Staging destination collision: {target}")
                source_hash = known_hash or _sha256(source)
                shutil.copy2(source, target, follow_symlinks=False)
                target_hash = _sha256(target)
                if target_hash != source_hash:
                    raise OSError(f"Copied file hash mismatch: {target}")
                operations.append({
                    "kind": kind,
                    "source": str(source),
                    "destination": str(destination / target.relative_to(output)),
                    "size_bytes": source.stat().st_size,
                    "sha256": source_hash,
                })
                done += 1
                state["completed_files"] = done
                _write_state(staging / "state.json", state)
                if progress:
                    progress(done, sources, str(source))
        state["status"] = "verified_awaiting_daw_validation"
        state["completed_files"] = done
        _write_state(staging / "state.json", state)
        # Keep the state beside the published copies while publishing the whole
        # tree with one same-filesystem rename.
        shutil.copy2(staging / "state.json", output / ".separation-rehearsal.json")
        os.replace(output, destination)
        (staging / "state.json").unlink()
        os.rmdir(staging)
        return destination
    except Exception:
        # The staging name is generated here, verified non-link and constrained
        # to the exact destination parent. Source files are never removed.
        if staging.exists() and not staging.is_symlink() and staging.parent == parent:
            shutil.rmtree(staging)
        raise
