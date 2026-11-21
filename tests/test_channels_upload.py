from __future__ import annotations

import json
from pathlib import Path

import pytest

from wechat_video.channels_metadata import build_channels_metadata, validate_channels_metadata
from wechat_video.channels_uploader import (
    UploadBlockedError,
    _approval_record,
    _matching_draft_entries,
    _validate_run_for_upload,
    approve_run,
)
from wechat_video.topic_approval import (
    TopicApprovalError,
    approve_fact_card,
    verify_fact_card_approval,
)


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_run(root: Path, *, qa_status: str = "PASS") -> Path:
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    _write(
        config_dir / "channels_upload.json",
        {
            "schema_version": 1,
            "account_name": "成核生长",
            "create_url": "https://channels.weixin.qq.com/platform/post/create",
            "draft_list_url": "https://channels.weixin.qq.com/platform/post/list",
            "edge_profile_dir": "runtime/edge-profile",
            "session_file": "runtime/edge_session.json",
            "jobs_dir": "runtime/upload_jobs",
            "approvals_dir": "runtime/approvals",
            "selectors_file": "config/selectors.yaml",
            "title_min_chars": 6,
            "title_max_chars": 16,
            "description_max_chars": 1000,
            "default_tags": ["#成核生长"],
            "safety": {
                "allow_publish": False,
                "allow_schedule": False,
                "allow_delete": False,
                "allow_overwrite": False,
                "cdp_host": "127.0.0.1",
            },
        },
    )
    (config_dir / "selectors.yaml").write_text(
        "account_identity:\n  exact_text: 成核生长\n", encoding="utf-8"
    )

    run_dir = root / "outputs" / "20261121_120000_example"
    run_dir.mkdir(parents=True)
    (run_dir / "final.mp4").write_bytes(b"x" * 120_000)
    _write(
        run_dir / "fact_card.json",
        {
            "fact_card_id": "TEST-001",
            "title": "测试科学视频：界面能与体相收益",
            "channels_title": "临界半径如何决定成核",
            "scientific_question": "为什么界面代价与体相收益会相互竞争？",
            "scope": "仅在本测试定义的模型条件下讨论。",
            "claims": [{
                "claim_id": "C1",
                "statement": "测试事实。",
                "source_ids": ["S1"],
                "evidence_status": "FULL_TEXT_LOCATED",
                "caveats": [],
            }],
            "approval_status": "DRAFT_PENDING_USER_REVIEW",
        },
    )
    _write(run_dir / "source_record.json", {"sources": [{"source_id": "S1"}]})
    _write(run_dir / "script.json", {"script_id": "TEST-SCRIPT"})
    _write(
        run_dir / "qa_report.json",
        {
            "overall_status": qa_status,
            "video_summary": {"duration_seconds": 60.0},
        },
    )
    return run_dir


def test_channels_metadata_uses_explicit_short_title_and_only_fact_card_text() -> None:
    card = {
        "fact_card_id": "CNT-1",
        "title": "临界晶核：界面代价与体相收益",
        "channels_title": "临界半径如何决定成核",
        "scientific_question": "为什么有些小晶核会消失，而更大的晶核可能继续长大？",
        "scope": "仅讨论经典均匀成核理论的球形近似。",
    }
    script = {"script_id": "S1", "title": "ignored for facts"}
    result = build_channels_metadata(card, script, "job_1")
    assert result["title"] == card["channels_title"]
    assert 6 <= len(result["title"]) <= 16
    assert card["scientific_question"] in result["description"]
    assert card["scope"] in result["description"]
    assert result["source"] == "fact_card_and_script_metadata"
    assert "ignored for facts" not in result["description"]
    validate_channels_metadata(result)


def test_metadata_rejects_short_title_outside_6_to_16_chars() -> None:
    with pytest.raises(ValueError, match="6–16"):
        validate_channels_metadata(
            {"job_id": "j1", "title": "这个标题长度明显超过十六个字符了吧", "description": "description"}
        )
    with pytest.raises(ValueError, match="6–16"):
        validate_channels_metadata(
            {"job_id": "j1", "title": "短", "description": "description"}
        )


