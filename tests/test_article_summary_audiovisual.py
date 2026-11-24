from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from wechat_video.media import _speech_region_mask
from wechat_video.article_summary import _narration_rhythm_report
from wechat_video.subtitles import write_chinese_subtitles
from wechat_video.timeline import (
    _fade_pcm_edges,
    build_audio_timeline,
    validate_audio_timeline,
)


def _write_voice(path: Path, seconds: float = 1.0) -> None:
    sample_rate = 44_100
    frames = int(sample_rate * seconds)
    # A deterministic speech-like signal, not a fixture audio asset.
    t = np.arange(frames, dtype=np.float64) / sample_rate
    signal = (np.sin(2 * np.pi * 180 * t) * 0.1 * 32767).astype("<i2")
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(signal.tobytes())


def _unit(unit_id: str, word_boundaries: list[dict] | None = None) -> dict:
    return {
        "unit_id": unit_id,
        "raw_text": "原始文本。",
        "spoken_text": "原始文本。",
        "display_text": "原始文本。",
        "claim_ids": ["C1"],
        "visual_trigger_ids": [f"B_{unit_id}"],
        "pause_after_ms": 500,
        "word_boundaries": word_boundaries or [],
        "subtitle_alignment_method": "edge_word_boundary" if word_boundaries else "speech_unit_envelope",
        "word_boundary_status": "word_boundaries_verified" if word_boundaries else "unavailable",
    }


def test_timeline_has_a_measured_outro_and_a_single_sample_clock(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    _write_voice(audio_dir / "U01.wav")
    _write_voice(audio_dir / "U02.wav")
    timeline = build_audio_timeline(
        [_unit("U01"), _unit("U02")],
        audio_dir=audio_dir,
        output_wav=tmp_path / "narration.wav",
        ffprobe_records={"U01": {}, "U02": {}},
        cover_duration_ms=1500,
        outro_duration_ms=900,
    )

    report = validate_audio_timeline(timeline)

    assert report["valid"] is True
    assert timeline["segments"][-1]["segment_id"] == "scene_99_outro"
    assert timeline["outro_duration_ms"] == 900
    assert timeline["segments"][-1]["duration_ms"] == 900
    assert timeline["total_sample_count"] == sum(
        int(segment["end_sample"]) - int(segment["start_sample"])
        for segment in timeline["segments"]
    )
    with wave.open(str(tmp_path / "narration.wav"), "rb") as reader:
        assert reader.getnframes() == timeline["total_sample_count"]


def test_speech_edge_fade_preserves_initial_transient_better_than_symmetric_fade() -> None:
    samples = np.full(100, 10_000, dtype="<i2")
    processed = np.frombuffer(_fade_pcm_edges(samples.tobytes(), 1000), dtype="<i2")

    assert len(processed) == len(samples)
    assert processed[0] == 0
    assert processed[1] == 10_000
    assert processed[2] == 10_000
    assert processed[-1] == 0
    assert processed[-11] == 10_000


def test_music_is_audible_on_cover_and_outro_but_not_inter_unit_gaps() -> None:
    timeline = {
        "segments": [
            {"kind": "cover", "start_sample": 0, "end_sample": 100},
            {"kind": "speech", "start_sample": 100, "end_sample": 200},
            {"kind": "silence", "start_sample": 200, "end_sample": 300},
            {"kind": "speech", "start_sample": 300, "end_sample": 400},
            {"kind": "outro", "start_sample": 400, "end_sample": 500},
        ]
    }
    mask = _speech_region_mask(timeline, 500, 1000, fade_ms=10)

    assert mask[20] > 0
    assert mask[150] > 0
    assert np.all(mask[200:300] == 0)
    assert mask[450] > 0
    assert mask[-1] == 0


def test_word_boundary_subtitles_are_phrase_timed_and_have_no_filled_black_box(tmp_path: Path) -> None:
    timeline = {
        "speech_units": [{
            "unit_id": "U01",
            "spoken_text": "研究团队观察到关键界面发生了明显变化。",
            "start_ms": 1000,
            "end_ms": 4000,
            "subtitle_alignment_method": "edge_word_boundary",
            "word_boundaries": [
                {"text": "研究团队", "start_ms": 0, "end_ms": 350},
                {"text": "观察到", "start_ms": 360, "end_ms": 680},
                {"text": "关键界面", "start_ms": 900, "end_ms": 1250},
                {"text": "发生了", "start_ms": 1300, "end_ms": 1600},
                {"text": "明显变化。", "start_ms": 1700, "end_ms": 2200},
            ],
        }]
    }
    layout = {
        "canvas": {"width": 1080, "height": 1920},
        "subtitle": {
            "max_line_chars_zh": 8,
            "cjk_font_size": 42,
            "zh_y_percent": 72.5,
            "margin_left": 75,
            "margin_right": 75,
        },
    }

    count = write_chinese_subtitles(
        timeline, tmp_path / "captions.srt", tmp_path / "captions.ass",
        layout, "Microsoft YaHei",
    )
    ass = (tmp_path / "captions.ass").read_text(encoding="utf-8-sig")
    srt = (tmp_path / "captions.srt").read_text(encoding="utf-8-sig")

    assert count >= 2
    assert len(timeline["subtitle_cues"]) == count
    assert all(item["alignment_method"] == "edge_word_boundary" for item in timeline["subtitle_cues"])
    assert all(1000 <= item["start_ms"] < item["end_ms"] <= 4000 for item in timeline["subtitle_cues"])
    assert "研究团队" in srt and "明显变化。" in srt
    assert "Style: ZH" in ass
    assert ",1,2,1,2," in ass or ",1,2,1," in ass
    assert "BorderStyle" in ass
    assert "Dialogue: 2," in ass



def test_narration_rhythm_report_counts_cjk_and_preserves_authored_pause_values() -> None:
    spoken = "科研团队通过系统实验验证关键机制及其适用边界" * 3 + "。"
    report = _narration_rhythm_report([{
        "unit_id": "U01",
        "spoken_text": spoken,
        "requested_pause_after_ms": 250,
        "pause_after_ms": 450,
    }])

    assert report["speech_units"][0]["spoken_cjk_characters"] == len(spoken)
    assert report["speech_units"][0]["requested_pause_after_ms"] == 250
    assert report["speech_units"][0]["effective_pause_after_ms"] == 450
    assert "long_speech_unit" in report["speech_units"][0]["warnings"]
    assert report["policy"] == "diagnostic_only_no_scientific_text_is_rewritten"


def test_unavailable_word_boundaries_fall_back_to_complete_unit_caption(tmp_path: Path) -> None:
    timeline = {
        "speech_units": [{
            "unit_id": "U01",
            "spoken_text": "保留完整语音单元。",
            "start_ms": 1000,
            "end_ms": 2500,
            "subtitle_alignment_method": "speech_unit_envelope",
            "word_boundaries": [],
        }]
    }
    layout = {
        "canvas": {"width": 1080, "height": 1920},
        "subtitle": {"max_line_chars_zh": 12, "cjk_font_size": 42, "zh_y_percent": 72.5},
    }

    count = write_chinese_subtitles(
        timeline, tmp_path / "fallback.srt", tmp_path / "fallback.ass",
        layout, "Microsoft YaHei",
    )

    assert count == 1
    assert timeline["subtitle_cues"][0]["alignment_method"] == "speech_unit_envelope"
    assert "保留完整语音单元。" in (tmp_path / "fallback.srt").read_text(encoding="utf-8-sig")
