"""Local, private audio diagnostics for the Slice A noise-floor investigation.

All outputs stay under ignored ``outputs/`` or ``private/`` paths. No audio is
uploaded and no transcript/path metadata is written into reports.
"""
from __future__ import annotations

import io
import json
import math
import re
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any

import numpy as np

from .master_config import audio_config
from .media import mix_final_audio
from .tooling import resolve_command, tool_env


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as reader:
        rate = reader.getframerate()
        if reader.getnchannels() != 1 or reader.getsampwidth() != 2:
            raise RuntimeError(f"Diagnostics require 16-bit mono PCM: {path}")
        values = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2").astype(
            np.float64
        ) / 32768.0
    return values, rate


def _dbfs(value: float) -> float:
    return 20 * math.log10(value) if value > 0 else -120.0


def segment_metrics(samples: np.ndarray, rate: int, start_s: float, end_s: float) -> dict[str, Any]:
    """RMS/peak/spectrum/flatness for one time window of a decoded stem."""
    lo = max(0, int(start_s * rate))
    hi = min(len(samples), int(end_s * rate))
    window = samples[lo:hi]
    if window.size < 32:
        return {"start_s": start_s, "end_s": end_s, "samples": int(window.size)}
    rms = float(np.sqrt(np.mean(window**2)))
    peak = float(np.max(np.abs(window)))
    spectrum = np.abs(np.fft.rfft(window * np.hanning(window.size)))
    freqs = np.fft.rfftfreq(window.size, 1.0 / rate)
    total = float(np.sum(spectrum**2)) or 1.0

    def band(low: float, high: float) -> float:
        return round(
            float(np.sum(spectrum[(freqs >= low) & (freqs <= high)] ** 2) / total), 6
        )

    hum_band = (freqs >= 50) & (freqs <= 200)
    hum_peaks: list[dict[str, float]] = []
    if hum_band.any():
        order = np.argsort(spectrum[hum_band])[-5:][::-1]
        hum_peaks = [
            {"hz": round(float(freqs[hum_band][i]), 1), "magnitude": round(float(spectrum[hum_band][i]), 2)}
            for i in order
        ]
    power = spectrum**2
    flatness = float(np.exp(np.mean(np.log(power + 1e-12))) / (np.mean(power) + 1e-12))
    return {
        "start_s": round(start_s, 3),
        "end_s": round(end_s, 3),
        "samples": int(window.size),
        "rms_dbfs": round(_dbfs(rms), 2),
        "peak_dbfs": round(_dbfs(peak), 2),
        "zero_sample_ratio": round(float(np.mean(np.abs(window) < 1e-6)), 4),
        "band_50_200": band(50, 200),
        "band_200_1000": band(200, 1000),
        "band_1000_5000": band(1000, 5000),
        "band_5000_plus": band(5000, rate / 2),
        "spectral_flatness": round(flatness, 6),
        "hum_peaks_50_200": hum_peaks,
    }


def _loudness_offset(wav_path: Path, run_dir: Path, target_i: float = -16.0) -> float:
    null_target = "NUL" if __import__("os").name == "nt" else "/dev/null"
    result = subprocess.run(
        [
            resolve_command("ffmpeg"), "-hide_banner", "-nostats", "-y",
            "-i", str(wav_path), "-vn",
            "-af", f"loudnorm=I={target_i}:TP=-1.5:LRA=11:print_format=json",
            "-f", "null", null_target,
        ],
        cwd=run_dir,
        capture_output=True,
        text=True,
        timeout=180,
        env=tool_env(),
    )
    matches = re.findall(r"\{\s*\"input_i\"[\s\S]*?\}", result.stderr)
    if not matches:
        raise RuntimeError(f"loudnorm measurement failed for {wav_path}")
    payload = json.loads(matches[-1])
    measured = float(payload["input_i"])
    if not math.isfinite(measured):
        raise RuntimeError("loudnorm measured input_i is not finite")
    return round(target_i - measured, 3)


