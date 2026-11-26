from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from wechat_video import daily_pipelines as daily


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _config(root: Path) -> None:
    _write(root / "configs" / "daily_pipelines.json", {
        "schema_version": 1,
        "timezone": "Asia/Shanghai",
        "outputs_root": "outputs",
        "runtime_root": "runtime/daily_pipelines",
        "lock_wait_seconds": 2,
        "opencode": {
            "executable": "opencode",
            "agent": "daily-content-planner",
            "model": None,
            "timeout_seconds": 60,
        },
        "literature": {
            "enabled": True,
            "upstream_daily_runs_dir": "runtime/upstream_daily_runs",
            "upstream_account_key": "research_subscription",
            "expected_public_account_biz_id": "MzIyMjY1ODkwMA==",
            "materialized_package_root": "runtime/upstream_article_packages",
            "max_articles_per_day": 1,
            "selection_policy": "latest_published_at",
            "source_cta_text": "更多详细解读见【成核生长】同名公众号",
            "outro_duration_ms": 1800,
        },
        "popularization": {
            "enabled": True,
            "fact_cards_dir": "fact_cards",
            "sources_file": "fact_cards/sources.json",
            "history_file": "runtime/daily_pipelines/popularization_history.json",
            "max_topics_per_day": 1,
            "language": "en-US",
            "target_duration_seconds": [55, 65],
        },
        "upload": {
            "account_name": "成核生长",
            "draft_only": True,
            "automatic_publication": False,
        },
    })


def _fact_card(root: Path, *, status: str) -> tuple[Path, Path]:
    cards = root / "fact_cards"
    cards.mkdir(parents=True, exist_ok=True)
    sources_path = cards / "sources.json"
    _write(sources_path, {
        "schema_version": 1,
        "sources": [{
            "source_id": "SRC-1",
            "title": "Source supporting the approved science claims",
            "url": "https://example.org/source",
            "access_status": "FULL_TEXT_LOCATED",
        }],
    })
    card_path = cards / "science_topic.json"
    _write(card_path, {
        "schema_version": 1,
        "fact_card_id": "SCIENCE-001",
        "title": "科学现象背后的关键机制",
        "channels_title": "关键机制如何起作用",
        "scientific_question": "为什么这个科学现象会发生？",
        "scope": "仅讨论 Fact Card 已明确的模型、条件和适用范围。",
        "approval_status": status,
        "approved_by": "user" if status == "APPROVED" else None,
        "approved_at": "2026-11-20T12:00:00+08:00" if status == "APPROVED" else None,
        "editorial_angle_id": "critical_radius_growth_perspective",
        "claims": [{
            "claim_id": "C1",
            "statement": "在记录的模型条件下，界面代价随面积增加。",
            "evidence_status": "FULL_TEXT_LOCATED",
            "source_ids": ["SRC-1"],
            "conditions": ["模型条件"],
            "caveats": ["不能外推到未测试体系。"],
        }],
    })
    return card_path, sources_path


def test_content_planner_fails_closed_without_explicit_model(tmp_path: Path, monkeypatch) -> None:
    config = {
        "opencode": {
            "executable": "opencode",
            "agent": "daily-content-planner",
            "model": None,
            "require_explicit_model": True,
        }
    }
    with pytest.raises(daily.DailyPipelineError, match="No OpenCode model is explicitly configured"):
        daily._run_content_planner(
            tmp_path,
            config,
            prompt="test",
            attachments=[],
        )


def test_published_local_date_converts_utc_to_shanghai_calendar_day() -> None:
    assert daily._published_local_date(
        "2026-11-23T17:00:00Z", "Asia/Shanghai"
    ) == date(2026, 11, 24)


def test_asia_shanghai_timezone_falls_back_when_windows_has_no_iana_database(monkeypatch) -> None:
    def missing_zoneinfo(name: str):
        raise daily.ZoneInfoNotFoundError(name)

    monkeypatch.setattr(daily, "ZoneInfo", missing_zoneinfo)

    zone = daily._configured_timezone("Asia/Shanghai")
    assert zone.utcoffset(None).total_seconds() == 8 * 60 * 60
    assert daily._published_local_date(
        "2026-11-23T17:00:00Z", "Asia/Shanghai"
    ) == date(2026, 11, 24)

    with pytest.raises(daily.DailyPipelineError, match="Invalid configured timezone"):
        daily._configured_timezone("America/New_York")


