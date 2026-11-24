from __future__ import annotations

import json
import sys
import types
import wave
from pathlib import Path

import pytest

from wechat_video import tts_provider
from wechat_video.timeline import validate_audio_timeline


ROOT = Path(__file__).resolve().parents[1]


def test_article_summary_tts_defaults_to_user_selected_edge_voice() -> None:
    config = tts_provider.load_article_summary_tts_config(ROOT)

    assert config["default_provider"] == "edge_tts"
    assert config["providers"]["edge_tts"]["voice"] == "zh-CN-XiaoxiaoNeural"
    assert config["providers"]["edge_tts"]["rate"] == "+0%"
    assert config["fallback_provider"] is None
    assert config["policy"]["automatic_provider_fallback"] is False
    assert config["policy"]["network_retries"] == 0


def test_article_summary_tts_rejects_implicit_fallback(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    source = json.loads(
        (ROOT / "configs" / "article_summary_tts.json").read_text(encoding="utf-8")
    )
    source["fallback_provider"] = "melo_onnx"
    (config_dir / "article_summary_tts.json").write_text(
        json.dumps(source), encoding="utf-8"
    )

    with pytest.raises(tts_provider.ArticleSummaryTtsError, match="fallback_provider must remain null"):
        tts_provider.load_article_summary_tts_config(tmp_path)


def test_edge_tts_generates_normalized_pcm_and_records_real_voice_parameters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, str]] = []

    class FakeCommunicate:
        def __init__(self, text: str, **kwargs: str) -> None:
            self.text = text
            calls.append({"text": text, **kwargs})

        async def save(self, path: str, metadata_path: str | None = None) -> None:
            Path(path).write_bytes(b"x" * 2048)
            if metadata_path:
                Path(metadata_path).write_text(
                    json.dumps({
                        "type": "WordBoundary", "offset": 0,
                        "duration": 10_000_000, "text": self.text,
                    }) + "\n",
                    encoding="utf-8",
                )

    monkeypatch.setitem(
        sys.modules,
        "edge_tts",
        types.SimpleNamespace(Communicate=FakeCommunicate),
    )
    monkeypatch.setattr(tts_provider.importlib.metadata, "version", lambda _name: "7.3.1")

    def fake_ffmpeg(args, **kwargs):
        target = Path(args[-1])
        target.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(target), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(44100)
            output.writeframes(b"\x01\x00" * 44100)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(tts_provider, "run_checked", fake_ffmpeg)

    config = tts_provider.load_article_summary_tts_config(ROOT)
    units = [{"unit_id": "U01", "spoken_text": "反铁磁材料里的磁畴。"}]
    audio_dir = tmp_path / "audio"
    result = tts_provider.generate_article_summary_speech_units(
        ROOT, config, units, audio_dir, "fake-ffmpeg"
    )

    assert result["engine"] == "Edge-TTS"
    assert result["provider_id"] == "edge_tts"
    assert result["voice"] == "zh-CN-XiaoxiaoNeural"
    assert result["automatic_fallback_used"] is False
    assert result["fallback_provider"] is None
    assert len(result["speech_units"]) == 1
    unit = result["speech_units"][0]
    assert unit["sample_rate"] == 44100
    assert unit["channels"] == 1
    assert unit["sample_width_bytes"] == 2
    assert unit["frames"] == 44100
    assert unit["duration_seconds"] == pytest.approx(1.0)
    assert unit["source_text_sha256"]
    assert unit["subtitle_alignment_method"] == "edge_word_boundary"
    assert unit["word_boundary_status"] == "word_boundaries_verified"
    assert unit["word_boundaries"] == [{
        "text": "反铁磁材料里的磁畴。", "start_ms": 0, "end_ms": 1000,
    }]
    assert calls == [{
        "text": "反铁磁材料里的磁畴。",
        "voice": "zh-CN-XiaoxiaoNeural",
        "rate": "+0%",
        "volume": "+0%",
        "pitch": "+0Hz",
        "boundary": "WordBoundary",
    }]


def test_edge_tts_failure_is_reported_without_retry_or_melo_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}

    class FailingCommunicate:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def save(self, _path: str, _metadata_path: str | None = None) -> None:
            calls["count"] += 1
            raise ConnectionError("service unavailable")

    monkeypatch.setitem(
        sys.modules,
        "edge_tts",
        types.SimpleNamespace(Communicate=FailingCommunicate),
    )
    monkeypatch.setattr(tts_provider.importlib.metadata, "version", lambda _name: "7.3.1")

    config = tts_provider.load_article_summary_tts_config(ROOT)
    with pytest.raises(tts_provider.ArticleSummaryTtsError, match="No retry or fallback was attempted"):
        tts_provider.generate_article_summary_speech_units(
            ROOT,
            config,
            [{"unit_id": "U01", "spoken_text": "测试句子。"}],
            tmp_path / "audio",
            "fake-ffmpeg",
        )

    assert calls["count"] == 1


