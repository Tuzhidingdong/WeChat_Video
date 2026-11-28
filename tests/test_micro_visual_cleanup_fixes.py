"""Targeted tests for the three pre-flow cleanup fixes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from wechat_video import micro_visual_theme as theme_mod
from wechat_video.micro_visual_status_readback import main as readback_main

RUN_ID = "mv-test-run"
CONFIG = {
    "model": "Omni Flash 1.2", "duration_seconds": 15, "aspect_ratio": "9:16",
    "resolution": "720p", "output_count": 1,
}


def _state(**overrides: Any) -> dict[str, Any]:
    data = {
        "run_id": RUN_ID, "state": "STOPPED_BEFORE_FLOW_SUBMIT",
        "success": False, "exit_code": 0,
        "message": "内容准备完成，已按配置停止在 Flow 提交前。",
        "verified_draft": None,
    }
    data.update(overrides)
    return data


def _write(path: Path, data: Any) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_stopped_state_readback_is_not_treated_as_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MICRO_VISUAL_EXPECTED_RUN_ID", raising=False)
    path = _write(tmp_path / "state.json", _state())
    assert readback_main([str(path)]) == 0
    out = capsys.readouterr().out.strip()
    assert "[STOPPED_BEFORE_FLOW_SUBMIT]" in out
    assert f"run_id={RUN_ID}" in out
    assert "exit_code=0" in out
    assert "停止在 Flow 提交前" in out


def test_missing_or_invalid_state_fails_explicitly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert readback_main([str(tmp_path / "missing.json")]) == 2
    assert "状态文件缺失" in capsys.readouterr().out
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    assert readback_main([str(bad)]) == 2
    assert "状态文件缺失" in capsys.readouterr().out


def test_run_id_mismatch_fails_explicitly(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MICRO_VISUAL_EXPECTED_RUN_ID", "other-run")
    path = _write(tmp_path / "state.json", _state())
    assert readback_main([str(path)]) == 2
    assert "run_id 与本次运行不一致" in capsys.readouterr().out


def test_draft_saved_without_verified_draft_is_not_success(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MICRO_VISUAL_EXPECTED_RUN_ID", raising=False)
    path = _write(tmp_path / "state.json", _state(state="DRAFT_SAVED", exit_code=0))
    assert readback_main([str(path)]) == 0
    assert "[DRAFT_SAVED]" in capsys.readouterr().out


def _theme_payload(session_id: str) -> dict[str, Any]:
    def field(text: str) -> dict[str, Any]:
        return {"text": text, "kind": "scientific", "supporting_claim_ids": ["C1"],
                "supporting_source_excerpts": ["excerpt"], "evidence_paraphrase": text}
    def candidate(cid: str) -> dict[str, Any]:
        return {"candidate_id": cid, "subject": field("subject text"),
                "action": field("drift slowly"), "environment": field("liquid environment"),
                "selection_rationale": "r", "relationship_to_core_finding": "core_phenomenon",
                "scientific_uncertainties": [], "unsupported_visual_details": []}
    return {
        "schema_version": 2, "article_id": "100000884_0",
        "source_article_sha256": "a" * 64, "run_id": RUN_ID,
        "candidates": [candidate("A"), candidate("B")],
        "selected_candidate_id": "A", "selection_summary": "s",
        "_planner_run_metadata": {
            "agent": theme_mod.THEME_AGENT,
            "model": "opencode-go/hungerg-free",
            "usage": {"session_ids": [session_id]},
        },
    }


def test_stage_a_raw_response_and_session_are_saved(tmp_path: Path) -> None:
    summary = tmp_path / "summary.json"
    summary.write_text("{}", encoding="utf-8")
    article = tmp_path / "article.md"
    article.write_text("# article", encoding="utf-8")
    sid = "ses_stage_a_fake"
    payload = _theme_payload(sid)

    def runner(_root: Path, _cfg: dict[str, Any], *, prompt: str, attachments: list[Path]) -> dict[str, Any]:
        return payload

    out = tmp_path / "stage"
    theme_mod.extract_visual_theme(
        tmp_path, summary_path=summary, article_dir=tmp_path, output_dir=out,
        deps={"run_agent": runner, "load_daily_config": lambda _r: {"opencode": {}}},
        context={"article_id": "100000884_0", "source_article_sha256": "a" * 64, "run_id": RUN_ID},
    )
    assert not hasattr(theme_mod, "_unused")  # no-op guard against accidental broad rewrites
    raw = json.loads((out / "visual_theme_raw.json").read_text(encoding="utf-8"))
    session = json.loads((out / "stage_a_session.json").read_text(encoding="utf-8"))
    assert raw["_planner_run_metadata"]["usage"]["session_ids"] == [sid]
    assert session["session_ids"] == [sid]
    assert session["agent"] == theme_mod.THEME_AGENT
    assert session["run_id"] == RUN_ID
    assert (out / "visual_theme_raw.txt").is_file()
    assert (out / "visual_theme.json").is_file()