def test_extract_model_usage_sums_opencode_step_finish_telemetry() -> None:
    events = [
        {
            "type": "step_finish",
            "sessionID": "ses_fixture",
            "part": {
                "reason": "tool-calls",
                "cost": 0.001,
                "tokens": {
                    "input": 100,
                    "output": 10,
                    "reasoning": 5,
                    "cache": {"read": 20, "write": 2},
                },
            },
        },
        {
            "type": "step_finish",
            "sessionID": "ses_fixture",
            "part": {
                "reason": "stop",
                "cost": 0.002,
                "tokens": {
                    "input": 200,
                    "output": 30,
                    "reasoning": 10,
                    "cache": {"read": 40, "write": 3},
                },
            },
        },
    ]
    usage = daily._extract_model_usage("\n".join(json.dumps(item) for item in events))

    assert usage["available"] is True
    assert usage["complete"] is True
    assert usage["session_ids"] == ["ses_fixture"]
    assert usage["step_count"] == 2
    assert usage["tokens"] == {
        "input": 300,
        "output": 40,
        "reasoning": 15,
        "cache_read": 60,
        "cache_write": 5,
        "total": 355,
        "total_including_cache_io": 420,
    }
    assert usage["cost"] == 0.003
    assert usage["cost_currency"] == "USD"


def test_model_usage_marks_jsonl_without_terminal_step_as_incomplete() -> None:
    event = {
        "type": "step_finish",
        "sessionID": "ses_partial",
        "part": {
            "reason": "tool-calls",
            "cost": 0.001,
            "tokens": {"input": 80, "output": 5, "reasoning": 0},
        },
    }
    usage = daily._extract_model_usage(json.dumps(event))

    assert usage["available"] is True
    assert usage["complete"] is False


def test_extract_exported_model_usage_recovers_aggregated_assistant_counters() -> None:
    exported = {
        "info": {"id": "ses_exported"},
        "messages": [
            {"info": {"role": "user"}, "parts": [{"type": "text", "text": "prompt"}]},
            {
                "info": {
                    "role": "assistant",
                    "tokens": {
                        "input": 150,
                        "output": 20,
                        "reasoning": 4,
                        "cache": {"read": 500, "write": 6},
                    },
                    "cost": 0.0042,
                },
                "parts": [{"type": "text", "text": "ok"}],
            },
        ],
    }

    usage = daily._extract_exported_model_usage(
        exported,
        fallback_session_id="ses_fallback",
    )

    assert usage["available"] is True
    assert usage["complete"] is True
    assert usage["session_ids"] == ["ses_exported"]
    assert usage["step_count"] == 1
    assert usage["tokens"] == {
        "input": 150,
        "output": 20,
        "reasoning": 4,
        "cache_read": 500,
        "cache_write": 6,
        "total": 174,
        "total_including_cache_io": 680,
    }
    assert usage["cost"] == 0.0042
    assert usage["source"] == "OpenCode opencode session export"


def test_extract_model_text_accepts_opencode_jsonl_text_events() -> None:
    output = (
        '{"type":"text","part":{"type":"text","text":"{\\"schema_version\\":1,"}}\n'
        '{"type":"text","part":{"type":"text","text":"\\"ok\\":true}"}}\n'
    )
    parsed = json.loads(daily._extract_model_text(output))
    assert parsed == {"schema_version": 1, "ok": True}


def test_popularization_duration_gate_uses_measured_timeline(tmp_path: Path) -> None:
    run_dir = tmp_path / "outputs" / "pop"
    run_dir.mkdir(parents=True)
    _write(run_dir / "audio_timing.json", {"total_duration_seconds": 60.0})

    passed = daily._popularization_duration_gate(run_dir, [55, 65])
    assert passed["status"] == "PASS"
    assert passed["measurement_authority"] == "audio_timing.json measured PCM sample clock"

    _write(run_dir / "audio_timing.json", {"total_duration_seconds": 67.2})
    failed = daily._popularization_duration_gate(run_dir, [55, 65])
    assert failed["status"] == "FAIL"
    assert failed["measured_seconds"] == 67.2


def test_pending_fact_cards_never_enter_approved_popularization_pool(tmp_path: Path) -> None:
    card_path, _ = _fact_card(tmp_path, status="DRAFT_PENDING_USER_REVIEW")

    approved, rejected = daily._approved_popularization_cards(tmp_path, {
        "popularization": {
            "fact_cards_dir": "fact_cards",
            "sources_file": "fact_cards/sources.json",
        }
    })

    assert approved == []
    assert rejected[0]["reason"] == "not_approved"


def test_tracked_approved_fact_card_is_eligible_only_with_registered_strategy(tmp_path: Path) -> None:
    card_path, _ = _fact_card(tmp_path, status="APPROVED")

    approved, rejected = daily._approved_popularization_cards(tmp_path, {
        "popularization": {
            "fact_cards_dir": "fact_cards",
            "sources_file": "fact_cards/sources.json",
        }
    })

    assert len(approved) == 1
    assert approved[0]["fact_card_id"] == "SCIENCE-001"
    assert approved[0]["path"] == card_path
    assert rejected == []


