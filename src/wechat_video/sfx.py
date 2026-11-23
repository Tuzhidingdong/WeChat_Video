"""Deterministic local sound cues and ambient bed (no sound packs, no network)."""
from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np


SAMPLE_RATE = 44_100
EVENTS: dict[str, dict[str, float | int]] = {
    "seed_flip": {"duration_ms": 220, "frequency": 180.0, "kind": "soft_pulse"},
    "term_conflict": {"duration_ms": 200, "frequency": 140.0, "kind": "soft_pulse"},
    "crossover": {"duration_ms": 260, "frequency": 210.0, "kind": "whoosh"},
    "peak_reveal": {"duration_ms": 240, "frequency": 240.0, "kind": "soft_pulse"},
    "cross_threshold": {"duration_ms": 260, "frequency": 190.0, "kind": "whoosh"},
    "resolve": {"duration_ms": 300, "frequency": 160.0, "kind": "soft_pulse"},
}


def _write_wav(path: Path, samples: np.ndarray, rate: int) -> None:
    pcm = np.clip(np.round(samples * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(pcm.tobytes())


def generate_sfx(out_dir: Path, sample_rate: int = SAMPLE_RATE) -> dict[str, int]:
    """Generate soft low-frequency cues; final relative gain is applied at mix time."""
    out_dir.mkdir(parents=True, exist_ok=True)
    durations: dict[str, int] = {}
    rng = np.random.default_rng(20261121)
    for name, config in EVENTS.items():
        duration_ms = int(config["duration_ms"])
        rate = int(sample_rate)
        count = int(rate * duration_ms / 1000)
        t = np.arange(count, dtype=np.float64) / rate
        envelope = np.sin(math.pi * np.linspace(0, 1, count)) ** 2
        frequency = float(config["frequency"])
        if config["kind"] == "whoosh":
            phase = 2 * math.pi * np.cumsum(frequency * (0.7 + 0.8 * t / max(t[-1], 1e-6))) / rate
            signal = np.sin(phase) + 0.08 * rng.normal(size=count)
        else:
            signal = np.sin(2 * math.pi * frequency * t) + 0.18 * np.sin(
                4 * math.pi * frequency * t
            )
        signal = signal * envelope
        peak = float(np.max(np.abs(signal))) or 1.0
        _write_wav(out_dir / f"{name}.wav", (signal / peak * 0.5).astype(np.float32), rate)
        durations[name] = duration_ms
    return durations


def generate_ambient(
    out_path: Path,
    sample_count: int,
    sample_rate: int,
    rms_dbfs: float,
    fade_ms: int,
) -> dict[str, float]:
    """Deterministic soft low-hiss bed with programme-boundary fades."""
    rng = np.random.default_rng(77123)
    count = int(sample_count)
    noise = rng.normal(size=count).astype(np.float64)
    # Gentle low-pass by a short moving average keeps the bed free of bright hiss.
    window = 64
    smoothed = np.convolve(noise, np.ones(window) / window, mode="same")
    rms = float(np.sqrt(np.mean(smoothed**2))) or 1.0
    target = 10 ** (rms_dbfs / 20.0)
    bed = smoothed / rms * target
    fade = int(max(0, fade_ms) * sample_rate / 1000)
    if fade > 0 and count > 2 * fade:
        envelope = np.ones(count)
        envelope[:fade] = np.linspace(0, 1, fade)
        envelope[-fade:] = np.linspace(1, 0, fade)
        bed *= envelope
    measured = float(np.sqrt(np.mean(bed**2)))
    _write_wav(out_path, bed.astype(np.float32), int(sample_rate))
    return {
        "sample_count": count,
        "sample_rate": int(sample_rate),
        "target_rms_dbfs": rms_dbfs,
        "measured_rms_dbfs": round(20 * math.log10(measured), 3) if measured > 0 else -120.0,
        "fade_ms": fade_ms,
        "texture": "soft_low_hiss",
    }


def generate_editorial_music_bed(
    out_path: Path,
    sample_count: int,
    sample_rate: int = SAMPLE_RATE,
    target_rms_dbfs: float = -28.0,
    fade_ms: int = 700,
) -> dict[str, float | int | str]:
    """Generate an original, deterministic low-level synth pad (not random noise).

    The bed is intentionally created locally, without downloaded music or samples.
    The mixer later gates it to measured speech regions so cover and inter-unit
    comprehension gaps remain genuinely silent.
    """
    count = int(sample_count)
    rate = int(sample_rate)
    if count <= 0 or rate < 8000:
        raise ValueError("Editorial music requires a positive sample count and a valid sample rate.")
    if not -40.0 <= float(target_rms_dbfs) <= -20.0:
        raise ValueError("Editorial music target RMS must be between -40 and -20 dBFS.")

    t = np.arange(count, dtype=np.float64) / rate
    # A slow four-chord progression using soft sine/triangle-like partials.
    chords = (
        (65.41, 98.00, 130.81, 196.00),   # C
        (58.27, 87.31, 116.54, 174.61),   # B-flat
        (69.30, 103.83, 138.59, 207.65),  # C-sharp / D-flat
        (61.74, 92.50, 123.47, 185.00),   # B
    )
    bar_samples = max(1, rate * 8)
    signal = np.zeros(count, dtype=np.float64)
    weights = (0.42, 0.29, 0.19, 0.10)
    bar_count = (count + bar_samples - 1) // bar_samples
    for index in range(bar_count):
        frequencies = chords[index % len(chords)]
        start = index * bar_samples
        end = min(count, start + bar_samples)
        local_t = t[start:end] - t[start]
        local = np.zeros(end - start, dtype=np.float64)
        for frequency, weight in zip(frequencies, weights):
            local += weight * np.sin(2 * math.pi * frequency * local_t)
        edge = min(rate // 4, len(local) // 2)
        if edge:
            phase = np.linspace(0.0, math.pi / 2.0, edge, endpoint=True)
            ramp = np.sin(phase) ** 2
            local[:edge] *= ramp
            local[-edge:] *= ramp[::-1]
        signal[start:end] += local
    modulation = 0.88 + 0.12 * np.sin(2 * math.pi * 0.075 * t)
    signal *= modulation
    rms = float(np.sqrt(np.mean(signal**2))) or 1.0
    signal *= (10 ** (float(target_rms_dbfs) / 20.0)) / rms

    fade_frames = min(count // 2, max(0, rate * int(fade_ms) // 1000))
    if fade_frames:
        phase = np.linspace(0.0, math.pi / 2.0, fade_frames, endpoint=True)
        ramp = np.sin(phase) ** 2
        signal[:fade_frames] *= ramp
        signal[-fade_frames:] *= ramp[::-1]

    _write_wav(out_path, signal, rate)
    measured = float(np.sqrt(np.mean(signal**2)))
    return {
        "sample_count": count,
        "sample_rate": rate,
        "target_rms_dbfs": float(target_rms_dbfs),
        "measured_rms_dbfs": 20 * math.log10(measured) if measured > 0 else -120.0,
        "fade_ms": int(fade_ms),
        "texture": "original_deterministic_harmonic_synth_pad",
    }
