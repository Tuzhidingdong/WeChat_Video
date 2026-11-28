"""Targeted tests for the downstream-only continuation guards."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from wechat_video import micro_visual_continuation as cont
from wechat_video.micro_visual_plan import prompt_sha256

JOB = "20261128_100000884_0_micro_visual_test"
PROMPT = "Create one 15 second 9:16 video.\nOne continuous microscopic shot: test subject drift slowly.\n"


def _job(root: Path, *, prompt: str = PROMPT, ledger: bool = False) -> Path:
    d = root / "outputs" / JOB
    d.mkdir(parents=True)
    plan = {
        "job_id": JOB, "draft_title": "胶束在界面横向铺展",
        "article_source": {"selected_article": {"run_id": "src-run"}},
    }
    binding = {
        "run_id": "mv-frozen", "article_id": "100000884_0",
        "source_article_sha256": "a" * 64, "source_run_id": "src-run",
        "flow_prompt_sha256": prompt_sha256(prompt.strip()),
    }
    evidence = {
        "article_id": "100000884_0", "source_article_sha256": "a" * 64,
        "selected_sentence_sha256": "b" * 64, "claim_ids": ["C1"],
        "source_excerpt": "原文摘录", "source_excerpt_references": [],
    }
    (d / "micro_visual_plan.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    (d / "visual_theme_binding.json").write_text(json.dumps(binding, ensure_ascii=False), encoding="utf-8")
    (d / "source_evidence.json").write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
    (d / "draft_title.txt").write_text(plan["draft_title"] + "\n", encoding="utf-8")
    (d / "flow_prompt.txt").write_text(prompt, encoding="utf-8")
    if ledger:
        p = root / cont.LEDGER_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"job_id": JOB, "flow_submitted": True}) + "\n", encoding="utf-8")
    return d


def _deps(tmp: Path) -> dict[str, Any]:
    calls: dict[str, Any] = {}

    class Browser:
        def __init__(self, page: Any, cfg: Any) -> None:
            self.page = page

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
            self.data: dict[str, Any] = {}

        def install(self) -> None:
            pass

        def capture(self, status: str, **_kw: Any) -> dict[str, Any]:
            self.data = {"flow_generation_status": status, "flow_job_id": "job-1"}
            return dict(self.data)

        def finalize(self, status: str, **_kw: Any) -> dict[str, Any]:
            self.data["flow_generation_status"] = status
            return dict(self.data)

    def submit(page: Any, cfg: Any, prompt: str) -> dict[str, Any]:
        calls["prompt"] = prompt
        return {"flow_job_id": "job-1", "flow_credit_usage": {"delta": 60}}

    def locate(page: Any, cfg: Any, **kwargs: Any) -> dict[str, Any]:
        return {"state": "RESULT_LOCATED"}

    def download(page: Any, capture: Any, located: dict[str, Any], cfg: Any) -> dict[str, Any]:
        path = tmp / "downloaded.mp4"
        path.write_bytes(b"x" * 200_000)
        return {"path": str(path), "sha256": "c" * 64}

    def upload(root: Path, run_dir: Path, evidence: dict[str, Any], **_kw: Any) -> dict[str, Any]:
        calls["upload"] = evidence
        return {
            "state": "DRAFT_SAVED", "title": evidence["draft_title"],
            "verified_draft": {"title": evidence["draft_title"], "row_text": "草稿 2026-11-28"},
        }

    return {
        "verify_identity": lambda *_a, **_k: {"verified": True, "account_name": "成核生长"},
        "ensure_session": lambda *_a, **_k: ({}, "ws://test"),
        "browser": lambda *_a, **_k: Browser(None, {}),
        "submit": submit,
        "flow_capture": FlowCapture,
        "locate_result": locate,
        "prepare_dir": lambda *_a, **_k: tmp / "downloads",
        "capture": lambda *_a, **_k: Capture(),
        "download_result": download,
        "upload": upload,
        "_calls": calls,
    }


def test_invalid_job_id_blocked(tmp_path: Path) -> None:
    with pytest.raises(cont.ContinuationError, match="invalid job_id"):
        cont.continue_micro_visual_run(tmp_path, "../bad")


def test_prompt_sha_mismatch_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = _job(tmp_path, prompt=PROMPT + "tampered\n")
    binding = json.loads((d / "visual_theme_binding.json").read_text(encoding="utf-8"))
    binding["flow_prompt_sha256"] = prompt_sha256(PROMPT.strip())
    (d / "visual_theme_binding.json").write_text(json.dumps(binding, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cont, "load_flow_config", lambda _r: {})
    with pytest.raises(cont.ContinuationError, match="frozen prompt SHA mismatch"):
        cont.continue_micro_visual_run(tmp_path, JOB, deps=_deps(tmp_path))


def test_prior_flow_submission_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _job(tmp_path, ledger=True)
    monkeypatch.setattr(cont, "load_flow_config", lambda _r: {})
    with pytest.raises(cont.ContinuationError, match="generation event is missing"):
        cont.continue_micro_visual_run(tmp_path, JOB, deps=_deps(tmp_path))


def test_submitted_without_video_resumes_download_without_new_generate(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = _job(tmp_path)
    (d / "flow_generation_event.json").write_text(json.dumps({
        "flow_prompt_sha256": prompt_sha256(PROMPT.strip()),
        "flow_submission_timestamp": "2026-11-28T22:00:00",
        "flow_model": "Omni Flash 1.2", "flow_duration": 15,
        "flow_generation_status": "SUBMITTED",
    }), encoding="utf-8")
    monkeypatch.setattr(cont, "load_flow_config", lambda _r: {
        "model": "Omni Flash 1.2", "duration_seconds": 15, "aspect_ratio": "9:16",
        "resolution": "720p", "output_count": 1, "result_locate_timeout_seconds": 10,
    })
    monkeypatch.setattr(cont, "validate_video", lambda _p, _c: {"status": "PASS", "sha256": "c" * 64})
    deps = _deps(tmp_path)
    deps["submit"] = lambda *_a, **_k: pytest.fail("Generate must not be submitted twice")
    result = cont.continue_micro_visual_run(tmp_path, JOB, deps=deps)
    assert result["state"] == "DRAFT_SAVED"
    assert (d / "final.mp4").is_file()


def test_happy_path_reaches_draft_saved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _job(tmp_path)
    monkeypatch.setattr(cont, "load_flow_config", lambda _r: {
        "model": "Omni Flash 1.2", "duration_seconds": 15, "aspect_ratio": "9:16",
        "resolution": "720p", "output_count": 1, "result_locate_timeout_seconds": 10,
    })
    monkeypatch.setattr(cont, "validate_video", lambda _p, _c: {"status": "PASS", "sha256": "c" * 64})
    deps = _deps(tmp_path)
    result = cont.continue_micro_visual_run(tmp_path, JOB, deps=deps)
    assert result["state"] == "DRAFT_SAVED"
    assert result["verified_draft"]["title"] == "胶束在界面横向铺展"
    assert deps["_calls"]["prompt"].strip() == PROMPT.strip()
    d = tmp_path / "outputs" / JOB
    assert (d / "flow_generation_report.json").is_file()
    assert (d / "video_validation_report.json").is_file()
    assert (d / "channels_upload_report.json").is_file()
    assert (d / "verified_draft.json").is_file()
    assert (d / "run_result.json").is_file()
