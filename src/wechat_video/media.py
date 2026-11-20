from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from .process import run_checked


def probe_media(path: Path, *, count_frames: bool = False) -> dict[str, Any]:
    args = ["ffprobe", "-v", "error"]
    if count_frames:
        args.extend(["-count_frames", "-select_streams", "v:0"])
    args.extend(["-show_streams", "-show_format", "-of", "json", str(path)])
    result = run_checked(args, timeout_seconds=90)
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
            "ffmpeg", "-hide_banner", "-nostats", "-y",
            "-i", str(audio_path),
            "-vn",
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
            "-f", "null", null_target,
        ],
        cwd=run_dir,
        timeout_seconds=180,
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


def assemble_final_video(
    scene_video: Path,
    narration_wav: Path,
    captions_ass: Path,
    output_mp4: Path,
    run_dir: Path,
) -> dict[str, Any]:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("FFmpeg / ffprobe 不在 PATH。")

    measured = _loudnorm_measurement(narration_wav, run_dir)
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
        "fps=30,setsar=1,format=yuv420p,"
        f"subtitles={relative_ass.as_posix()}"
    )
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    result = run_checked(
        [
            "ffmpeg", "-hide_banner", "-y",
            "-i", str(scene_video),
            "-i", str(narration_wav),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-vf", filter_chain,
            "-af", loudnorm,
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "19",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            "-fps_mode", "cfr",
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
    }
