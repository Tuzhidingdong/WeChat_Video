"""Third independent pipeline: existing summary -> one Flow draft.

No local video QA, no Pillow/FFmpeg processing, no publication.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import channels_uploader as cu
from . import micro_visual_dedup as dedup
from .micro_visual_flow_identity import FlowGenerationCapture
from .micro_visual_article_source import (
    ARTICLE_SOURCE_READY,
    BLOCKED_ARTICLE_SOURCE,
    SKIPPED_NO_NEW_ARTICLE,
    MicroVisualArticleSourceError,
    find_fresh_summary_candidates,
    prepare_article_summary,
)
from .micro_visual_browser import (
    FlowBrowserController,
    ensure_flow_session,
    load_flow_config,
    submit_flow_generation,
)
from .micro_visual_download import (
    DownloadCapture,
    MicroVisualDownloadError,
    prepare_job_download_dir,
)
from .micro_visual_flow_result import (
    FlowResultError, classify_states, download_generation_result, locate_generation_result,
)
from .micro_visual_content_summary import verify_run_binding
from .micro_visual_plan import build_micro_visual_spec, prompt_sha256
from .micro_visual_theme import compile_visual_prompt, extract_visual_theme
from .micro_visual_summary_source import (
    SKIPPED_NO_ELIGIBLE_SUMMARY,
    SKIPPED_NO_VISUALLY_SUITABLE_SENTENCE,
    find_candidate_summaries,
    select_sentence,
    sentence_key,
)
from .micro_visual_upload_adapter import (
    DRAFT_SAVED, upload_micro_visual_run, verify_uploader_identity,
)
STOPPED_BEFORE_FLOW_SUBMIT = "STOPPED_BEFORE_FLOW_SUBMIT"

LEDGER_PATH = "runtime/micro_visual_jobs.jsonl"

STATUSES = {
    DRAFT_SAVED,
    SKIPPED_NO_ELIGIBLE_SUMMARY,
    SKIPPED_NO_VISUALLY_SUITABLE_SENTENCE,
    SKIPPED_NO_NEW_ARTICLE,
    BLOCKED_ARTICLE_SOURCE,
    STOPPED_BEFORE_FLOW_SUBMIT,
    "BLOCKED_UPLOADER_IDENTITY",
    "BLOCKED_FLOW_15S_UNAVAILABLE",
    "BLOCKED_FLOW_QUOTA",
    "BLOCKED_BROWSER_PROFILE",
    "BLOCKED_FLOW_DOWNLOAD",
    "BLOCKED_DRAFT_UPLOAD_ADAPTER",
    "FAILED_DRAFT_SAVE",
    "FAILED",
}


class MicroVisualPipelineError(RuntimeError):
    def __init__(self, state: str, message: str):
        super().__init__(message)
        self.state = state


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MicroVisualPipelineError("FAILED", f"corrupt ledger line: {exc}") from exc
        if not isinstance(value, dict):
            raise MicroVisualPipelineError("FAILED", "ledger line is not an object")
        records.append(value)
    return records


def _append_ledger(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _result(state: str, **fields: Any) -> dict[str, Any]:
    if state not in STATUSES:
        raise MicroVisualPipelineError("FAILED", f"unknown state {state!r}")
    return {"state": state, "automatic_publication": False, **fields}


def _default_deps() -> dict[str, Any]:
    return {
        "load_config": load_flow_config,
        "ensure_session": ensure_flow_session,
        "browser": lambda ws, cfg: FlowBrowserController(ws, cfg),
        "prepare_dir": prepare_job_download_dir,
        "capture": lambda page, job_dir: DownloadCapture(page, job_dir),
        "submit": submit_flow_generation,
        "flow_capture": FlowGenerationCapture,
        "locate_result": locate_generation_result,
        "download_result": download_generation_result,
        "upload": upload_micro_visual_run,
        "prepare_article_source": prepare_article_summary,
        "extract_visual_theme": extract_visual_theme,
        "compile_visual_prompt": compile_visual_prompt,
        "find_candidate_summaries": find_fresh_summary_candidates,
        "select_sentence": select_sentence,
        "verify_identity": verify_uploader_identity,
        "dedup_used_keys": dedup.used_keys,
        "record_dedup": dedup.record_decision,
    }


def run_literature_micro_visual(
    project_root: Path,
    *,
    published_date: str | None = None,
    deps: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    root = project_root.resolve()
    deps = {**_default_deps(), **(deps or {})}
    ledger_path = root / LEDGER_PATH
    ledger = _read_ledger(ledger_path)
    legacy_used = {
        str(record.get("dedup_key") or "")
        for record in ledger
        if record.get("flow_submitted") or record.get("state") == DRAFT_SAVED
    }

    try:
        config = deps["load_config"](root)
    except Exception as exc:  # noqa: BLE001 - config failure is an explicit blocked state
        state = getattr(exc, "state", "FAILED")
        if state not in STATUSES:
            state = "FAILED"
        _append_ledger(ledger_path, {
            "job_id": "CONFIG_FAILURE",
            "draft_state": state,
            "error": str(exc),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        return _result(state, reason=str(exc))

    # Phase 1-2: reuse the second BAT's discover_upstream_literature_runs()
    # through prepare_article_summary(). No active collection launcher exists.
    try:
        source_kwargs: dict[str, Any] = {"published_date": published_date}
        if run_id is not None:
            source_kwargs["run_id"] = run_id
        prepared = deps["prepare_article_source"](root, config, **source_kwargs)
    except (MicroVisualArticleSourceError, RuntimeError) as exc:
        _append_ledger(ledger_path, {
            "job_id": "ARTICLE_SOURCE",
            "draft_state": exc.state,
            "error": str(exc),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        return _result(exc.state, reason=str(exc))
    if prepared.get("state") != ARTICLE_SOURCE_READY:
        return _result(BLOCKED_ARTICLE_SOURCE, reason="article source did not become ready")

    selected_article = dict(prepared.get("selected_article") or {})
    acquisition = {
        "state": "LOCAL_DAILY_RUNS_ONLY",
        "acquisition_mode": "reused_local",
        "run_id": selected_article.get("run_id"),
        "source_root": selected_article.get("source_root"),
        "slot1_path": selected_article.get("slot1_path"),
        "slot1_sha256": selected_article.get("slot1_sha256"),
    }

    candidates = deps["find_candidate_summaries"](
        root, input_root=prepared.get("summary_input_root")
    )
    if not candidates:
        return _result(SKIPPED_NO_ELIGIBLE_SUMMARY, reason="no QA-passed summary from this run")
    used = deps["dedup_used_keys"](root)
    sentence_used = set(used.get("sentence") or set()) | legacy_used
    chosen = None
    for candidate in candidates:
        evidence = deps["select_sentence"](candidate, used_keys=sentence_used)
        if evidence is None:
            continue
        chosen = (candidate, evidence)
        break
    if chosen is None:
        return _result(SKIPPED_NO_VISUALLY_SUITABLE_SENTENCE)

    candidate, evidence = chosen

    # Article-specific visual theme (Stage A) and prompt compilation (Stage B).
    # A failure here must block; there is no silent fallback to the fixed template.
    summary_run_dir = Path(prepared.get("summary_run_dir") or "")
    article_dir = Path(prepared.get("article_package_dir") or root)
    if run_id is not None:
        verify_run_binding(
            summary_run_dir,
            run_id=run_id,
            article_id=str(evidence.get("article_id") or ""),
            source_article_sha256=str(evidence.get("source_article_sha256") or ""),
        )
    theme_context: dict[str, Any] = {
        "article_id": str(evidence.get("article_id") or ""),
        "source_article_sha256": str(evidence.get("source_article_sha256") or ""),
        "run_id": run_id,
    }
    summary_file = summary_run_dir / "summary.json"
    article_file = article_dir / "article.md"
    if summary_file.is_file():
        theme_context["summary"] = json.loads(summary_file.read_text(encoding="utf-8"))
    if article_file.is_file():
        theme_context["article_text"] = article_file.read_text(encoding="utf-8")
    theme = deps["extract_visual_theme"](
        root,
        summary_path=summary_file,
        article_dir=article_dir,
        output_dir=summary_run_dir,
        config=config,
        context=theme_context,
    )
    article_visual_prompt = deps["compile_visual_prompt"](theme, config, **theme_context)

    title_override = str(config.get("draft_title_override") or "").strip()
    if title_override:
        matching_unit = next(
            (unit for unit in (candidate["summary"].get("speech_units") or [])
             if isinstance(unit, dict) and title_override in str(unit.get("spoken_text") or "")),
            None,
        )
        if matching_unit is None:
            return _result(
                SKIPPED_NO_VISUALLY_SUITABLE_SENTENCE,
                reason=f"configured title is not a summary substring: {title_override!r}",
            )
        claim_ids = [
            str(item) for item in (matching_unit.get("claim_ids") or [])
            if str(item) in candidate["claim_index"]
        ]
        if not claim_ids:
            return _result(SKIPPED_NO_VISUALLY_SUITABLE_SENTENCE, reason="configured title has no claim evidence")
        evidence["draft_title"] = title_override
        evidence["selected_sentence"] = title_override
        evidence["claim_ids"] = claim_ids
        evidence["source_excerpt_references"] = [
            {"claim_id": cid, "source_excerpt": candidate["claim_index"][cid]["source_excerpt"]}
            for cid in claim_ids
        ]
        evidence["source_excerpt"] = evidence["source_excerpt_references"][0]["source_excerpt"]
        evidence["draft_title_sha256"] = sentence_key(
            evidence["article_id"], evidence["source_article_sha256"], title_override
        )
        evidence["selected_title_sha256"] = evidence["draft_title_sha256"]
        evidence["selected_sentence_sha256"] = evidence["draft_title_sha256"]
        evidence["selected_text_source"] = "speech_units[].spoken_text (configured exact summary clause)"
    dedup_key = evidence["selected_sentence_sha256"]
    if dedup_key in sentence_used:
        return _result(SKIPPED_NO_ELIGIBLE_SUMMARY, reason="already submitted for this sentence")

    job_id = str(prepared["job_id"])
    run_dir = root / "outputs" / job_id
    if run_dir.exists():
        return _result(SKIPPED_NO_ELIGIBLE_SUMMARY, reason=f"run directory already exists: {job_id}")

    submitted = False
    flow_identity: dict[str, Any] = {}
    identity_capture: Any = None
    identity: dict[str, Any] | None = None
    try:
        spec = build_micro_visual_spec(
            evidence, config, visual_prompt=article_visual_prompt
        )
        visual_hash = dedup.visual_prompt_sha256(str(spec["visual_prompt"]))
        recipe_hash = dedup.scene_recipe_sha256(evidence, spec)
        duplicate_reasons = dedup.check_duplicates(used, evidence, spec)
        if duplicate_reasons:
            deps["record_dedup"](root, {
                "job_id": job_id, "article_id": evidence["article_id"],
                "selected_sentence_sha256": dedup_key,
                "visual_prompt_sha256": visual_hash,
                "scene_recipe_sha256": recipe_hash,
                "flow_submitted": False, "state": SKIPPED_NO_ELIGIBLE_SUMMARY,
            })
            return _result(
                SKIPPED_NO_ELIGIBLE_SUMMARY,
                reason="cross-job duplicate before Flow: " + ", ".join(duplicate_reasons),
            )

        prompt = spec["final_prompt"]
        run_dir.mkdir(parents=True, exist_ok=False)
        theme_file = summary_run_dir / "visual_theme.json"
        cu._write_json_atomic(run_dir / "visual_theme_binding.json", {
            "run_id": run_id,
            "article_id": str(evidence.get("article_id") or ""),
            "source_article_sha256": str(evidence.get("source_article_sha256") or ""),
            "source_run_id": acquisition.get("run_id") or selected_article.get("run_id"),
            "summary_run_dir": str(summary_run_dir),
            "summary_sha256": (
                cu._sha256(summary_run_dir / "summary.json")
                if (summary_run_dir / "summary.json").is_file() else None
            ),
            "visual_theme_sha256": cu._sha256(theme_file) if theme_file.is_file() else None,
            "flow_prompt_sha256": prompt_sha256(prompt),
            "prompt_builder_sha256": spec["prompt_builder_sha256"],
            "article_specific_theme": bool(theme),
        })
        cu._write_json_atomic(
            run_dir / "micro_visual_plan.json",
            {
                "job_id": job_id,
                "draft_title": evidence["draft_title"],
                "visual_prompt": spec["visual_prompt"],
                "evidence_metadata": spec["evidence_metadata"],
                "prompt_builder_sha256": spec["prompt_builder_sha256"],
                "visual_prompt_sha256": visual_hash,
                "scene_recipe_sha256": recipe_hash,
                "article_source": {
                    "upstream_acquisition": acquisition,
                    "selected_article": prepared["selected_article"],
                    "planner_summary_path": prepared["planner_summary_path"],
                    "summary_run_dir": prepared["summary_run_dir"],
                    "discovery": prepared["discovery"],
                },
                "uploader_identity": identity,
                "config": {
                    key: config.get(key) for key in (
                        "model", "duration_seconds", "aspect_ratio", "resolution", "output_count"
                    )
                },
            },
        )
        (run_dir / "draft_title.txt").write_text(
            evidence["draft_title"] + "\n", encoding="utf-8"
        )
        cu._write_json_atomic(run_dir / "source_evidence.json", spec["evidence_metadata"])
        (run_dir / "flow_prompt.txt").write_text(prompt + "\n", encoding="utf-8")

        if bool(config.get("stop_before_flow_submit")):
            prompt_path = run_dir / "flow_prompt.txt"
            _append_ledger(ledger_path, {
                "job_id": job_id,
                "draft_state": STOPPED_BEFORE_FLOW_SUBMIT,
                "upstream_run_id": acquisition.get("run_id"),
                "selected_article": selected_article,
                "article_summary_run_dir": prepared["summary_run_dir"],
                "flow_prompt_path": str(prompt_path),
                "flow_prompt_sha256": prompt_sha256(prompt),
                "created_at": datetime.now().isoformat(timespec="seconds"),
            })
            return _result(
                STOPPED_BEFORE_FLOW_SUBMIT,
                job_id=job_id,
                upstream_run_id=acquisition.get("run_id"),
                selected_article=selected_article,
                article_summary_run_dir=prepared["summary_run_dir"],
                planner_summary_path=prepared["planner_summary_path"],
                flow_prompt_path=str(prompt_path),
                flow_prompt_sha256=prompt_sha256(prompt),
                flow_prompt=prompt,
                evidence_metadata=spec["evidence_metadata"],
                config={key: config.get(key) for key in (
                    "model", "duration_seconds", "aspect_ratio", "resolution", "output_count"
                )},
            )

        # Preflight the Channels identity BEFORE spending Flow credits.
        identity = deps["verify_identity"](
            root, config_override=config.get("_uploader_config_override")
        )
        if not identity.get("verified"):
            deps["record_dedup"](root, {
                "job_id": job_id, "article_id": evidence["article_id"],
                "selected_sentence_sha256": dedup_key,
                "visual_prompt_sha256": visual_hash,
                "scene_recipe_sha256": recipe_hash,
                "flow_submitted": False, "state": "BLOCKED_UPLOADER_IDENTITY",
            })
            return _result(
                "BLOCKED_UPLOADER_IDENTITY",
                reason="Channels account identity preflight failed before Flow generation",
                identity=identity,
            )

        session, websocket = deps["ensure_session"](root, config)
        with deps["browser"](websocket, config) as controller:
            identity_capture = deps["flow_capture"](controller.page, run_dir, config, prompt)
            identity_capture.install()
            submission = deps["submit"](controller.page, config, prompt)
            submitted = True
            flow_identity = identity_capture.capture(
                "SUBMITTED", submitted_at=datetime.now().isoformat(timespec="seconds")
            )
            located = deps["locate_result"](
                controller.page, config,
                timeout_seconds=float(config.get("result_locate_timeout_seconds", 300)),
                expected_prompt=prompt,
            )
            if located.get("state") != "RESULT_LOCATED":
                platform_error = str(located.get("reason") or "")
                flow_identity = identity_capture.finalize(
                    "BLOCKED_FLOW_DOWNLOAD", error=platform_error
                )
                raise FlowResultError(
                    "BLOCKED_FLOW_DOWNLOAD",
                    f"generation submitted but result not located: {located.get('reason')}",
                )
            job_dir = deps["prepare_dir"](root, config, job_id)
            capture = deps["capture"](controller.page, job_dir)
            capture.install()
            downloaded = deps["download_result"](
                controller.page, capture, located, config
            )
        original = run_dir / "flow_original.mp4"
        final = run_dir / "final.mp4"
        shutil.copy2(downloaded["path"], original)
        shutil.copy2(downloaded["path"], final)
        (run_dir / "final_video_sha256.txt").write_text(
            downloaded["sha256"] + "\n", encoding="utf-8"
        )

        upload = deps["upload"](root, run_dir, evidence)
        draft = upload.get("verified_draft")
        draft_ok = (
            isinstance(draft, dict)
            and bool(str(draft.get("title") or "").strip())
            and str(draft.get("title")) == str(upload.get("title") or "")
            and bool(str(draft.get("row_text") or "").strip())
        )
        state = (
            DRAFT_SAVED
            if upload.get("state") == DRAFT_SAVED and draft_ok
            else "FAILED_DRAFT_SAVE"
        )
        if identity_capture is not None:
            flow_identity = identity_capture.finalize(state)
        record = {
            "job_id": job_id,
            "article_id": evidence["article_id"],
            "source_article_sha256": evidence["source_article_sha256"],
            "selected_sentence": evidence["selected_sentence"],
            "selected_sentence_sha256": dedup_key,
            "claim_ids": evidence["claim_ids"],
            "source_excerpt_references": evidence["source_excerpt_references"],
            "flow_model": config.get("model"),
            "flow_duration": config.get("duration_seconds"),
            "flow_job_id": submission.get("flow_job_id"),
            "flow_credit_usage": submission.get("flow_credit_usage"),
            "flow_generation_event": flow_identity,
            "flow_prompt_sha256": prompt_sha256(prompt),
            "visual_prompt_sha256": visual_hash,
            "scene_recipe_sha256": recipe_hash,
            "article_summary_run_dir": prepared["summary_run_dir"],
            "upstream_run_id": acquisition.get("run_id"),
            "upstream_acquisition_mode": acquisition.get("acquisition_mode"),
            "selected_article": prepared["selected_article"],
            "prompt_builder_sha256": spec["prompt_builder_sha256"],
            "draft_title": evidence["draft_title"],
            "draft_title_sha256": evidence["draft_title_sha256"],
            "evidence_metadata": spec["evidence_metadata"],
            "flow_submitted": True,
            **classify_states(
                submitted=True,
                generation_evidence=True,
                downloaded=True,
                draft_saved=state == DRAFT_SAVED,
            ),
            "downloaded_mp4_path": downloaded["path"],
            "downloaded_mp4_sha256": downloaded["sha256"],
            "draft_state": state,
            "verified_draft": upload.get("verified_draft"),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "dedup_key": dedup_key,
        }
        _append_ledger(ledger_path, record)
        deps["record_dedup"](root, {
            "job_id": job_id,
            "article_id": evidence["article_id"],
            "selected_sentence": evidence["selected_sentence"],
            "selected_sentence_sha256": dedup_key,
            "visual_prompt_sha256": visual_hash,
            "scene_recipe_sha256": recipe_hash,
            "flow_submitted": True,
            "state": state,
        })
        cu._write_json_atomic(run_dir / "upload_result.json", upload)
        cu._write_json_atomic(
            run_dir / "run_result.json",
            _result(
                state,
                job_id=job_id,
                verified_draft=upload.get("verified_draft"),
                draft_title=upload.get("title"),
            ),
        )
        return _result(
            state,
            job_id=job_id,
            verified_draft=upload.get("verified_draft"),
            draft_title=upload.get("title"),
        )
    except MicroVisualDownloadError as exc:
        state = exc.state
        message = str(exc)
    except Exception as exc:  # noqa: BLE001
        state = getattr(exc, "state", "FAILED")
        if state not in STATUSES:
            state = "FAILED"
        message = str(exc)
    if identity_capture is not None:
        try:
            flow_identity = identity_capture.finalize(state, error=message)
        except Exception:  # noqa: BLE001 - ledger write must still happen
            pass
    record = {
        "job_id": job_id,
        "article_id": evidence["article_id"],
        "source_article_sha256": evidence["source_article_sha256"],
        "selected_sentence": evidence["selected_sentence"],
        "selected_sentence_sha256": dedup_key,
        "dedup_key": dedup_key,
        "flow_submitted": submitted,
        **classify_states(
            submitted=submitted,
            generation_evidence=state == DRAFT_SAVED,
            downloaded=state == DRAFT_SAVED,
            draft_saved=state == DRAFT_SAVED,
        ),
        "draft_state": state,
        "visual_prompt_sha256": visual_hash,
        "scene_recipe_sha256": recipe_hash,
        "article_summary_run_dir": prepared["summary_run_dir"],
        "upstream_run_id": acquisition.get("run_id"),
        "upstream_acquisition_mode": acquisition.get("acquisition_mode"),
        "flow_generation_event": flow_identity,
        "error": message,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    _append_ledger(ledger_path, record)
    deps["record_dedup"](root, {
        "job_id": job_id,
        "article_id": evidence["article_id"],
        "selected_sentence": evidence["selected_sentence"],
        "selected_sentence_sha256": dedup_key,
        "visual_prompt_sha256": visual_hash,
        "scene_recipe_sha256": recipe_hash,
        "flow_submitted": submitted,
        "state": state,
    })
    return _result(state, job_id=job_id, reason=message)
