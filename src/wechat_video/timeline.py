from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Any

import numpy as np


COVER_DURATION_MS = 1000
DEFAULT_INTER_UNIT_PAUSE_MS = 220
UNIT_EDGE_FADE_MS = 12
COMPREHENSION_PAUSE_MIN_MS = 500
COMPREHENSION_PAUSE_MAX_MS = 800


def _pause_ms_for_unit(unit: dict[str, Any]) -> int:
    value = int(unit.get("pause_after_ms", DEFAULT_INTER_UNIT_PAUSE_MS))
    if value < 0 or value > 2000:
        raise ValueError(f"pause_after_ms out of range for {unit.get('unit_id')}: {value}")
    return value


def _round_samples_to_ms(samples: int, sample_rate: int) -> int:
    return (samples * 1000 + sample_rate // 2) // sample_rate


def _silence_bytes(frames: int, channels: int, sample_width: int) -> bytes:
    return b"\x00" * (frames * channels * sample_width)


def _fade_pcm_edges(pcm: bytes, sample_rate: int, fade_ms: int) -> bytes:
    """Apply short equal-power edge fades to prevent clicks at phrase boundaries."""
    samples = np.frombuffer(pcm, dtype="<i2")
    fade_frames = min(samples.size // 2, max(0, sample_rate * fade_ms // 1000))
    if fade_frames <= 0:
        return pcm
    values = samples.astype(np.float64)
    phase = np.linspace(0.0, np.pi / 2.0, fade_frames, endpoint=True)
    ramp = np.sin(phase) ** 2
    values[:fade_frames] *= ramp
    values[-fade_frames:] *= ramp[::-1]
    return np.clip(np.rint(values), -32768, 32767).astype("<i2").tobytes()


def build_audio_timeline(
    units: list[dict[str, Any]],
    *,
    audio_dir: Path,
    output_wav: Path,
    ffprobe_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not units:
        raise ValueError("无法为零个 speech unit 建立时间轴。")

    wav_info: list[dict[str, Any]] = []
    for unit in units:
        path = audio_dir / f"{unit['unit_id']}.wav"
        with wave.open(str(path), "rb") as reader:
            meta = {
                "path": path,
                "channels": reader.getnchannels(),
                "sample_width": reader.getsampwidth(),
                "sample_rate": reader.getframerate(),
                "frames": reader.getnframes(),
                "compression": reader.getcomptype(),
            }
        if meta["compression"] != "NONE" or meta["channels"] != 1 or meta["sample_width"] != 2:
            raise ValueError(
                f"{unit['unit_id']} 必须为未压缩的 16-bit mono PCM WAV：{meta}"
            )
        if meta["frames"] <= 0:
            raise ValueError(f"{unit['unit_id']} 是空音频。")
        wav_info.append(meta)

    sample_rates = {x["sample_rate"] for x in wav_info}
    if len(sample_rates) != 1:
        raise ValueError(
            "各 speech unit 的采样率不一致；Slice A 暂不进行隐式重采样："
            f"{sorted(sample_rates)}"
        )
    sample_rate = sample_rates.pop()
    cover_frames = sample_rate * COVER_DURATION_MS // 1000

    output_wav.parent.mkdir(parents=True, exist_ok=True)
    segments: list[dict[str, Any]] = [
        {
            "segment_id": "scene_00_cover",
            "kind": "cover",
            "start_sample": 0,
            "end_sample": cover_frames,
            "start_ms": 0,
            "end_ms": COVER_DURATION_MS,
            "speech": False,
            "subtitle": False,
        }
    ]
    cue_records: list[dict[str, Any]] = []
    cursor = cover_frames
    first_cue_start_sample: int | None = None

    with wave.open(str(output_wav), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(_silence_bytes(cover_frames, 1, 2))

        for index, (unit, meta) in enumerate(zip(units, wav_info)):
            path = meta["path"]
            with wave.open(str(path), "rb") as reader:
                pcm = reader.readframes(reader.getnframes())
            expected_bytes = meta["frames"] * 2
            if len(pcm) != expected_bytes:
                raise ValueError(f"{unit['unit_id']} WAV 数据长度与帧数不一致。")
            pcm = _fade_pcm_edges(pcm, sample_rate, UNIT_EDGE_FADE_MS)

            start_sample = cursor
            end_sample = start_sample + meta["frames"]
            if first_cue_start_sample is None:
                first_cue_start_sample = start_sample
            writer.writeframes(pcm)
            segments.append(
                {
                    "segment_id": unit["unit_id"],
                    "kind": "speech",
                    "audio_file": str(path),
                    "start_sample": start_sample,
                    "end_sample": end_sample,
                    "start_ms": _round_samples_to_ms(start_sample, sample_rate),
                    "end_ms": _round_samples_to_ms(end_sample, sample_rate),
                    "sample_rate": sample_rate,
                    "sample_count": meta["frames"],
                    "speech": True,
                    "subtitle": True,
                }
            )
            probe = ffprobe_records[unit["unit_id"]]
            cue_records.append(
                {
                    "unit_id": unit["unit_id"],
                    "raw_text": unit["raw_text"],
                    "display_text": unit["display_text"],
                    "display_text_zh": unit.get("display_text_zh", ""),
                    "spoken_text": unit["spoken_text"],
                    "claim_ids": unit["claim_ids"],
                    "visual_trigger_ids": unit["visual_trigger_ids"],
                    "rhythm_block_id": unit.get("rhythm_block_id"),
                    "sfx_trigger_id": unit.get("sfx_trigger_id"),
                    "audio_file": str(path),
                    "sample_rate": sample_rate,
                    "channels": 1,
                    "sample_count": meta["frames"],
                    "duration_seconds_from_samples": meta["frames"] / sample_rate,
                    "ffprobe": probe,
                    "start_sample": start_sample,
                    "end_sample": end_sample,
                    "start_ms": _round_samples_to_ms(start_sample, sample_rate),
                    "end_ms": _round_samples_to_ms(end_sample, sample_rate),
                }
            )
            cursor = end_sample

            if index < len(units) - 1:
                pause_ms = _pause_ms_for_unit(unit)
                gap_frames = sample_rate * pause_ms // 1000
                gap_start = cursor
                gap_end = cursor + gap_frames
                writer.writeframes(_silence_bytes(gap_frames, 1, 2))
                segments.append(
                    {
                        "segment_id": f"pause_after_{unit['unit_id']}",
                        "kind": "silence",
                        "start_sample": gap_start,
                        "end_sample": gap_end,
                        "start_ms": _round_samples_to_ms(gap_start, sample_rate),
                        "end_ms": _round_samples_to_ms(gap_end, sample_rate),
                        "duration_ms": pause_ms,
                    }
                )
                cursor = gap_end

    total_frames = cursor
    if first_cue_start_sample != cover_frames:
        raise ValueError("第一条旁白必须在显式封面结束时开始（1000 ms）。")
    if not segments or segments[0]["segment_id"] != "scene_00_cover":
        raise ValueError("时间轴缺少 scene_00_cover。")

    return {
        "schema_version": 1,
        "time_origin": "final_mp4_first_frame",
        "fps": 30,
        "audio_sample_rate": sample_rate,
        "audio_channels": 1,
        "audio_sample_width_bytes": 2,
        "cover": segments[0],
        "segments": segments,
        "speech_units": cue_records,
        "sfx_events": [],
        "ambient_regions": [
            {
                "start_sample": segment["start_sample"],
                "end_sample": segment["end_sample"],
                "kind": segment["kind"],
            }
            for segment in segments
            if segment["kind"] in {"cover", "silence"}
        ],
        "rhythm_blocks": [],
        "total_sample_count": total_frames,
        "total_duration_ms": _round_samples_to_ms(total_frames, sample_rate),
        "total_duration_seconds": total_frames / sample_rate,
        "cover_to_first_speech_gap_ms": 0,
        "audio_boundary_transition": {
            "inter_unit_pause_ms": DEFAULT_INTER_UNIT_PAUSE_MS,
            "speech_edge_fade_ms": UNIT_EDGE_FADE_MS,
            "fade_curve": "equal_power_sine_squared",
        },
        "timing_authority": "measured WAV sample counts; ffprobe metadata retained per speech unit",
    }


def attach_editorial_events(
    timeline: dict[str, Any], units: list[dict[str, Any]], sfx_durations_ms: dict[str, int]
) -> dict[str, Any]:
    """Attach global-origin SFX events and rhythm blocks to the timeline."""
    sample_rate = int(timeline["audio_sample_rate"])
    total_samples = int(timeline["total_sample_count"])
    events: list[dict[str, Any]] = []
    for cue, unit in zip(timeline["speech_units"], units):
        trigger = unit.get("sfx_trigger_id")
        if not trigger:
            continue
        duration_ms = int(sfx_durations_ms.get(trigger, 180))
        start = int(cue["start_sample"])
        end = min(total_samples, start + sample_rate * duration_ms // 1000)
        if end <= start:
            raise ValueError(f"SFX event {trigger} falls outside the global timeline")
        events.append(
            {
                "event_id": f"sfx_{cue['unit_id']}_{trigger}",
                "sfx_trigger_id": trigger,
                "unit_id": cue["unit_id"],
                "start_sample": start,
                "end_sample": end,
                "start_ms": _round_samples_to_ms(start, sample_rate),
                "end_ms": _round_samples_to_ms(end, sample_rate),
                "duration_ms": _round_samples_to_ms(end - start, sample_rate),
                "file": f"sfx/{trigger}.wav",
                "peak_target": 0.06,
            }
        )
    timeline["sfx_events"] = events
    timeline["rhythm_blocks"] = []
    for unit in units:
        block_id = unit.get("rhythm_block_id")
        if not timeline["rhythm_blocks"] or timeline["rhythm_blocks"][-1]["block_id"] != block_id:
            timeline["rhythm_blocks"].append({"block_id": block_id, "unit_ids": []})
        timeline["rhythm_blocks"][-1]["unit_ids"].append(unit["unit_id"])
    return timeline


def write_timeline(path: Path, timeline: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
