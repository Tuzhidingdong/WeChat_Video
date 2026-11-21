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
    assert audio["preset_id"] == "clean_voice_no_bed"
    assert audio["default_profile"] == "clean_voice_no_bed"
    assert audio["ambient_bed"]["enabled"] is False
    assert audio["noise_policy"]["default_no_continuous_noise"] is True
    assert "ambient_bed_duck_and_mix" not in audio["processing_order"]
    assert "highpass" in audio["required_ffmpeg_filters"]
    assert audio["ambient_bed"]["rms_target_dbfs"] == -30.0
    assert audio["sfx"]["relative_level_db"] == -13.5
    assert theme["stage_scale"]["target"] == 1.30
    assert 1.25 <= theme["stage_scale"]["min"] <= theme["stage_scale"]["target"] <= theme["stage_scale"]["max"] <= 1.35
    assert 0.20 <= theme["hook_ghost"]["inactive_opacity"] <= 0.25
    assert theme["formula_pulse"]["scale_peak"] == 1.18
    assert theme["ending_halo"]["period_seconds"] == 2.0


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


def test_default_mix_keeps_gaps_digitally_silent_with_relative_sfx(tmp_path: Path) -> None:
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
    timeline = {
        "speech_units": [{"unit_id": "u1", "start_sample": rate, "end_sample": 2 * rate}],
        "segments": [
            {"kind": "cover", "start_sample": 0, "end_sample": rate},
            {"kind": "silence", "start_sample": 2 * rate, "end_sample": 3 * rate},
        ],
    }
    report = mix_final_audio(
        narration, events, tmp_path, mix_path,
        config=audio_config(str(ROOT)), timeline=timeline,
    )
    assert report["sample_count"] == rate * 3
    assert report["clipped_samples"] == 0
    assert report["ambient_bed"]["enabled"] is False
    assert report["silence_diagnostics"]["voice_gaps_true_silence"] is True
    assert report["silence_diagnostics"]["final_gaps_near_digital_silence"] is True
    assert report["voice_peak_dbfs"] <= -3.0 + 0.2
    assert report["sfx_events"]
    for event in report["sfx_events"]:
        relative = event["measured_sfx_rms_dbfs"] - event["local_voice_rms_dbfs"]
        assert -15.0 <= relative <= -12.0
    with wave.open(str(mix_path), "rb") as reader:
        mixed = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2")
    assert np.all(mixed[:rate] == 0), "Default profile must not add a noise bed in the opening gap"
    assert np.all(mixed[2 * rate :] == 0), "Default profile must keep the closing gap silent"


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
    assert manifest["stage_scale"]["target"] == 1.30


def test_manifest_has_distinct_term_pulses_hook_ghost_and_halo() -> None:
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
    gamma = by_type["gamma_cubed_pulse"]
    driving = by_type["driving_force_squared_pulse"]
    assert gamma["event_id"] != driving["event_id"]
    assert gamma["pulse_term"] == "gamma"
    assert driving["pulse_term"] == "driving_force"
    assert gamma["pulse_symbol"] == r"\gamma^3"
    assert driving["pulse_symbol"] == r"\Delta g_v^2"
    assert gamma["pulse_scale_peak"] == 1.18
    assert gamma["dim_only_non_current_terms"] is True
    assert gamma["unit_id"] != driving["unit_id"]
    gamma_unit = next(u for u in units if u["unit_id"] == gamma["unit_id"])
    driving_unit = next(u for u in units if u["unit_id"] == driving["unit_id"])
    assert "surface energy cubed" in gamma_unit["spoken_text"]
    assert "driving force squared" in driving_unit["spoken_text"]
    ghost = by_type["hook_comparison_ghost"]
    assert ghost["inactive_side_never_removed"] is True
    assert 0.20 <= ghost["inactive_opacity"] <= 0.25
    halo = by_type["final_breathing_halo"]
    assert halo["period_seconds"] == 2.0
    assert halo["approx_cycles"] >= 2.0
    assert halo["critical_marker_unchanged"] is True
