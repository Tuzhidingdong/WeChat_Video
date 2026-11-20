from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

from wechat_video.fact_card import FactCardError, load_fact_card
from wechat_video.timeline import build_audio_timeline


def _write_wav(path: Path, sample_rate: int, frames: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(b"\x00\x01" * frames)


def test_pending_fact_card_is_blocked_without_review_override(tmp_path: Path) -> None:
    card = {
        "approval_status": "DRAFT_PENDING_USER_REVIEW",
        "claims": [
            {
                "claim_id": "C1",
                "statement": "A test claim.",
                "source_ids": ["S1"],
                "evidence_status": "FULL_TEXT_LOCATED",
                "caveats": [],
            }
        ],
    }
    source_doc = {"sources": [{"source_id": "S1"}]}
    card_path = tmp_path / "card.json"
    source_path = tmp_path / "sources.json"
    card_path.write_text(json.dumps(card), encoding="utf-8")
    source_path.write_text(json.dumps(source_doc), encoding="utf-8")

    with pytest.raises(FactCardError, match="尚未获人工批准"):
        load_fact_card(card_path, source_path, allow_pending_review=False)

    loaded, _, pending = load_fact_card(
        card_path, source_path, allow_pending_review=True
    )
    assert loaded["approval_status"] == "DRAFT_PENDING_USER_REVIEW"
    assert pending is True


def test_global_timeline_has_explicit_cover_and_measured_audio(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    _write_wav(audio_dir / "U01.wav", sample_rate=44_100, frames=44_100)
    _write_wav(audio_dir / "U02.wav", sample_rate=44_100, frames=88_200)
    units = [
        {
            "unit_id": "U01",
            "raw_text": "一",
            "display_text": "一",
            "spoken_text": "一",
            "claim_ids": ["C1"],
            "visual_trigger_ids": ["A"],
        },
        {
            "unit_id": "U02",
            "raw_text": "二",
            "display_text": "二",
            "spoken_text": "二",
            "claim_ids": ["C1"],
            "visual_trigger_ids": ["B"],
        },
    ]
    timeline = build_audio_timeline(
        units,
        audio_dir=audio_dir,
        output_wav=tmp_path / "narration.wav",
        ffprobe_records={"U01": {"streams": []}, "U02": {"streams": []}},
    )

    assert timeline["cover"]["start_ms"] == 0
    assert timeline["cover"]["end_ms"] == 1000
    assert timeline["speech_units"][0]["start_sample"] == 44_100
    assert timeline["speech_units"][0]["start_ms"] == 1000
    assert timeline["speech_units"][0]["end_ms"] == 2000
    assert timeline["speech_units"][1]["start_ms"] == 2280
    assert timeline["speech_units"][1]["sample_count"] == 88_200
    assert timeline["total_duration_ms"] == 4280


def test_timeline_rejects_mixed_sample_rates(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    _write_wav(audio_dir / "U01.wav", sample_rate=44_100, frames=44_100)
    _write_wav(audio_dir / "U02.wav", sample_rate=22_050, frames=22_050)
    units = [
        {
            "unit_id": "U01", "raw_text": "1", "display_text": "1",
            "spoken_text": "1", "claim_ids": ["C1"], "visual_trigger_ids": ["A"],
        },
        {
            "unit_id": "U02", "raw_text": "2", "display_text": "2",
            "spoken_text": "2", "claim_ids": ["C1"], "visual_trigger_ids": ["B"],
        },
    ]
    with pytest.raises(ValueError, match="采样率不一致"):
        build_audio_timeline(
            units,
            audio_dir=audio_dir,
            output_wav=tmp_path / "narration.wav",
            ffprobe_records={"U01": {}, "U02": {}},
        )
