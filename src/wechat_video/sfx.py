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