def test_hash_bound_approval_keeps_pending_fact_card_eligible_after_recheck(tmp_path: Path) -> None:
    from wechat_video.topic_approval import approve_fact_card

    card_path, sources_path = _fact_card(
        tmp_path, status="DRAFT_PENDING_USER_REVIEW"
    )
    approve_fact_card(
        tmp_path,
        card_path,
        approved_by="test-user",
        confirmation="APPROVE FACT CARD SCIENCE-001",
    )

    approved, rejected = daily._approved_popularization_cards(tmp_path, {
        "popularization": {
            "fact_cards_dir": "fact_cards",
            "sources_file": "fact_cards/sources.json",
        }
    })
    assert len(approved) == 1
    assert rejected == []

    loaded = daily._load_selected_popularization_card(
        tmp_path,
        card_path,
        sources_path,
        expected_card_sha256=approved[0]["fact_card_sha256"],
        expected_source_sha256=approved[0]["source_record_sha256"],
    )
    assert loaded["approval_status"] == "DRAFT_PENDING_USER_REVIEW"


def test_read_only_literature_inspection_has_no_production_side_effects(tmp_path: Path) -> None:
    _config(tmp_path)
    report = daily.inspect_daily_literature_sources(
        tmp_path,
        published_date="2026-11-23",
    )

    assert report["state"] == "SKIPPED_NO_ELIGIBLE_ARTICLE"
    assert report["mode"] == "READ_ONLY_DISCOVERY"
    assert report["candidate_count"] == 0
    assert report["side_effects"] == {
        "materialized_package": False,
        "open_code_started": False,
        "tts_started": False,
        "manim_started": False,
        "ffmpeg_started": False,
        "upload_attempted": False,
    }
    assert not (tmp_path / "runtime" / "upstream_article_packages").exists()
    assert not (tmp_path / "outputs").exists()


def test_missing_daily_sources_return_safe_skip_without_model_or_upload(tmp_path: Path) -> None:
    _config(tmp_path)
    (tmp_path / "runtime" / "upstream_daily_runs").mkdir(parents=True)
    (tmp_path / "outputs").mkdir()
    literature = daily.run_daily_literature(tmp_path, published_date="2026-11-23")
    popularization = daily.run_daily_popularization(tmp_path, local_date="2026-11-24")

    assert literature["state"] == "SKIPPED_NO_ELIGIBLE_ARTICLE"
    assert popularization["state"] == "SKIPPED_NO_APPROVED_TOPIC"


def test_job_record_prevents_automatic_repeat_after_side_effect(tmp_path: Path) -> None:
    path = tmp_path / "jobs" / "literature.json"
    record = daily._start_job(
        path, content_type="literature", local_date=date(2026, 11, 24), source_id="article-1"
    )
    daily._update_job(path, record, "VIDEO_QA_PASSED", video_sha256="abc")

    with pytest.raises(daily.DailyPipelineError, match="refusing automatic rerun"):
        daily._start_job(
            path, content_type="literature", local_date=date(2026, 11, 24), source_id="article-1"
        )


def _read_json_for_test(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_daily_failure_reconciles_a_verified_draft_from_uploader_journal(tmp_path: Path) -> None:
    _config(tmp_path)
    _write(tmp_path / "config" / "channels_upload.json", {
        "jobs_dir": "runtime/upload_jobs",
    })
    job_path = (
        tmp_path / "runtime" / "daily_pipelines" / "jobs"
        / "2026-11-24" / "literature.json"
    )
    _write(job_path, {
        "content_type": "literature",
        "state": "UPLOADING",
        "run_dir": str(tmp_path / "outputs" / "run-001"),
        "source_id": "article-001",
    })
    _write(tmp_path / "runtime" / "upload_jobs" / "run-001.json", {
        "job_id": "run-001",
        "source_run_id": "run-001",
        "upload_attempt": 1,
        "state": "DRAFT_SAVED",
        "account_name": "成核生长",
        "verified_draft": {"title": "已验证草稿"},
    })

    state = daily._mark_daily_job(
        tmp_path,
        _read_json_for_test(tmp_path / "configs" / "daily_pipelines.json"),
        date(2026, 11, 24),
        "literature",
        "UPLOAD_UNKNOWN",
        "simulated exception after uploader completed",
    )
    saved = json.loads(job_path.read_text(encoding="utf-8"))

    assert state == "DRAFT_SAVED"
    assert saved["state"] == "DRAFT_SAVED"
    assert saved["recovered_from_upload_journal"] is True
    assert saved["verified_draft"]["title"] == "已验证草稿"


def test_two_pipeline_dispatcher_continues_after_one_pipeline_failure(tmp_path: Path, monkeypatch) -> None:
    _config(tmp_path)
    calls: list[str] = []

    def fail_literature(_root, _config, *, published_date):
        calls.append("literature")
        raise RuntimeError("fixture literature failure")

    def save_popularization(_root, _config, *, local_date):
        calls.append("popularization")
        return {"state": "DRAFT_SAVED", "source_id": "SCIENCE-001"}

    monkeypatch.setattr(daily, "_run_literature_locked", fail_literature)
    monkeypatch.setattr(daily, "_run_popularization_locked", save_popularization)

    result = daily.run_daily_two_videos(tmp_path, published_date="2026-11-23")

    assert calls == ["literature", "popularization"]
    assert result["literature"]["state"] == "FAILED"
    assert result["popularization"]["state"] == "DRAFT_SAVED"
    assert result["overall_state"] == "PARTIAL_OR_BLOCKED"
