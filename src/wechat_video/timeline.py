from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Any

import numpy as np

from .speech_alignment import normalize_word_boundary_coverage_text


COVER_DURATION_MS = 1000
DEFAULT_INTER_UNIT_PAUSE_MS = 500
UNIT_FADE_IN_MS = 2
UNIT_FADE_OUT_MS = 10
OUTRO_TAIL_MS = 900
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


def _fade_pcm_edges(
    pcm: bytes,
    sample_rate: int,
    fade_in_ms: int = UNIT_FADE_IN_MS,
    fade_out_ms: int = UNIT_FADE_OUT_MS,
) -> bytes:
    """Protect initial speech transients while preventing release clicks."""
    samples = np.frombuffer(pcm, dtype="<i2")
    if samples.size < 2:
        return pcm
    values = samples.astype(np.float64)
    in_frames = min(samples.size // 2, max(0, sample_rate * fade_in_ms // 1000))
    out_frames = min(samples.size // 2, max(0, sample_rate * fade_out_ms // 1000))
    if in_frames:
        phase = np.linspace(0.0, np.pi / 2.0, in_frames, endpoint=True)
        values[:in_frames] *= np.sin(phase) ** 2
    if out_frames:
        phase = np.linspace(0.0, np.pi / 2.0, out_frames, endpoint=True)
        values[-out_frames:] *= (np.sin(phase) ** 2)[::-1]
    return np.clip(np.rint(values), -32768, 32767).astype("<i2").tobytes()


def build_audio_timeline(
    units: list[dict[str, Any]],
    *,
    audio_dir: Path,
    output_wav: Path,
    ffprobe_records: dict[str, dict[str, Any]],
    cover_duration_ms: int = COVER_DURATION_MS,
    outro_duration_ms: int = OUTRO_TAIL_MS,
) -> dict[str, Any]:
    if not units:
        raise ValueError("无法为零个 speech unit 建立时间轴。")
    if not 1000 <= int(cover_duration_ms) <= 3000:
        raise ValueError("封面时长必须在 1000–3000 ms 之间。")
    cover_duration_ms = int(cover_duration_ms)
    if not 600 <= int(outro_duration_ms) <= 2000:
        raise ValueError("片尾停留时长必须在 600–2000 ms 之间。")
    outro_duration_ms = int(outro_duration_ms)

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
    cover_frames = sample_rate * cover_duration_ms // 1000

    output_wav.parent.mkdir(parents=True, exist_ok=True)
    segments: list[dict[str, Any]] = [
        {
            "segment_id": "scene_00_cover",
            "kind": "cover",
            "start_sample": 0,
            "end_sample": cover_frames,
            "start_ms": 0,
            "end_ms": cover_duration_ms,
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
            pcm = _fade_pcm_edges(pcm, sample_rate)

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
                    "word_boundaries": list(unit.get("word_boundaries") or []),
                    "subtitle_alignment_method": str(
                        unit.get("subtitle_alignment_method") or "speech_unit_envelope"
                    ),
                    "word_boundary_status": str(unit.get("word_boundary_status") or "unavailable"),
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

        outro_frames = sample_rate * outro_duration_ms // 1000
        outro_start = cursor
        outro_end = outro_start + outro_frames
        writer.writeframes(_silence_bytes(outro_frames, 1, 2))
        segments.append(
            {
                "segment_id": "scene_99_outro",
                "kind": "outro",
                "start_sample": outro_start,
                "end_sample": outro_end,
                "start_ms": _round_samples_to_ms(outro_start, sample_rate),
                "end_ms": _round_samples_to_ms(outro_end, sample_rate),
                "duration_ms": outro_duration_ms,
                "speech": False,
                "subtitle": False,
            }
        )
        cursor = outro_end

    total_frames = cursor
    if first_cue_start_sample != cover_frames:
        raise ValueError("第一条旁白必须在显式封面结束时开始。")
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
        "cover_duration_ms": cover_duration_ms,
        "outro_duration_ms": outro_duration_ms,
        "outro": segments[-1],
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
            if segment["kind"] in {"cover", "silence", "outro"}
        ],
        "rhythm_blocks": [],
        "total_sample_count": total_frames,
        "total_duration_ms": _round_samples_to_ms(total_frames, sample_rate),
        "total_duration_seconds": total_frames / sample_rate,
        "cover_to_first_speech_gap_ms": 0,
        "audio_boundary_transition": {
            "inter_unit_pause_ms": DEFAULT_INTER_UNIT_PAUSE_MS,
            "speech_edge_fade_in_ms": UNIT_FADE_IN_MS,
            "speech_edge_fade_out_ms": UNIT_FADE_OUT_MS,
            "fade_curve": "asymmetric_equal_power_sine_squared",
            "outro_tail_ms": outro_duration_ms,
        },
        "timing_authority": "measured WAV sample counts; ffprobe metadata retained per speech unit",
    }


def validate_audio_timeline(timeline: dict[str, Any]) -> dict[str, Any]:
    """Prove that every cue/scene boundary is derived from one contiguous PCM sample clock."""
    try:
        sample_rate = int(timeline["audio_sample_rate"])
        total_samples = int(timeline["total_sample_count"])
        segments = timeline["segments"]
        cues = timeline["speech_units"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Audio timeline is missing its sample-clock fields.") from exc
    if sample_rate <= 0 or total_samples <= 0:
        raise ValueError("Audio timeline sample rate and total sample count must be positive.")
    if not isinstance(segments, list) or not segments:
        raise ValueError("Audio timeline must contain ordered segments.")
    if not isinstance(cues, list) or not cues:
        raise ValueError("Audio timeline must contain speech-unit cues.")

    cursor = 0
    speech_segments: dict[str, dict[str, Any]] = {}
    for segment in segments:
        try:
            start = int(segment["start_sample"])
            end = int(segment["end_sample"])
            start_ms = int(segment["start_ms"])
            end_ms = int(segment["end_ms"])
            kind = str(segment["kind"])
            segment_id = str(segment["segment_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Audio timeline contains a malformed segment.") from exc
        if start != cursor or end < start:
            raise ValueError(
                f"Audio timeline has a gap, overlap, or reversed segment at {segment_id}: "
                f"expected start={cursor}, actual={start}, end={end}."
            )
        if start_ms != _round_samples_to_ms(start, sample_rate) or end_ms != _round_samples_to_ms(end, sample_rate):
            raise ValueError(f"Audio timeline millisecond boundary disagrees with PCM samples: {segment_id}.")
        if kind == "speech":
            if segment_id in speech_segments:
                raise ValueError(f"Duplicate speech segment in audio timeline: {segment_id}.")
            speech_segments[segment_id] = segment
        cursor = end

    if cursor != total_samples:
        raise ValueError(
            f"Audio timeline ends at sample {cursor}, but total_sample_count is {total_samples}."
        )
    if segments[0].get("segment_id") != "scene_00_cover" or int(segments[0].get("start_sample", -1)) != 0:
        raise ValueError("Audio timeline must begin with the explicit cover segment.")

    cue_ids: set[str] = set()
    for cue in cues:
        unit_id = str(cue.get("unit_id") or "")
        if not unit_id or unit_id in cue_ids:
            raise ValueError(f"Missing or duplicate speech cue unit_id: {unit_id!r}.")
        cue_ids.add(unit_id)
        segment = speech_segments.get(unit_id)
        if segment is None:
            raise ValueError(f"Speech cue {unit_id} has no matching speech segment.")
        for key in ("start_sample", "end_sample", "start_ms", "end_ms"):
            if int(cue.get(key, -1)) != int(segment.get(key, -2)):
                raise ValueError(f"Speech cue {unit_id} {key} does not match its audio segment.")
        sample_count = int(cue.get("sample_count", -1))
        if sample_count != int(cue["end_sample"]) - int(cue["start_sample"]):
            raise ValueError(f"Speech cue {unit_id} sample_count disagrees with its boundaries.")
        alignment = str(cue.get("subtitle_alignment_method") or "speech_unit_envelope")
        word_boundaries = cue.get("word_boundaries") or []
        if alignment == "edge_word_boundary":
            if not isinstance(word_boundaries, list) or not word_boundaries:
                raise ValueError(f"Speech cue {unit_id} claims word-boundary alignment but has no boundaries.")
            speech_duration_ms = _round_samples_to_ms(sample_count, sample_rate)
            last_end = -1
            boundary_text: list[str] = []
            for boundary in word_boundaries:
                text = str(boundary.get("text") or "")
                start_ms = int(boundary.get("start_ms", -1))
                end_ms = int(boundary.get("end_ms", -1))
                if not text or start_ms < 0 or end_ms <= start_ms or end_ms > speech_duration_ms + 1:
                    raise ValueError(f"Speech cue {unit_id} has an invalid word-boundary interval.")
                if start_ms < last_end:
                    raise ValueError(f"Speech cue {unit_id} word boundaries are not ordered.")
                last_end = end_ms
                boundary_text.append(text)
            normalized_boundary_text = normalize_word_boundary_coverage_text("".join(boundary_text))
            normalized_spoken_text = normalize_word_boundary_coverage_text(str(cue.get("spoken_text", "")))
            if not normalized_spoken_text or normalized_boundary_text != normalized_spoken_text:
                raise ValueError(f"Speech cue {unit_id} word boundaries do not cover the exact spoken text.")
    if cue_ids != set(speech_segments):
        raise ValueError("Speech cue IDs and speech segment IDs are not a one-to-one match.")

    measured_seconds = total_samples / sample_rate
    if abs(float(timeline.get("total_duration_seconds", -1.0)) - measured_seconds) > 1e-9:
        raise ValueError("Audio timeline duration is not derived from total PCM sample count.")
    fallback_cues = [
        cue for cue in cues
        if cue.get("subtitle_alignment_method") != "edge_word_boundary"
    ]
    return {
        "valid": True,
        "sample_rate": sample_rate,
        "total_sample_count": total_samples,
        "speech_unit_count": len(cues),
        "word_boundary_aligned_unit_count": sum(
            1 for cue in cues if cue.get("subtitle_alignment_method") == "edge_word_boundary"
        ),
        "word_boundary_fallback_unit_count": len(fallback_cues),
        "word_boundary_fallback_units": [
            {
                "unit_id": str(cue.get("unit_id") or ""),
                "status": str(cue.get("word_boundary_status") or "unavailable"),
            }
            for cue in fallback_cues
        ],
        "outro_duration_ms": int(timeline.get("outro_duration_ms", 0)),
        "segment_count": len(segments),
        "authority": "measured_pcm_wav_sample_counts",
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
        onset_guard_ms = min(180, max(100, duration_ms))
        start = min(
            int(cue["end_sample"]) - 1,
            int(cue["start_sample"]) + sample_rate * onset_guard_ms // 1000,
        )
        end = min(
            total_samples,
            int(cue["end_sample"]),
            start + sample_rate * duration_ms // 1000,
        )
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
                "onset_guard_ms": onset_guard_ms,
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
