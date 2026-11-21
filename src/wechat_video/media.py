from __future__ import annotations

import json
import math
import os
import re
import wave
from pathlib import Path
from typing import Any

import numpy as np

from .master_config import audio_config
from .process import run_checked
from .sfx import generate_ambient
from .tooling import resolve_command, tool_env


def probe_media(path: Path, *, count_frames: bool = False) -> dict[str, Any]:
    args = [resolve_command("ffprobe"), "-v", "error"]
    if count_frames:
        # Count frames without -select_streams: QA needs both video and audio streams.
        args.append("-count_frames")
    args.extend(["-show_streams", "-show_format", "-of", "json", str(path)])
    result = run_checked(args, timeout_seconds=90, env=tool_env())
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ffprobe 返回无效 JSON：{path}") from exc
    if not data.get("streams"):
        raise RuntimeError(f"媒体文件没有可识别的流：{path}")
    return data


def _loudnorm_measurement(
    audio_path: Path, run_dir: Path, target_i: float, target_tp: float
) -> dict[str, str]:
    null_target = "NUL" if os.name == "nt" else "/dev/null"
    result = run_checked(
        [
            resolve_command("ffmpeg"), "-hide_banner", "-nostats", "-y",
            "-i", str(audio_path),
            "-vn",
            "-af", f"loudnorm=I={target_i}:TP={target_tp}:LRA=11:print_format=json",
            "-f", "null", null_target,
        ],
        cwd=run_dir,
        timeout_seconds=180,
        env=tool_env(),
    )
    matches = re.findall(r"\{\s*\"input_i\"[\s\S]*?\}", result.stderr)
    if not matches:
        raise RuntimeError("FFmpeg loudnorm 第一遍没有返回测量 JSON，不能安全地继续音频归一化。")
    try:
        measurement = json.loads(matches[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("无法解析 FFmpeg loudnorm 测量值。") from exc
    fields = {
        "measured_I": "input_i",
        "measured_TP": "input_tp",
        "measured_LRA": "input_lra",
        "measured_thresh": "input_thresh",
        "offset": "target_offset",
    }
    values: dict[str, str] = {}
    for target, source in fields.items():
        value = str(measurement.get(source, ""))
        if not value or value in {"-inf", "inf", "nan"}:
            raise RuntimeError(f"loudnorm 测量值无效：{source}={value}")
        values[target] = value
    return values


def _dbfs(value: float) -> float:
    return 20 * math.log10(value) if value > 0 else -120.0


def _ducking_envelope(voice: np.ndarray, sample_rate: int, duck_db: float) -> np.ndarray:
    """Smooth gain envelope: full bed in gaps, reduced under active narration."""
    frame = 1024
    count = len(voice) // frame
    if count == 0:
        return np.ones(len(voice))
    frames = voice[: count * frame].reshape(count, frame)
    rms = np.sqrt(np.mean(frames**2, axis=1))
    active = (rms > 10 ** (-45 / 20)).astype(np.float32)
    smooth_frames = max(1, int(0.18 * sample_rate / frame))
    kernel = np.ones(smooth_frames) / smooth_frames
    activity = np.convolve(active, kernel, mode="same")
    reduction = 10 ** (-abs(duck_db) / 20)
    gain = 1.0 - activity * (1.0 - reduction)
    gain = np.clip(gain, reduction, 1.0)
    return np.interp(np.arange(len(voice)), np.arange(count) * frame, gain)


def mix_final_audio(
    narration_wav: Path,
    sfx_events: list[dict[str, Any]],
    run_dir: Path,
    output_wav: Path,
    config: dict[str, Any] | None = None,
    timeline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mix narration, relative-level SFX and optional ducked ambient bed.

    The voice waveform and all stems keep the exact narration sample count; the
    mixture fails closed on clipping rather than silently limiting or clipping.
    """
    cfg = config or audio_config()
    with wave.open(str(narration_wav), "rb") as reader:
        rate = reader.getframerate()
        if reader.getnchannels() != 1 or reader.getsampwidth() != 2:
            raise RuntimeError("Narration must be 16-bit mono PCM for deterministic mixing.")
        voice = (
            np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2").astype(np.float64)
            / 32768.0
        )

    ceiling = float(cfg["voice_headroom"]["premix_peak_ceiling_dbfs"])
    voice_peak = float(np.max(np.abs(voice))) if voice.size else 0.0
    ceiling_gain_db = 0.0
    if _dbfs(voice_peak) > ceiling:
        ceiling_gain_db = ceiling - _dbfs(voice_peak)
        voice *= 10 ** (ceiling_gain_db / 20.0)

    ambient_report: dict[str, Any] = {
        "enabled": False,
        "profile": cfg.get("default_profile", "clean_voice_no_bed"),
        "reason": "default profile excludes continuous random-noise bed",
    }
    bed = np.zeros_like(voice)
    amb_cfg = cfg["ambient_bed"]
    if amb_cfg.get("enabled", False):
        bed_path = run_dir / "ambient_bed.wav"
        ambient_report = generate_ambient(
            bed_path,
            len(voice),
            rate,
            float(amb_cfg["rms_target_dbfs"]),
            int(amb_cfg["fade_ms"]),
        )
        with wave.open(str(bed_path), "rb") as reader:
            bed = (
                np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2").astype(np.float64)
                / 32768.0
            )
        if len(bed) != len(voice):
            raise RuntimeError("Ambient bed sample count does not match narration.")
        duck = _ducking_envelope(voice, rate, float(amb_cfg["duck_db"]))
        bed = bed * duck
        ambient_report["enabled"] = True
        ambient_report["duck_db"] = amb_cfg["duck_db"]
        ambient_report["continuous_through_gaps"] = True

    sfx_cfg = cfg["sfx"]
    relative_db = float(sfx_cfg["relative_level_db"])
    min_db = float(sfx_cfg["min_relative_db"])
    max_db = float(sfx_cfg["max_relative_db"])
    if not min_db <= relative_db <= max_db:
        raise RuntimeError("Configured SFX relative level is outside the allowed range.")
    window = int(rate * float(sfx_cfg["measurement_window_ms"]) / 1000)
    cue_map = {
        cue["unit_id"]: (int(cue["start_sample"]), int(cue["end_sample"]))
        for cue in (timeline or {}).get("speech_units", [])
    }
    sfx_reports: list[dict[str, Any]] = []
    sfx_mix = np.zeros_like(voice)
    for event in sfx_events:
        sfx_path = run_dir / event["file"]
        if not sfx_path.is_file():
            raise RuntimeError(f"SFX file missing: {sfx_path}")
        with wave.open(str(sfx_path), "rb") as reader:
            if reader.getframerate() != rate or reader.getnchannels() != 1 or reader.getsampwidth() != 2:
                raise RuntimeError(f"SFX format mismatch: {sfx_path}")
            clip = (
                np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2").astype(np.float64)
                / 32768.0
            )
        start = int(event["start_sample"])
        end = min(len(voice), start + len(clip))
        if end <= start:
            raise RuntimeError(f"SFX event outside narration: {event.get('event_id')}")
        # Measure against the full active speech unit when the timeline is known;
        # TTS chunks often begin with a short lead-in silence.
        cue = cue_map.get(str(event.get("unit_id", "")))
        if cue:
            lo = max(0, cue[0] + min(window // 2, max(0, (cue[1] - cue[0]) // 10)))
            hi = min(len(voice), cue[1])
        else:
            lo = max(0, start + window // 2)
            hi = min(len(voice), start + 2 * window)
        if hi <= lo:
            lo, hi = max(0, start), min(len(voice), start + window)
            if hi <= lo:
                raise RuntimeError(f"No local speech window for SFX {event.get('event_id')}")
        local = voice[lo:hi]
        local_rms = float(np.sqrt(np.mean(local**2))) if local.size else 0.0
        if local_rms <= 0:
            local_rms = float(np.sqrt(np.mean(voice**2))) or 1e-6
        target_rms_db = _dbfs(local_rms) + relative_db
        clip_rms = float(np.sqrt(np.mean(clip**2))) or 1e-6
        gain = 10 ** ((target_rms_db - _dbfs(clip_rms)) / 20.0)
        scaled = clip * gain
        sfx_mix[start:end] += scaled[: end - start]
        sfx_reports.append(
            {
                "event_id": event.get("event_id"),
                "start_sample": start,
                "local_voice_rms_dbfs": round(_dbfs(local_rms), 2),
                "target_relative_db": relative_db,
                "target_sfx_rms_dbfs": round(target_rms_db, 2),
                "measured_sfx_rms_dbfs": round(_dbfs(float(np.sqrt(np.mean(scaled**2)))), 2),
                "gain": round(gain, 4),
                "peak_dbfs": round(_dbfs(float(np.max(np.abs(scaled)))), 2),
            }
        )

    mixed = voice + bed + sfx_mix
    peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
    clipped = int(np.sum(np.abs(mixed) >= 1.0))
    if clipped:
        raise RuntimeError(f"Final mix has {clipped} clipped samples; refusing to clip silently.")

    gap_voice: list[np.ndarray] = []
    gap_final: list[np.ndarray] = []
    for segment in (timeline or {}).get("segments", []):
        if segment.get("kind") not in {"cover", "silence"}:
            continue
        lo = max(0, int(segment["start_sample"]))
        hi = min(len(voice), int(segment["end_sample"]))
        if hi > lo:
            gap_voice.append(voice[lo:hi])
            gap_final.append(mixed[lo:hi])
    silence_diagnostics: dict[str, Any] = {"gap_segments": len(gap_voice)}
    if gap_voice:
        voice_gaps = np.concatenate(gap_voice)
        final_gaps = np.concatenate(gap_final)
        voice_gap_rms = float(np.sqrt(np.mean(voice_gaps**2)))
        final_gap_rms = float(np.sqrt(np.mean(final_gaps**2)))
        ceiling = float(
            cfg.get("noise_policy", {}).get("gap_noise_ceiling_dbfs", -45.0)
        )
        silence_diagnostics.update(
            {
                "gap_sample_count": int(voice_gaps.size),
                "voice_gap_rms_dbfs": round(_dbfs(voice_gap_rms), 2),
                "final_gap_rms_dbfs": round(_dbfs(final_gap_rms), 2),
                "voice_gaps_true_silence": bool(np.all(voice_gaps == 0.0)),
                "final_gaps_near_digital_silence": bool(_dbfs(final_gap_rms) <= ceiling),
                "gap_noise_ceiling_dbfs": ceiling,
            }
        )

    output = np.clip(np.round(mixed * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(output_wav), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(output.tobytes())
    return {
        "sample_count": len(output),
        "sample_rate": rate,
        "voice_peak_dbfs": round(_dbfs(voice_peak), 2),
        "voice_ceiling_dbfs": ceiling,
        "voice_ceiling_gain_db": round(ceiling_gain_db, 3),
        "ambient_bed": ambient_report,
        "silence_diagnostics": silence_diagnostics,
        "sfx_events": sfx_reports,
        "sfx_relative_db": relative_db,
        "peak_dbfs": round(_dbfs(peak), 2),
        "clipped_samples": 0,
    }


def _cfr_flag(ffmpeg_exe: str) -> list[str]:
    output = run_checked([ffmpeg_exe, "-version"], timeout_seconds=20, env=tool_env()).stdout
    match = re.search(r"ffmpeg version\s+(\d+)", output)
    major = int(match.group(1)) if match else 4
    return ["-fps_mode", "cfr"] if major >= 5 else ["-vsync", "cfr"]


def assemble_final_video(
    scene_video: Path,
    audio_wav: Path,
    captions_ass: Path,
    output_mp4: Path,
    run_dir: Path,
    expected_frames: int,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config or audio_config()
    final_cfg = cfg["final_programme"]
    target_i = float(final_cfg["integrated_lufs"])
    target_tp = float(final_cfg["true_peak_dbtp"])
    ffmpeg_exe = resolve_command("ffmpeg")
    resolve_command("ffprobe")

    # One full-programme loudnorm pass. Two-pass linear mode (measured_* plus
    # linear=true) can deadlock this FFmpeg build with a denoise-free voice stem,
    # so use a single-pass normalization in the same mux process. This is still a
    # single loudness-normalization pass over the finished voice+SFX programme.
    measured = _loudnorm_measurement(audio_wav, run_dir, target_i, target_tp)
    loudnorm = (
        f"loudnorm=I={target_i}:TP={target_tp}:LRA=11:print_format=summary"
    )
    try:
        relative_ass = captions_ass.resolve().relative_to(run_dir.resolve())
    except ValueError as exc:
        raise RuntimeError("字幕文件必须位于当前运行目录内。") from exc
    filter_chain = (
        "scale=1080:1920:force_original_aspect_ratio=decrease:flags=lanczos,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,"
        "fps=30,setsar=1,"
        f"trim=end_frame={int(expected_frames)},setpts=PTS-STARTPTS,"
        f"format=yuv420p,subtitles={relative_ass.as_posix()}"
    )
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    result = run_checked(
        [
            ffmpeg_exe, "-hide_banner", "-y",
            "-i", str(scene_video),
            "-i", str(audio_wav),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-vf", filter_chain,
            "-af", loudnorm,
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "19",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            *_cfr_flag(ffmpeg_exe),
            "-c:a", str(final_cfg["codec"]),
            "-b:a", f"{int(final_cfg['bitrate_kbps'])}k",
            "-ar", str(int(final_cfg["sample_rate"])),
            "-ac", str(int(final_cfg["channels"])),
            "-shortest",
            "-movflags", "+faststart",
            str(output_mp4),
        ],
        cwd=run_dir,
        timeout_seconds=900,
    )
    return {
        "loudness_target": {
            "integrated_loudness_lufs": target_i,
            "true_peak_dbtp": target_tp,
            "lra": 11,
        },
        "preset_id": cfg["preset_id"],
        "loudnorm_measurement": measured,
        "ffmpeg_output_tail": result.stderr[-1200:],
        "subtitle_filter_path_mode": "relative filename from run directory",
        "audio_input": audio_wav.name,
        "loudnorm_pass": "single_pass_full_programme",
        "expected_frames": int(expected_frames),
        "video_trim": f"trim=end_frame={int(expected_frames)}",
    }
