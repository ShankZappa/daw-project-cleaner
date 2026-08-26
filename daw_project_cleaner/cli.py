from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import PURGE_ENABLED, __version__
from .model import report_from_dict
from .archive_audit import audit_archive, save_audit
from .archive_queue import build_archive_queue
from .separation_plan import build_separation_plan
from .separation_stage import stage_separation_copy
from .publication import (
    build_publication_plan,
    publish_normalized_batch,
    restore_publication,
    withdraw_publication,
)
from .scanner import DEFAULT_EXCLUSIONS, save_report, scan_root
from .transaction import (
    SafetyError,
    purge_session,
    prepare_controlled_copy_marker,
    quarantine_backup_policy,
    quarantine_normalized_pilot,
    quarantine_normalized_batch,
    quarantine_report,
    restore_session,
    rewrite_quarantine_pilot,
)
from .rewrite_validation import save_validation, validate_corpus
from .remote_scan import REMOTE_EXCLUSIONS, remote_quick_scan
from .normalization_validation import (
    save_normalization_validation,
    validate_normalization_pair,
)


def _size(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return str(value)


def main() -> None:
    """Present an expected refusal as a sentence, not as a stack trace.

    Every gate in this tool is meant to fail closed and say why. Without this
    the message reached the operator as an unhandled Python traceback, and the
    native app put that traceback straight into an alert. Unexpected exceptions
    keep their traceback: those are defects and must stay visible.
    """
    try:
        _dispatch()
    except SafetyError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        raise SystemExit(3)
    except OSError as exc:
        print(f"Storage error: {exc}", file=sys.stderr)
        raise SystemExit(4)


def _dispatch() -> None:
    parser = argparse.ArgumentParser(
        prog="daw-project-cleaner",
        description="Safety-first Cubase/Nuendo project archive cleaner",
    )
    # The application decides what an operator sees; the command line used to
    # show all 21 subcommands, internal pilots and research paths included.
    # Everything keeps working - only discovery is narrowed to the documented
    # workflow. DAW_PROJECT_CLEANER_ADVANCED=1 lists the rest.
    advanced = os.environ.get("DAW_PROJECT_CLEANER_ADVANCED") == "1"
    parser.add_argument(
        "--version", action="version", version=f"daw-project-cleaner {__version__}",
        help="Print the version and exit",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def internal() -> dict:
        # argparse lists a subcommand only when it is given a help string, and
        # SUPPRESS is not honoured for subparsers - it prints literally. So the
        # keyword is omitted entirely to hide one.
        return {"help": "internal"} if advanced else {}
    scan = commands.add_parser("scan", help="Read-only safety scan of one project folder")
    scan.add_argument("root", type=Path)
    scan.add_argument("--report", type=Path, required=True)
    scan.add_argument("--exclude", action="append", default=[])
    scan.add_argument("--workers", type=int, default=4)
    scan.add_argument("--events-jsonl", action="store_true")
    scan.add_argument(
        "--keep-backups", choices=["all", "10", "5", "3", "1", "0"],
        default="0",
    )
    scan.add_argument("--backup-protect-media", action="store_true")
    remote_scan = commands.add_parser("remote-scan", **internal())
    remote_scan.add_argument("root", type=Path)
    remote_scan.add_argument("--report", type=Path, required=True)
    remote_scan.add_argument("--ui-report", type=Path)
    remote_scan.add_argument("--exclude", action="append", default=[])
    remote_scan.add_argument("--events-jsonl", action="store_true")
    remote_scan.add_argument("--no-resume", action="store_true")
    remote_scan.add_argument("--checkpoint-every", type=int, default=25)
    remote_scan.add_argument("--directory-limit", type=int)
    quarantine = commands.add_parser("quarantine", help="Move validated unused media into recoverable quarantine")
    quarantine.add_argument("report", type=Path)
    quarantine.add_argument("--confirm", required=True)
    pilot = commands.add_parser("apply-pilot", **internal())
    pilot.add_argument("report", type=Path)
    pilot.add_argument("--confirm", required=True)
    pilot.add_argument("--project", action="append")
    pilot.add_argument("--quarantine-root", type=Path)
    backup_apply = commands.add_parser("apply-backup-policy", help="Move policy-selected older backups into recoverable quarantine")
    backup_apply.add_argument("report", type=Path)
    backup_apply.add_argument("--quarantine-root", type=Path, required=True)
    backup_apply.add_argument("--confirm", required=True)
    prepare = commands.add_parser("prepare-controlled-copy", **internal())
    prepare.add_argument("root", type=Path)
    prepare.add_argument("--confirm", required=True)
    restore = commands.add_parser("restore", help="Return every file in a quarantine session to its exact source")
    restore.add_argument("session", type=Path)
    purge = commands.add_parser(
        "purge",
        **({"help": "Permanently delete a validated session after the recovery window"}
           if PURGE_ENABLED else {}),
    )
    purge.add_argument("session", type=Path)
    purge.add_argument("--confirm", required=True)
    audit = commands.add_parser("archive-audit", **internal())
    audit.add_argument("root", type=Path)
    audit.add_argument("--report", type=Path, required=True)
    audit.add_argument("--workers", type=int, default=4)
    audit.add_argument("--sample-projects", type=int)
    audit.add_argument("--seed", type=int, default=89)
    archive_plan = commands.add_parser("archive-plan", **internal())
    archive_plan.add_argument("audit", type=Path)
    archive_plan.add_argument("--report", type=Path, required=True)
    archive_plan.add_argument("--target", default="Nuendo 15")
    archive_queue = commands.add_parser("archive-queue", help="Plan the shared-archive workflow for folders with shared media")
    archive_queue.add_argument("root", type=Path)
    archive_queue.add_argument("--report", type=Path, required=True)
    archive_queue.add_argument("--audit-report", type=Path, required=True)
    archive_queue.add_argument("--workers", type=int, default=4)
    archive_queue.add_argument("--target", default="Nuendo 15")
    separation = commands.add_parser("separation-plan", **internal())
    separation.add_argument("audit", type=Path)
    separation.add_argument("--report", type=Path, required=True)
    separation.add_argument("--destination-root", type=Path, required=True)
    separation.add_argument("--master-project")
    separation.add_argument("--target", default="Nuendo 15")
    separation.add_argument(
        "--resolve-missing-file", type=Path, action="append", default=[],
        help="Exact-name regular file for a missing media reference",
    )
    separation_stage = commands.add_parser("stage-separation-copy", **internal())
    separation_stage.add_argument("plan", type=Path)
    separation_stage.add_argument("--project", action="append")
    separation_stage.add_argument("--confirm", required=True)
    publication_plan = commands.add_parser("publication-plan", **internal())
    publication_plan.add_argument("--validation", type=Path, action="append", required=True)
    publication_plan.add_argument("--destination", type=Path, required=True)
    publication_plan.add_argument("--report", type=Path, required=True)
    publication_apply = commands.add_parser("publish-normalized-batch", **internal())
    publication_apply.add_argument("plan", type=Path)
    publication_apply.add_argument("--confirm", required=True)
    publication_withdraw = commands.add_parser("withdraw-publication", **internal())
    publication_withdraw.add_argument("destination", type=Path)
    publication_withdraw.add_argument("--quarantine", type=Path, required=True)
    publication_withdraw.add_argument("--confirm", required=True)
    publication_restore = commands.add_parser("restore-publication", **internal())
    publication_restore.add_argument("session", type=Path)
    normalization = commands.add_parser("validate-normalization", help="Compare a DAW-created CONTROL/CLEANED pair")
    normalization.add_argument("control", type=Path)
    normalization.add_argument("cleaned", type=Path)
    normalization.add_argument("--media-root", type=Path, required=True)
    normalization.add_argument("--report", type=Path, required=True)
    normalization.add_argument("--daw-open-confirmed", action="store_true")
    normalized_apply = commands.add_parser("apply-normalized-pilot", **internal())
    normalized_apply.add_argument("report", type=Path)
    normalized_apply.add_argument("--confirm", required=True)
    normalized_batch = commands.add_parser("apply-normalized-batch", help="Quarantine media a validated CLEANED batch no longer references")
    normalized_batch.add_argument("--report", type=Path, action="append", required=True)
    normalized_batch.add_argument("--confirm", required=True)
    rewrite_validation = commands.add_parser("rewrite-validate", **internal())
    rewrite_validation.add_argument("corpus", type=Path)
    rewrite_validation.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "quarantine":
        if args.confirm != "QUARANTINE":
            parser.error("quarantine confirmation did not match")
        raw = json.loads(args.report.read_text(encoding="utf-8"))
        session = quarantine_report(report_from_dict(raw), lambda done, total, path: print(f"[{done}/{total}] {path}", flush=True))
        print(f"SESSION: {session}")
        return
    if args.command == "apply-pilot":
        if args.confirm != "CONTROLLED COPY APPLY":
            parser.error("controlled-copy Apply confirmation did not match")
        raw = json.loads(args.report.read_text(encoding="utf-8"))
        session = rewrite_quarantine_pilot(
            report_from_dict(raw),
            lambda done, total, path: print(f"[{done}/{total}] {path}", flush=True),
            selected_project_paths=args.project,
            quarantine_root=args.quarantine_root,
        )
        print(f"PILOT SESSION: {session}")
        return
    if args.command == "apply-normalized-pilot":
        if args.confirm != "QUARANTINE NORMALIZED COPY":
            parser.error("normalized-copy Apply confirmation did not match")
        validation = json.loads(args.report.read_text(encoding="utf-8"))
        session = quarantine_normalized_pilot(
            validation,
            lambda done, total, path: print(
                f"[{done}/{total}] {path}", flush=True
            ),
        )
        print(f"NORMALIZED PILOT SESSION: {session}")
        return
    if args.command == "apply-normalized-batch":
        if args.confirm != "QUARANTINE NORMALIZED BATCH":
            parser.error("normalized-batch Apply confirmation did not match")
        validations = [
            json.loads(path.read_text(encoding="utf-8")) for path in args.report
        ]
        for validation in validations:
            prepare_controlled_copy_marker(Path(validation["media_root"]))
        sessions = quarantine_normalized_batch(
            validations,
            lambda done, total, path: print(
                f"[{done}/{total}] {path}", flush=True
            ),
        )
        for session in sessions:
            print(f"NORMALIZED BATCH SESSION: {session}")
        return
    if args.command == "apply-backup-policy":
        if args.confirm != "APPLY BACKUP POLICY":
            parser.error("backup policy confirmation did not match")
        raw = json.loads(args.report.read_text(encoding="utf-8"))
        session = quarantine_backup_policy(
            report_from_dict(raw), args.quarantine_root,
            lambda done, total, path: print(
                f"[{done}/{total}] {path}", flush=True
            ),
        )
        print(f"BACKUP SESSION: {session}")
        return
    if args.command == "prepare-controlled-copy":
        if args.confirm != "THIS IS A DISPOSABLE COPY":
            parser.error("controlled-copy marker confirmation did not match")
        marker = prepare_controlled_copy_marker(args.root)
        print(f"CONTROLLED COPY MARKER: {marker}")
        return
    if args.command == "restore":
        print(f"Restored files: {restore_session(args.session)}")
        return
    if args.command == "purge":
        print(f"Permanently deleted quarantined files: {purge_session(args.session, args.confirm)}")
        return
    if args.command == "archive-audit":
        result = audit_archive(
            args.root, workers=args.workers, sample_projects=args.sample_projects,
            seed=args.seed, progress=lambda message: print(message, flush=True),
        )
        save_audit(result, args.report)
        print(json.dumps(result["summary"], indent=2), flush=True)
        print(f"Report: {args.report.resolve()}")
        return
    if args.command == "archive-plan":
        audit_result = json.loads(args.audit.read_text(encoding="utf-8"))
        result = build_archive_queue(audit_result, target=args.target)
        save_audit(result, args.report)
        print(json.dumps(result["summary"], indent=2), flush=True)
        print(f"Report: {args.report.resolve()}")
        return
    if args.command == "archive-queue":
        audit_result = audit_archive(
            args.root, workers=args.workers,
            progress=lambda message: print(message, flush=True),
        )
        save_audit(audit_result, args.audit_report)
        result = build_archive_queue(audit_result, target=args.target)
        save_audit(result, args.report)
        print(json.dumps(result["summary"], indent=2), flush=True)
        print(f"Audit report: {args.audit_report.resolve()}")
        print(f"Queue report: {args.report.resolve()}")
        return
    if args.command == "separation-plan":
        audit_result = json.loads(args.audit.read_text(encoding="utf-8"))
        result = build_separation_plan(
            audit_result,
            args.destination_root,
            master_project=args.master_project,
            target_application=args.target,
            missing_media_files=args.resolve_missing_file,
        )
        save_audit(result, args.report)
        print(json.dumps(result["summary"], indent=2), flush=True)
        print(f"Report: {args.report.resolve()}")
        return
    if args.command == "stage-separation-copy":
        if args.confirm != "STAGE SEPARATION COPY":
            parser.error("separation-copy confirmation did not match")
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        destination = stage_separation_copy(
            plan,
            selected_projects=args.project,
            progress=lambda done, total, path: print(
                f"[{done}/{total}] {path}", flush=True
            ),
        )
        print(f"SEPARATION COPY: {destination}")
        return
    if args.command == "publication-plan":
        validations = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in args.validation
        ]
        result = build_publication_plan(validations, args.destination)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.report.with_name(args.report.name + ".tmp")
        temporary.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(args.report)
        print(json.dumps(result["summary"], indent=2), flush=True)
        print(f"Report: {args.report.resolve()}")
        return
    if args.command == "publish-normalized-batch":
        if args.confirm != "PUBLISH VERIFIED PROJECT BATCH":
            parser.error("publication confirmation did not match")
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        destination = publish_normalized_batch(
            plan, progress=lambda done, total, path: print(
                f"[{done}/{total}] {path}", flush=True
            ),
        )
        print(f"PUBLISHED VERIFIED BATCH: {destination}")
        return
    if args.command == "withdraw-publication":
        if args.confirm != "WITHDRAW VERIFIED PUBLICATION":
            parser.error("publication withdrawal confirmation did not match")
        session = withdraw_publication(args.destination, args.quarantine)
        print(f"PUBLICATION WITHDRAWAL SESSION: {session}")
        return
    if args.command == "restore-publication":
        destination = restore_publication(args.session)
        print(f"RESTORED PUBLICATION: {destination}")
        return
    if args.command == "validate-normalization":
        result = validate_normalization_pair(
            args.control, args.cleaned, args.media_root,
            daw_open_confirmed=args.daw_open_confirmed,
        )
        save_normalization_validation(result, args.report)
        print(json.dumps(result["summary"], indent=2), flush=True)
        print(f"Report: {args.report.resolve()}")
        if not result["summary"]["structural_valid"]:
            raise SystemExit(2)
        return
    if args.command == "rewrite-validate":
        result = validate_corpus(args.corpus)
        save_validation(result, args.report)
        print(json.dumps(result["summary"], indent=2), flush=True)
        print(f"Report: {args.report.resolve()}")
        if result["summary"]["blocked"]:
            raise SystemExit(2)
        return
    if args.command == "remote-scan":
        result = remote_quick_scan(
            args.root, args.report, ui_report_path=args.ui_report,
            exclusions=REMOTE_EXCLUSIONS + args.exclude,
            progress=lambda done, total, path: print(
                f"[{done}/{total}] {path}", flush=True
            ),
            result_callback=(
                lambda item: print(
                    "PROJECT_EVENT " + json.dumps(
                        item, ensure_ascii=False, separators=(",", ":")
                    ), flush=True,
                )
            ) if args.events_jsonl else None,
            resume=not args.no_resume,
            checkpoint_every=args.checkpoint_every,
            directory_limit=args.directory_limit,
        )
        summary = result["summary"]
        print(
            f"Quick inventory: {summary['projects']} projects, "
            f"{summary['backups']} backups, {summary['media_files']} media files",
            flush=True,
        )
        print(
            "Quick inventory complete" if result["complete"]
            else "Quick inventory paused; progress is saved",
            flush=True,
        )
        print(f"Report: {(args.ui_report or args.report).resolve()}")
        if not result["complete"]:
            raise SystemExit(130)
        return
    report = scan_root(
        args.root,
        DEFAULT_EXCLUSIONS + args.exclude,
        args.workers,
        lambda done, total, path: print(f"[{done}/{total}] {path}", flush=True),
        result_callback=(
            lambda result: print(
                "PROJECT_EVENT " + json.dumps(
                    result.to_dict(), ensure_ascii=False, separators=(",", ":")
                ),
                flush=True,
            )
        ) if args.events_jsonl else None,
        backup_keep=None if args.keep_backups == "all" else int(args.keep_backups),
        backup_protect_media=args.backup_protect_media,
    )
    save_report(report, args.report)
    print(f"Projects: {len(report.projects)}")
    print(f"Potential candidates: {_size(report.potential_reclaimable_bytes)}")
    print(
        f"Backups: {len(report.backups)} found, "
        f"{sum(item.action == 'quarantine' for item in report.backups)} to quarantine"
    )
    print(f"Report: {args.report.resolve()}")


if __name__ == "__main__":
    main()
