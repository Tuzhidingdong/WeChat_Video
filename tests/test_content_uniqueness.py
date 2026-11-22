from __future__ import annotations

import json
from pathlib import Path

import pytest

from wechat_video.content_uniqueness import (
    build_content_fingerprint,
    compare_fingerprints,
)
from wechat_video.fact_card import FactCardError, validate_script_claim_links
from wechat_video.pipeline import (
    VISUAL_STRATEGIES,
    _build_storyboard,
    _visual_strategy,
)


def _write(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _script(script_id="S1", angle="critical_radius_growth_perspective", n=3):
    units = []
    for i in range(n):
        units.append({
            "unit_id": f"U{i:02d}",
            "raw_text": f"line {i}",
            "display_text": f"line {i}",
            "spoken_text": f"line {i}",
            "display_text_zh": f"第{i}行",
            "claim_ids": ["CNT-01"],
            "visual_trigger_ids": ["CURVE_DRAW"],
            "rhythm_block_id": "HOOK",
        })
    return {
        "script_id": script_id,
        "editorial_angle_id": angle,
        "title": "title",
        "speech_units": units,
    }


def _run(root: Path, name: str, script: dict, template="template_a", strategy="s1"):
    d = root / name
    _write(d / "script.json", script)
    _write(d / "qa_report.json", {"overall_status": "PASS"})
    _write(d / "storyboard.json", {
        "scene_template": template,
        "visual_strategy": strategy,
        "sequence": [{"scene_id": "s0", "template": template}],
    })
    _write(d / "scene_render_manifest.json", {"template": template, "visual_strategy": strategy})
    return d


def test_different_editorial_angles_produce_different_storyboards() -> None:
    a = _build_storyboard(_script(angle="critical_radius_growth_perspective"))
    b = _build_storyboard(_script(angle="free_energy_barrier_perspective"))
    assert a["scene_template"] != b["scene_template"]
    assert a["visual_strategy"] != b["visual_strategy"]
    assert a["visual_opening"] != b["visual_opening"]
    assert a["scene_template"] == "critical_nucleus_free_energy_barrier"
    assert b["scene_template"] == "critical_nucleus_barrier_peak_anatomy"


def test_visual_strategy_is_selected_by_config_not_fact_card_id() -> None:
    assert "free_energy_barrier_perspective" in VISUAL_STRATEGIES
    assert "critical_radius_growth_perspective" in VISUAL_STRATEGIES
    strategy = _visual_strategy({"editorial_angle_id": "free_energy_barrier_perspective"})
    assert strategy["visual_strategy"] == "barrier_peak_anatomy"


def test_unregistered_angle_fails_closed() -> None:
    with pytest.raises(FactCardError):
        _visual_strategy({"editorial_angle_id": "not_registered"})


def test_same_script_only_different_fact_card_title_fails_gate(tmp_path) -> None:
    script = _script()
    a = _run(tmp_path, "run_a", script)
    b = _run(tmp_path, "run_b", dict(script, title="different title"))
    fp_a, fp_b = build_content_fingerprint(a), build_content_fingerprint(b)
    result = compare_fingerprints(fp_b, [fp_a])
    assert result["passes"] is False
    assert "identical_essential_identity" in result["comparisons"][0]["reasons"]


def test_reencoded_mp4_but_same_script_fails_gate(tmp_path) -> None:
    # MP4 hash differences are not content evidence; same script must still fail.
    script = _script()
    a = _run(tmp_path, "run_a", script)
    b = _run(tmp_path, "run_b", script, template="template_a", strategy="s1")
    fp_a, fp_b = build_content_fingerprint(a), build_content_fingerprint(b)
    result = compare_fingerprints(fp_b, [fp_a])
    assert result["passes"] is False
    assert "identical_script_sha256" in result["comparisons"][0]["reasons"]


def test_truly_different_script_and_visual_passes_gate(tmp_path) -> None:
    script_a = _script(script_id="S1", angle="critical_radius_growth_perspective")
    script_b = dict(
        _script(script_id="S2", angle="free_energy_barrier_perspective"),
        speech_units=[
            dict(u, spoken_text=f"barrier line {i}",
                 visual_trigger_ids=["BARRIER_EQ" if i % 2 else "CRITICAL_PEAK"])
            for i, u in enumerate(_script(script_id="S2", n=3)["speech_units"])
        ],
    )
    a = _run(tmp_path, "run_a", script_a)
    b = _run(tmp_path, "run_b", script_b, template="template_b", strategy="barrier_peak_anatomy")
    fp_a, fp_b = build_content_fingerprint(a), build_content_fingerprint(b)
    result = compare_fingerprints(fp_b, [fp_a])
    assert result["passes"] is True
    assert fp_a["essential_identity_sha256"] != fp_b["essential_identity_sha256"]


def test_new_script_claims_are_valid() -> None:
    card = {
        "claims": [
            {"claim_id": "CNT-01", "statement": "s1"},
            {"claim_id": "CNT-03", "statement": "s3"},
        ],
        "source_ids": ["SRC-1"],
        "scientific_question": "q",
        "scope": "scope",
    }
    script = _script()
    script["speech_units"][0]["claim_ids"] = ["CNT-01", "CNT-03"]
    validate_script_claim_links(script, card)  # must not raise
    script["speech_units"][0]["claim_ids"] = ["CNT-99"]
    with pytest.raises(Exception):
        validate_script_claim_links(script, card)


def test_stage_manifest_template_follows_visual_strategy() -> None:
    from wechat_video.visual_stages import build_stage_manifest

    cues = [{"start_ms": 0, "end_ms": 3000}]
    unit = [{
        "unit_id": "V01", "visual_trigger_ids": ["CRITICAL_PEAK"],
        "rhythm_block_id": "HOOK",
    }]
    growth = build_stage_manifest(cues, unit, visual_strategy="particle_growth_curve")
    barrier = build_stage_manifest(cues, unit, visual_strategy="barrier_peak_anatomy")
    assert growth["template"] == "critical_nucleus_free_energy_barrier"
    assert barrier["template"] == "critical_nucleus_barrier_peak_anatomy"
    assert barrier["visual_strategy"] == "barrier_peak_anatomy"


def test_barrier_curve_hook_is_curve_first() -> None:
    from wechat_video.scenes.critical_nucleus import _barrier_curve_hook

    src = Path(__file__).parent.parent / "src" / "wechat_video" / "scenes" / "critical_nucleus.py"
    body = src.read_text(encoding="utf-8")
    fn = body[body.index("def _barrier_curve_hook"):body.index("class CriticalNucleusScene")]
    assert "Free energy along the pathway" in fn
    assert "r^*" in fn and "\\Delta G^*" in fn
    assert _barrier_curve_hook is not None


def test_real_barrier_script_differs_from_original(tmp_path) -> None:
    root = Path(__file__).resolve().parents[1]
    old = json.loads((root / "content" / "sample_script.en.json").read_text(encoding="utf-8"))
    new = json.loads(
        (root / "content" / "barrier_perspective_script.en.json").read_text(encoding="utf-8")
    )
    assert new["script_id"] != old["script_id"]
    assert new["editorial_angle_id"] == "free_energy_barrier_perspective"
    old_spoken = [u["spoken_text"] for u in old["speech_units"]]
    new_spoken = [u["spoken_text"] for u in new["speech_units"]]
    assert new_spoken != old_spoken
    assert sum(1 for a, b in zip(old_spoken, new_spoken) if a != b) >= len(old_spoken) / 2
    assert new["rhythm_blocks"] != old["rhythm_blocks"]
