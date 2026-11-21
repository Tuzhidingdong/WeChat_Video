from __future__ import annotations

import json
from pathlib import Path

from wechat_video.hook_motion import hook_particle_states, mean_radial_distance
from wechat_video.master_config import theme_config
from wechat_video.subtitles import write_subtitles
from wechat_video.visual_stages import build_motion_manifest


ROOT = Path(__file__).resolve().parents[1]
EXACT_VOLUME_CUE = "That gain scales with volume, r³."


def _script() -> dict:
    return json.loads((ROOT / "content" / "sample_script.en.json").read_text(encoding="utf-8"))


def _cues(units: list[dict]) -> list[dict]:
    return [
        {
            "unit_id": u["unit_id"],
            "start_ms": 1000 + index * 3000,
            "end_ms": 1000 + index * 3000 + 2500,
        }
        for index, u in enumerate(units)
    ]


def _manifest() -> dict:
    script = _script()
    return build_motion_manifest(_cues(script["speech_units"]), script["speech_units"])


def test_volume_caption_uses_superscript_three_only_for_volume() -> None:
    units = {unit["unit_id"]: unit for unit in _script()["speech_units"]}
    volume = units["U07"]
    area = units["U05"]
    assert volume["display_text"] == EXACT_VOLUME_CUE
    assert volume["raw_text"] == EXACT_VOLUME_CUE
    assert volume["spoken_text"] == "That gain scales with volume, r cubed."
    assert "r³" in volume["display_text"] and "r²" not in volume["display_text"]
    # The separate 2D area cue must remain r².
    assert area["display_text"] == "It scales with surface area, r²."
    assert "r²" in area["display_text"] and "r³" not in area["display_text"]
    assert volume["display_text_zh"] == "收益随体积立方增长。"


def test_rendered_caption_preserves_superscript_glyph(tmp_path: Path) -> None:
    units = {unit["unit_id"]: unit for unit in _script()["speech_units"]}
    timeline = {
        "speech_units": [
            {"unit_id": "U05", "display_text": units["U05"]["display_text"],
             "display_text_zh": units["U05"]["display_text_zh"],
             "start_ms": 1000, "end_ms": 3000},
            {"unit_id": "U07", "display_text": units["U07"]["display_text"],
             "display_text_zh": units["U07"]["display_text_zh"],
             "start_ms": 3000, "end_ms": 5000},
        ]
    }
    layout = {
        "canvas": {"width": 1080, "height": 1920},
        "subtitle": {
            "max_line_chars": 36, "max_line_chars_en": 36, "max_line_chars_zh": 12,
            "latin_font_size": 40, "cjk_font_size": 46,
            "en_y_percent": 70.5, "zh_y_percent": 75.5,
            "outline": 2, "shadow": 1, "margin_left": 162, "margin_right": 162,
        },
    }
    srt = tmp_path / "captions.srt"
    ass = tmp_path / "captions.ass"
    write_subtitles(timeline, srt, ass, layout, "Arial", cjk_font_family="Microsoft YaHei")
    srt_text = srt.read_text(encoding="utf-8-sig")
    ass_text = ass.read_text(encoding="utf-8-sig")
    assert EXACT_VOLUME_CUE in srt_text
    assert EXACT_VOLUME_CUE in ass_text
    assert "It scales with surface area, r²." in srt_text


def test_marker_rises_monotonically_to_peak_and_next_cue_holds() -> None:
    by_type = {e["motion_type"]: e for e in _manifest()["events"]}
    rise = by_type["rise_to_peak"]
    hold = by_type["peak_hold"]
    assert rise["follows_plotted_curve"] is True
    assert rise["monotonic_toward_peak"] is True
    assert rise["no_right_branch_travel"] is True
    xs = [s["x"] for s in rise["samples"]]
    assert xs == sorted(xs)
    assert xs[0] == 0.0
    assert xs[-1] == rise["marker_peak_x"] == 1.0
    assert rise["held_at_peak_after_fraction"] == 0.8
    assert hold["held_at_peak"] is True and hold["stationary"] is True
    assert hold["marker_start_x"] == hold["marker_end_x"] == 1.0


def test_thermo_hierarchy_and_clock_strike_through() -> None:
    by_type = {e["motion_type"]: e for e in _manifest()["events"]}
    item = by_type["affirmed_vs_excluded"]
    assert item["affirmed_read_order_first"] is True
    assert item["affirmed_position"] == "upper"
    assert item["affirmed_primary"] is True
    assert item["affirmed_mark"] == "check"
    assert item["rejected_position"] == "lower_right"
    assert item["rejected_secondary"] is True
    assert item["strike_through_over_symbol"] is True
    assert item["strike_through_visible"] is True
    theme = theme_config(str(ROOT))
    assert theme["concept_hierarchy"]["read_order"] == "affirmed_first"
    assert theme["concept_visuals"]["speed_label_zh"] == "速度"
    # Nucleation-specific wording must not leak into the global template rule.
    assert "Speed" not in json.dumps(theme["concept_hierarchy"])
    assert "r*" not in json.dumps(theme["concept_hierarchy"])


def test_hook_first_frame_particles_and_inward_outward_motion() -> None:
    first = hook_particle_states(0.0)
    assert first["active_side"] == "left"
    assert len(first["left"]) == 4
    assert all(p["opacity"] > 0.9 and p["radius"] > 0 for p in first["left"])
    assert len(first["right"]) == 4  # ghost never removed
    left_radii = [mean_radial_distance(hook_particle_states(t)["left"]) for t in (0.0, 0.5, 1.0, 1.5, 2.0)]
    assert left_radii == sorted(left_radii, reverse=True)
    assert left_radii[0] > left_radii[-1] * 5
    right_radii = [mean_radial_distance(hook_particle_states(t)["right"]) for t in (2.0, 2.5, 3.0, 3.5, 4.0)]
    assert right_radii == sorted(right_radii)
    assert hook_particle_states(3.0)["active_side"] == "right"
    manifest_event = next(
        e for e in _manifest()["events"] if e["motion_type"] == "hook_comparison_ghost"
    )
    assert manifest_event["first_frame_left_particles"] == 4
    assert manifest_event["first_frame_non_empty"] is True
    assert manifest_event["left_inward"] is True and manifest_event["right_outward"] is True


def test_accepted_visuals_are_not_regressed() -> None:
    script = _script()
    triggers = {t for unit in script["speech_units"] for t in unit["visual_trigger_ids"]}
    assert {"VOLUME_SCALING", "AREA_SCALING", "GAMMA_CUBED_PULSE",
            "DRIVING_FORCE_SQUARED_PULSE", "MODEL_ASSUMPTION",
            "SUBCRITICAL_RETURN", "SUPERCRITICAL_DESCENT"}.issubset(triggers)
    theme = theme_config(str(ROOT))
    assert theme["dimension_visual_mapping"]["3D"]["geometry"].startswith("isometric")
    assert theme["dimension_visual_mapping"]["2D"]["geometry"].startswith("annulus")
    roles = theme["formula_symbol_roles"]
    assert roles["gamma"] == "resistance"
    assert roles["delta_g_v"] == "driving_force"
    assert roles["barrier"] == "critical"
    by_type = {e["motion_type"]: e for e in _manifest()["events"]}
    assert by_type["subcritical_return"]["crosses_threshold"] is False
    assert by_type["supercritical_descent"]["monotonic"] is True