def test_draft_match_requires_title_and_explicit_draft_status() -> None:
    selectors = {"draft_status_texts": ["草稿", "草稿箱"]}
    snapshot = {
        "entries": [
            "临界半径如何决定成核 已发布",
            "临界半径如何决定成核 草稿 2026-11-21",
        ]
    }
    matches = _matching_draft_entries(snapshot, "临界半径如何决定成核", selectors)
    assert len(matches) == 1
    assert "草稿" in matches[0]


def test_pending_sample_requires_explicit_human_approval(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path)
    with pytest.raises(UploadBlockedError, match="Approval phrase did not match"):
        approve_run(
            tmp_path,
            run_dir,
            approved_by="test-user",
            confirmation="NO",
        )
    assert not (tmp_path / "runtime" / "approvals" / f"{run_dir.name}.json").exists()


def test_explicit_approval_is_bound_to_exact_artifact_hashes(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path)
    approval = approve_run(
        tmp_path,
        run_dir,
        approved_by="test-user",
        confirmation="APPROVE TEST-001",
    )
    saved = tmp_path / "runtime" / "approvals" / f"{run_dir.name}.json"
    assert saved.is_file()
    assert approval["fact_card_approved"] is True
    assert approval["video_accepted"] is True
    assert approval["qa_status"] == "PASS"
    assert len(approval["video_sha256"]) == 64

    (run_dir / "final.mp4").write_bytes(b"changed" * 20_000)
    config = {"approvals_dir": "runtime/approvals"}
    with pytest.raises(UploadBlockedError, match="changed or is missing"):
        _approval_record(tmp_path, config, run_dir)


def test_warning_or_failed_qa_cannot_be_approved(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path, qa_status="PASS_WITH_WARNINGS")
    with pytest.raises(UploadBlockedError, match="strict QA PASS"):
        approve_run(
            tmp_path,
            run_dir,
            approved_by="test-user",
            confirmation="APPROVE TEST-001",
        )


def test_fact_card_approval_is_one_time_and_hash_bound_to_sources(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path)
    fact_dir = tmp_path / "fact_cards"
    fact_dir.mkdir(parents=True)
    card_path = fact_dir / "test_card.json"
    source_path = fact_dir / "sources.json"
    import shutil

    shutil.copy2(run_dir / "fact_card.json", card_path)
    shutil.copy2(run_dir / "source_record.json", source_path)

    with pytest.raises(TopicApprovalError, match="phrase did not match"):
        approve_fact_card(
            tmp_path,
            card_path,
            approved_by="test-user",
            confirmation="NO",
        )
    approval_file = tmp_path / "runtime" / "topic_approvals" / "TEST-001.json"
    assert not approval_file.exists()

    record = approve_fact_card(
        tmp_path,
        card_path,
        approved_by="test-user",
        confirmation="APPROVE FACT CARD TEST-001",
    )
    assert approval_file.is_file()
    assert record["fact_card_sha256"]
    assert record["source_record_sha256"]

    verified = verify_fact_card_approval(tmp_path, card_path, source_path)
    assert verified is not None
    assert verified["approval_type"] == "local_hash_bound"

    source_path.write_text(
        source_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    with pytest.raises(TopicApprovalError, match="Source record changed"):
        verify_fact_card_approval(tmp_path, card_path, source_path)


def test_upload_validation_accepts_one_time_topic_approval_without_daily_video_approval(
    tmp_path: Path,
) -> None:
    run_dir = _make_run(tmp_path)
    fact_dir = tmp_path / "fact_cards"
    fact_dir.mkdir(parents=True)
    card_path = fact_dir / "test_card.json"
    source_path = fact_dir / "sources.json"
    import shutil

    shutil.copy2(run_dir / "fact_card.json", card_path)
    shutil.copy2(run_dir / "source_record.json", source_path)
    approve_fact_card(
        tmp_path,
        card_path,
        approved_by="test-user",
        confirmation="APPROVE FACT CARD TEST-001",
    )

    config = json.loads((tmp_path / "config" / "channels_upload.json").read_text(encoding="utf-8"))
    metadata, qa, approval = _validate_run_for_upload(tmp_path, run_dir, config)
    assert metadata["title"] == "临界半径如何决定成核"
    assert qa["overall_status"] == "PASS"
    assert approval["approval_type"] == "local_hash_bound"
    assert not (tmp_path / "runtime" / "approvals" / f"{run_dir.name}.json").exists()
