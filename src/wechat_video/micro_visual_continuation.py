"""Safe downstream-only continuation for one frozen Micro Visual job.

Requires an explicit job_id. Never runs article discovery, Summary, Planner,
Stage A or Stage B. Reuses the existing Flow browser/submission/download and
Channels upload adapter.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from . import channels_uploader as cu
from .media import probe_media
from .micro_visual_browser import (
    FlowBrowserController, ensure_flow_session, load_flow_config, submit_flow_generation,
)
from .micro_visual_download import DownloadCapture, prepare_job_download_dir
from .micro_visual_flow_identity import FlowGenerationCapture
from .micro_visual_flow_result import (
    classify_states, download_generation_result, locate_generation_result,
)
from .micro_visual_plan import prompt_sha256
from .micro_visual_upload_adapter import (
    DRAFT_SAVED, upload_micro_visual_run, verify_uploader_identity,
)
from .process import run_checked
from .tooling import resolve_command, tool_env

LEDGER_PATH = "runtime/micro_visual_jobs.jsonl"


class ContinuationError(RuntimeError):
    pass


def _read_ledger(root: Path) -> list[dict[str, Any]]:
    path = root / LEDGER_PATH
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _append_ledger(root: Path, record: dict[str, Any]) -> None:
    path = root / LEDGER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()


def validate_video(path: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Read-only media validation; fail closed on missing/invalid streams."""
    probe = probe_media(path, count_frames=True)
    video = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in probe.get("streams", []) if s.get("codec_type") == "audio"), None)
    if video is None:
        raise ContinuationError("video stream missing")
    if audio is None:
        raise ContinuationError("audio stream missing")
    duration = float((probe.get("format") or {}).get("duration") or 0)
    if not 10.0 <= duration <= 20.0:
        raise ContinuationError(f"unexpected duration: {duration}")
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    if width <= 0 or height <= 0 or abs(width / height - 9 / 16) > 0.05:
        raise ContinuationError(f"unexpected frame size/aspect: {width}x{height}")
    frames = int(video.get("nb_read_frames") or 0)
    if frames <= 0:
        raise ContinuationError("no decodable video frames")
    # Decode the whole file to prove it is playable, without re-encoding it.
    run_checked(
        [resolve_command("ffmpeg"), "-v", "error", "-i", str(path), "-f", "null", "-"],
        timeout_seconds=300, env=tool_env(),
    )
    return {
        "status": "PASS",
        "path": str(path),
        "sha256": cu._sha256(path),
        "size_bytes": path.stat().st_size,
        "duration_seconds": duration,
        "width": width, "height": height,
        "aspect_ratio": f"{width}:{height}",
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "decoded_frames": frames,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }


