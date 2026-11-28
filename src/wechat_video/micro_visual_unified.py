"""One BAT entry: resume a safe unfinished Micro Visual job or start a full new one."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .micro_visual_browser import load_flow_config
from .micro_visual_continuation import (
    continue_micro_visual_run, finalize_existing_draft,
)
from .micro_visual_pipeline import run_literature_micro_visual

LEDGER_PATH = "runtime/micro_visual_jobs.jsonl"
JOB_MARKER = "micro_visual_plan.json"
# States where a real job directory exists and downstream work can safely resume.
RESUMABLE_STATES = {
    "STOPPED_BEFORE_FLOW_SUBMIT", "FAILED", "FLOW_SUBMISSION_UNKNOWN",
    "BLOCKED_FLOW_DOWNLOAD", "FAILED_DRAFT_SAVE", "FAILED_VIDEO_VALIDATION",
}
# Real jobs that need a human/platform condition cleared; never auto-restarted.
MANUAL_BLOCK_STATES = {
    "BLOCKED_UPLOADER_IDENTITY", "BLOCKED_FLOW_15S_UNAVAILABLE",
    "BLOCKED_FLOW_QUOTA", "BLOCKED_BROWSER_PROFILE",
    "BLOCKED_DRAFT_UPLOAD_ADAPTER", "UPLOAD_UNKNOWN",
}
# Ledger-only records from stages that never created a job directory.
PRE_JOB_STATES = {
    "CONFIG_FAILURE", "BLOCKED_ARTICLE_SOURCE", "SKIPPED_NO_NEW_ARTICLE",
    "SKIPPED_NO_ELIGIBLE_SUMMARY", "SKIPPED_NO_VISUALLY_SUITABLE_SENTENCE",
}


class UnifiedDecisionError(RuntimeError):
    """Ambiguous, corrupt or unsafe job state: stop, never guess."""


@dataclass(frozen=True)
class Decision:
    action: str  # resume | complete | new
    job_id: str | None
    reason: str
    evidence: dict[str, Any]


def _read_ledger(root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    path = root / LEDGER_PATH
    if not path.is_file():
        return {}, []
    latest: dict[str, dict[str, Any]] = {}
    corrupted: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            corrupted.append("ledger has an unparseable line")
            continue
        if not isinstance(record, dict) or not str(record.get("job_id") or "").strip():
            corrupted.append("ledger record lacks job_id")
            continue
        latest[str(record["job_id"])] = record
    return latest, corrupted


def _job_dirs(root: Path) -> dict[str, Path]:
    outputs = root / "outputs"
    found: dict[str, Path] = {}
    if not outputs.is_dir():
        return found
    for path in sorted(outputs.iterdir()):
        if path.is_dir() and (path / JOB_MARKER).is_file():
            found[path.name] = path
    return found


def classify_jobs(root: Path) -> Decision:
    """Classify all known jobs. Ambiguity or corruption always fails closed."""
    root = root.resolve()
    ledger, corrupted = _read_ledger(root)
    dirs = _job_dirs(root)
    if corrupted:
        raise UnifiedDecisionError("; ".join(corrupted))
    problems: list[str] = []
    resumable: list[str] = []
    blocked: list[str] = []
    completed: list[str] = []
    for job_id in sorted(set(ledger) | set(dirs)):
        record = ledger.get(job_id)
        job_dir = dirs.get(job_id)
        if job_dir is None:
            state = str((record or {}).get("draft_state") or "")
            if state in PRE_JOB_STATES:
                # No job directory was ever created: this is a ledger-only
                # failure, not an unfinished job. It must not block a new run.
                continue
            if state == "DRAFT_SAVED":
                problems.append(f"{job_id}: DRAFT_SAVED ledger has no job directory")
            else:
                problems.append(f"{job_id}: ledger record has no job directory")
            continue
        required = [JOB_MARKER, "flow_prompt.txt", "visual_theme_binding.json", "source_evidence.json"]
        missing = [name for name in required if not (job_dir / name).is_file()]
        if missing:
            problems.append(f"{job_id}: missing required artifacts: {missing}")
            continue
        if record is None:
            problems.append(f"{job_id}: job directory has no ledger state")
            continue
        state = str(record.get("draft_state") or "")
        if state == "DRAFT_SAVED":
            draft = record.get("verified_draft")
            if not isinstance(draft, dict) or not str(draft.get("title") or "").strip():
                problems.append(f"{job_id}: DRAFT_SAVED without verified_draft")
                continue
            completed.append(job_id)
        elif state in MANUAL_BLOCK_STATES:
            blocked.append(job_id)
        elif record.get("flow_submitted") is True or state in RESUMABLE_STATES:
            if record.get("flow_submitted") is True and not (job_dir / "flow_generation_event.json").is_file():
                problems.append(f"{job_id}: flow_submitted=true without generation event")
                continue
            resumable.append(job_id)
        else:
            problems.append(f"{job_id}: unknown state {state!r}")
    if problems:
        raise UnifiedDecisionError("; ".join(problems))
    if len(resumable) > 1 or len(blocked) > 1 or (resumable and blocked):
        raise UnifiedDecisionError(
            "unclear which job to continue; resumable=" + ",".join(resumable)
            + " blocked=" + ",".join(blocked)
        )
    if blocked:
        job_id = blocked[0]
        return Decision("blocked", job_id,
                        f"job {job_id} needs manual clearance before continuation",
                        {"job_id": job_id, "state": str(ledger[job_id].get("draft_state") or "")})
    if resumable:
        job_id = resumable[0]
        return Decision("resume", job_id, "one safe unfinished job found", {
            "job_id": job_id, "state": str(ledger[job_id].get("draft_state") or ""),
            "flow_submitted": bool(ledger[job_id].get("flow_submitted")),
        })
    return Decision("new", None,
                    "no unfinished job; starting a full new production run",
                    {"completed_jobs": completed})


def run_unified(
    project_root: Path,
    *,
    deps: dict[str, Any] | None = None,
    classify: Callable[[Path], Decision] = classify_jobs,
) -> dict[str, Any]:
    root = project_root.resolve()
    decision = classify(root)
    overrides = dict(deps or {})
    generated_run_id: str | None = None
    if decision.action == "blocked":
        return {
            "state": "FAILED", "automatic_publication": False,
            "reason": decision.reason,
            "unified_mode": "blocked", "unified_reason": decision.reason,
            "unified_job_id": decision.job_id,
        }
    if decision.action == "resume":
        resume_override = overrides.get("resume")
        if resume_override is not None:
            result = resume_override(root, decision.job_id)
        else:
            result = continue_micro_visual_run(root, decision.job_id, deps=overrides)
    elif decision.action == "complete":
        result = overrides.get("finalize", finalize_existing_draft)(root, decision.job_id)
    else:
        # Explicit full-production mode: keep the frozen config file untouched,
        # but do not stop at Flow for this run.
        generated_run_id = f"mv-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        mode_deps = dict(overrides)
        base_load = mode_deps.get("load_config") or load_flow_config

        def full_load(path: Path) -> dict[str, Any]:
            cfg = dict(base_load(path))
            cfg["stop_before_flow_submit"] = False
            return cfg

        mode_deps["load_config"] = full_load
        result = overrides.get("new_run", run_literature_micro_visual)(
            root, deps=mode_deps, run_id=generated_run_id
        )
    result = dict(result or {})
    result["unified_mode"] = decision.action
    result["unified_reason"] = decision.reason
    result["unified_job_id"] = (
        result.get("job_id") or decision.job_id
    ) if decision.action != "new" else result.get("job_id")
    result["unified_run_id"] = result.get("run_id") or generated_run_id
    return result