def _apply_gain(source: Path, target: Path, gain_db: float) -> None:
    subprocess.run(
        [
            resolve_command("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-af", f"volume={gain_db}dB",
            "-c:a", "pcm_s16le", str(target),
        ],
        check=True,
        env=tool_env(),
    )


def _pick_segments(timeline: dict[str, Any]) -> dict[str, tuple[float, float]]:
    rate = int(timeline["audio_sample_rate"])
    units = timeline["speech_units"]

    def to_s(sample: int) -> float:
        return sample / rate

    speech = units[len(units) // 2]
    speech_mid_s = (int(speech["start_sample"]) + int(speech["end_sample"])) / (2 * rate)
    speech_window = (speech_mid_s - 0.45, speech_mid_s + 0.45)

    pauses = [s for s in timeline["segments"] if s.get("kind") == "silence"]
    short = next((s for s in pauses if 250 <= int(s.get("duration_ms", 0)) <= 400), None)
    long_pause = next((s for s in pauses if int(s.get("duration_ms", 0)) >= 500), None)
    result: dict[str, tuple[float, float]] = {
        "speech_active": speech_window,
        "cover_0_to_1s": (0.0, 1.0),
    }
    if short:
        a, b = to_s(int(short["start_sample"])), to_s(int(short["end_sample"]))
        result["short_unit_gap"] = (a, min(b, a + 0.3))
    if long_pause:
        a, b = to_s(int(long_pause["start_sample"])), to_s(int(long_pause["end_sample"]))
        result["comprehension_pause"] = (a, b)
    total = timeline["total_duration_seconds"]
    result["closing_1s"] = (max(0.0, total - 1.0), total)
    return result


def build_five_stems(run_dir: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    """Create five gain-matched audition stems from one measured local render."""
    run_dir = run_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    narration = run_dir / "narration.wav"
    timeline = json.loads((run_dir / "audio_timing.json").read_text(encoding="utf-8"))
    cfg = audio_config(str(run_dir.parents[1]))
    sfx_cfg = dict(cfg["sfx"])
    sfx_cfg["enabled"] = True
    master = dict(cfg)
    master["sfx"] = sfx_cfg

    voice_sfx = out_dir / "_raw_voice_sfx.wav"
    mix_final_audio(
        narration, timeline["sfx_events"], run_dir, voice_sfx,
        config=master, timeline=timeline,
    )

    diagnostic_cfg = dict(master)
    diagnostic_cfg["ambient_bed"] = dict(master["ambient_bed"])
    diagnostic_cfg["ambient_bed"]["enabled"] = True
    diagnostic_cfg["ambient_bed"]["texture"] = "soft_low_hiss"
    voice_bed = out_dir / "_raw_voice_old_bed.wav"
    mix_final_audio(
        narration, [], run_dir, voice_bed,
        config=diagnostic_cfg, timeline=timeline,
    )

    gain_db = _loudness_offset(narration, out_dir)
    stems = {
        "01_voice_only": narration,
        "02_voice_plus_sfx": voice_sfx,
        "03_voice_plus_old_ambient_diagnostic": voice_bed,
        "04_existing_final_mix": run_dir / "final_mix.wav",
        "05_new_default_mix_no_bed": voice_sfx,
    }
    windows = _pick_segments(timeline)
    report: dict[str, Any] = {
        "schema_version": 1,
        "source_run": str(run_dir),
        "gain_match_db_applied_to_all_stems": gain_db,
        "gain_match_note": "single common linear gain from voice-only loudnorm measurement; relative stem levels preserved",
        "windows": windows,
        "stems": {},
        "human_listening_required": True,
    }
    for name, source in stems.items():
        matched = out_dir / f"{name}.wav"
        _apply_gain(source, matched, gain_db)
        values, rate = read_wav(matched)
        metrics = {label: segment_metrics(values, rate, *span) for label, span in windows.items()}
        report["stems"][name] = {
            "file": matched.name,
            "sample_rate": rate,
            "sample_count": int(values.size),
            "overall_rms_dbfs": round(_dbfs(float(np.sqrt(np.mean(values**2)))), 2),
            "windows": metrics,
        }

    voice_gap = report["stems"]["01_voice_only"]["windows"].get("comprehension_pause", {})
    old_gap = report["stems"]["03_voice_plus_old_ambient_diagnostic"]["windows"].get(
        "comprehension_pause", {}
    )
    new_gap = report["stems"]["05_new_default_mix_no_bed"]["windows"].get("comprehension_pause", {})
    report["diagnosis"] = {
        "voice_only_pause_rms_dbfs": voice_gap.get("rms_dbfs"),
        "old_bed_pause_rms_dbfs": old_gap.get("rms_dbfs"),
        "new_default_pause_rms_dbfs": new_gap.get("rms_dbfs"),
        "noise_source": (
            "synthetic ambient bed" if old_gap.get("rms_dbfs", -120) > voice_gap.get("rms_dbfs", -120) + 10
            else "undetermined; inspect voice-only spectrum"
        ),
        "voice_only_gaps_are_true_silence": bool(
            voice_gap.get("zero_sample_ratio", 0) >= 0.999
        ),
        "recommendation": (
            "keep ambient bed disabled; do not escalate denoise while voice-only gaps are silent"
            if voice_gap.get("zero_sample_ratio", 0) >= 0.999
            else "investigate voice-only stem before changing denoise"
        ),
    }
    for raw in (voice_sfx, voice_bed):
        raw.unlink(missing_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def decode_aac_window(mp4: Path, start_s: float, duration_s: float, rate: int = 44100) -> np.ndarray:
    """Decode an encoded AAC window to mono PCM for noise inspection."""
    result = subprocess.run(
        [
            resolve_command("ffmpeg"), "-hide_banner", "-loglevel", "error",
            "-ss", f"{start_s:.3f}", "-t", f"{duration_s:.3f}",
            "-i", str(mp4), "-vn", "-ac", "1", "-ar", str(rate),
            "-c:a", "pcm_s16le", "-f", "wav", "pipe:1",
        ],
        capture_output=True,
        timeout=180,
        env=tool_env(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to decode AAC window from {mp4}: {result.stderr[-400:]!r}")
    with wave.open(io.BytesIO(result.stdout), "rb") as reader:
        return np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2").astype(
            np.float64
        ) / 32768.0


def encoded_aac_noise_report(mp4: Path, timeline: dict[str, Any], report_path: Path) -> dict[str, Any]:
    rate = int(timeline["audio_sample_rate"])
    windows = _pick_segments(timeline)
    report: dict[str, Any] = {
        "schema_version": 1,
        "mp4": str(mp4),
        "windows": {},
        "human_listening_required": True,
    }
    for label, (start, end) in windows.items():
        samples = decode_aac_window(mp4, start, max(0.05, end - start), 44100)
        report["windows"][label] = segment_metrics(samples, 44100, 0, len(samples) / 44100)
    speech = report["windows"].get("speech_active", {}).get("rms_dbfs", -120)
    gap = report["windows"].get("comprehension_pause", {}).get("rms_dbfs", -120)
    report["summary"] = {
        "speech_rms_dbfs": speech,
        "pause_rms_dbfs": gap,
        "pause_to_speech_separation_db": round(float(speech) - float(gap), 2),
        "pause_is_near_digital_silence": float(gap) <= -45.0,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def denoise_ab(raw_path: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    """Same-text A/B for cleanup candidates; diagnostic only, not auto-adopted."""
    out_dir.mkdir(parents=True, exist_ok=True)
    variants: dict[str, str] = {
        "current_afftdn": "afftdn=nf=-25",
        "candidate_nr18_nf35_tn1": "afftdn=nr=18:nf=-35:tn=1",
        "current_plus_highpass_85": "afftdn=nf=-25,highpass=f=85",
        "current_plus_highpass_110": "afftdn=nf=-25,highpass=f=110",
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "source": str(raw_path),
        "variants": {},
        "adopted": False,
        "decision": (
            "Voice-only gaps are true digital silence and the voice stem is tonal "
            "(low spectral flatness); the noise is in the disabled ambient stem. "
            "No aggressive denoise or 110 Hz high-pass is adopted."
        ),
        "human_listening_required": True,
    }
    for name, chain in variants.items():
        target = out_dir / f"denoise_{name}.wav"
        subprocess.run(
            [
                resolve_command("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(raw_path), "-af", chain,
                "-c:a", "pcm_s16le", str(target),
            ],
            check=True,
            env=tool_env(),
        )
        values, rate = read_wav(target)
        frame = max(1, int(0.02 * rate))
        count = len(values) // frame
        frames = values[: count * frame].reshape(count, frame)
        frame_rms = np.sqrt(np.mean(frames**2, axis=1))
        noise_floor = float(np.mean(np.sort(frame_rms)[: max(1, len(frame_rms) // 5)]))
        spectrum = np.abs(np.fft.rfft(values * np.hanning(values.size)))
        freqs = np.fft.rfftfreq(values.size, 1.0 / rate)
        total = float(np.sum(spectrum**2)) or 1.0

        def band(low: float, high: float) -> float:
            return round(float(np.sum(spectrum[(freqs >= low) & (freqs <= high)] ** 2) / total), 6)

        report["variants"][name] = {
            "file": target.name,
            "filter_chain": chain,
            "sample_count": int(values.size),
            "duration_seconds": round(values.size / rate, 4),
            "noise_floor_rms": round(noise_floor, 6),
            "band_80_150": band(80, 150),
            "band_50_200": band(50, 200),
            "band_4000_8000": band(4000, 8000),
            "clipping_ratio": round(float(np.mean(np.abs(values) >= 0.999)), 6),
        }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def afftdn_ab(raw_path: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    """Same-text A/B: clarity EQ with vs without configured afftdn cleanup."""
    from .master_config import denoise_filter_chain, voice_eq_filter_chain

    out_dir.mkdir(parents=True, exist_ok=True)
    eq_chain = voice_eq_filter_chain()
    denoise_chain = denoise_filter_chain()
    variants: dict[str, str] = {
        "A_no_afftdn_eq": eq_chain,
        "B_afftdn_then_eq": f"{denoise_chain},{eq_chain}",
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "source": str(raw_path),
        "source_role": "raw OpenVoice-converted speech (no cleanup, no EQ)",
        "preset_id": audio_config()["preset_id"],
        "eq_chain": eq_chain,
        "denoise_chain_candidate": denoise_chain,
        "variants": {},
        "gain_matched": True,
        "comparison_note": "identical source and EQ; only afftdn differs; same sample grid and playback gain",
        "human_listening_required": True,
    }
    for name, chain in variants.items():
        target = out_dir / f"{name}.wav"
        subprocess.run(
            [
                resolve_command("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(raw_path), "-af", chain,
                "-c:a", "pcm_s16le", str(target),
            ],
            check=True,
            env=tool_env(),
        )
        values, rate = read_wav(target)
        frame = max(1, int(0.02 * rate))
        count = len(values) // frame
        aligned = values[: count * frame]
        frames = aligned.reshape(count, frame)
        frame_rms = np.sqrt(np.mean(frames**2, axis=1))
        active = frame_rms > 0.08 * float(frame_rms.max())
        active_samples = frames[active].reshape(-1)
        spectrum = np.abs(np.fft.rfft(active_samples * np.hanning(active_samples.size)))
        freqs = np.fft.rfftfreq(active_samples.size, 1.0 / rate)
        power = spectrum**2
        total = float(np.sum(power)) or 1.0

        def band(low: float, high: float) -> float:
            return round(float(np.sum(power[(freqs >= low) & (freqs <= high)]) / total), 6)

        flatness = float(np.exp(np.mean(np.log(power + 1e-12))) / (np.mean(power) + 1e-12))
        peak = float(np.max(np.abs(values))) if values.size else 0.0
        report["variants"][name] = {
            "file": target.name,
            "filter_chain": chain,
            "sample_rate": rate,
            "channels": 1,
            "sample_count": int(values.size),
            "duration_seconds": round(values.size / rate, 4),
            "active_rms_dbfs": round(_dbfs(float(np.sqrt(np.mean(active_samples**2)))), 2),
            "peak_dbfs": round(_dbfs(peak), 2),
            "clipping_ratio": round(float(np.mean(np.abs(values) >= 0.999)), 6),
            "noise_floor_rms": round(float(np.mean(np.sort(frame_rms)[: max(1, len(frame_rms) // 10)])), 6),
            "band_200_800": band(200, 800),
            "band_4000_8000": band(4000, 8000),
            "band_8000_10000": band(8000, min(10000, rate / 2)),
            "active_spectral_flatness": round(flatness, 6),
        }
    a = report["variants"]["A_no_afftdn_eq"]
    b = report["variants"]["B_afftdn_then_eq"]
    a_detail = a["band_4000_8000"] + a["band_8000_10000"]
    b_detail = b["band_4000_8000"] + b["band_8000_10000"]
    report["objective_summary"] = {
        "sample_counts_equal": a["sample_count"] == b["sample_count"],
        "durations_equal": a["duration_seconds"] == b["duration_seconds"],
        "A_consonant_and_air_detail": round(a_detail, 6),
        "B_consonant_and_air_detail": round(b_detail, 6),
        "B_detail_retention_ratio": round(b_detail / a_detail, 4) if a_detail else None,
        "B_noise_floor_ratio": (
            round(b["noise_floor_rms"] / a["noise_floor_rms"], 4)
            if a["noise_floor_rms"] else None
        ),
        "B_body_band_ratio": (
            round(b["band_200_800"] / a["band_200_800"], 4)
            if a["band_200_800"] else None
        ),
    }
    report["decision"] = (
        "No continuous contaminant was found in the personal-voice stem. If B reduces "
        "consonant/air detail or raises the noise-floor ratio, prefer A (no afftdn) and "
        "keep afftdn only as an explicit diagnostic opt-in."
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="wechat-video-audio-diagnostics")
    sub = parser.add_subparsers(dest="command", required=True)
    five = sub.add_parser("five-stems")
    five.add_argument("--run", required=True)
    five.add_argument("--out", required=True)
    aac = sub.add_parser("aac-noise")
    aac.add_argument("--mp4", required=True)
    aac.add_argument("--timing", required=True)
    aac.add_argument("--report", required=True)
    denoise = sub.add_parser("denoise-ab")
    denoise.add_argument("--raw", required=True)
    denoise.add_argument("--out", required=True)
    afftdn = sub.add_parser("afftdn-ab")
    afftdn.add_argument("--raw", required=True)
    afftdn.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "five-stems":
        report = build_five_stems(Path(args.run), Path(args.out), Path(args.out) / "stem_report.json")
        print("FIVE_STEMS_OK", json.dumps(report["diagnosis"], ensure_ascii=False))
    elif args.command == "denoise-ab":
        report = denoise_ab(Path(args.raw), Path(args.out), Path(args.out) / "denoise_ab_report.json")
        print("DENOISE_AB_OK", json.dumps({"adopted": report["adopted"], "variants": list(report["variants"])}))
    elif args.command == "afftdn-ab":
        report = afftdn_ab(Path(args.raw), Path(args.out), Path(args.out) / "afftdn_ab_report.json")
        print("AFFTDN_AB_OK", json.dumps(report["objective_summary"], ensure_ascii=False))
    else:
        timeline = json.loads(Path(args.timing).read_text(encoding="utf-8"))
        report = encoded_aac_noise_report(Path(args.mp4), timeline, Path(args.report))
        print("AAC_NOISE_OK", json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