def _sample_timeline() -> dict:
    segments = [
        {
            "segment_id": "scene_00_cover", "kind": "cover",
            "start_sample": 0, "end_sample": 10, "start_ms": 0, "end_ms": 1000,
        },
        {
            "segment_id": "U01", "kind": "speech",
            "start_sample": 10, "end_sample": 30, "start_ms": 1000, "end_ms": 3000,
        },
        {
            "segment_id": "pause_after_U01", "kind": "silence",
            "start_sample": 30, "end_sample": 35, "start_ms": 3000, "end_ms": 3500,
        },
        {
            "segment_id": "U02", "kind": "speech",
            "start_sample": 35, "end_sample": 45, "start_ms": 3500, "end_ms": 4500,
        },
    ]
    cues = [
        {
            "unit_id": "U01", "start_sample": 10, "end_sample": 30,
            "start_ms": 1000, "end_ms": 3000, "sample_count": 20,
        },
        {
            "unit_id": "U02", "start_sample": 35, "end_sample": 45,
            "start_ms": 3500, "end_ms": 4500, "sample_count": 10,
        },
    ]
    return {
        "audio_sample_rate": 10,
        "total_sample_count": 45,
        "total_duration_seconds": 4.5,
        "segments": segments,
        "speech_units": cues,
    }


def test_audio_timeline_requires_contiguous_sample_clock_and_matching_speech_cues() -> None:
    timeline = _sample_timeline()

    report = validate_audio_timeline(timeline)

    assert report["valid"] is True
    assert report["authority"] == "measured_pcm_wav_sample_counts"
    assert report["speech_unit_count"] == 2
    assert report["total_sample_count"] == 45


def test_edge_word_boundary_metadata_rejects_text_coverage_mismatch(tmp_path: Path) -> None:
    metadata = tmp_path / "U01.jsonl"
    metadata.write_text(
        json.dumps({"type": "WordBoundary", "offset": 0, "duration": 100000, "text": "错字"}) + "\n",
        encoding="utf-8",
    )
    boundaries, status = tts_provider._read_word_boundary_metadata(
        metadata, "正确原文。", 1.0
    )
    assert boundaries == []
    assert status == "text_coverage_mismatch"


def test_audio_timeline_rejects_cue_that_runs_ahead_of_its_visual_segment() -> None:
    timeline = _sample_timeline()
    timeline["speech_units"][1]["start_sample"] -= 5
    timeline["speech_units"][1]["start_ms"] -= 500

    with pytest.raises(ValueError, match="does not match its audio segment"):
        validate_audio_timeline(timeline)



def test_edge_word_boundary_metadata_accepts_punctuation_omission_and_preserves_times(
    tmp_path: Path,
) -> None:
    metadata = tmp_path / "U01.jsonl"
    events = [
        {"type": "WordBoundary", "offset": 1_000_000, "duration": 4_000_000, "text": "反铁"},
        {"type": "WordBoundary", "offset": 5_000_000, "duration": 4_000_000, "text": "磁材料"},
        {"type": "WordBoundary", "offset": 9_000_000, "duration": 5_000_000, "text": "里的"},
        {"type": "WordBoundary", "offset": 14_000_000, "duration": 6_000_000, "text": "磁畴"},
    ]
    metadata.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
        encoding="utf-8",
    )

    boundaries, status = tts_provider._read_word_boundary_metadata(
        metadata, "反铁磁材料，里的磁畴。", 3.0
    )

    assert status == "word_boundaries_verified"
    assert boundaries == [
        {"text": "反铁", "start_ms": 100, "end_ms": 500},
        {"text": "磁材料", "start_ms": 500, "end_ms": 900},
        {"text": "里的", "start_ms": 900, "end_ms": 1400},
        {"text": "磁畴", "start_ms": 1400, "end_ms": 2000},
    ]


def test_audio_timeline_reports_word_boundary_alignment_and_explicit_fallbacks() -> None:
    timeline = _sample_timeline()
    timeline["speech_units"][0].update({
        "spoken_text": "反铁磁材料，里的磁畴。",
        "subtitle_alignment_method": "edge_word_boundary",
        "word_boundary_status": "word_boundaries_verified",
        "word_boundaries": [
            {"text": "反铁", "start_ms": 0, "end_ms": 500},
            {"text": "磁材料", "start_ms": 500, "end_ms": 1300},
            {"text": "里的磁畴", "start_ms": 1300, "end_ms": 2000},
        ],
    })
    timeline["speech_units"][1]["word_boundary_status"] = "metadata_missing"

    report = validate_audio_timeline(timeline)

    assert report["word_boundary_aligned_unit_count"] == 1
    assert report["word_boundary_fallback_unit_count"] == 1
    assert report["word_boundary_fallback_units"] == [
        {"unit_id": "U02", "status": "metadata_missing"}
    ]
