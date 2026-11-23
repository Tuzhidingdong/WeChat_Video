from __future__ import annotations

import json
import math
import os
import queue
import re
import subprocess
import threading
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np

from .master_config import audio_config
from .process import ExternalProcessError, run_checked
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


def _fade_audio_edges(samples: np.ndarray, sample_rate: int, fade_ms: int) -> np.ndarray:
    """Apply a short equal-power fade to an SFX clip without changing its duration."""
    if fade_ms <= 0 or samples.size < 2:
        return samples
    fade_frames = min(samples.size // 2, sample_rate * fade_ms // 1000)
    if fade_frames <= 0:
        return samples
    result = samples.copy()
    phase = np.linspace(0.0, np.pi / 2.0, fade_frames, endpoint=True)
    ramp = np.sin(phase) ** 2
    result[:fade_frames] *= ramp
    result[-fade_frames:] *= ramp[::-1]
    return result


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


def _speech_region_mask(
    timeline: dict[str, Any] | None,
    sample_count: int,
    sample_rate: int,
    fade_ms: int = 120,
) -> np.ndarray:
    """Return a smooth mask that keeps editorial music out of true-silence regions."""
    mask = np.zeros(int(sample_count), dtype=np.float64)
    if not timeline:
        return mask
    fade_frames = max(0, int(sample_rate) * int(fade_ms) // 1000)
    for segment in timeline.get("segments", []):
        if segment.get("kind") != "speech":
            continue
        start = max(0, min(len(mask), int(segment.get("start_sample", 0))))
        end = max(start, min(len(mask), int(segment.get("end_sample", 0))))
        if end <= start:
            continue
        mask[start:end] = 1.0
        edge = min(fade_frames, (end - start) // 2)
        if edge > 0:
            phase = np.linspace(0.0, np.pi / 2.0, edge, endpoint=True)
            ramp = np.sin(phase) ** 2
            mask[start:start + edge] *= ramp
            mask[end - edge:end] *= ramp[::-1]
    return mask


def mix_final_audio(
    narration_wav: Path,
    sfx_events: list[dict[str, Any]],
    run_dir: Path,
    output_wav: Path,
    config: dict[str, Any] | None = None,
    timeline: dict[str, Any] | None = None,
    music_bed_path: Path | None = None,
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

    music_mix = np.zeros_like(voice)
    music_report: dict[str, Any] = {
        "enabled": False,
        "reason": "No original editorial music bed was supplied.",
    }
    if music_bed_path is not None:
        music_cfg = cfg.get("article_summary_music", {})
        with wave.open(str(music_bed_path), "rb") as reader:
            if reader.getframerate() != rate or reader.getnchannels() != 1 or reader.getsampwidth() != 2:
                raise RuntimeError("Editorial music bed must match narration mono PCM format.")
            music = (
                np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2").astype(np.float64)
                / 32768.0
            )
        if len(music) != len(voice):
            raise RuntimeError("Editorial music sample count does not match narration.")
        speech_mask = _speech_region_mask(
            timeline,
            len(voice),
            rate,
            int(music_cfg.get("edge_fade_ms", 120)),
        )
        duck_db = float(music_cfg.get("duck_db", 3.5))
        duck = _ducking_envelope(voice, rate, duck_db)
        music_mix = music * speech_mask * duck
        music_report = {
            "enabled": True,
            "file": str(music_bed_path),
            "target_rms_dbfs": float(music_cfg.get("target_rms_dbfs", -28.0)),
            "measured_source_rms_dbfs": round(_dbfs(float(np.sqrt(np.mean(music**2)))), 2),
            "duck_db": duck_db,
            "edge_fade_ms": int(music_cfg.get("edge_fade_ms", 120)),
            "only_during_speech": True,
            "silent_cover_and_unit_gaps_preserved": True,
            "texture": "original_deterministic_harmonic_synth_pad",
        }

    sfx_cfg = cfg["sfx"]
    relative_db = float(sfx_cfg["relative_level_db"])
    min_db = float(sfx_cfg["min_relative_db"])
    max_db = float(sfx_cfg["max_relative_db"])
    sfx_edge_fade_ms = int(sfx_cfg.get("edge_fade_ms", 15))
    if sfx_edge_fade_ms < 0 or sfx_edge_fade_ms > 100:
        raise RuntimeError("Configured SFX edge fade must be between 0 and 100 ms.")
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
        clip = _fade_audio_edges(clip, rate, sfx_edge_fade_ms)
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
        event_relative_db = float(event.get("relative_level_db", relative_db))
        if not -30.0 <= event_relative_db <= -10.0:
            raise RuntimeError(
                f"SFX event relative level must be between -30 and -10 dB: {event_relative_db}"
            )
        target_rms_db = _dbfs(local_rms) + event_relative_db
        clip_rms = float(np.sqrt(np.mean(clip**2))) or 1e-6
        gain = 10 ** ((target_rms_db - _dbfs(clip_rms)) / 20.0)
        scaled = clip * gain
        sfx_mix[start:end] += scaled[: end - start]
        sfx_reports.append(
            {
                "event_id": event.get("event_id"),
                "start_sample": start,
                "local_voice_rms_dbfs": round(_dbfs(local_rms), 2),
                "target_relative_db": event_relative_db,
                "target_sfx_rms_dbfs": round(target_rms_db, 2),
                "measured_sfx_rms_dbfs": round(_dbfs(float(np.sqrt(np.mean(scaled**2)))), 2),
                "gain": round(gain, 4),
                "edge_fade_ms": sfx_edge_fade_ms,
                "peak_dbfs": round(_dbfs(float(np.max(np.abs(scaled)))), 2),
            }
        )

    mixed = voice + bed + music_mix + sfx_mix
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
        "editorial_music_bed": music_report,
        "silence_diagnostics": silence_diagnostics,
        "sfx_events": sfx_reports,
        "sfx_relative_db": relative_db,
        "sfx_edge_fade_ms": sfx_edge_fade_ms,
        "peak_dbfs": round(_dbfs(peak), 2),
        "clipped_samples": 0,
    }


def _cfr_flag(ffmpeg_exe: str) -> list[str]:
    output = run_checked([ffmpeg_exe, "-version"], timeout_seconds=20, env=tool_env()).stdout
    match = re.search(r"ffmpeg version\s+(\d+)", output)
    major = int(match.group(1)) if match else 4
    return ["-fps_mode", "cfr"] if major >= 5 else ["-vsync", "cfr"]


def _tail_text(path: Path, max_chars: int = 6000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-max_chars:]


def _terminate_external_process(process: Any) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
        try:
            process.wait(timeout=5)
        except Exception:
            pass


def _run_ffmpeg_stage(
    args: list[str],
    *,
    cwd: Path,
    stage_name: str,
    progress_path: Path,
    timeout_seconds: int = 900,
    stall_timeout_seconds: int = 120,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one FFmpeg stage with machine-readable progress and a no-progress watchdog.

    FFmpeg's progress stream is drained on a dedicated thread, while stderr is
    written to a stage log file. This avoids pipe back-pressure and gives a
    bounded failure when an encoder/filter graph stops advancing.
    """
    if not args:
        raise ValueError("FFmpeg stage command must not be empty.")
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path = progress_path.with_suffix(".stderr.log")
    progress_path.write_text("", encoding="utf-8")
    command = [
        str(args[0]),
        "-hide_banner",
        "-nostats",
        "-progress",
        "pipe:1",
        "-stats_period",
        "1",
        *[str(item) for item in args[1:]],
    ]
    output_path = Path(str(args[-1]))
    output_queue: queue.Queue[str | None] = queue.Queue()
    progress_lines: list[str] = []
    state: dict[str, str] = {}
    latest: dict[str, str] = {}
    stdout_finished = False

    try:
        stderr_handle = stderr_path.open("w", encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ExternalProcessError(
            f"无法创建 FFmpeg 阶段日志（{stage_name}）：{stderr_path}；{exc}"
        ) from exc

    with stderr_handle:
        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=stderr_handle,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                shell=False,
            )
        except OSError as exc:
            raise ExternalProcessError(
                f"无法启动 FFmpeg 阶段（{stage_name}）：{command[0]}；{exc}"
            ) from exc

        def _read_stdout() -> None:
            try:
                assert process.stdout is not None
                for line in process.stdout:
                    output_queue.put(line)
            finally:
                output_queue.put(None)

        reader = threading.Thread(
            target=_read_stdout,
            name=f"ffmpeg-progress-{stage_name}",
            daemon=True,
        )
        reader.start()
        started = time.monotonic()
        last_progress_at = started
        last_signature: tuple[str | None, ...] | None = None
        failure_reason: str | None = None

        try:
            while True:
                try:
                    line = output_queue.get(timeout=0.2)
                    if line is None:
                        stdout_finished = True
                    else:
                        progress_lines.append(line)
                        stripped = line.strip()
                        if "=" in stripped:
                            key, value = stripped.split("=", 1)
                            state[key] = value
                            if key == "progress":
                                latest = dict(state)
                                signature = tuple(
                                    latest.get(field)
                                    for field in (
                                        "frame",
                                        "out_time_us",
                                        "out_time_ms",
                                        "out_time",
                                        "total_size",
                                    )
                                )
                                if any(value not in (None, "", "N/A") for value in signature):
                                    if signature != last_signature:
                                        last_signature = signature
                                        last_progress_at = time.monotonic()
                                state = {}
                except queue.Empty:
                    pass

                return_code = process.poll()
                now = time.monotonic()
                if return_code is not None and stdout_finished:
                    break
                if now - started >= timeout_seconds:
                    failure_reason = f"absolute timeout after {timeout_seconds}s"
                    break
                if now - last_progress_at >= stall_timeout_seconds:
                    failure_reason = (
                        f"no FFmpeg progress for {stall_timeout_seconds}s"
                    )
                    break
        finally:
            if failure_reason is not None:
                _terminate_external_process(process)
            if process.stdout is not None:
                try:
                    process.stdout.close()
                except Exception:
                    pass
            reader.join(timeout=2)

        return_code = process.wait()
        progress_text = "".join(progress_lines)
        progress_path.write_text(progress_text, encoding="utf-8")
        stderr_text = _tail_text(stderr_path)
        try:
            output_bytes = output_path.stat().st_size
        except OSError:
            output_bytes = 0

        last_progress = {
            key: latest.get(key)
            for key in ("frame", "out_time", "out_time_us", "total_size", "progress")
            if latest.get(key) is not None
        }
        if failure_reason is not None:
            raise ExternalProcessError(
                f"FFmpeg 阶段停滞或超时（{stage_name}）：{failure_reason}；"
                f"last_progress={last_progress}; output_bytes={output_bytes}; "
                f"progress_log={progress_path}; stderr_log={stderr_path}\n{stderr_text}"
            )
        if return_code != 0:
            raise ExternalProcessError(
                f"FFmpeg 阶段失败（{stage_name}），退出码 {return_code}；"
                f"last_progress={last_progress}; output_bytes={output_bytes}; "
                f"progress_log={progress_path}; stderr_log={stderr_path}\n{stderr_text}"
            )

    return subprocess.CompletedProcess(
        command,
        int(return_code),
        progress_text,
        stderr_text,
    )


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

    # Preserve the existing one-pass full-programme loudness target, but encode
    # video and normalized audio in separate FFmpeg processes. This removes the
    # combined video-filter/audio-loudnorm graph that repeatedly stalled at frame 0.
    measured = _loudnorm_measurement(audio_wav, run_dir, target_i, target_tp)
    loudnorm = (
        f"loudnorm=I={target_i}:TP={target_tp}:LRA=11:print_format=summary"
    )
    try:
        relative_ass = captions_ass.resolve().relative_to(run_dir.resolve())
    except ValueError as exc:
        raise RuntimeError("字幕文件必须位于当前运行目录内。") from exc

    if output_mp4.exists():
        raise RuntimeError(
            f"拒绝覆盖已存在的最终视频：{output_mp4}。每次合成必须使用全新运行目录。"
        )
    work_dir = run_dir / "assembly_work"
    work_dir.mkdir(parents=True, exist_ok=False)
    video_only = work_dir / "video_only.mp4"
    normalized_audio = work_dir / "normalized_audio.m4a"
    if video_only.exists() or normalized_audio.exists():
        raise RuntimeError("当前运行目录已有 FFmpeg 中间产物；拒绝覆盖。")

    filter_chain = (
        "scale=1080:1920:force_original_aspect_ratio=decrease:flags=lanczos,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,"
        "fps=30,setsar=1,"
        f"trim=end_frame={int(expected_frames)},setpts=PTS-STARTPTS,"
        f"format=yuv420p,subtitles={relative_ass.as_posix()}"
    )
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    stage_reports: list[dict[str, Any]] = []

    def run_stage(
        stage_name: str,
        command: list[str],
        stage_output: Path,
        *,
        timeout_seconds: int = 900,
        stall_timeout_seconds: int = 120,
    ) -> subprocess.CompletedProcess[str]:
        started = time.monotonic()
        progress_path = work_dir / f"{stage_name}.progress.txt"
        result = _run_ffmpeg_stage(
            command,
            cwd=run_dir,
            stage_name=stage_name,
            progress_path=progress_path,
            timeout_seconds=timeout_seconds,
            stall_timeout_seconds=stall_timeout_seconds,
            env=tool_env(),
        )
        if not stage_output.is_file() or stage_output.stat().st_size < 1024:
            raise ExternalProcessError(
                f"FFmpeg 阶段 {stage_name} 返回成功，但输出文件缺失或过小：{stage_output}"
            )
        stage_reports.append(
            {
                "stage": stage_name,
                "duration_seconds": round(time.monotonic() - started, 3),
                "output": str(stage_output),
                "output_bytes": stage_output.stat().st_size,
                "progress_log": str(progress_path),
                "stderr_log": str(progress_path.with_suffix(".stderr.log")),
                "stderr_tail": result.stderr[-1200:],
            }
        )
        return result

    # Stage 1: subtitle burn-in and H.264 video encoding only.
    video_command = [
        ffmpeg_exe,
        "-hide_banner",
        "-y",
        "-i",
        str(scene_video),
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        filter_chain,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "19",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "30",
        *_cfr_flag(ffmpeg_exe),
        "-frames:v",
        str(int(expected_frames)),
        str(video_only),
    ]
    run_stage("video_encode", video_command, video_only)

    # Stage 2: one full-programme loudnorm pass and AAC encode, independent of video.
    audio_command = [
        ffmpeg_exe,
        "-hide_banner",
        "-y",
        "-i",
        str(audio_wav),
        "-map",
        "0:a:0",
        "-vn",
        "-af",
        loudnorm,
        "-c:a",
        str(final_cfg["codec"]),
        "-b:a",
        f"{int(final_cfg['bitrate_kbps'])}k",
        "-ar",
        str(int(final_cfg["sample_rate"])),
        "-ac",
        str(int(final_cfg["channels"])),
        str(normalized_audio),
    ]
    run_stage("audio_normalize", audio_command, normalized_audio)

    # Stage 3: stream-copy mux only; no filters or encoders run in this stage.
    mux_command = [
        ffmpeg_exe,
        "-hide_banner",
        "-y",
        "-i",
        str(video_only),
        "-i",
        str(normalized_audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c",
        "copy",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_mp4),
    ]
    mux_result = run_stage("final_mux", mux_command, output_mp4)

    return {
        "loudness_target": {
            "integrated_loudness_lufs": target_i,
            "true_peak_dbtp": target_tp,
            "lra": 11,
        },
        "preset_id": cfg["preset_id"],
        "loudnorm_measurement": measured,
        "ffmpeg_output_tail": mux_result.stderr[-1200:],
        "subtitle_filter_path_mode": "relative filename from run directory",
        "audio_input": audio_wav.name,
        "loudnorm_pass": "single_pass_full_programme_audio_only_stage",
        "assembly_mode": "separate_video_encode_audio_normalize_then_stream_copy_mux",
        "ffmpeg_no_progress_timeout_seconds": 120,
        "expected_frames": int(expected_frames),
        "video_trim": f"trim=end_frame={int(expected_frames)}",
        "stages": stage_reports,
    }
