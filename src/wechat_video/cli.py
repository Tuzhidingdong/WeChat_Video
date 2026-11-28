from __future__ import annotations

import uuid

import argparse
import getpass
import json
import sys
from datetime import datetime
from pathlib import Path

from .article_summary import run_article_summary
from .daily_pipelines import (
    inspect_daily_literature_sources,
    run_daily_literature,
    run_daily_popularization,
    run_daily_two_videos,
)
from .daily_readiness import inspect_daily_two_video_readiness
from . import channels_uploader as cu
from .channels_uploader import (
    UploadBlockedError,
    approve_latest_run,
    approve_run,
    inspect_channels_ui,
    open_channels_session,
    reconcile_upload,
    record_manual_review,
    upload_latest_approved_run,
    upload_run_to_channels,
)
from .micro_visual_browser import load_flow_config
from .micro_visual_continuation import continue_micro_visual_run, finalize_existing_draft
from .micro_visual_browser_lifecycle import BrowserLifecycle
from .micro_visual_pipeline import (
    DRAFT_SAVED, STOPPED_BEFORE_FLOW_SUBMIT, run_literature_micro_visual,
)
from .micro_visual_status import classify_micro_visual_result
from .micro_visual_unified import run_unified
from .model_setup import download_chinese_model, download_model
from .pipeline import run_slice_a
from .preflight import run_preflight
from .publication_source_evidence import (
    PublicationSourceEvidenceError,
    record_source_evidence,
)
from .topic_approval import approve_fact_card
from .tooling import describe_tools, tool_path_for_bat


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _validate_editorial_angle(card_path: Path, script_path: Path) -> None:
    """Refuse a script that does not match the fact card's editorial angle."""
    card = json.loads(card_path.read_text(encoding="utf-8"))
    script = json.loads(script_path.read_text(encoding="utf-8"))
    expected = str(card.get("editorial_angle_id") or "").strip()
    actual = str(script.get("editorial_angle_id") or "").strip()
    if expected and expected != actual:
        raise SystemExit(
            f"Fact Card editorial_angle_id {expected!r} does not match script "
            f"{script_path.name} (editorial_angle_id {actual!r}). "
            "Refusing to silently fall back to a different script. "
            "Pass the matching --script explicitly."
        )
    if not expected and actual:
        raise SystemExit(
            f"Script {script_path.name} declares editorial angle {actual!r}, but the "
            "Fact Card declares none. Pass the matching --fact-card explicitly."
        )


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
    model_zh = sub.add_parser("download-model-zh", help="Download the local Chinese MeloTTS model for article-summary narration.")
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

    run_and_upload = sub.add_parser(
        "run-slice-a-and-upload-draft",
        help="Generate the current Slice A review sample and save it as an unpublished draft.",
    )
    run_and_upload.add_argument("--project-root", type=Path, default=root)
    run_and_upload.add_argument(
        "--fact-card",
        type=Path,
        default=root / "fact_cards" / "critical_nucleus_free_energy_candidate.json",
    )
    run_and_upload.add_argument(
        "--script",
        type=Path,
        default=root / "content" / "sample_script.en.json",
    )
    run_and_upload.add_argument("--output-root", type=Path, default=Path("outputs"))

    session = sub.add_parser(
        "channels-session",
        help="Open/reuse the dedicated Edge profile at the official Channels Assistant page.",
    )
    session.add_argument("--project-root", type=Path, default=root)
    session.add_argument(
        "--wait-login-seconds",
        type=int,
        default=5,
        help="Brief bounded wait for the expected account name after the page loads; QR login remains manual.",
    )

    inspect = sub.add_parser(
        "channels-inspect",
        help="Inspect visible Channels UI controls without uploading or saving anything.",
    )
    inspect.add_argument("--project-root", type=Path, default=root)

    approve_card = sub.add_parser(
        "approve-fact-card",
        help="Record a one-time topic-governance approval for the human-approved Verified Topic Pool.",
    )
    approve_card.add_argument("--project-root", type=Path, default=root)
    approve_card.add_argument(
        "--card",
        type=Path,
        default=root / "fact_cards" / "critical_nucleus_free_energy_candidate.json",
    )
    approve_card.add_argument("--approved-by", default=getpass.getuser())

    approve = sub.add_parser(
        "approve-run",
        help="Record an optional local review receipt for one QA-passed video and its Fact Card.",
    )
    approve.add_argument("--project-root", type=Path, default=root)
    approve.add_argument("--run-dir", type=Path, required=True)
    approve.add_argument("--approved-by", default=getpass.getuser())

    upload = sub.add_parser(
        "channels-upload",
        help="Upload one strict-QA-PASS run and save it as an unpublished draft.",
    )
    upload.add_argument("--project-root", type=Path, default=root)
    upload.add_argument("--run-dir", type=Path, required=True)

    approve_latest = sub.add_parser(
        "approve-latest-run",
        help="Review the newest strict-QA-PASS output and record explicit human approval.",
    )
    approve_latest.add_argument("--project-root", type=Path, default=root)
    approve_latest.add_argument("--approved-by", default=getpass.getuser())

    upload_latest = sub.add_parser(
        "channels-upload-latest",
        help="Upload the newest strict-QA-PASS run; duplicate protection remains active.",
    )
    upload_latest.add_argument("--project-root", type=Path, default=root)

    reconcile = sub.add_parser(
        "channels-reconcile",
        help="Read-only reconciliation of a prior uncertain upload; never uploads or clicks Save.",
    )
    reconcile.add_argument("--project-root", type=Path, default=root)
    reconcile.add_argument("--job-id", required=True)

    manual_review = sub.add_parser(
        "channels-record-manual-review",
        help="Record an explicit user inspection of an uncertain draft; never opens a browser or retries upload.",
    )
    manual_review.add_argument("--project-root", type=Path, default=root)
    manual_review.add_argument("--job-id", required=True)
    manual_review.add_argument(
        "--result",
        choices=("draft-found", "not-found"),
        required=True,
    )
    manual_review.add_argument("--reviewed-by", default=getpass.getuser())
    manual_review.add_argument("--row-text")
    manual_review.add_argument("--note", default="")
    manual_review.add_argument("--confirmation", required=True)

    article_summary = sub.add_parser(
        "run-article-summary",
        help="Create a local-only Chinese one-minute video from an exported published WeChat article.",
    )
    article_summary.add_argument("--project-root", type=Path, default=root)
    article_summary.add_argument("--article-dir", type=Path, required=True)
    article_summary.add_argument("--summary", type=Path, required=True)
    article_summary.add_argument("--output-root", type=Path, default=Path("outputs"))

    inspect_literature = sub.add_parser(
        "inspect-literature-upstream",
        help="Read-only inspect of eligible published articles from WeChat_control daily-run artifacts; no production side effects.",
    )
    inspect_literature.add_argument("--project-root", type=Path, default=root)
    inspect_literature.add_argument("--published-date", help="Optional Asia/Shanghai publication date YYYY-MM-DD.")

    record_source = sub.add_parser(
        "record-literature-source-evidence",
        help="Atomically add a validated browser-observed publication source to the unique matching Video evidence bundle.",
    )
    record_source.add_argument("--project-root", type=Path, default=root)
    record_source.add_argument("--observation", type=Path, required=True)

    readiness = sub.add_parser(
        "inspect-daily-two-video-readiness",
        help="Read-only unified readiness report for both daily BATs; starts no production step.",
    )
    readiness.add_argument("--project-root", type=Path, default=root)
    readiness.add_argument("--published-date", help="Optional Asia/Shanghai publication date YYYY-MM-DD.")

    literature_daily = sub.add_parser(
        "run-literature-daily",
        help="Select yesterday's published literature article, render it, QA it, and save the exact output as a draft.",
    )
    literature_daily.add_argument("--project-root", type=Path, default=root)
    literature_daily.add_argument("--published-date", help="Optional Asia/Shanghai publication date YYYY-MM-DD.")

    popularization_daily = sub.add_parser(
        "run-popularization-daily",
        help="Select one unused approved Fact Card, render it, QA it, and save the exact output as a draft.",
    )
    popularization_daily.add_argument("--project-root", type=Path, default=root)
    popularization_daily.add_argument("--local-date", help="Optional Asia/Shanghai job date YYYY-MM-DD.")

    daily_both = sub.add_parser(
        "run-daily-two-videos",
        help="Run literature and popularization pipelines sequentially and report each result independently.",
    )
    daily_both.add_argument("--project-root", type=Path, default=root)
    daily_both.add_argument("--published-date", help="Optional Asia/Shanghai publication date YYYY-MM-DD.")

    micro_visual = sub.add_parser(
        "run-literature-micro-visual",
        help="Create one 15s Flow video from an existing summary and save a verified draft.",
    )
    micro_visual.add_argument("--project-root", type=Path, default=root)
    micro_visual.add_argument("--published-date", help="Optional Asia/Shanghai publication date YYYY-MM-DD.")
    micro_visual.add_argument("--state-file", type=Path, default=None,
                              help="Write the business status JSON used by the BAT for user-visible text.")

    continuation = sub.add_parser(
        "continue-micro-visual",
        help="Continue ONE frozen Micro Visual job from Flow submission to a verified draft.",
    )
    continuation.add_argument("--project-root", type=Path, default=root)
    continuation.add_argument("--job-id", required=True,
                              help="Existing job directory name under outputs/.")
    continuation.add_argument("--state-file", type=Path, default=None)

    finalize_draft = sub.add_parser(
        "finalize-micro-visual-draft",
        help="Finalize an already-saved Micro Visual draft without uploading again.",
    )
    finalize_draft.add_argument("--project-root", type=Path, default=root)
    finalize_draft.add_argument("--job-id", required=True)

    unified = sub.add_parser(
        "run-micro-visual-unified",
        help="Automatically resume a safe unfinished job or run the full Micro Visual pipeline.",
    )
    unified.add_argument("--project-root", type=Path, default=root)
    unified.add_argument("--state-file", type=Path, default=None)

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
            print(f"Local offline Chinese MeloTTS model ready: {model_path}")
            return 0
        if args.command == "tool-path":
            print(tool_path_for_bat(root))
            return 0
        if args.command == "tools-status":
            print(json.dumps(describe_tools(root), ensure_ascii=False, indent=2))
            return 0
        if args.command == "run-article-summary":
            run_dir = run_article_summary(
                args.project_root,
                article_dir=args.article_dir,
                summary_path=args.summary,
                output_root=args.output_root,
            )
            print(json.dumps({
                "run_dir": str(run_dir),
                "video": str(run_dir / "final.mp4"),
                "qa_report": str(run_dir / "qa_report.json"),
                "channels_metadata": str(run_dir / "channels_draft.json"),
                "upload_eligible": _read_json(run_dir / "content_qa_report.json").get("upload_eligible") is True,
                "automatic_upload": False,
                "automatic_publication": False,
            }, ensure_ascii=False, indent=2))
            print("Local article-summary preview created. No upload or publication was attempted.")
            return 0
        if args.command == "inspect-literature-upstream":
            result = inspect_daily_literature_sources(
                args.project_root,
                published_date=args.published_date,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "record-literature-source-evidence":
            project_root = args.project_root.resolve()
            config = json.loads((project_root / "configs" / "daily_pipelines.json").read_text(encoding="utf-8"))
            outputs_root = project_root / str(config.get("outputs_root") or "outputs")
            result = record_source_evidence(
                observation_path=args.observation,
                evidence_root=outputs_root,
                expected_biz_id=str(config["literature"]["expected_public_account_biz_id"]),
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "inspect-daily-two-video-readiness":
            result = inspect_daily_two_video_readiness(
                args.project_root,
                published_date=args.published_date,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "run-literature-daily":
            result = run_daily_literature(
                args.project_root,
                published_date=args.published_date,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            selected = result.get("selected_article") or {}
            print(
                f"[LITERATURE SUMMARY] window="
                f"{result.get('window_start', 'n/a')}..{result.get('window_end', 'n/a')} "
                f"scanned_runs={result.get('upstream_run_count', 0)} "
                f"found={result.get('found_article_count', 0)} "
                f"eligible={result.get('candidate_count', 0)} "
                f"deferred={len(result.get('deferred_candidates') or [])}"
            )
            if selected:
                print(
                    f"[LITERATURE SUMMARY] selected={selected.get('article_id')} "
                    f"published={selected.get('local_date')} title={selected.get('title')}"
                )
            elif result.get("reason"):
                print(f"[LITERATURE SUMMARY] reason={result['reason']}")
            return 0 if result.get("state") in {
                "DRAFT_SAVED", "SKIPPED_NO_ELIGIBLE_ARTICLE", "DISABLED"
            } else 2 if result.get("state") == "UPLOAD_UNKNOWN" else 1
        if args.command == "run-popularization-daily":
            result = run_daily_popularization(
                args.project_root,
                local_date=args.local_date,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("state") in {
                "DRAFT_SAVED", "SKIPPED_NO_APPROVED_TOPIC", "DISABLED"
            } else 2 if result.get("state") == "UPLOAD_UNKNOWN" else 1
        if args.command == "run-daily-two-videos":
            result = run_daily_two_videos(
                args.project_root,
                published_date=args.published_date,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("overall_state") in {"DRAFTS_SAVED", "COMPLETED_WITH_SKIPS"} else 2
        if args.command == "run-micro-visual-unified":
            project_root = args.project_root.resolve()
            state_path = Path(args.state_file).resolve() if args.state_file is not None else None
            run_id = f"mv-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
            if state_path is not None:
                try:
                    state_path.parent.mkdir(parents=True, exist_ok=True)
                    cu._write_json_atomic(state_path, {
                        "run_id": run_id, "state": "RUNNING", "success": False,
                        "message": "统一入口已启动，正在判断续作或新建。", "exit_code": None,
                    })
                except Exception:  # noqa: BLE001
                    pass
            lifecycle = None
            before_sessions: dict[str, dict[str, object]] = {}
            try:
                flow_cfg = load_flow_config(project_root)
                override = flow_cfg.get("_uploader_config_override") or {}
                uploader_session = Path(
                    str(override.get("session_file") or (project_root / "runtime/edge_session.json"))
                ).resolve()
                lifecycle = BrowserLifecycle(project_root, {
                    "flow": Path(flow_cfg["_flow_session_file"]).resolve(),
                    "uploader": uploader_session,
                })
                before_sessions = lifecycle.snapshot()
            except Exception:  # noqa: BLE001
                lifecycle = None
            result = None
            try:
                result = run_unified(project_root)
            finally:
                if lifecycle is not None:
                    lifecycle.close_owned(before_sessions)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            status = classify_micro_visual_result(result)
            message = status["message"]
            if isinstance(result, dict) and result.get("unified_mode"):
                message = (
                    f"[统一入口:{result['unified_mode']}] "
                    + (f"job={result.get('unified_job_id')} " if result.get("unified_job_id") else "")
                    + message
                )
            if state_path is not None:
                try:
                    cu._write_json_atomic(state_path, {
                        "run_id": run_id, "state": status["state"], "success": status["success"],
                        "message": message, "exit_code": status["exit_code"],
                        "unified_mode": (result or {}).get("unified_mode"),
                        "unified_job_id": (result or {}).get("unified_job_id"),
                        "verified_draft": (result or {}).get("verified_draft"),
                        "draft_title": (result or {}).get("draft_title"),
                        "browser_cleanup": getattr(lifecycle, "results", []),
                    })
                except Exception:  # noqa: BLE001
                    pass
            print(f"[MICRO VISUAL STATE] {message}")
            return int(status["exit_code"])
        if args.command == "finalize-micro-visual-draft":
            result = finalize_existing_draft(args.project_root.resolve(), args.job_id)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            status = classify_micro_visual_result(result)
            print(f"[MICRO VISUAL STATE] {status['message']}")
            return int(status["exit_code"])
        if args.command == "continue-micro-visual":
            project_root = args.project_root.resolve()
            state_path = Path(args.state_file).resolve() if args.state_file is not None else None
            run_id = f"mv-cont-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
            if state_path is not None:
                try:
                    state_path.parent.mkdir(parents=True, exist_ok=True)
                    cu._write_json_atomic(state_path, {
                        "run_id": run_id, "state": "RUNNING", "success": False,
                        "message": "本次续作已启动，业务结果尚未确定。", "exit_code": None,
                    })
                except Exception:  # noqa: BLE001
                    pass
            lifecycle = None
            before_sessions: dict[str, dict[str, object]] = {}
            try:
                flow_cfg = load_flow_config(project_root)
                override = flow_cfg.get("_uploader_config_override") or {}
                uploader_session = Path(
                    str(override.get("session_file") or (project_root / "runtime/edge_session.json"))
                ).resolve()
                lifecycle = BrowserLifecycle(project_root, {
                    "flow": Path(flow_cfg["_flow_session_file"]).resolve(),
                    "uploader": uploader_session,
                })
                before_sessions = lifecycle.snapshot()
            except Exception:  # noqa: BLE001
                lifecycle = None
            result = None
            try:
                result = continue_micro_visual_run(
                    project_root, args.job_id
                )
            finally:
                if lifecycle is not None:
                    lifecycle.close_owned(before_sessions)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            status = classify_micro_visual_result(result)
            if state_path is not None:
                try:
                    cu._write_json_atomic(state_path, {
                        "run_id": run_id, "state": status["state"], "success": status["success"],
                        "message": status["message"], "exit_code": status["exit_code"],
                        "verified_draft": (result or {}).get("verified_draft"),
                        "draft_title": (result or {}).get("draft_title"),
                        "browser_cleanup": getattr(lifecycle, "results", []),
                    })
                except Exception:  # noqa: BLE001
                    pass
            print(f"[MICRO VISUAL STATE] {status['message']}")
            return int(status["exit_code"])
        if args.command == "run-literature-micro-visual":
            project_root = args.project_root.resolve()
            state_path = Path(args.state_file).resolve() if args.state_file is not None else None
            run_id = f"mv-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
            if state_path is not None:
                try:
                    state_path.parent.mkdir(parents=True, exist_ok=True)
                    cu._write_json_atomic(state_path, {
                        "run_id": run_id,
                        "state": "RUNNING",
                        "success": False,
                        "message": "本次运行已启动，业务结果尚未确定。",
                        "exit_code": None,
                    })
                except Exception:  # noqa: BLE001 - never mask the business result
                    pass
            lifecycle = None
            before_sessions: dict[str, dict[str, object]] = {}
            try:
                flow_cfg = load_flow_config(project_root)
                override = flow_cfg.get("_uploader_config_override") or {}
                uploader_session = Path(
                    str(override.get("session_file") or (project_root / "runtime/edge_session.json"))
                ).resolve()
                lifecycle = BrowserLifecycle(project_root, {
                    "flow": Path(flow_cfg["_flow_session_file"]).resolve(),
                    "uploader": uploader_session,
                })
                before_sessions = lifecycle.snapshot()
            except Exception:  # noqa: BLE001 - cleanup is best-effort, never masks business result
                lifecycle = None
            result = None
            try:
                result = run_literature_micro_visual(
                    args.project_root, published_date=args.published_date,
                    run_id=run_id,
                )
            finally:
                if lifecycle is not None:
                    lifecycle.close_owned(before_sessions)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            status = classify_micro_visual_result(result)
            if state_path is not None:
                try:
                    cu._write_json_atomic(state_path, {
                        "run_id": run_id,
                        "state": status["state"],
                        "success": status["success"],
                        "message": status["message"],
                        "exit_code": status["exit_code"],
                        "verified_draft": (result or {}).get("verified_draft"),
                        "draft_title": (result or {}).get("draft_title"),
                        "browser_cleanup": getattr(lifecycle, "results", []),
                    })
                except Exception:  # noqa: BLE001 - never mask the business result
                    pass
            print(f"[MICRO VISUAL STATE] {status['message']}")
            return int(status["exit_code"])
        if args.command == "run-slice-a":
            _validate_editorial_angle(args.fact_card, args.script)
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
        if args.command == "run-slice-a-and-upload-draft":
            _validate_editorial_angle(args.fact_card, args.script)
            run_dir = run_slice_a(
                args.project_root,
                card_path=args.fact_card,
                script_path=args.script,
                output_root=args.output_root,
                allow_pending_review=True,
            )
            upload = upload_run_to_channels(args.project_root.resolve(), run_dir)
            upload_report = {
                "schema_version": 1,
                "job_id": upload["job_id"],
                "source_run_id": upload.get("source_run_id", run_dir.name),
                "upload_attempt": upload.get("upload_attempt", 1),
                "state": upload["state"],
                "account_name": upload["account_name"],
                "title": upload["title"],
                "verified_draft": upload["verified_draft"],
                "save_action": upload.get("save_action"),
                "mobile_app_visibility_verified": bool(upload.get("mobile_app_visibility_verified", False)),
                "headless": bool(upload.get("headless", False)),
                "authorization_basis": upload["authorization_basis"],
                "automatic_publication": False,
            }
            (run_dir / "channels_upload_report.json").write_text(
                json.dumps(upload_report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            review_status_path = run_dir / "review_status.json"
            review_status = json.loads(review_status_path.read_text(encoding="utf-8"))
            review_status["draft_upload_status"] = upload["state"]
            review_status["draft_upload_authorization"] = upload["authorization_basis"]
            review_status["automatic_upload"] = True
            review_status["automatic_publication"] = False
            review_status_path.write_text(
                json.dumps(review_status, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            review_path = run_dir / "REVIEW.md"
            with review_path.open("a", encoding="utf-8") as handle:
                handle.write("\n## Unpublished Channels draft\n\n")
                handle.write(f"- State: {upload['state']}\n")
                handle.write(f"- Account: {upload['account_name']}\n")
                handle.write(f"- Title: {upload['title']}\n")
                handle.write("- The new row was read back from the actual draft list.\n")
                handle.write("- Final publication remains manual.\n")
            print(json.dumps({
                "run_dir": str(run_dir),
                "video": str(run_dir / "final.mp4"),
                "qa_report": str(run_dir / "qa_report.json"),
                "channels_upload_report": str(run_dir / "channels_upload_report.json"),
                "upload": upload,
                "automatic_publication": False,
            }, ensure_ascii=False, indent=2))
            print("Verified unpublished draft. No Publish/Send/Schedule action was performed.")
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
        if args.command == "approve-fact-card":
            result = approve_fact_card(
                args.project_root.resolve(),
                args.card,
                approved_by=args.approved_by,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print("Fact Card/source approved once. Future outputs still require strict QA PASS.")
            return 0
        if args.command == "approve-latest-run":
            result = approve_latest_run(
                args.project_root.resolve(),
                approved_by=args.approved_by,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print("Optional local review receipt recorded for this exact artifact package.")
            return 0
        if args.command == "approve-run":
            result = approve_run(
                args.project_root.resolve(),
                args.run_dir,
                approved_by=args.approved_by,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print("Optional local review receipt recorded for this exact artifact package.")
            return 0
        if args.command == "channels-upload-latest":
            result = upload_latest_approved_run(args.project_root.resolve())
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print("Verified unpublished draft. No Publish/Send action was performed.")
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
        if args.command == "channels-record-manual-review":
            result = record_manual_review(
                args.project_root.resolve(),
                args.job_id,
                result=args.result,
                reviewed_by=args.reviewed_by,
                row_text=args.row_text,
                note=args.note,
                confirmation=args.confirmation,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print("Manual review recorded. No browser, upload, save or publication action was performed.")
            return 0
        return 2
    except UploadBlockedError as exc:
        print(f"\nCHANNELS WORKFLOW BLOCKED: {exc}", file=sys.stderr)
        return 2
    except PublicationSourceEvidenceError as exc:
        print(f"\nPUBLICATION SOURCE EVIDENCE REJECTED: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"\nWECHAT VIDEO FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
