from __future__ import annotations

import json
import os
import re
import wave
from pathlib import Path
from typing import Any

import numpy as np

from .process import run_checked
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


def _loudnorm_measurement(audio_path: Path, run_dir: Path) -> dict[str, str]:
    null_target = "NUL" if os.name == "nt" else "/dev/null"
    result = run_checked(
        [
            resolve_command("ffmpeg"), "-hide_banner", "-nostats", "-y",
            "-i", str(audio_path),
            "-vn",
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
            "-f", "null", null_target,
        ],
        cwd=run_dir,
        timeout_seconds=180,
        env=tool_env(),
    )
    matches = re.findall(r"\{\s*\"input_i\"[\s\S]*?\}", result.stderr)
    if not matches:
        raise RuntimeError(
            "FFmpeg loudnorm 第一遍没有返回测量 JSON，不能安全地继续音频归一化。"
        )
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


def mix_final_audio(
    narration_wav: Path,
    sfx_events: list[dict[str, Any]],
    run_dir: Path,
    output_wav: Path,
) -> dict[str, Any]:
    """Mix sparse SFX over the authored narration without shifting any samples."""
    with wave.open(str(narration_wav), "rb") as reader:
        rate = reader.getframerate()
        channels = reader.getnchannels()
        width = reader.getsampwidth()
        if channels != 1 or width != 2:
            raise RuntimeError("Narration must be 16-bit mono PCM for deterministic mixing.")
        pcm = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2").astype(np.float32)
    mixed = pcm.copy()
    for event in sfx_events:
        sfx_path = run_dir / event["file"]
        if not sfx_path.is_file():
            raise RuntimeError(f"SFX file missing: {sfx_path}")
        with wave.open(str(sfx_path), "rb") as reader:
            if reader.getframerate() != rate or reader.getnchannels() != 1 or reader.getsampwidth() != 2:
                raise RuntimeError(f"SFX format mismatch: {sfx_path}")
            clip = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2").astype(np.float32)
        start = int(event["start_sample"])
        end = min(len(mixed), start + len(clip))
        if end <= start:
            raise RuntimeError(f"SFX event outside narration: {event.get('event_id')}")
        gain = float(event.get("peak_target", 0.06)) / 0.06
        mixed[start:end] += clip[: end - start] * gain
    peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
    clipped = mixed[np.abs(mixed) > 32767.0].size
    output = np.clip(np.round(mixed), -32768, 32767).astype("<i2")
    with wave.open(str(output_wav), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(output.tobytes())
    return {
        "sample_count": len(output),
        "sample_rate": rate,
        "peak": round(peak, 2),
        "clipped_samples": int(clipped),
        "sfx_events": len(sfx_events),
    }


def _cfr_flag(ffmpeg_exe: str) -> list[str]:
    output = run_checked(
        [ffmpeg_exe, "-version"], timeout_seconds=20, env=tool_env()
    ).stdout
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
) -> dict[str, Any]:
    ffmpeg_exe = resolve_command("ffmpeg")
    resolve_command("ffprobe")

    measured = _loudnorm_measurement(audio_wav, run_dir)
    loudnorm = (
        "loudnorm=I=-16:TP=-1.5:LRA=11:"
        f"measured_I={measured['measured_I']}:"
        f"measured_TP={measured['measured_TP']}:"
        f"measured_LRA={measured['measured_LRA']}:"
        f"measured_thresh={measured['measured_thresh']}:"
        f"offset={measured['offset']}:linear=true:print_format=summary"
    )
    # Relative ASS filename avoids Windows drive-letter/colon escaping in the libass filter.
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
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "44100",
            "-ac", "1",
            "-shortest",
            "-movflags", "+faststart",
            str(output_mp4),
        ],
        cwd=run_dir,
        timeout_seconds=900,
    )
    return {
        "loudness_target": {"integrated_loudness_lufs": -16, "true_peak_dbtp": -1.5, "lra": 11},
        "loudnorm_measurement": measured,
        "ffmpeg_output_tail": result.stderr[-1200:],
        "subtitle_filter_path_mode": "relative filename from run directory",
        "audio_input": audio_wav.name,
        "expected_frames": int(expected_frames),
        "video_trim": f"trim=end_frame={int(expected_frames)}",
    }
