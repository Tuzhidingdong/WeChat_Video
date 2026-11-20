from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import soundfile as sf

from wechat_video.fact_card import (
    FactCardError,
    load_fact_card,
    validate_script_claim_links,
)
from wechat_video.model_setup import _model_dir_valid
from wechat_video.preflight import find_font
from wechat_video.subtitles import _wrap_text, write_subtitles
from wechat_video.tooling import model_root
from wechat_video.tts import LocalTtsError, _create_engine, engine_label
from wechat_video.visual_stages import build_stage_manifest, stage_for_unit


ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


def _layout() -> dict:
    return json.loads((ROOT / "configs" / "layout.json").read_text(encoding="utf-8"))


def _english_script() -> dict:
    return json.loads((ROOT / "content" / "sample_script.en.json").read_text(encoding="utf-8"))


def test_repository_fact_card_gate_blocks_pending_card() -> None:
    card = ROOT / "fact_cards" / "critical_nucleus_free_energy_candidate.json"
    sources = ROOT / "fact_cards" / "sources.json"
    loaded, _, pending = load_fact_card(card, sources, allow_pending_review=True)
    assert loaded["approval_status"] == "DRAFT_PENDING_USER_REVIEW"
    assert pending is True
    with pytest.raises(FactCardError):
        load_fact_card(card, sources, allow_pending_review=False)


def test_english_script_has_no_cjk_and_valid_claim_links() -> None:
    script = _english_script()
    assert script["language"] == "en-US"
    visible = [script["title"], script["pronunciation_review_text"]]
    for unit in script["speech_units"]:
        visible.extend([unit["raw_text"], unit["display_text"], unit["spoken_text"]])
    assert all(not CJK.search(text) for text in visible)

    card, _, _ = load_fact_card(
        ROOT / "fact_cards" / "critical_nucleus_free_energy_candidate.json",
        ROOT / "fact_cards" / "sources.json",
        allow_pending_review=True,
    )
    validate_script_claim_links(script, card)


def test_visual_stage_mapping_is_unique_and_manifest_consistent() -> None:
    script = _english_script()
    cues = [
        {
            "unit_id": unit["unit_id"],
            "start_ms": 1000 + index * 6000,
            "end_ms": 1000 + index * 6000 + 5000,
        }
        for index, unit in enumerate(script["speech_units"])
    ]
    manifest = build_stage_manifest(cues, script["speech_units"], fps=30)
    ids = [stage["stage_id"] for stage in manifest["stages"]]
    assert len(ids) == len(set(ids))
    assert all(stage["active_stage"] == stage["stage_id"] for stage in manifest["stages"])
    assert all(
        stage["transition_start_frame"] <= stage["transition_end_frame"] <= stage["end_frame"]
        for stage in manifest["stages"]
    )
    assert stage_for_unit(script["speech_units"][4])[0] == "critical_threshold"


def test_layout_uses_symmetric_portrait_content_band() -> None:
    layout = _layout()
    canvas = layout["canvas"]
    assert (canvas["width"], canvas["height"], canvas["fps"]) == (1080, 1920, 30)
    zones = layout["safe_zones"]
    assert zones["left_margin_percent"] == zones["right_reserved_percent"] == 15
    assert (zones["science_content_top_percent"], zones["science_content_bottom_percent"]) == (10, 68)
    assert (zones["subtitle_top_percent"], zones["subtitle_bottom_percent"]) == (68, 78)
    family, font_path = find_font(layout["subtitle"]["preferred_fonts"])
    assert family in layout["subtitle"]["preferred_fonts"]
    assert Path(font_path).is_file()


def test_subtitles_use_global_origin_and_english_font(tmp_path: Path) -> None:
    work = tmp_path / "english path with spaces"
    work.mkdir()
    timeline = {
        "speech_units": [
            {
                "display_text": "The critical radius separates growth from dissolution.",
                "start_ms": 1000,
                "end_ms": 2500,
            }
        ]
    }
    count = write_subtitles(
        timeline,
        work / "captions.srt",
        work / "captions.ass",
        _layout(),
        "Arial",
    )
    assert count == 1
    srt = (work / "captions.srt").read_text(encoding="utf-8-sig")
    ass = (work / "captions.ass").read_text(encoding="utf-8-sig")
    assert "00:00:01,000 --> 00:00:02,500" in srt
    assert "Dialogue: 0,0:00:01.00,0:00:02.50,Default" in ass
    assert "Style: Default,Arial" in ass
    assert not CJK.search(srt) and not CJK.search(ass)


def test_english_subtitle_wrapping_does_not_split_words() -> None:
    text = (
        "Why do some tiny crystal nuclei disappear, while others keep growing? "
        "The answer is energy competition."
    )
    wrapped = _wrap_text(text, 38)
    assert "\n" in wrapped
    assert " ".join(wrapped.split()) == " ".join(text.split())


def test_default_model_is_piper_english_and_legacy_is_preserved() -> None:
    default = model_root()
    assert default.name == "vits-piper-en_US-lessac-medium"
    assert _model_dir_valid(default)
    assert engine_label(default).startswith("sherpa-onnx Piper VITS")
    legacy = ROOT / "assets" / "models" / "vits-melo-tts-zh_en"
    assert legacy.is_dir() and _model_dir_valid(legacy)


def test_personal_voice_profile_registered_and_ab_samples_valid() -> None:
    profile = ROOT / "private" / "voice_profile"
    metadata_path = profile / "voice_profile.json"
    assert metadata_path.is_file()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["base_speaker"] == "EN-US"
    assert len(metadata["fingerprint"]) == 64
    assert metadata["watermark_preserved"] is True
    assert (profile / "target_se.pth").is_file()
    for name in ("ab_base_en_us.wav", "ab_user_voice_en.wav"):
        info = sf.info(str(profile / name))
        assert info.frames > 0 and info.samplerate > 0


def test_offline_tts_rejects_missing_model_without_fallback(tmp_path: Path) -> None:
    with pytest.raises(LocalTtsError, match="Offline TTS model file missing"):
        _create_engine(tmp_path / "absent_model")
