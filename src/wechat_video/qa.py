from __future__ import annotations

import json
import math
import os
import re
import wave
from fractions import Fraction
from pathlib import Path
from typing import Any

from .master_config import voice_eq_filter_chain
from .media import probe_media
from .process import run_checked
from .tooling import resolve_command, tool_env


TARGET_INTEGRATED_LOUDNESS_LUFS = -16.0
TARGET_TRUE_PEAK_DBTP = -1.5
# Small allowance for AAC encoding and measurement variation around the requested target.
INTEGRATED_LOUDNESS_TOLERANCE_LU = 1.0
TRUE_PEAK_TOLERANCE_DB = 0.3


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


def _stream_duration_seconds(stream: dict[str, Any]) -> float | None:
    raw_duration = stream.get("duration")
    if raw_duration not in (None, "", "N/A"):
        try:
            value = float(raw_duration)
        except (TypeError, ValueError):
            value = math.nan
        if math.isfinite(value) and value >= 0:
            return value

    duration_ts = stream.get("duration_ts")
    time_base = stream.get("time_base")
    if duration_ts is None or not time_base:
        return None
    try:
        value = Fraction(str(duration_ts)) * Fraction(str(time_base))
    except (ValueError, ZeroDivisionError):
        return None
    seconds = float(value)
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _expected_frame_count(timeline: dict[str, Any]) -> int:
    """Quantize the global audio end boundary to the requested video frame rate."""
    try:
        samples = int(timeline["total_sample_count"])
        sample_rate = int(timeline["audio_sample_rate"])
        fps = Fraction(str(timeline["fps"]))
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError(
            "Timeline must include positive total_sample_count, audio_sample_rate, and fps."
        ) from exc
    if samples <= 0 or sample_rate <= 0 or fps <= 0:
        raise ValueError(
            "Timeline frame-budget inputs must be positive: "
            f"samples={samples}, sample_rate={sample_rate}, fps={fps}."
        )
    # Fraction + round preserves Python's documented nearest/ties-to-even rule without
    # introducing an intermediate rounded millisecond duration.
    return round(Fraction(samples) * fps / sample_rate)


