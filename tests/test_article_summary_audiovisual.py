from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from wechat_video.media import (
    _frame_completion_filter,
    _speech_region_mask,
    assemble_final_video,
)
from wechat_video.article_summary import _audio_duration_breakdown, _narration_duration_budget
from wechat_video.article_summary import _narration_rhythm_report
from wechat_video.subtitles import (
    _han_character_count,
    _merge_short_caption_groups,
    _strip_trailing_caption_punctuation,
    write_chinese_subtitles,
)
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


def test_video_frame_completion_pads_tail_before_strict_frame_budget_trim() -> None:
    filters = _frame_completion_filter(2188)

    assert filters == "tpad=stop_mode=clone:stop=6,trim=end_frame=2188"
    assert filters.index("tpad=") < filters.index("trim=end_frame=")


def test_final_video_assembly_pads_short_scene_and_preserves_exact_muxed_frames(
    tmp_path: Path, monkeypatch,
) -> None:
    from wechat_video import media

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    scene_video = run_dir / "scene.mp4"
    audio_wav = run_dir / "final_mix.wav"
    captions_ass = run_dir / "captions.ass"
    output_mp4 = run_dir / "final.mp4"
    for path in (scene_video, audio_wav, captions_ass):
        path.write_bytes(b"fixture")

    observed_commands: list[tuple[str, list[str]]] = []
    frame_counts = {
        "scene.mp4": 2184,
        "video_only.mp4": 2188,
        "final.mp4": 2188,
    }

    def fake_probe(path: Path, *, count_frames: bool = False) -> dict:
        assert count_frames is True
        return {
            "streams": [{
                "codec_type": "video",
                "nb_read_frames": str(frame_counts[Path(path).name]),
            }]
        }

    def fake_ffmpeg_stage(args: list[str], **kwargs) -> subprocess.CompletedProcess:
        stage_name = str(kwargs["stage_name"])
        output = Path(str(args[-1]))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"x" * 2048)
        observed_commands.append((stage_name, list(args)))
        return subprocess.CompletedProcess(args, 0, "progress=continue", "")

    monkeypatch.setattr(media, "resolve_command", lambda name: name)
    monkeypatch.setattr(media, "_cfr_flag", lambda _exe: ["-fps_mode", "cfr"])
    monkeypatch.setattr(media, "tool_env", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(media, "probe_media", fake_probe)
    monkeypatch.setattr(
        media, "_loudnorm_measurement",
        lambda *_args, **_kwargs: {"measured_I": "-20", "measured_TP": "-2"},
    )
    monkeypatch.setattr(media, "_run_ffmpeg_stage", fake_ffmpeg_stage)

    report = assemble_final_video(
        scene_video,
        audio_wav,
        captions_ass,
        output_mp4,
        run_dir,
        2188,
        config={
            "preset_id": "test",
            "final_programme": {
                "integrated_lufs": -16.0,
                "true_peak_dbtp": -1.5,
                "codec": "aac",
                "bitrate_kbps": 192,
                "sample_rate": 44_100,
                "channels": 1,
            },
        },
    )

    assert report["video_frame_validation"] == {
        "scene_input_frames": 2184,
        "video_only_encoded_frames": 2188,
        "final_mux_frames": 2188,
        "expected_frames": 2188,
        "scene_tail_frames_padded": 4,
        "maximum_allowed_tail_padding_frames": 6,
        "status": "PASS",
        "policy": "clone_last_scene_frame_if_needed_then_strictly_trim_to_audio_frame_budget",
    }
    video_command = next(args for name, args in observed_commands if name == "video_encode")
    video_filter = video_command[video_command.index("-vf") + 1]
    assert "tpad=stop_mode=clone:stop=6,trim=end_frame=2188" in video_filter
    mux_command = next(args for name, args in observed_commands if name == "final_mux")
    assert "-shortest" not in mux_command


def test_assembly_rejects_scene_deficit_beyond_bounded_tail_padding(
    tmp_path: Path, monkeypatch,
) -> None:
    from wechat_video import media

    monkeypatch.setattr(media, "resolve_command", lambda name: name)
    monkeypatch.setattr(media, "_video_frame_count", lambda _path: 2181)

    with pytest.raises(media.ExternalProcessError, match="too short for bounded frame completion"):
        assemble_final_video(
            tmp_path / "scene.mp4",
            tmp_path / "audio.wav",
            tmp_path / "captions.ass",
            tmp_path / "final.mp4",
            tmp_path,
            2188,
            config={
                "final_programme": {"integrated_lufs": -16.0, "true_peak_dbtp": -1.5},
            },
        )


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
    assert "研究团队" in srt and "明显变化" in srt
    assert "明显变化。" not in srt
    assert "Style: ZH,Microsoft YaHei,50," in ass
    assert "&H00222222" in ass
    assert "BorderStyle" in ass
    assert "Dialogue: 2," in ass
    assert timeline["subtitle_alignment"]["outline"] == 0
    assert timeline["subtitle_alignment"]["shadow"] == 0



def test_short_cjk_caption_fragments_merge_and_terminal_punctuation_is_display_only() -> None:
    groups = [
        {"unit_id": "U01", "text": "所以，", "start_ms": 1000, "end_ms": 1250, "alignment_method": "edge_word_boundary"},
        {"unit_id": "U01", "text": "缺陷，", "start_ms": 1250, "end_ms": 1500, "alignment_method": "edge_word_boundary"},
        {"unit_id": "U01", "text": "可以固定位置。", "start_ms": 1500, "end_ms": 2200, "alignment_method": "edge_word_boundary"},
    ]

    merged = _merge_short_caption_groups(groups)

    assert len(merged) == 1
    assert merged[0]["text"] == "所以，缺陷，可以固定位置。"
    assert _han_character_count(merged[0]["text"]) >= 5
    assert _strip_trailing_caption_punctuation(merged[0]["text"]) == "所以，缺陷，可以固定位置"
    assert groups[0]["text"] == "所以，"


def test_narration_rhythm_report_counts_cjk_and_preserves_authored_pause_values() -> None:
    spoken = "科研团队通过系统实验验证关键机制及其适用边界" * 3 + "。"
    report = _narration_rhythm_report([{
        "unit_id": "U01",
        "spoken_text": spoken,
        "requested_pause_after_ms": 250,
        "pause_after_ms": 450,
    }])

    assert report["speech_units"][0]["spoken_cjk_characters"] == len(spoken.rstrip("。"))
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



def test_word_boundary_subtitles_restore_authored_punctuation_without_changing_timing(
    tmp_path: Path,
) -> None:
    original_boundaries = [
        {"text": "研究团队观", "start_ms": 0, "end_ms": 500},
        {"text": "察到关键界面", "start_ms": 550, "end_ms": 1200},
        {"text": "发生了明显变化", "start_ms": 1300, "end_ms": 2200},
    ]
    timeline = {
        "speech_units": [{
            "unit_id": "U01",
            "spoken_text": "研究团队，观察到关键界面发生了明显变化。",
            "start_ms": 1000,
            "end_ms": 4000,
            "subtitle_alignment_method": "edge_word_boundary",
            "word_boundaries": [dict(boundary) for boundary in original_boundaries],
        }]
    }
    layout = {
        "canvas": {"width": 1080, "height": 1920},
        "subtitle": {
            "max_line_chars_zh": 12,
            "cjk_font_size": 42,
            "zh_y_percent": 72.5,
            "margin_left": 75,
            "margin_right": 75,
        },
    }

    write_chinese_subtitles(
        timeline, tmp_path / "restored.srt", tmp_path / "restored.ass",
        layout, "Microsoft YaHei",
    )

    srt = (tmp_path / "restored.srt").read_text(encoding="utf-8-sig")
    assert "研究团队，观察到关键界面" in srt
    assert "明显变化" in srt
    assert "明显变化。" not in srt
    assert timeline["subtitle_cues"][0]["source_text"].endswith("。")
    assert timeline["speech_units"][0]["word_boundaries"] == original_boundaries


def test_one_minute_script_budget_is_checked_before_tts() -> None:
    summary = {
        "spoken_cjk_characters": 230,
        "cover_duration_ms": 1500,
        "outro_duration_ms": 900,
        "speech_units": [{"pause_after_ms": 450} for _ in range(7)],
    }
    tts_config = {
        "providers": {"edge_tts": {"rate": "+5%"}},
        "duration_policy": {
            "target_programme_seconds": 60,
            "minimum_programme_seconds": 58,
            "maximum_programme_seconds": 62,
            "target_cjk_characters": {"minimum": 222, "maximum": 235},
            "expected_cjk_characters_per_second_at_default_rate": 4.2,
            "rate_adjustment": {"reference_rate_percent": 5, "maximum_percent": 8},
        },
    }

    report = _narration_duration_budget(summary, tts_config)

    assert 58 <= report["estimated_programme_seconds"] <= 62
    assert report["estimated_pause_seconds"] == 2.7
    assert report["configured_edge_rate"] == "+5%"
    assert report["automatic_rate_adaptation"] is False

    summary["spoken_cjk_characters"] = 271
    with pytest.raises(Exception, match="calibrated one-minute planning range"):
        _narration_duration_budget(summary, tts_config)


def test_audio_duration_breakdown_separates_speech_cover_pauses_and_outro() -> None:
    timeline = {
        "audio_sample_rate": 1000,
        "segments": [
            {"kind": "cover", "start_sample": 0, "end_sample": 1500},
            {"kind": "speech", "start_sample": 1500, "end_sample": 9500},
            {"kind": "silence", "start_sample": 9500, "end_sample": 9950},
            {"kind": "outro", "start_sample": 9950, "end_sample": 10850},
        ],
        "speech_units": [
            {"unit_id": "U01", "sample_count": 8000},
        ],
    }

    report = _audio_duration_breakdown(timeline)

    assert report["speech_seconds"] == 8.0
    assert report["cover_seconds"] == 1.5
    assert report["pause_seconds"] == 0.45
    assert report["outro_seconds"] == 0.9
    assert report["unit_durations_seconds"] == {"U01": 8.0}
