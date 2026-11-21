from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from .channels_uploader import (
    UploadBlockedError,
    approve_run,
    inspect_channels_ui,
    open_channels_session,
    reconcile_upload,
    upload_run_to_channels,
)
from .model_setup import download_chinese_model, download_model
from .pipeline import run_slice_a
from .preflight import run_preflight
from .tooling import describe_tools, tool_path_for_bat


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    root = _project_root()
    parser = argparse.ArgumentParser(
        prog="wechat-video",
        description="WeChat science animation — local production and unpublished Channels drafts",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    preflight = sub.add_parser("preflight", help="Check the local rendering and TTS environment.")
    preflight.add_argument("--project-root", type=Path, default=root)
    preflight.add_argument("--allow-missing-model", action="store_true")

    model = sub.add_parser("download-model", help="Download the default English Piper VITS voice.")
    model.add_argument("--project-root", type=Path, default=root)
    model_zh = sub.add_parser("download-model-zh", help="Download the legacy MeloTTS zh_en rollback voice.")
    model_zh.add_argument("--project-root", type=Path, default=root)

    sub.add_parser(
        "tool-path",
        help="Print project-local tool bin directories for the BAT launchers.",
    )
    sub.add_parser(
        "tools-status",
        help="Print resolved project-local tool and model status as JSON.",
    )

    run = sub.add_parser("run-slice-a", help="Create one local critical-nucleus sample MP4.")
    run.add_argument("--project-root", type=Path, default=root)
    run.add_argument(
        "--fact-card",
        type=Path,
        default=root / "fact_cards" / "critical_nucleus_free_energy_candidate.json",
    )
    run.add_argument(
        "--script",
        type=Path,
        default=root / "content" / "sample_script.en.json",
    )
    run.add_argument("--output-root", type=Path, default=Path("outputs"))
    run.add_argument(
        "--review-sample",
        action="store_true",
        help="Allow a pending Fact Card for a local review sample; output remains not-for-publication.",
    )

    session = sub.add_parser(
        "channels-session",
        help="Open/reuse the dedicated Edge profile at the official Channels Assistant page.",
    )
    session.add_argument("--project-root", type=Path, default=root)
    session.add_argument(
        "--wait-login-seconds",
        type=int,
        default=0,
        help="Optional bounded wait for the expected account name after manual QR login.",
    )

    inspect = sub.add_parser(
        "channels-inspect",
        help="Inspect visible Channels UI controls without uploading or saving anything.",
    )
    inspect.add_argument("--project-root", type=Path, default=root)

    approve = sub.add_parser(
        "approve-run",
        help="Record explicit human approval of one QA-passed video and its Fact Card.",
    )
    approve.add_argument("--project-root", type=Path, default=root)
    approve.add_argument("--run-dir", type=Path, required=True)
    approve.add_argument("--approved-by", default=getpass.getuser())

    upload = sub.add_parser(
        "channels-upload",
        help="Upload one explicitly approved, QA-passed run and save it as an unpublished draft.",
    )
    upload.add_argument("--project-root", type=Path, default=root)
    upload.add_argument("--run-dir", type=Path, required=True)

    reconcile = sub.add_parser(
        "channels-reconcile",
        help="Read-only reconciliation of a prior uncertain upload; never uploads or clicks Save.",
    )
    reconcile.add_argument("--project-root", type=Path, default=root)
    reconcile.add_argument("--job-id", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    root = _project_root()
    args = build_parser().parse_args(argv)
    try:
        if args.command == "preflight":
            result = run_preflight(
                args.project_root.resolve(),
                require_tts_model=not args.allow_missing_model,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "download-model":
            model_path = download_model(args.project_root.resolve())
            print(f"Local offline English TTS model ready: {model_path}")
            return 0
        if args.command == "download-model-zh":
            model_path = download_chinese_model(args.project_root.resolve())
            print(f"Local offline legacy zh TTS model ready: {model_path}")
            return 0
        if args.command == "tool-path":
            print(tool_path_for_bat(root))
            return 0
        if args.command == "tools-status":
            print(json.dumps(describe_tools(root), ensure_ascii=False, indent=2))
            return 0
        if args.command == "run-slice-a":
            run_dir = run_slice_a(
                args.project_root,
                card_path=args.fact_card,
                script_path=args.script,
                output_root=args.output_root,
                allow_pending_review=args.review_sample,
            )
            print(f"\nSlice A review package: {run_dir}")
            print(f"Video: {run_dir / 'final.mp4'}")
            print(f"Report: {run_dir / 'qa_report.json'}")
            print(f"Channels metadata: {run_dir / 'channels_draft.json'}")
            return 0
        if args.command == "channels-session":
            result = open_channels_session(
                args.project_root.resolve(),
                wait_login_seconds=args.wait_login_seconds,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "channels-inspect":
            result = inspect_channels_ui(args.project_root.resolve())
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "approve-run":
            result = approve_run(
                args.project_root.resolve(),
                args.run_dir,
                approved_by=args.approved_by,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print("Local approval recorded. This exact artifact package is now eligible for draft upload.")
            return 0
        if args.command == "channels-upload":
            result = upload_run_to_channels(args.project_root.resolve(), args.run_dir)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print("Verified unpublished draft. No Publish/Send action was performed.")
            return 0
        if args.command == "channels-reconcile":
            result = reconcile_upload(args.project_root.resolve(), args.job_id)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        return 2
    except UploadBlockedError as exc:
        print(f"\nCHANNELS WORKFLOW BLOCKED: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"\nWECHAT VIDEO FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
