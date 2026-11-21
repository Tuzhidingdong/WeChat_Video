from __future__ import annotations

import json
import re
import wave
from pathlib import Path

import pytest

from wechat_video import qa
from wechat_video.fact_card import load_fact_card
from wechat_video.preflight import font_supports_chars, find_font
from wechat_video.sfx import generate_sfx
from wechat_video.subtitles import write_subtitles
from wechat_video.timeline import attach_editorial_events, build_audio_timeline
from wechat_video.visual_stages import build_motion_manifest, build_stage_manifest


ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r"[\u3400-\u9fff]")


def _script() -> dict:
    return json.loads((ROOT / "content" / "sample_script.en.json").read_text(encoding="utf-8"))


def _layout() -> dict:
    return json.loads((ROOT / "configs" / "layout.json").read_text(encoding="utf-8"))


def _facts() -> set[str]:
    card, _, _ = load_fact_card(
        ROOT / "fact_cards" / "critical_nucleus_free_energy_candidate.json",
        ROOT / "fact_cards" / "sources.json",
        allow_pending_review=True,
    )
    return {claim["claim_id"] for claim in card["claims"]}


def test_bilingual_script_schema_claims_and_lengths() -> None:
    script = _script()
    units = script["speech_units"]
    assert 16 <= len(units) <= 24
    ids = [u["unit_id"] for u in units]
    assert len(ids) == len(set(ids))
    valid_claims = _facts()
    for unit in units:
        for field in ("raw_text", "display_text", "spoken_text", "display_text_zh"):
            assert unit[field].strip()
        assert not CJK.search(unit["raw_text"] + unit["display_text"] + unit["spoken_text"])
        assert CJK.search(unit["display_text_zh"])
        assert len(unit["display_text"]) <= 36
        assert len(unit["display_text_zh"]) <= 12
        assert set(unit["claim_ids"]).issubset(valid_claims)
        assert unit["rhythm_block_id"] in {
            "HOOK", "CONFLICT", "MECHANISM", "APPLICATION", "TAKEAWAY"
        }
        assert unit["visual_trigger_ids"]


def test_comprehension_pauses_are_configured() -> None:
    units = _script()["speech_units"]
    pauses = {u["unit_id"]: u["pause_after_ms"] for u in units if u["pause_after_ms"] >= 500}
    assert {"U12", "U13"}.issubset(pauses)
    assert all(500 <= value <= 800 for value in pauses.values())


def test_latin_and_cjk_fonts_are_validated_separately() -> None:
    layout = _layout()
    latin, latin_path = find_font(layout["subtitle"]["latin_fonts"])
    cjk, cjk_path = find_font(
        layout["subtitle"]["cjk_fonts"], required_chars="成核临界半径"
    )
    assert latin in layout["subtitle"]["latin_fonts"]
    assert cjk in layout["subtitle"]["cjk_fonts"]
    assert font_supports_chars(cjk_path, "成核临界半径") is True
    assert font_supports_chars(latin_path, "成核临界半径") is False


def test_stage_and_motion_manifests_cover_every_block() -> None:
    script = _script()
    units = script["speech_units"]
    cues = [
        {
            "unit_id": u["unit_id"],
            "start_ms": 1000 + index * 2500,
            "end_ms": 1000 + index * 2500 + 2200,
        }
        for index, u in enumerate(units)
    ]
    stages = build_stage_manifest(cues, units)
    ids = [s["stage_id"] for s in stages["stages"]]
    assert len(ids) == len(set(ids))
    assert all(s["active_stage"] == s["stage_id"] for s in stages["stages"])

    motion = build_motion_manifest(cues, units)
    blocks = {event["rhythm_block_id"] for event in motion["events"]}
    assert {"HOOK", "CONFLICT", "MECHANISM", "APPLICATION", "TAKEAWAY"}.issubset(blocks)
    assert all(event["dim_opacity"] == pytest.approx(0.25) for event in motion["events"])


def test_bilingual_subtitles_share_cue_timings(tmp_path: Path) -> None:
    layout = _layout()
    timeline = {
        "speech_units": [
            {
                "display_text": "A tiny radius decides.",
                "display_text_zh": "微小半径决定结果。",
                "start_ms": 1000,
                "end_ms": 2500,
            }
        ]
    }
    count = write_subtitles(
        timeline,
        tmp_path / "captions.srt",
        tmp_path / "captions.ass",
        layout,
        "Arial",
        cjk_font_family="Microsoft YaHei",
    )
    assert count == 1
    ass = (tmp_path / "captions.ass").read_text(encoding="utf-8-sig")
    srt = (tmp_path / "captions.srt").read_text(encoding="utf-8-sig")
    assert "Style: EN,Arial" in ass and "Style: ZH,Microsoft YaHei" in ass
    assert ass.count("Dialogue:") == 2
    assert "微小半径决定结果。" in srt
    assert "A tiny radius decides." in srt
    assert not CJK.search(srt.split("\n")[1])


