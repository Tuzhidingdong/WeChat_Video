from __future__ import annotations

import json
import wave
from pathlib import Path

import numpy as np

from wechat_video.master_config import (
    audio_config,
    theme_config,
    theme_color,
    voice_eq_filter_chain,
)
from wechat_video.media import mix_final_audio
from wechat_video.sfx import generate_ambient, generate_sfx
from wechat_video.visual_stages import build_motion_manifest


ROOT = Path(__file__).resolve().parents[1]


def test_master_configs_are_complete_and_domain_neutral() -> None:
    theme = theme_config(str(ROOT))
    audio = audio_config(str(ROOT))
    assert theme["theme_id"]
    assert theme["palette"]["resistance"] == "#F08A5D"
    assert theme["palette"]["driving_force"] == "#61D6C8"
    assert theme["palette"]["critical"] == "#FFD166"
    assert theme["palette"]["neutral"] == "#F4F7FB"
    assert theme["portrait_grid"]["science_top_percent"] == 20
    assert theme["portrait_grid"]["science_bottom_percent"] == 66
    assert theme["portrait_grid"]["bottom_ui_reserve_percent"] == 20
    assert theme["portrait_grid"]["right_ui_reserve_percent"] == 15
    assert theme["dimension_visual_mapping"]["2D"]["geometry"].startswith("annulus")
    assert theme["dimension_visual_mapping"]["3D"]["geometry"].startswith("isometric")
    assert theme["focus_rules"]["primary_curve_opacity_during_motion"] == 1.0
    assert theme["hook_pattern"]["static_title_card_allowed"] is False
    assert "critical radius" in " ".join(theme["semantic_roles"]["critical"]).lower()
    assert audio["preset_id"] == "voice_clarity_v1"
    assert "highpass" in audio["required_ffmpeg_filters"]
    assert audio["ambient_bed"]["rms_target_dbfs"] == -30.0
    assert audio["sfx"]["relative_level_db"] == -13.5


def test_eq_filter_chain_is_built_from_config_values() -> None:
    audio = audio_config(str(ROOT))
    chain = voice_eq_filter_chain(audio)
    eq = audio["voice_eq"]
    assert f"highpass=f={eq['highpass_hz']}" in chain
    assert f"f={eq['low_mid_hz']}:t=q:w={eq['low_mid_q']}:g={eq['low_mid_gain_db']}" in chain
    assert f"f={eq['presence_hz']}:t=q:w={eq['presence_q']}:g={eq['presence_gain_db']}" in chain
    assert f"highshelf=f={eq['air_hz']}:g={eq['air_gain_db']}" in chain
    assert theme_color("resistance") == theme_config()["palette"]["resistance"]


def test_ambient_bed_is_continuous_and_on_target(tmp_path: Path) -> None:
    path = tmp_path / "ambient.wav"
    info = generate_ambient(path, 44100 * 3, 44100, -30.0, 400)
    assert info["sample_count"] == 44100 * 3
    assert -33.0 <= info["measured_rms_dbfs"] <= -29.5
    with wave.open(str(path), "rb") as reader:
        assert reader.getnframes() == 44100 * 3


def test_mix_has_ambient_in_gaps_and_relative_sfx_without_clipping(tmp_path: Path) -> None:
    rate = 44100
    narration = tmp_path / "narration.wav"
    samples = np.zeros(rate * 3, dtype=np.float32)
    samples[rate : 2 * rate] = 0.25 * np.sin(
        2 * np.pi * 220 * np.arange(rate) / rate
    ).astype(np.float32)
    with wave.open(str(narration), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes((samples * 32767).astype("<i2").tobytes())

    sfx_dir = tmp_path / "sfx"
    generate_sfx(sfx_dir, sample_rate=rate)
    events = [
        {
            "event_id": "sfx_test",
            "file": "sfx/seed_flip.wav",
            "start_sample": rate + 1000,
            "end_sample": rate + 2000,
        }
    ]
    mix_path = tmp_path / "final_mix.wav"
    report = mix_final_audio(narration, events, tmp_path, mix_path, config=audio_config(str(ROOT)))
    assert report["sample_count"] == rate * 3
    assert report["clipped_samples"] == 0
    assert report["ambient_bed"]["enabled"] is True
    assert report["ambient_bed"]["continuous_through_gaps"] is True
    assert -33 <= report["ambient_bed"]["measured_rms_dbfs"] <= -30
    assert report["voice_peak_dbfs"] <= -3.0 + 0.2
    assert report["sfx_events"]
    for event in report["sfx_events"]:
        relative = event["measured_sfx_rms_dbfs"] - event["local_voice_rms_dbfs"]
        assert -15.0 <= relative <= -12.0
    with wave.open(str(mix_path), "rb") as reader:
        mixed = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2")
    gap = mixed[:rate]
    assert np.any(gap != 0), "Ambient bed must fill the hard-silence gap"


def test_motion_manifest_encodes_opposite_paths_and_focus() -> None:
    script = json.loads((ROOT / "content" / "sample_script.en.json").read_text(encoding="utf-8"))
    units = script["speech_units"]
    cues = [
        {
            "unit_id": u["unit_id"],
            "start_ms": 1000 + index * 3000,
            "end_ms": 1000 + index * 3000 + 2500,
        }
        for index, u in enumerate(units)
    ]
    manifest = build_motion_manifest(cues, units)
    by_type = {event["motion_type"]: event for event in manifest["events"]}
    sub = by_type["subcritical_return"]
    sup = by_type["supercritical_descent"]
    assert sub["crosses_threshold"] is False
    assert sub["path_end_x"] < sub["threshold_x"]
    assert sub["easing"] == "reverse_after_approach"
    assert sub["marker_fade_end"] == 0.0
    assert sup["path_start_x"] > sup["threshold_x"]
    assert sup["monotonic"] is True
    assert sup["easing"] == "p_squared"
    assert sub["graph_opacity_during_motion"] == 1.0
    assert sup["marker_opacity_during_motion"] == 1.0
