"""Mock-based tests for the single unified BAT entry."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from wechat_video import micro_visual_unified as unified


def _job(root: Path, job_id: str, *, state: str = "STOPPED_BEFORE_FLOW_SUBMIT",
         flow_submitted: bool | None = None, event: bool = False,
         verified: bool = False, artifacts: bool = True) -> Path:
    d = root / "outputs" / job_id
    d.mkdir(parents=True, exist_ok=True)
    if artifacts:
        for name in ("micro_visual_plan.json", "flow_prompt.txt",
                     "visual_theme_binding.json", "source_evidence.json"):
            (d / name).write_text("{}", encoding="utf-8")
    if event:
        (d / "flow_generation_event.json").write_text("{}", encoding="utf-8")
    ledger = root / unified.LEDGER_PATH
    ledger.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {"job_id": job_id, "draft_state": state}
    if flow_submitted is not None:
        record["flow_submitted"] = flow_submitted
    if verified:
        record["verified_draft"] = {"title": "标题", "row_text": "标题 2026-11-28"}
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return d


def test_bat_uses_single_unified_entry() -> None:
    root = Path(__file__).resolve().parents[1]
    bat = (root / "Run_Literature_Micro_Visual.bat").read_text(encoding="utf-8")
    assert "run-micro-visual-unified" in bat
    assert "run-literature-micro-visual" not in bat


def test_no_unfinished_job_starts_full_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _job(tmp_path, "done", state="DRAFT_SAVED", flow_submitted=True, verified=True, event=True)
    calls: dict[str, Any] = {}
    def finalize(_r: Path, j: str) -> dict[str, Any]:
        calls["finalize"] = j
        return {"state": "DRAFT_SAVED"}
    monkeypatch.setattr(unified, "finalize_existing_draft", finalize)
    monkeypatch.setattr(unified, "continue_micro_visual_run",
                        lambda *_a, **_k: pytest.fail("must not resume a completed job"))

    def new_run(_root: Path, *, deps: dict[str, Any]) -> dict[str, Any]:
        cfg = deps["load_config"](_root)
        calls["stop_before_flow_submit"] = cfg["stop_before_flow_submit"]
        return {"state": "DRAFT_SAVED", "verified_draft": {"title": "t", "row_text": "r"}}

    monkeypatch.setattr(unified, "run_literature_micro_visual", new_run)
    result = unified.run_unified(tmp_path, deps={
        "load_config": lambda _r: {"stop_before_flow_submit": True},
    })
    assert result["unified_mode"] == "new"
    assert calls["stop_before_flow_submit"] is False


def test_stopped_job_resumes_original(tmp_path: Path) -> None:
    _job(tmp_path, "stopped")
    result = unified.run_unified(tmp_path, deps={
        "resume": lambda _r, j: {"state": "DRAFT_SAVED", "job_id": j,
                                  "verified_draft": {"title": "t", "row_text": "r"}},
        "new_run": lambda *_a, **_k: pytest.fail("must not create a new job"),
    })
    assert result["unified_mode"] == "resume"
    assert result["unified_job_id"] == "stopped"


def test_submitted_job_never_resubmits_generate(tmp_path: Path) -> None:
    _job(tmp_path, "submitted", state="FAILED", flow_submitted=True, event=True)
    captured: dict[str, Any] = {}

    def resume(_root: Path, job_id: str) -> dict[str, Any]:
        captured["job"] = job_id
        return {"state": "DRAFT_SAVED", "verified_draft": {"title": "t", "row_text": "r"}}

    result = unified.run_unified(tmp_path, deps={"resume": resume})
    assert result["unified_mode"] == "resume"
    assert captured["job"] == "submitted"


def test_downloaded_job_resumes_without_upstream(tmp_path: Path) -> None:
    _job(tmp_path, "downloaded", state="FAILED", flow_submitted=True, event=True)
    (tmp_path / "outputs/downloaded/final.mp4").write_bytes(b"x" * 1000)
    result = unified.run_unified(tmp_path, deps={
        "resume": lambda _r, j: {"state": "DRAFT_SAVED", "job_id": j,
                                  "verified_draft": {"title": "t", "row_text": "r"}},
    })
    assert result["unified_job_id"] == "downloaded"


def test_completed_job_is_not_uploaded_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _job(tmp_path, "complete", state="DRAFT_SAVED", flow_submitted=True, event=True, verified=True)
    calls: dict[str, Any] = {}
    def finalize(_r: Path, j: str) -> dict[str, Any]:
        calls["finalize"] = j
        return {"state": "DRAFT_SAVED", "verified_draft": {"title": "t", "row_text": "r"}}
    monkeypatch.setattr(unified, "finalize_existing_draft", finalize)
    monkeypatch.setattr(unified, "continue_micro_visual_run",
                        lambda *_a, **_k: pytest.fail("must not upload again"))
    def new_run(_root: Path, *, deps: dict[str, Any]) -> dict[str, Any]:
        return {"state": "DRAFT_SAVED", "verified_draft": {"title": "t", "row_text": "r"}}
    monkeypatch.setattr(unified, "run_literature_micro_visual", new_run)
    result = unified.run_unified(tmp_path, deps={
        "load_config": lambda _r: {"stop_before_flow_submit": True},
    })
    assert result["unified_mode"] == "new"
    assert "finalize" not in calls
    assert "resume" not in calls


def test_corrupt_job_stops_instead_of_new_run(tmp_path: Path) -> None:
    d = _job(tmp_path, "broken", artifacts=False)
    with pytest.raises(unified.UnifiedDecisionError, match="no job directory"):
        unified.classify_jobs(tmp_path)
    with pytest.raises(unified.UnifiedDecisionError):
        unified.run_unified(tmp_path, deps={
            "new_run": lambda *_a, **_k: pytest.fail("must not create new job")})


def test_submitted_without_event_stops(tmp_path: Path) -> None:
    _job(tmp_path, "unsafe", state="FAILED", flow_submitted=True)
    with pytest.raises(unified.UnifiedDecisionError, match="without generation event"):
        unified.classify_jobs(tmp_path)


def test_multiple_unfinished_jobs_stop(tmp_path: Path) -> None:
    _job(tmp_path, "one")
    _job(tmp_path, "two")
    with pytest.raises(unified.UnifiedDecisionError, match="multiple unfinished jobs"):
        unified.classify_jobs(tmp_path)
