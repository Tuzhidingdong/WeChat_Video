"""Mock integration: classifier + REAL continuation code (no LLM/Flow/network)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from wechat_video import micro_visual_continuation as cont
from wechat_video import micro_visual_unified as unified
from wechat_video.micro_visual_plan import prompt_sha256

PROMPT = "Create one 15 second 9:16 video.\nOne continuous microscopic shot: micelles spread.\n"
TITLE = "盐效应与界面离子调控"


def _setup(root: Path, job: str = "job-1", *, state: str = "STOPPED_BEFORE_FLOW_SUBMIT",
           submitted: bool = False, event: bool = True, event_sha: str | None = None,
           final: bool = False) -> Path:
    d = root / "outputs" / job
    d.mkdir(parents=True, exist_ok=True)
    sha = prompt_sha256(PROMPT.strip())
    summary_dir = root / "outputs" / "summary-run"
    summary_dir.mkdir(parents=True, exist_ok=True)
    (summary_dir / "summary.json").write_text(
        json.dumps({"channels_title": TITLE}, ensure_ascii=False), encoding="utf-8")
    (d / "micro_visual_plan.json").write_text(json.dumps({
        "job_id": job, "draft_title": "一个超过十六字的摘要句子不适合作为草稿标题使用",
    }, ensure_ascii=False), encoding="utf-8")
    (d / "draft_title.txt").write_text(
        "一个超过十六字的摘要句子不适合作为草稿标题使用\n", encoding="utf-8")
    (d / "flow_prompt.txt").write_text(PROMPT, encoding="utf-8")
    (d / "visual_theme_binding.json").write_text(json.dumps({
        "run_id": "mv-frozen", "article_id": "100000884_0",
        "source_article_sha256": "a" * 64, "source_run_id": "src-run",
        "flow_prompt_sha256": sha, "summary_run_dir": str(summary_dir),
    }, ensure_ascii=False), encoding="utf-8")
    (d / "source_evidence.json").write_text(json.dumps({
        "article_id": "100000884_0", "source_article_sha256": "a" * 64,
        "selected_sentence_sha256": "b" * 64, "claim_ids": ["C1"],
        "source_excerpt": "原文摘录", "source_excerpt_references": [],
    }, ensure_ascii=False), encoding="utf-8")
    if event:
        (d / "flow_generation_event.json").write_text(json.dumps({
            "flow_prompt_sha256": event_sha or sha,
            "flow_submission_timestamp": "2026-11-28T22:00:00",
            "flow_model": "Omni Flash 1.2", "flow_duration": 15,
            "flow_generation_status": "SUBMITTED",
        }, ensure_ascii=False), encoding="utf-8")
    if final:
        (d / "final.mp4").write_bytes(b"x" * 200_000)
    ledger = root / unified.LEDGER_PATH
    ledger.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {"job_id": job, "draft_state": state}
    if submitted:
        record["flow_submitted"] = True
    if state == "DRAFT_SAVED":
        record["verified_draft"] = {"title": TITLE, "row_text": TITLE + " 2026-11-28"}
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return d


def _deps(tmp: Path, calls: dict[str, Any]) -> dict[str, Any]:
    class Browser:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.page = None

        def __enter__(self) -> "Browser":
            return self

        def __exit__(self, *_a: Any) -> None:
            return None

    class Capture:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        def install(self) -> None:
            pass

    class FlowCapture:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        def install(self) -> None:
            pass

        def capture(self, status: str, **_kw: Any) -> dict[str, Any]:
            calls["captured"] = status
            return {"flow_generation_status": status, "flow_project_id": "p"}

        def finalize(self, status: str, **_kw: Any) -> dict[str, Any]:
            return {"flow_generation_status": status, "flow_project_id": "p"}

    def submit(*_a: Any, **_k: Any) -> dict[str, Any]:
        calls["submit"] = True
        pytest.fail("Generate must not be submitted twice")

    def locate(*_a: Any, **_k: Any) -> dict[str, Any]:
        calls["locate"] = True
        return {"state": "RESULT_LOCATED"}

    def download(*_a: Any, **_k: Any) -> dict[str, Any]:
        calls["download"] = True
        p = tmp / "downloaded.mp4"
        p.write_bytes(b"y" * 200_000)
        return {"path": str(p), "sha256": "c" * 64}

    def upload(_root: Path, run_dir: Path, evidence: dict[str, Any], **_kw: Any) -> dict[str, Any]:
        calls["upload"] = evidence["draft_title"]
        return {
            "state": "DRAFT_SAVED", "title": evidence["draft_title"],
            "verified_draft": {"title": evidence["draft_title"], "row_text": TITLE + " 2026-11-28"},
        }

    return {
        "verify_identity": lambda *_a, **_k: {"verified": True, "account_name": "成核生长"},
        "ensure_session": lambda *_a, **_k: ({}, "ws://test"),
        "browser": lambda *_a, **_k: Browser(),
        "submit": submit,
        "flow_capture": FlowCapture,
        "locate_result": locate,
        "prepare_dir": lambda *_a, **_k: tmp / "downloads",
        "capture": lambda *_a, **_k: Capture(),
        "download_result": download,
        "upload": upload,
    }


def _patch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cont, "load_flow_config", lambda _r: {
        "model": "Omni Flash 1.2", "duration_seconds": 15, "aspect_ratio": "9:16",
        "resolution": "720p", "output_count": 1, "result_locate_timeout_seconds": 10,
    })
    monkeypatch.setattr(cont, "validate_video", lambda _p, _c: {"status": "PASS", "sha256": "c" * 64})


def test_submitted_without_video_resumes_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(tmp_path, submitted=True, final=False)
    _patch(monkeypatch)
    calls: dict[str, Any] = {}
    result = unified.run_unified(tmp_path, deps=_deps(tmp_path, calls))
    assert result["unified_mode"] == "resume"
    assert result["state"] == "DRAFT_SAVED", result.get("reason")
    assert "submit" not in calls
    assert calls["locate"] and calls["download"]
    assert (tmp_path / "outputs/job-1/final.mp4").is_file()


def test_submitted_with_video_skips_download_and_uploads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(tmp_path, submitted=True, final=True)
    _patch(monkeypatch)
    calls: dict[str, Any] = {}
    result = unified.run_unified(tmp_path, deps=_deps(tmp_path, calls))
    assert result["unified_mode"] == "resume"
    assert result["state"] == "DRAFT_SAVED"
    assert "submit" not in calls
    assert "locate" not in calls and "download" not in calls
    assert calls["upload"] == TITLE


def test_submitted_without_event_stops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(tmp_path, submitted=True, event=False)
    _patch(monkeypatch)
    calls: dict[str, Any] = {}
    with pytest.raises(unified.UnifiedDecisionError, match="without generation event"):
        unified.run_unified(tmp_path, deps=_deps(tmp_path, calls))
    assert "submit" not in calls


def test_event_prompt_mismatch_stops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(tmp_path, submitted=True, event_sha="f" * 64)
    _patch(monkeypatch)
    calls: dict[str, Any] = {}
    with pytest.raises(cont.ContinuationError, match="prompt SHA mismatch"):
        unified.run_unified(tmp_path, deps=_deps(tmp_path, calls))
    assert "submit" not in calls


def test_new_run_id_then_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def new_run(root: Path, *, deps: dict[str, Any], run_id: str) -> dict[str, Any]:
        assert run_id.startswith("mv-")
        assert deps["load_config"](root)["stop_before_flow_submit"] is False
        d = _setup(root, job="interrupted", state="STOPPED_BEFORE_FLOW_SUBMIT")
        binding = json.loads((d / "visual_theme_binding.json").read_text(encoding="utf-8"))
        binding["run_id"] = run_id
        (d / "visual_theme_binding.json").write_text(
            json.dumps(binding, ensure_ascii=False), encoding="utf-8")
        return {"state": "STOPPED_BEFORE_FLOW_SUBMIT", "job_id": "interrupted", "run_id": run_id}

    monkeypatch.setattr(unified, "run_literature_micro_visual", new_run)
    first = unified.run_unified(tmp_path, deps={
        "load_config": lambda _r: {"stop_before_flow_submit": True},
    })
    assert first["unified_mode"] == "new"
    assert first["unified_run_id"].startswith("mv-")

    _patch(monkeypatch)
    calls: dict[str, Any] = {}
    second = unified.run_unified(tmp_path, deps=_deps(tmp_path, calls))
    assert second["unified_mode"] == "resume"
    assert second["unified_job_id"] == "interrupted"
    assert "submit" not in calls
    assert second["state"] == "DRAFT_SAVED"


def test_manual_block_is_recognized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(tmp_path, state="BLOCKED_UPLOADER_IDENTITY")
    _patch(monkeypatch)
    calls: dict[str, Any] = {}
    result = unified.run_unified(tmp_path, deps=_deps(tmp_path, calls))
    assert result["unified_mode"] == "blocked"
    assert result["unified_job_id"] == "job-1"
    assert "submit" not in calls and "upload" not in calls


def test_completed_job_does_not_upload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(tmp_path, state="DRAFT_SAVED", submitted=True, final=True)
    _patch(monkeypatch)
    calls: dict[str, Any] = {}
    monkeypatch.setattr(unified, "run_literature_micro_visual",
                        lambda *_a, **_k: {"state": "DRAFT_SAVED", "job_id": "new"})
    result = unified.run_unified(tmp_path, deps={
        **_deps(tmp_path, calls),
        "load_config": lambda _r: {"stop_before_flow_submit": True},
        "finalize": lambda *_a, **_k: pytest.fail("completed job must not be re-finalized/uploaded"),
    })
    assert result["unified_mode"] == "new"
    assert "upload" not in calls and "submit" not in calls
