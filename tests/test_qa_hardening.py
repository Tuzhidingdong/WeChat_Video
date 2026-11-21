from __future__ import annotations

import json
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from wechat_video import qa


@pytest.fixture
def timeline() -> dict:
    sample_rate = 44_100
    total_samples = 60_800 * sample_rate // 1000
    return {
        "fps": 30,
        "audio_sample_rate": sample_rate,
        "total_sample_count": total_samples,
        "total_duration_seconds": total_samples / sample_rate,
        "total_duration_ms": 60_800,
        "cover": {"start_ms": 0, "end_ms": 1000},
        "speech_units": [{"unit_id": "u1", "start_ms": 1000, "end_ms": 60_800}],
    }


@pytest.fixture
def narration(tmp_path: Path) -> Path:
    path = tmp_path / "narration.wav"
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(44_100)
        writer.writeframes(b"\x00\x00" * 44_100)
    return path


def probe(*, frames: int = 1824, r_fps: str = "30/1", avg_fps: str = "30/1", audio_duration: str | None = "60.8", sample_rate: str = "44100", channels: int = 1) -> dict:
    audio = {
        "codec_type": "audio",
        "codec_name": "aac",
        "sample_rate": sample_rate,
        "channels": channels,
    }
    if audio_duration is not None:
        audio["duration"] = audio_duration
    return {
        "streams": [
            {
                "codec_type": "video",
                "width": 1080,
                "height": 1920,
                "avg_frame_rate": avg_fps,
                "r_frame_rate": r_fps,
                "pix_fmt": "yuv420p",
                "sample_aspect_ratio": "1:1",
                "nb_read_frames": str(frames),
            },
            audio,
        ],
        "format": {"duration": "60.8"},
    }


def install_probe_and_loudness(monkeypatch: pytest.MonkeyPatch, data: dict, *, integrated: float = -16.2, peak: float = -1.6) -> None:
    monkeypatch.setattr(qa, "probe_media", lambda *_args, **_kwargs: data)
    monkeypatch.setattr(qa, "resolve_command", lambda name: name)
    monkeypatch.setattr(qa, "tool_env", lambda: {})
    payload = {
        "input_i": str(integrated),
        "input_tp": str(peak),
        "input_lra": "3.2",
    }
    monkeypatch.setattr(
        qa,
        "run_checked",
        lambda *_args, **_kwargs: SimpleNamespace(stderr=json.dumps(payload), stdout=""),
    )


def run(tmp_path: Path, narration: Path, timeline: dict) -> dict:
    report_path = tmp_path / "qa_report.json"
    report = qa.run_qa(Path("final.mp4"), narration, timeline, 1, report_path)
    assert report_path.is_file()
    return report


def status(report: dict, name: str) -> str:
    return next(item["status"] for item in report["checks"] if item["check"] == name)


def test_qa_passes_exact_global_frame_budget_and_encoded_audio_targets(tmp_path, narration, timeline, monkeypatch):
    install_probe_and_loudness(monkeypatch, probe())
    report = run(tmp_path, narration, timeline)
    assert report["overall_status"] == "PASS"
    assert report["video_summary"]["frame_count"] == 1824
    assert report["video_summary"]["expected_frame_count"] == 1824
    assert status(report, "frame_count_matches_global_timeline") == "PASS"
    assert status(report, "final_aac_integrated_loudness") == "PASS"
    assert status(report, "final_aac_true_peak_ceiling") == "PASS"
    assert report["audio_summary"]["loudness_after_aac_encoding"]["true_peak_dbtp"] == -1.6


def test_qa_fails_if_rendered_frame_count_differs_from_timeline(tmp_path, narration, timeline, monkeypatch):
    install_probe_and_loudness(monkeypatch, probe(frames=1823))
    with pytest.raises(RuntimeError, match="frame_count_matches_global_timeline"):
        run(tmp_path, narration, timeline)
    report = json.loads((tmp_path / "qa_report.json").read_text(encoding="utf-8"))
    assert status(report, "frame_count_matches_global_timeline") == "FAIL"
    assert report["video_summary"]["expected_frame_count"] == 1824


def test_qa_rejects_non_cfr_metadata_even_when_average_fps_matches(tmp_path, narration, timeline, monkeypatch):
    install_probe_and_loudness(monkeypatch, probe(r_fps="60/1", avg_fps="30/1"))
    with pytest.raises(RuntimeError, match="constant_30_fps"):
        run(tmp_path, narration, timeline)


@pytest.mark.parametrize(
    "kwargs,check_name",
    [
        ({"sample_rate": "48000"}, "audio_sample_rate_44100"),
        ({"channels": 2}, "audio_mono"),
        ({"audio_duration": None}, "audio_stream_duration_available"),
    ],
)
def test_qa_rejects_invalid_or_missing_encoded_audio_metadata(tmp_path, narration, timeline, monkeypatch, kwargs, check_name):
    install_probe_and_loudness(monkeypatch, probe(**kwargs))
    with pytest.raises(RuntimeError, match=check_name):
        run(tmp_path, narration, timeline)
    report = json.loads((tmp_path / "qa_report.json").read_text(encoding="utf-8"))
    assert status(report, check_name) == "FAIL"


def test_qa_rejects_final_aac_true_peak_above_ceiling(tmp_path, narration, timeline, monkeypatch):
    install_probe_and_loudness(monkeypatch, probe(), integrated=-16.0, peak=-0.8)
    with pytest.raises(RuntimeError, match="final_aac_true_peak_ceiling"):
        run(tmp_path, narration, timeline)


def test_qa_rejects_final_aac_integrated_loudness_outside_tolerance(tmp_path, narration, timeline, monkeypatch):
    install_probe_and_loudness(monkeypatch, probe(), integrated=-18.0, peak=-1.6)
    with pytest.raises(RuntimeError, match="final_aac_integrated_loudness"):
        run(tmp_path, narration, timeline)


def test_expected_frame_count_uses_exact_sample_boundary_rounding():
    assert qa._expected_frame_count(
        {"total_sample_count": 44_100, "audio_sample_rate": 44_100, "fps": 30}
    ) == 30
    # A half-frame tie follows Python's documented ties-to-even rounding rule.
    assert qa._expected_frame_count(
        {"total_sample_count": 735, "audio_sample_rate": 44_100, "fps": 30}
    ) == 0
    assert qa._expected_frame_count(
        {"total_sample_count": 2205, "audio_sample_rate": 44_100, "fps": 30}
    ) == 2


def test_stream_duration_can_be_derived_from_timestamp_and_time_base():
    assert qa._stream_duration_seconds({"duration_ts": "2681280", "time_base": "1/44100"}) == pytest.approx(60.8)