def continue_micro_visual_run(
    project_root: Path,
    job_id: str,
    *,
    deps: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = project_root.resolve()
    if not job_id or any(ch in job_id for ch in "\\/.."):
        raise ContinuationError("invalid job_id")
    run_dir = root / "outputs" / job_id
    if not run_dir.is_dir():
        raise ContinuationError(f"job directory missing: {run_dir}")
    plan = json.loads((run_dir / "micro_visual_plan.json").read_text(encoding="utf-8"))
    binding = json.loads((run_dir / "visual_theme_binding.json").read_text(encoding="utf-8"))
    source_evidence = json.loads((run_dir / "source_evidence.json").read_text(encoding="utf-8"))
    if str(plan.get("job_id")) != job_id:
        raise ContinuationError("plan job_id mismatch")
    if str(binding.get("article_id")) != str(source_evidence.get("article_id")):
        raise ContinuationError("article identity mismatch")
    draft_title = (run_dir / "draft_title.txt").read_text(encoding="utf-8").strip()
    if draft_title != str(plan.get("draft_title") or ""):
        raise ContinuationError("draft title mismatch")
    # A selected sentence can exceed the Channels 6-16 character title limit.
    # Fall back to the frozen Summary's own channels_title (never invent one).
    if not 6 <= len(draft_title) <= 16:
        summary_file = Path(str(binding.get("summary_run_dir") or "")) / "summary.json"
        if not summary_file.is_file():
            raise ContinuationError("draft title invalid and frozen summary unavailable")
        frozen = json.loads(summary_file.read_text(encoding="utf-8"))
        candidate = str(frozen.get("channels_title") or frozen.get("summary_title") or "").strip()
        if not 6 <= len(candidate) <= 16:
            raise ContinuationError("frozen summary has no valid 6-16 character title")
        draft_title = candidate
        (run_dir / "draft_title_effective.txt").write_text(draft_title + "\n", encoding="utf-8")
    original_prompt = (run_dir / "flow_prompt.txt").read_text(encoding="utf-8").strip()
    if prompt_sha256(original_prompt) != str(binding.get("flow_prompt_sha256") or ""):
        raise ContinuationError("frozen prompt SHA mismatch")
    submitted_path = run_dir / "flow_prompt_submitted.txt"
    prompt = (submitted_path.read_text(encoding="utf-8").strip()
              if submitted_path.is_file() else original_prompt)
    if not prompt:
        raise ContinuationError("submitted prompt is empty")
    for key in ("run_id", "article_id", "source_article_sha256", "source_run_id"):
        if not binding.get(key):
            raise ContinuationError(f"missing identity field: {key}")
    for record in _read_ledger(root):
        if str(record.get("job_id")) == job_id and (
                record.get("flow_submitted") is True
                or str(record.get("draft_state")) == DRAFT_SAVED):
            raise ContinuationError("this job already submitted Flow or saved a draft")

    config = load_flow_config(root)
    overrides = deps or {}
    verify_identity = overrides.get("verify_identity", verify_uploader_identity)
    ensure_session = overrides.get("ensure_session", ensure_flow_session)
    browser = overrides.get("browser", lambda ws, cfg: FlowBrowserController(ws, cfg))
    submit = overrides.get("submit", submit_flow_generation)
    flow_capture_cls = overrides.get("flow_capture", FlowGenerationCapture)
    locate = overrides.get("locate_result", locate_generation_result)
    prepare_dir = overrides.get("prepare_dir", prepare_job_download_dir)
    capture_cls = overrides.get("capture", DownloadCapture)
    download = overrides.get("download_result", download_generation_result)
    upload = overrides.get("upload", upload_micro_visual_run)

    identity = verify_identity(root, config_override=config.get("_uploader_config_override"))
    if not identity.get("verified"):
        raise ContinuationError("Channels identity preflight failed; no Flow submission")
    cu._write_json_atomic(run_dir / "uploader_identity.json", identity)

    evidence = {
        "article_id": binding["article_id"],
        "source_article_sha256": binding["source_article_sha256"],
        "draft_title": draft_title,
        "selected_sentence": draft_title,
        "selected_sentence_sha256": source_evidence.get("selected_sentence_sha256") or "",
        "selected_title_sha256": source_evidence.get("selected_title_sha256")
        or source_evidence.get("selected_sentence_sha256") or "",
        "claim_ids": source_evidence.get("claim_ids") or [],
        "source_excerpt": source_evidence.get("source_excerpt") or "",
        "source_excerpt_references": source_evidence.get("source_excerpt_references") or [],
    }

    flow_event_file = run_dir / "flow_generation_event.json"
    final_path = run_dir / "final.mp4"
    resumed = flow_event_file.is_file() and final_path.is_file()
    flow_identity: dict[str, Any] | None = None
    submission: dict[str, Any] | None = None
    downloaded: dict[str, Any] | None = None
    if resumed:
        event = json.loads(flow_event_file.read_text(encoding="utf-8"))
        if prompt_sha256(prompt) != str(event.get("flow_prompt_sha256") or ""):
            raise ContinuationError("existing Flow event prompt SHA mismatch")
        flow_identity = event
        submission = {"flow_job_id": event.get("flow_generation_id"),
                      "flow_credit_usage": event.get("flow_credit_usage"),
                      "resumed_after_successful_submission": True}
        downloaded = {"path": str(final_path), "sha256": cu._sha256(final_path)}
    else:
        session, websocket = ensure_session(root, config)
        try:
            with browser(websocket, config) as controller:
                flow_capture = flow_capture_cls(controller.page, run_dir, config, prompt)
                flow_capture.install()
                submission = submit(controller.page, config, prompt)
                submitted_at = datetime.now().isoformat(timespec="seconds")
                flow_identity = flow_capture.capture("SUBMITTED", submitted_at=submitted_at)
                cu._write_json_atomic(run_dir / "flow_generation_report.json", {
                    "job_id": job_id,
                    "frozen_run_id": binding["run_id"],
                    "submitted_at": submitted_at,
                    "submission": submission,
                    "original_prompt_sha256": prompt_sha256(original_prompt),
                    "submitted_prompt_sha256": prompt_sha256(prompt),
                    "flow_generation_event": flow_identity,
                })
                located = locate(
                    controller.page, config,
                    timeout_seconds=float(config.get("result_locate_timeout_seconds", 300)),
                    expected_prompt=prompt,
                )
                if located.get("state") != "RESULT_LOCATED":
                    flow_identity = flow_capture.finalize(
                        "BLOCKED_FLOW_DOWNLOAD", error=str(located.get("reason") or "")
                    )
                    raise ContinuationError("generation submitted but result not located")
                job_dir = prepare_dir(root, config, job_id)
                capture = capture_cls(controller.page, job_dir)
                capture.install()
                downloaded = download(controller.page, capture, located, config)
        except Exception as exc:  # noqa: BLE001 - record truthful failure state
            if flow_identity is not None:
                try:
                    flow_capture.finalize("FAILED", error=str(exc)[:1200])
                except Exception:
                    pass
            state = "FLOW_SUBMISSION_UNKNOWN" if submission is not None else "FAILED"
            _append_ledger(root, {
                "job_id": job_id, "draft_state": state, "flow_submitted": submission is not None,
                "error": str(exc), "created_at": datetime.now().isoformat(timespec="seconds"),
            })
            return _result(state, job_id=job_id, reason=str(exc))

    original_mp4 = run_dir / "flow_original.mp4"
    final_mp4 = run_dir / "final.mp4"
    source_mp4 = Path(str(downloaded["path"])).resolve()
    if source_mp4 != final_mp4.resolve():
        shutil.copy2(source_mp4, original_mp4)
        shutil.copy2(source_mp4, final_mp4)
    (run_dir / "final_video_sha256.txt").write_text(cu._sha256(final_mp4) + "\n", encoding="utf-8")
    validation = validate_video(final_mp4, config)
    cu._write_json_atomic(run_dir / "video_validation_report.json", validation)
    if validation["status"] != "PASS":
        _append_ledger(root, {
            "job_id": job_id, "draft_state": "FAILED_VIDEO_VALIDATION",
            "flow_submitted": True, "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        return _result("FAILED_VIDEO_VALIDATION", job_id=job_id, reason="video validation failed")

    # The current Channels shell only mounts the draft submenu after its
    # "内容管理" link is activated. Keep the mature adapter flow but open that
    # menu first, via a scoped runtime wrapper (no shared-source change).
    original_nav = cu._click_draft_list_nav_entry

    def nav_with_content_menu(page: Any, selectors: Any) -> None:
        link = page.locator("a:has-text('内容管理')")
        if link.count():
            try:
                link.first.click(timeout=10_000)
                page.wait_for_timeout(1_200)
            except Exception:  # noqa: BLE001 - fall back to original navigation
                pass
        return original_nav(page, selectors)

    cu._click_draft_list_nav_entry = nav_with_content_menu
    try:
        upload_result = upload(
            root, run_dir, evidence,
            source_run_id=str(binding.get("source_run_id") or job_id),
            reuse_existing_page=True,
        )
    finally:
        cu._click_draft_list_nav_entry = original_nav
    cu._write_json_atomic(run_dir / "channels_upload_report.json", upload_result)
    draft = upload_result.get("verified_draft")
    cu._write_json_atomic(run_dir / "verified_draft.json", draft or {})
    draft_ok = (
        isinstance(draft, dict)
        and str(draft.get("title") or "") == upload_result.get("title")
        and bool(str(draft.get("row_text") or "").strip())
    )
    state = DRAFT_SAVED if upload_result.get("state") == DRAFT_SAVED and draft_ok else "FAILED_DRAFT_SAVE"
    if resumed:
        flow_identity = dict(flow_identity or {})
        flow_identity["flow_generation_status"] = state
        cu._write_json_atomic(run_dir / "flow_generation_event.json", flow_identity)
    else:
        flow_identity = flow_capture.finalize(state)
    record = {
        "job_id": job_id,
        "frozen_run_id": binding["run_id"],
        "article_id": binding["article_id"],
        "source_article_sha256": binding["source_article_sha256"],
        "source_run_id": binding["source_run_id"],
        "flow_model": config.get("model"),
        "flow_duration": config.get("duration_seconds"),
        "flow_job_id": submission.get("flow_job_id"),
        "flow_credit_usage": submission.get("flow_credit_usage"),
        "flow_generation_event": flow_identity,
        "flow_prompt_sha256": prompt_sha256(prompt),
        "original_prompt_sha256": prompt_sha256(original_prompt),
        "downloaded_mp4_sha256": validation["sha256"],
        "video_validation": validation,
        "draft_title": draft_title,
        "state": state,
        "draft_state": state,
        "verified_draft": draft,
        "flow_submitted": True,
        **classify_states(
            submitted=True, generation_evidence=True, downloaded=True,
            draft_saved=state == DRAFT_SAVED,
        ),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    _append_ledger(root, record)
    cu._write_json_atomic(run_dir / "run_result.json", record)
    return record


def finalize_existing_draft(project_root: Path, job_id: str) -> dict[str, Any]:
    """Finalize an already-saved draft without any upload/save action."""
    root = project_root.resolve()
    run_dir = root / "outputs" / job_id
    if not run_dir.is_dir():
        raise ContinuationError("job directory missing")
    binding = json.loads((run_dir / "visual_theme_binding.json").read_text(encoding="utf-8"))
    channels = json.loads((run_dir / "channels_draft.json").read_text(encoding="utf-8"))
    event_path = run_dir / "flow_generation_event.json"
    event = json.loads(event_path.read_text(encoding="utf-8"))
    validation = json.loads((run_dir / "video_validation_report.json").read_text(encoding="utf-8"))
    config, _selectors = cu._load_config(root)
    jobs_dir = Path(str(config.get("jobs_dir") or "runtime/upload_jobs"))
    if not jobs_dir.is_absolute():
        jobs_dir = root / jobs_dir
    saved = []
    for path in jobs_dir.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if (str(job.get("state")) == DRAFT_SAVED
                and str(job.get("logical_job_id") or "") == job_id
                and isinstance(job.get("verified_draft"), dict)
                and str(job.get("title")) == str(channels.get("title") or "")):
            saved.append(job)
    if not saved:
        raise ContinuationError("no DRAFT_SAVED upload job for this job_id")
    job = max(saved, key=lambda item: str(item.get("upload_attempt") or ""))
    draft = job["verified_draft"]
    cu._write_json_atomic(run_dir / "channels_upload_report.json", job)
    cu._write_json_atomic(run_dir / "verified_draft.json", draft)
    event["flow_generation_status"] = DRAFT_SAVED
    cu._write_json_atomic(event_path, event)
    record = {
        "state": DRAFT_SAVED, "draft_state": DRAFT_SAVED,
        "automatic_publication": False, "job_id": job_id,
        "frozen_run_id": binding.get("run_id"),
        "article_id": binding.get("article_id"),
        "source_article_sha256": binding.get("source_article_sha256"),
        "source_run_id": binding.get("source_run_id"),
        "flow_model": event.get("flow_model"),
        "flow_duration": event.get("flow_duration"),
        "flow_generation_event": event,
        "flow_prompt_sha256": event.get("flow_prompt_sha256"),
        "downloaded_mp4_sha256": validation.get("sha256"),
        "video_validation": validation,
        "draft_title": job.get("title"),
        "verified_draft": draft,
        "flow_submitted": True,
        **classify_states(
            submitted=True, generation_evidence=True, downloaded=True, draft_saved=True,
        ),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    for existing in _read_ledger(root):
        if (str(existing.get("job_id")) == job_id
                and str(existing.get("draft_state")) == DRAFT_SAVED):
            return record
    _append_ledger(root, {
        "job_id": job_id, "draft_state": DRAFT_SAVED,
        "flow_submitted": True, "verified_draft": draft,
        "draft_title": job.get("title"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    })
    cu._write_json_atomic(run_dir / "run_result.json", record)
    return record


def _result(state: str, **kwargs: Any) -> dict[str, Any]:
    return {"state": state, "automatic_publication": False, **kwargs}
