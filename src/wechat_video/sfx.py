"""Tiny deterministic local sound cues for Slice A visual turning points."""
from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np


SAMPLE_RATE = 44_100
PEAK = 0.06

EVENTS: dict[str, dict[str, float | int]] = {
    "seed_flip": {"duration_ms": 220, "frequency": 620.0, "kind": "pop"},
    "term_conflict": {"duration_ms": 200, "frequency": 280.0, "kind": "tone"},
    "crossover": {"duration_ms": 260, "frequency": 420.0, "kind": "whoosh"},
    "peak_reveal": {"duration_ms": 240, "frequency": 760.0, "kind": "pop"},
    "cross_threshold": {"duration_ms": 260, "frequency": 520.0, "kind": "whoosh"},
    "resolve": {"duration_ms": 300, "frequency": 660.0, "kind": "tone"},
}


def generate_sfx(out_dir: Path, sample_rate: int = SAMPLE_RATE) -> dict[str, int]:
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
            phase = 2 * math.pi * np.cumsum(frequency * (0.6 + 1.8 * t / max(t[-1], 1e-6))) / rate
            signal = np.sin(phase) + 0.18 * rng.normal(size=count)
        elif config["kind"] == "pop":
            phase = 2 * math.pi * frequency * t * (1.0 - 0.35 * t / max(t[-1], 1e-6))
            signal = np.sin(phase) + 0.25 * np.sin(2 * phase)
        else:
            signal = np.sin(2 * math.pi * frequency * t) + 0.35 * np.sin(4 * math.pi * frequency * t)
        signal = signal * envelope
        peak = float(np.max(np.abs(signal))) or 1.0
        pcm = np.clip(np.round(signal / peak * PEAK * 32767), -32768, 32767).astype("<i2")
        path = out_dir / f"{name}.wav"
        with wave.open(str(path), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(rate)
            writer.writeframes(pcm.tobytes())
        durations[name] = duration_ms
    return durations
