from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Any

from .media import probe_media


def _stream(data: dict[str, Any], kind: str) -> dict[str, Any] | None:
    return next((x for x in data.get("streams", []) if x.get("codec_type") == kind), None)


def _fps(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    try:
        a, b = value.split("/", 1)
        return float(a) / float(b)
    except (ValueError, ZeroDivisionError):
        return None


def run_qa(
    final_mp4: Path,
    narration_wav: Path,
    timeline: dict[str, Any],
    subtitle_count: int,
    output_path: Path,
) -> dict[str, Any]:
    probe = probe_media(final_mp4, count_frames=True)
    video = _stream(probe, "video")
    audio = _stream(probe, "audio")
    if video is None or audio is None:
        raise RuntimeError("最终 MP4 必须同时包含视频流和音频流。")

    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "status": "PASS" if passed else "FAIL", "detail": detail})

    width = int(video.get("width", 0))
    height = int(video.get("height", 0))
    fps = _fps(video.get("avg_frame_rate"))
    pix_fmt = video.get("pix_fmt")
    sar = video.get("sample_aspect_ratio")
    frame_count = int(video.get("nb_read_frames") or 0)
    video_duration = float(probe["format"].get("duration", 0.0))
    expected_duration = float(timeline["total_duration_seconds"])
    audio_duration = float(audio.get("duration") or video_duration)
    duration_delta = abs(video_duration - expected_duration)

    check("portrait_resolution", width == 1080 and height == 1920, f"{width}x{height}")
    check("constant_30_fps", fps is not None and abs(fps - 30.0) < 0.01, f"avg_frame_rate={video.get('avg_frame_rate')}")
    check("yuv420p", pix_fmt == "yuv420p", f"pix_fmt={pix_fmt}")
    check("square_pixels", sar in {"1:1", "1/1"}, f"sample_aspect_ratio={sar}")
    check("audio_stream_present", audio is not None, f"codec={audio.get('codec_name')}")
    check(
        "timeline_duration_match",
        duration_delta <= 0.25,
        f"video={video_duration:.3f}s; timeline={expected_duration:.3f}s; delta={duration_delta:.3f}s",
    )
    check(
        "audio_video_duration_match",
        abs(video_duration - audio_duration) <= 0.35,
        f"video={video_duration:.3f}s; audio={audio_duration:.3f}s",
    )
    check("one_subtitle_cue_per_speech_unit", subtitle_count == len(timeline["speech_units"]), f"{subtitle_count} vs {len(timeline['speech_units'])}")
    check(
        "explicit_one_second_cover",
        timeline["cover"]["start_ms"] == 0 and timeline["cover"]["end_ms"] == 1000,
        str(timeline["cover"]),
    )
    check(
        "first_speech_after_cover",
        timeline["speech_units"][0]["start_ms"] >= 1000,
        f"first cue starts at {timeline['speech_units'][0]['start_ms']} ms",
    )
    check("frame_count_available", frame_count > 0, f"nb_read_frames={frame_count}")

    with wave.open(str(narration_wav), "rb") as wav:
        initial_samples = wav.readframes(wav.getframerate())
    check(
        "first_second_is_silence",
        not any(initial_samples),
        "The first 1000 ms contains silence; the cover has no narration.",
    )

    duration_warning = not (55.0 <= video_duration <= 65.0)
    if duration_warning:
        checks.append(
            {
                "check": "preferred_55_to_65_second_duration",
                "status": "WARN",
                "detail": f"Rendered duration is {video_duration:.2f}s; inspect measured TTS pacing and narration clarity.",
            }
        )
    else:
        check(
            "preferred_55_to_65_second_duration",
            True,
            f"{video_duration:.2f}s",
        )

    failures = [item for item in checks if item["status"] == "FAIL"]
    warnings = [item for item in checks if item["status"] == "WARN"]
    report = {
        "schema_version": 1,
        "overall_status": "FAIL" if failures else ("PASS_WITH_WARNINGS" if warnings else "PASS"),
        "final_mp4": str(final_mp4),
        "media_probe": probe,
        "video_summary": {
            "width": width,
            "height": height,
            "fps": fps,
            "pixel_format": pix_fmt,
            "sample_aspect_ratio": sar,
            "frame_count": frame_count,
            "duration_seconds": video_duration,
        },
        "audio_summary": {
            "codec": audio.get("codec_name"),
            "sample_rate": audio.get("sample_rate"),
            "channels": audio.get("channels"),
            "duration_seconds": audio_duration,
        },
        "checks": checks,
        "manual_review_required": [
            "Listen to every English speech unit and the pronunciation_review.wav.",
            "Check all scientific terms, equation labels, and the sign convention for Δg_v.",
            "Inspect the cover, subtitle safe band, and any text near WeChat interface areas.",
            "Check that narration and visual trigger events are synchronized.",
            "Review the pending Fact Card before treating the sample as scientifically approved.",
        ],
        "user_acceptance_pending": True,
    }
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if failures:
        failed = "; ".join(x["check"] + ": " + x["detail"] for x in failures)
        raise RuntimeError(f"最终 MP4 未通过强制 QA：{failed}")
    return report