def test_timeline_honours_per_unit_pause_and_sfx_events(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    for unit_id in ("U01", "U02"):
        with wave.open(str(audio_dir / f"{unit_id}.wav"), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(44100)
            writer.writeframes(b"\x00\x01" * 4410)
    units = [
        {
            "unit_id": "U01",
            "raw_text": "a",
            "display_text": "a",
            "display_text_zh": "甲",
            "spoken_text": "a",
            "claim_ids": ["CNT-04"],
            "visual_trigger_ids": ["SEED_FORM_DISSOLVE"],
            "rhythm_block_id": "HOOK",
            "pause_after_ms": 650,
            "sfx_trigger_id": "seed_flip",
        },
        {
            "unit_id": "U02",
            "raw_text": "b",
            "display_text": "b",
            "display_text_zh": "乙",
            "spoken_text": "b",
            "claim_ids": ["CNT-04"],
            "visual_trigger_ids": ["SEED_QUESTION"],
            "rhythm_block_id": "HOOK",
        },
    ]
    timeline = build_audio_timeline(
        units,
        audio_dir=audio_dir,
        output_wav=tmp_path / "narration.wav",
        ffprobe_records={"U01": {"streams": []}, "U02": {"streams": []}},
    )
    sfx_dir = tmp_path / "sfx"
    durations = generate_sfx(sfx_dir)
    attach_editorial_events(timeline, units, durations)
    pauses = [s for s in timeline["segments"] if s.get("kind") == "silence"]
    assert pauses[0]["duration_ms"] == 650
    event = timeline["sfx_events"][0]
    assert 0 <= event["start_sample"] < event["end_sample"] <= timeline["total_sample_count"]


def test_qa_accepts_context_only_with_true_personal_voice(tmp_path: Path, monkeypatch) -> None:
    narration = tmp_path / "narration.wav"
    with wave.open(str(narration), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(44100)
        writer.writeframes(b"\x00\x00" * 44100)
    timeline = {
        "fps": 30,
        "audio_sample_rate": 44100,
        "total_sample_count": 44100,
        "total_duration_seconds": 1.0,
        "cover": {"start_ms": 0, "end_ms": 1000},
        "speech_units": [
            {
                "unit_id": "u1",
                "start_ms": 1000,
                "end_ms": 1000,
                "display_text_zh": "中文",
            }
        ],
        "segments": [
            {"kind": "silence", "duration_ms": 650},
            {"kind": "silence", "duration_ms": 650},
        ],
        "sfx_events": [],
    }
    probe = {
        "streams": [
            {"codec_type": "video", "width": 1080, "height": 1920,
             "avg_frame_rate": "30/1", "r_frame_rate": "30/1", "pix_fmt": "yuv420p",
             "sample_aspect_ratio": "1:1", "nb_read_frames": "30"},
            {"codec_type": "audio", "codec_name": "aac", "sample_rate": "44100",
             "channels": 1, "duration": "1.0"},
        ],
        "format": {"duration": "1.0"},
    }
    from types import SimpleNamespace

    monkeypatch.setattr(qa, "probe_media", lambda *_a, **_k: probe)
    monkeypatch.setattr(qa, "resolve_command", lambda name: name)
    monkeypatch.setattr(qa, "tool_env", lambda: {})
    monkeypatch.setattr(
        qa, "run_checked",
        lambda *_a, **_k: SimpleNamespace(
            stderr=json.dumps({"input_i": "-16.2", "input_tp": "-1.6"}), stdout=""
        ),
    )
    from wechat_video.master_config import audio_config, theme_config, voice_eq_filter_chain

    audio_master = audio_config(str(ROOT))
    theme_master = theme_config(str(ROOT))
    context = {
        "audio_manifest": {
            "engine": "MeloTTS EN-US -> OpenVoice V2 ToneColorConverter (CPU)",
            "voice_profile_fingerprint": "abc",
            "cleanup_steps": {
                "clarity_eq": voice_eq_filter_chain(audio_master),
                "post_conversion": "none (disabled by default profile)",
            },
        },
        "environment": {"cjk_font": {"verified_codepoints": "成核"}},
        "motion_manifest": {
            "events": [
                {"rhythm_block_id": block, "motion_type": f"motion_{block}"} for block in
                ("HOOK", "CONFLICT", "MECHANISM", "APPLICATION", "TAKEAWAY")
            ]
            + [
                {
                    "motion_type": "subcritical_return",
                    "crosses_threshold": False,
                    "path_end_x": 0.12,
                    "graph_opacity_during_motion": 1.0,
                },
                {
                    "motion_type": "supercritical_descent",
                    "path_start_x": 1.08,
                    "monotonic": True,
                    "marker_opacity_during_motion": 1.0,
                },
            ]
        },
        "audio_master": audio_master,
        "theme_master": theme_master,
        "mix_report": {
            "voice_peak_dbfs": -6.0,
            "clipped_samples": 0,
            "ambient_bed": {"enabled": False, "profile": "clean_voice_no_bed"},
            "silence_diagnostics": {
                "gap_segments": 2,
                "voice_gaps_true_silence": True,
                "voice_gap_rms_dbfs": -120.0,
                "final_gaps_near_digital_silence": True,
                "final_gap_rms_dbfs": -120.0,
                "gap_noise_ceiling_dbfs": -45.0,
            },
            "sfx_events": [
                {
                    "measured_sfx_rms_dbfs": -28.0,
                    "local_voice_rms_dbfs": -14.5,
                }
            ],
        },
        "aac_noise": {
            "summary": {
                "speech_rms_dbfs": -18.0,
                "pause_rms_dbfs": -110.0,
                "pause_to_speech_separation_db": 92.0,
                "pause_is_near_digital_silence": True,
            }
        },
    }
    timeline["speech_units"][0]["sample_count"] = 44100
    report = qa.run_qa(Path("final.mp4"), narration, timeline, 1,
                       tmp_path / "qa.json", context=context)
    statuses = {c["check"]: c["status"] for c in report["checks"]}
    assert statuses["personal_voice_engine_truth"] == "PASS"
    assert statuses["bilingual_subtitle_cues"] == "PASS"
    assert statuses["cjk_glyph_coverage_verified"] == "PASS"
