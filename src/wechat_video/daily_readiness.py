"""Unified, strictly read-only readiness inspection for the two daily BATs.

This module never starts production, a browser, a model task, TTS, Manim, FFmpeg,
or an upload. It only reads configuration, existing local artifacts and tool paths.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from .daily_pipelines import (
    VISUAL_STRATEGIES,
    _approved_popularization_cards,
    _load_config,
    _project_path,
    _read_history,
    inspect_daily_literature_sources,
)
from .tooling import describe_tools

def _git_value(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15, check=False,
        )
    except Exception:
        return ""
    return (result.stdout or "").strip()


READY = "READY_FOR_HUMAN_AUTHORIZATION"
PARTIAL = "PARTIALLY_READY"
BLOCKED = "BLOCKED"


def inspect_daily_two_video_readiness(
    project_root: Path,
    *,
    published_date: str | None = None,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    config = _load_config(project_root)
    tools = describe_tools(project_root)
    literature = inspect_daily_literature_sources(project_root, published_date=published_date)
    approved, rejected_cards = _approved_popularization_cards(project_root, config)

    opencode = config.get("opencode") or {}
    model = str(opencode.get("model") or "").strip() or None
    model_ok = bool(model)
    tools_ok = all(
        item.get("present") for key, item in tools.items()
        if key in {"ffmpeg", "ffprobe", "latex", "dvisvgm", "model_zh"}
    )

    lit_candidates = literature.get("candidates") or []
    lit_eligible = int(literature.get("eligible_candidate_count") or 0)
    lit_newest = lit_candidates[0] if lit_candidates else None
    lit_blockers: list[str] = []
    if lit_eligible <= 0:
        lit_blockers.append("no_unproduced_eligible_literature_article")
    if not model_ok:
        lit_blockers.append("opencode_planner_model_not_configured")
    if not tools_ok:
        lit_blockers.append("production_tools_missing")
    lit_status = READY if not lit_blockers else (BLOCKED if lit_eligible <= 0 else PARTIAL)

    pop_cfg = config.get("popularization") or {}
    cards_root = _project_path(project_root, str(pop_cfg.get("fact_cards_dir") or "fact_cards"))
    card_files = sorted(cards_root.glob("*.json")) if cards_root.is_dir() else []
    card_files = [p for p in card_files if p.name != "sources.json"]
    history_path = _project_path(
        project_root, str(pop_cfg.get("history_file") or "runtime/daily_pipelines/popularization_history.json")
    )
    history = _read_history(history_path)
    used_ids = {str(v) for v in (history.get("used_fact_card_ids") or [])}
    pop_blockers: list[str] = []
    if not approved:
        pop_blockers.append("no_approved_fact_card")
    if not model_ok:
        pop_blockers.append("opencode_planner_model_not_configured")
    if not tools_ok:
        pop_blockers.append("production_tools_missing")
    pop_status = READY if not pop_blockers else (BLOCKED if not approved else PARTIAL)

    shared_blockers: list[str] = []
    if not model_ok:
        shared_blockers.append("opencode_planner_model_not_configured")
    if not tools_ok:
        shared_blockers.append("production_tools_missing")
    shared_blockers.append("first_run_draft_acceptance_not_performed")
    shared_status = PARTIAL if not (not model_ok and not tools_ok) else BLOCKED

    return {
        "schema_version": 1,
        "command": "inspect-daily-two-video-readiness",
        "mode": "READ_ONLY",
        "literature": {
            "status": lit_status,
            "published_date": literature.get("published_date"),
            "window_start": literature.get("window_start"),
            "window_end": literature.get("window_end"),
            "lookback_days": literature.get("lookback_days"),
            "upstream_run_count": literature.get("upstream_run_count"),
            "found_article_count": literature.get("found_article_count"),
            "candidate_count": literature.get("candidate_count"),
            "eligible_candidate_count": lit_eligible,
            "already_rendered_count": literature.get("already_rendered_count"),
            "rejected_count": literature.get("rejected_count"),
            "rejection_categories": literature.get("rejection_categories"),
            "selected_candidate": literature.get("selected_candidate"),
            "deferred_candidates": literature.get("deferred_candidates", []),
            "expiring_candidates": literature.get("expiring_candidates", []),
            "newest_candidate": {
                "article_id": lit_newest.get("article_id"),
                "appmsgid": lit_newest.get("appmsgid"),
                "title": lit_newest.get("title"),
                "published_at": lit_newest.get("published_at"),
                "markdown_sha256": lit_newest.get("slot1_markdown_sha256"),
                "publication_evidence_dir": lit_newest.get("publication_evidence_dir"),
                "image_asset_source": lit_newest.get("image_asset_source"),
                "verified_local_image_count": lit_newest.get("verified_local_image_count"),
                "already_rendered": lit_newest.get("already_rendered"),
            } if lit_newest else None,
            "rejected_run_count": literature.get("rejected_run_count"),
            "blockers": lit_blockers,
            "technically_ready_for_first_run": lit_status == READY,
        },
        "popularization": {
            "status": pop_status,
            "fact_card_file_count": len(card_files),
            "approved_count": len(approved),
            "registered_visual_strategies": sorted(VISUAL_STRATEGIES),
            "used_fact_card_ids": sorted(used_ids),
            "rejected_cards": rejected_cards[:20],
            "blockers": pop_blockers,
            "technically_ready_for_first_run": pop_status == READY,
        },
        "shared": {
            "status": shared_status,
            "branch_head": _git_value(project_root, "rev-parse", "HEAD"),
            "branch_name": _git_value(project_root, "branch", "--show-current"),
            "tracked_worktree_dirty": bool(_git_value(project_root, "status", "--porcelain", "--untracked-files=no")),
            "python": sys.version.split()[0],
            "python_executable": str(Path(sys.executable).resolve()),
            "opencode_model": model,
            "opencode_requires_explicit_model": bool(opencode.get("require_explicit_model")),
            "tool_paths": {
                key: {"path": str(item.get("path") or ""), "present": bool(item.get("present"))}
                for key, item in tools.items() if isinstance(item, dict)
            },
            "upload": {
                "account_name": (config.get("upload") or {}).get("account_name"),
                "draft_only": (config.get("upload") or {}).get("draft_only"),
                "automatic_publication": (config.get("upload") or {}).get("automatic_publication"),
            },
            "production_lock_path": str(_project_path(
                project_root,
                str(Path(str(config.get("runtime_root", "runtime"))) / "daily_pipelines" / "pipeline.lock"),
            )),
            "task_scheduler_preconditions_met": False,
            "blockers": shared_blockers,
        },
        "side_effects": {
            "production_job_record_written": False,
            "article_package_materialized": False,
            "model_task_started": False,
            "tts_started": False,
            "manim_started": False,
            "ffmpeg_started": False,
            "edge_browser_started": False,
            "upload_attempted": False,
            "draft_saved": False,
            "input_files_modified": False,
        },
    }