def _measure_final_audio_loudness(final_mp4: Path) -> dict[str, float]:
    """Measure the encoded AAC stream, not only the pre-encode narration WAV."""
    null_target = "NUL" if os.name == "nt" else "/dev/null"
    result = run_checked(
        [
            resolve_command("ffmpeg"), "-hide_banner", "-nostats", "-i", str(final_mp4),
            "-map", "0:a:0", "-vn",
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
            "-f", "null", null_target,
        ],
        cwd=final_mp4.parent,
        timeout_seconds=180,
        env=tool_env(),
    )
    output = (result.stderr or "") + "\n" + (result.stdout or "")
    matches = re.findall(r"\{\s*\"input_i\"[\s\S]*?\}", output)
    if not matches:
        raise RuntimeError("FFmpeg 未返回最终 AAC 音频的 loudnorm 测量 JSON。")
    try:
        payload = json.loads(matches[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("无法解析最终 AAC 音频的 loudnorm 测量结果。") from exc

    fields = {
        "integrated_loudness_lufs": "input_i",
        "true_peak_dbtp": "input_tp",
    }
    values: dict[str, float] = {}
    for target, source in fields.items():
        try:
            value = float(payload[source])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"最终 AAC loudnorm 测量缺少有效字段 {source}。") from exc
        if not math.isfinite(value):
            raise RuntimeError(f"最终 AAC loudnorm 测量字段 {source} 非有限值：{value}。")
        values[target] = value

    try:
        lra = float(payload.get("input_lra", "nan"))
    except (TypeError, ValueError):
        lra = math.nan
    if math.isfinite(lra):
        values["loudness_range_lu"] = lra
    return values


def state_threshold(theme_master: dict[str, Any]) -> float:
    return float(theme_master.get("state_curve_motion", {}).get("threshold_x", 1.0))


def run_qa(
    final_mp4: Path,
    narration_wav: Path,
    timeline: dict[str, Any],
    subtitle_count: int,
    output_path: Path,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = context or {}
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
    target_fps = float(timeline.get("fps", 0) or 0)
    avg_fps = _fps(video.get("avg_frame_rate"))
    nominal_fps = _fps(video.get("r_frame_rate"))
    pix_fmt = video.get("pix_fmt")
    sar = video.get("sample_aspect_ratio")
    try:
        frame_count = int(video.get("nb_read_frames") or 0)
    except (TypeError, ValueError):
        frame_count = 0

    format_duration = probe.get("format", {}).get("duration")
    try:
        video_duration = float(format_duration)
    except (TypeError, ValueError):
        video_duration = _stream_duration_seconds(video)
    if video_duration is None or not math.isfinite(video_duration):
        video_duration = 0.0

    audio_duration = _stream_duration_seconds(audio)
    expected_duration = float(timeline.get("total_duration_seconds", 0.0) or 0.0)
    duration_delta = abs(video_duration - expected_duration)

    check("portrait_resolution", width == 1080 and height == 1920, f"{width}x{height}")
    cfr_ok = (
        target_fps > 0
        and avg_fps is not None
        and nominal_fps is not None
        and abs(avg_fps - target_fps) < 0.01
        and abs(nominal_fps - target_fps) < 0.01
    )
    check(
        "constant_30_fps",
        cfr_ok,
        f"target={target_fps:g}; avg_frame_rate={video.get('avg_frame_rate')}; "
        f"r_frame_rate={video.get('r_frame_rate')}",
    )
    check("yuv420p", pix_fmt == "yuv420p", f"pix_fmt={pix_fmt}")
    check("square_pixels", sar in {"1:1", "1/1"}, f"sample_aspect_ratio={sar}")
    check("audio_stream_present", audio is not None, f"codec={audio.get('codec_name')}")
    check(
        "audio_sample_rate_44100",
        str(audio.get("sample_rate", "")) == "44100",
        f"sample_rate={audio.get('sample_rate')}",
    )
    check(
        "audio_mono",
        int(audio.get("channels", 0) or 0) == 1,
        f"channels={audio.get('channels')}",
    )
    check("video_duration_available", video_duration > 0, f"video_duration={video_duration}")
    check(
        "timeline_duration_match",
        duration_delta <= 0.25,
        f"video={video_duration:.3f}s; timeline={expected_duration:.3f}s; delta={duration_delta:.3f}s",
    )
    check(
        "audio_stream_duration_available",
        audio_duration is not None and audio_duration > 0,
        f"audio_stream_duration={audio_duration}",
    )
    check(
        "audio_video_duration_match",
        audio_duration is not None and abs(video_duration - audio_duration) <= 0.35,
        f"video={video_duration:.3f}s; audio={audio_duration if audio_duration is not None else 'unavailable'}",
    )
    check(
        "one_subtitle_cue_per_speech_unit",
        subtitle_count == len(timeline["speech_units"]),
        f"{subtitle_count} vs {len(timeline['speech_units'])}",
    )
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

    try:
        expected_frames = _expected_frame_count(timeline)
        check(
            "frame_count_matches_global_timeline",
            frame_count == expected_frames,
            f"actual={frame_count}; expected={expected_frames}; "
            f"samples={timeline['total_sample_count']} at {timeline['audio_sample_rate']}Hz; "
            f"fps={timeline['fps']}",
        )
    except (KeyError, TypeError, ValueError) as exc:
        expected_frames = None
        check("frame_count_matches_global_timeline", False, str(exc))

    with wave.open(str(narration_wav), "rb") as wav:
        initial_samples = wav.readframes(wav.getframerate())
    check(
        "first_second_is_silence",
        not any(initial_samples),
        "The first 1000 ms contains silence; the cover has no narration.",
    )

    try:
        final_audio_loudness = _measure_final_audio_loudness(final_mp4)
        integrated = final_audio_loudness["integrated_loudness_lufs"]
        true_peak = final_audio_loudness["true_peak_dbtp"]
        check(
            "final_aac_integrated_loudness",
            abs(integrated - TARGET_INTEGRATED_LOUDNESS_LUFS) <= INTEGRATED_LOUDNESS_TOLERANCE_LU,
            f"measured={integrated:.2f} LUFS; target={TARGET_INTEGRATED_LOUDNESS_LUFS:.1f} "
            f"±{INTEGRATED_LOUDNESS_TOLERANCE_LU:.1f} LU",
        )
        check(
            "final_aac_true_peak_ceiling",
            true_peak <= TARGET_TRUE_PEAK_DBTP + TRUE_PEAK_TOLERANCE_DB,
            f"measured={true_peak:.2f} dBTP; ceiling={TARGET_TRUE_PEAK_DBTP + TRUE_PEAK_TOLERANCE_DB:.1f} dBTP",
        )
        loudness_error = None
    except Exception as exc:
        final_audio_loudness = None
        loudness_error = str(exc)
        check("final_aac_loudness_measurement", False, loudness_error)

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
        check("preferred_55_to_65_second_duration", True, f"{video_duration:.2f}s")

    if context:
        audio_manifest = context.get("audio_manifest", {})
        engine = str(audio_manifest.get("engine", ""))
        check(
            "personal_voice_engine_truth",
            "OpenVoice" in engine and "sherpa" not in engine.lower(),
            f"audio_manifest.engine={engine}",
        )
        check(
            "personal_voice_profile_recorded",
            bool(audio_manifest.get("voice_profile_fingerprint")),
            f"profile={audio_manifest.get('voice_profile')}",
        )
        cues = timeline["speech_units"]
        check(
            "bilingual_subtitle_cues",
            all(str(cue.get("display_text_zh", "")).strip() for cue in cues),
            f"{sum(bool(str(c.get('display_text_zh', '')).strip()) for c in cues)}/{len(cues)}",
        )
        environment = context.get("environment", {})
        check(
            "cjk_glyph_coverage_verified",
            bool(environment.get("cjk_font", {}).get("verified_codepoints")),
            str(environment.get("cjk_font", {}).get("family")),
        )
        pauses = [s for s in timeline.get("segments", []) if s.get("kind") == "silence"]
        long_pauses = [s for s in pauses if s.get("duration_ms", 0) >= 500]
        check(
            "comprehension_pauses_present",
            len(long_pauses) >= 2,
            f"{len(long_pauses)} configured pauses of 500ms or more",
        )
        sfx_events = timeline.get("sfx_events", [])
        total_samples = int(timeline["total_sample_count"])
        check(
            "sfx_events_within_global_timeline",
            all(0 <= int(e["start_sample"]) < int(e["end_sample"]) <= total_samples for e in sfx_events),
            f"{len(sfx_events)} events",
        )
        motion = context.get("motion_manifest", {})
        event_blocks = {e.get("rhythm_block_id") for e in motion.get("events", [])}
        expected_blocks = {"HOOK", "CONFLICT", "MECHANISM", "APPLICATION", "TAKEAWAY"}
        check(
            "motion_event_in_every_rhythm_block",
            expected_blocks.issubset(event_blocks),
            f"blocks={sorted(str(b) for b in event_blocks if b)}",
        )

        audio_master = context.get("audio_master", {})
        theme_master = context.get("theme_master", {})
        mix_report = context.get("mix_report", {})
        check(
            "series_master_configs_loaded",
            bool(audio_master.get("preset_id")) and bool(theme_master.get("theme_id")),
            f"theme={theme_master.get('theme_id')}; preset={audio_master.get('preset_id')}",
        )
        expected_eq = voice_eq_filter_chain(audio_master) if audio_master else ""
        recorded_eq = str(audio_manifest.get("cleanup_steps", {}).get("clarity_eq", ""))
        check(
            "effective_voice_eq_matches_config",
            bool(expected_eq) and recorded_eq == expected_eq,
            f"recorded={recorded_eq}",
        )
        denoise_default = bool(audio_master.get("denoise", {}).get("enabled", False))
        recorded_cleanup = str(
            audio_manifest.get("cleanup_steps", {}).get("post_conversion", "")
        )
        check(
            "post_conversion_denoise_matches_default_profile",
            (not denoise_default and recorded_cleanup.startswith("none"))
            or (denoise_default and bool(recorded_cleanup) and not recorded_cleanup.startswith("none")),
            f"default_enabled={denoise_default}; recorded={recorded_cleanup}",
        )
        units = timeline["speech_units"]
        check(
            "processed_voice_samples_valid",
            all(int(u.get("sample_count", 0)) > 0 for u in units),
            f"{len(units)} units",
        )
        ceiling = float(
            audio_master.get("voice_headroom", {}).get("premix_peak_ceiling_dbfs", -3.0)
        )
        voice_peak_dbfs = float(mix_report.get("voice_peak_dbfs", -120.0))
        check(
            "voice_peak_within_premix_ceiling",
            voice_peak_dbfs <= ceiling + 0.2,
            f"peak={voice_peak_dbfs} dBFS; ceiling={ceiling} dBFS",
        )
        amb_cfg = audio_master.get("ambient_bed", {})
        ambient = mix_report.get("ambient_bed", {})
        amb_cfg_enabled = bool(amb_cfg.get("enabled", False))
        amb_mixed_enabled = bool(ambient.get("enabled", False))
        check(
            "default_ambient_bed_disabled",
            amb_cfg_enabled is False and amb_mixed_enabled is False,
            f"config_enabled={amb_cfg_enabled}; mixed_enabled={amb_mixed_enabled}; "
            f"profile={audio_master.get('default_profile')}",
        )
        policy = audio_master.get("noise_policy", {})
        check(
            "no_continuous_random_noise_bed_in_default",
            policy.get("default_no_continuous_noise") is True
            and policy.get("random_noise_bed_allowed_in_default") is False
            and "ambient_bed_duck_and_mix" not in audio_master.get("processing_order", []),
            f"processing_order_tail={audio_master.get('processing_order', [])[-2:]}",
        )
        silence = mix_report.get("silence_diagnostics", {})
        check(
            "voice_gaps_are_true_silence",
            silence.get("voice_gaps_true_silence") is True,
            f"gap_voice_rms={silence.get('voice_gap_rms_dbfs')} dBFS; "
            f"segments={silence.get('gap_segments')}",
        )
        check(
            "final_mix_gaps_free_of_continuous_noise",
            silence.get("final_gaps_near_digital_silence") is True,
            f"gap_final_rms={silence.get('final_gap_rms_dbfs')} dBFS; "
            f"ceiling={silence.get('gap_noise_ceiling_dbfs')} dBFS",
        )
        aac_noise = context.get("aac_noise", {}).get("summary", {})
        sep_ok = float(
            aac_noise.get("pause_to_speech_separation_db", 0)
        ) >= float(policy.get("gap_to_speech_separation_db", 25.0))
        check(
            "encoded_aac_pause_is_quiet",
            bool(aac_noise.get("pause_is_near_digital_silence")) and sep_ok,
            f"pause_rms={aac_noise.get('pause_rms_dbfs')} dBFS; "
            f"speech_rms={aac_noise.get('speech_rms_dbfs')} dBFS; "
            f"separation={aac_noise.get('pause_to_speech_separation_db')} dB",
        )
        sfx_reports = mix_report.get("sfx_events", [])
        relative_values = [
            float(e["measured_sfx_rms_dbfs"]) - float(e["local_voice_rms_dbfs"])
            for e in sfx_reports
            if "measured_sfx_rms_dbfs" in e and "local_voice_rms_dbfs" in e
        ]
        sfx_cfg = audio_master.get("sfx", {})
        sfx_ok = bool(relative_values) and all(
            float(sfx_cfg.get("min_relative_db", -15)) <= value <= float(
                sfx_cfg.get("max_relative_db", -12)
            )
            for value in relative_values
        )
        check("sfx_relative_level_in_range", sfx_ok, f"levels={[round(v, 2) for v in relative_values]}")
        check(
            "final_mix_has_no_clipped_samples",
            int(mix_report.get("clipped_samples", -1)) == 0,
            f"clipped={mix_report.get('clipped_samples')}",
        )
        by_type = {e.get("motion_type"): e for e in motion.get("events", [])}
        sub = by_type.get("subcritical_return", {})
        sup = by_type.get("supercritical_descent", {})
        threshold = float(state_threshold(theme_master))
        path_ok = (
            bool(sub)
            and bool(sup)
            and sub.get("crosses_threshold") is False
            and float(sub.get("path_end_x", 1)) < threshold
            and float(sup.get("path_start_x", 0)) > threshold
            and sup.get("monotonic") is True
            and float(sub.get("graph_opacity_during_motion", 0)) == 1.0
            and float(sup.get("marker_opacity_during_motion", 0)) == 1.0
        )
        check(
            "state_curve_paths_and_focus_valid",
            path_ok,
            f"sub_end={sub.get('path_end_x')}; sub_crosses={sub.get('crosses_threshold')}; "
            f"sup_start={sup.get('path_start_x')}; sup_monotonic={sup.get('monotonic')}; "
            f"graph_opacity={sub.get('graph_opacity_during_motion')}; "
            f"marker_opacity={sup.get('marker_opacity_during_motion')}; threshold={threshold}",
        )

    failures = [item for item in checks if item["status"] == "FAIL"]
    warnings = [item for item in checks if item["status"] == "WARN"]
    report = {
        "schema_version": 1,
        "final_mp4": str(final_mp4),
        "media_probe": probe,
        "video_summary": {
            "width": width,
            "height": height,
            "fps": avg_fps,
            "nominal_fps": nominal_fps,
            "pixel_format": pix_fmt,
            "sample_aspect_ratio": sar,
            "frame_count": frame_count,
            "expected_frame_count": expected_frames,
            "duration_seconds": video_duration,
        },
        "audio_summary": {
            "codec": audio.get("codec_name"),
            "sample_rate": audio.get("sample_rate"),
            "channels": audio.get("channels"),
            "duration_seconds": audio_duration,
            "loudness_after_aac_encoding": final_audio_loudness,
            "loudness_measurement_error": loudness_error,
        },
        "qa_targets": {
            "integrated_loudness_lufs": TARGET_INTEGRATED_LOUDNESS_LUFS,
            "integrated_loudness_tolerance_lu": INTEGRATED_LOUDNESS_TOLERANCE_LU,
            "true_peak_dbtp": TARGET_TRUE_PEAK_DBTP,
            "true_peak_tolerance_db": TRUE_PEAK_TOLERANCE_DB,
            "audio_sample_rate": 44100,
            "audio_channels": 1,
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
        "overall_status": "FAIL" if failures else ("PASS_WITH_WARNINGS" if warnings else "PASS"),
    }
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if failures:
        failed = "; ".join(x["check"] + ": " + x["detail"] for x in failures)
        raise RuntimeError(f"最终 MP4 未通过强制 QA：{failed}")
    return report
