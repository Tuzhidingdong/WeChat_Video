from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .audio_diagnostics import encoded_aac_noise_report
from .channels_metadata import build_channels_metadata
from .fact_card import FactCardError, load_fact_card, read_json, validate_script_claim_links
from .master_config import audio_config, theme_config
from .media import assemble_final_video, mix_final_audio, probe_media
from .preflight import run_preflight
from .qa import run_qa
from .render import render_critical_nucleus_scene
from .sfx import generate_sfx
from .subtitles import write_subtitles
from .topic_approval import verify_fact_card_approval
from .timeline import attach_editorial_events, build_audio_timeline, write_timeline
from .tooling import model_root as configured_model_root
from .tts import generate_speech_units
from .visual_stages import build_motion_manifest, build_stage_manifest


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_script_markdown(path: Path, script: dict[str, Any]) -> None:
    lines = [
        "# Slice A Bilingual Script",
        "",
        f"- Script ID: {script.get('script_id', '')}",
        f"- Title: {script.get('title', '')}",
        f"- Language: {script.get('language', '')}",
        "",
    ]
    for unit in script["speech_units"]:
        lines.extend(
            [
                f"## {unit['unit_id']} — {unit.get('rhythm_block_id', '')}",
                "",
                f"- English: {unit['spoken_text']}",
                f"- 中文: {unit['display_text_zh']}",
                f"- Claim IDs: {', '.join(unit['claim_ids'])}",
                f"- Visual triggers: {', '.join(unit['visual_trigger_ids'])}",
                f"- Pause after: {unit.get('pause_after_ms', 280)} ms",
                "",
            ]
        )
    lines.extend(
        [
            "## Pronunciation review",
            "",
            script.get("pronunciation_review_text", ""),
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _make_logger(run_dir: Path) -> logging.Logger:
    logger = logging.getLogger(f"wechat_video.{run_dir.name}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.FileHandler(run_dir / "run.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(stream)
    return logger


def _build_storyboard(script: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "storyboard_id": "CNT-STORYBOARD-001",
        "scene_template": "critical_nucleus_free_energy_barrier",
        "scene_family_count": 1,
        "scene_count": 1,
        "question": script.get("title", "Why do some nuclei grow while others dissolve?"),
        "sequence": [
            {
                "scene_id": "scene_00_cover",
                "start_ms": 0,
                "end_ms": 1000,
                "template": "explicit_cover",
            },
            {
                "scene_id": "scene_01_energy_competition",
                "template": "critical_nucleus_free_energy_barrier",
                "description": "One critical-nucleus template presents the competing energy terms, the free-energy curve, and the critical radius.",
            },
        ],
        "cue_checkpoints": [
            {
                "unit_id": unit["unit_id"],
                "claim_ids": unit["claim_ids"],
                "visual_trigger_ids": unit["visual_trigger_ids"],
                "rhythm_block_id": unit.get("rhythm_block_id"),
                "time_source": "audio_timing.json measured speech-unit boundaries",
            }
            for unit in script["speech_units"]
        ],
        "rhythm_blocks": script.get("rhythm_blocks", []),
        "editorial_beats": [
            {"trigger": key, "purpose": value}
            for key, value in {
                "HOOK": "counter-intuitive hook",
                "CONFLICT": "surface vs bulk conflict",
                "AREA_SCALING": "r² vs r³ crossover",
                "CRITICAL_PEAK": "critical-radius peak",
                "TAKEAWAY": "final practical takeaway",
            }.items()
        ],
        "registered_template_only": True,
        "no_generated_executable_scene_code": True,
    }


def run_slice_a(
    project_root: Path,
    *,
    card_path: Path,
    script_path: Path,
    output_root: Path,
    allow_pending_review: bool = False,
) -> Path:
    project_root = project_root.resolve()
    card_path = card_path.resolve()
    script_path = script_path.resolve()
    source_path = project_root / "fact_cards" / "sources.json"

    card, source_doc, pending = load_fact_card(
        card_path,
        source_path,
        allow_pending_review=True,
    )
    topic_approval = verify_fact_card_approval(
        project_root, card_path, source_path
    )
    if pending and topic_approval is not None:
        pending = False
    elif pending and not allow_pending_review:
        raise FactCardError(
            "Fact Card 尚未获批准。请先运行 approve-fact-card 一次性批准该选题；"
            "审阅样片仍可使用 --review-sample，但不得上传。"
        )
    script = read_json(script_path)
    validate_script_claim_links(script, card)

    run_id = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    run_dir = (project_root / output_root / f"{run_id}_critical_nucleus").resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "audio").mkdir()
    logger = _make_logger(run_dir)
    logger.info("Slice A run started: %s", run_id)
    logger.info("Fact Card: %s; approval_status=%s", card["fact_card_id"], card["approval_status"])

    shutil.copy2(card_path, run_dir / "fact_card.json")
    shutil.copy2(source_path, run_dir / "source_record.json")
    shutil.copy2(script_path, run_dir / "script.json")
    _write_script_markdown(run_dir / "script_en.md", script)
    _write_json(
        run_dir / "channels_draft.json",
        build_channels_metadata(card, script, run_id, account_name="成核生长"),
    )
    layout = read_json(project_root / "configs" / "layout.json")
    _write_json(run_dir / "layout_profile.json", layout)

    logger.info("Running project-environment preflight.")
    environment = run_preflight(project_root, require_tts_model=True)
    _write_json(run_dir / "environment_report.json", environment)
    font_family = environment["font_family"]

    units = script["speech_units"]
    model_root = configured_model_root(project_root)
    logger.info("Generating %d English speech units with the personal voice profile.", len(units))
    tts_results = generate_speech_units(
        model_root,
        units,
        run_dir / "audio",
        script["pronunciation_review_text"],
    )
    voice_manifest_path = run_dir / "voice_generation_manifest.json"
    voice_manifest = (
        json.loads(voice_manifest_path.read_text(encoding="utf-8"))
        if voice_manifest_path.is_file()
        else {}
    )
    _write_json(
        run_dir / "audio_manifest.json",
        {
            "engine": voice_manifest.get("engine", "MeloTTS EN-US -> OpenVoice V2 (personal profile)"),
            "provider": voice_manifest.get("provider", "cpu"),
            "voice_profile": voice_manifest.get("voice_profile"),
            "voice_profile_fingerprint": voice_manifest.get("voice_profile_fingerprint"),
            "base_speaker": voice_manifest.get("base_speaker"),
            "watermark_preserved": voice_manifest.get("watermark_preserved"),
            "cleanup_steps": voice_manifest.get("cleanup_steps", {}),
            "speech_units": tts_results,
        },
    )

    logger.info("Measuring audio chunks and building the global timeline.")
    audio_probes = {
        item["unit_id"]: probe_media(Path(item["audio_file"]))
        for item in tts_results
    }
    narration_wav = run_dir / "narration.wav"
    timeline = build_audio_timeline(
        units,
        audio_dir=run_dir / "audio",
        output_wav=narration_wav,
        ffprobe_records=audio_probes,
    )
    sfx_durations = generate_sfx(
        run_dir / "sfx", sample_rate=int(timeline["audio_sample_rate"])
    )
    attach_editorial_events(timeline, units, sfx_durations)
    write_timeline(run_dir / "audio_timing.json", timeline)
    if not (55_000 <= int(timeline["total_duration_ms"]) <= 65_000):
        logger.warning(
            "Measured narration is %.2fs, outside the preferred 55–65s window; "
            "speech will not be accelerated or stretched.",
            timeline["total_duration_seconds"],
        )

    storyboard = _build_storyboard(script)
    for index, cue in enumerate(timeline["speech_units"]):
        storyboard["cue_checkpoints"][index].update(
            {
                "start_ms": cue["start_ms"],
                "end_ms": cue["end_ms"],
                "duration_ms": cue["end_ms"] - cue["start_ms"],
            }
        )
    _write_json(run_dir / "storyboard.json", storyboard)

    stage_manifest = build_stage_manifest(
        timeline["speech_units"], units, fps=int(timeline["fps"])
    )
    _write_json(run_dir / "visual_stage_manifest.json", stage_manifest)
    motion_manifest = build_motion_manifest(
        timeline["speech_units"], units, fps=int(timeline["fps"])
    )
    _write_json(run_dir / "motion_event_manifest.json", motion_manifest)
    logger.info(
        "Visual stages: %s", ", ".join(s["stage_id"] for s in stage_manifest["stages"])
    )

    cjk_font = environment["cjk_font"]["family"]
    subtitle_count = write_subtitles(
        timeline,
        run_dir / "captions.srt",
        run_dir / "captions.ass",
        layout,
        font_family,
        cjk_font_family=cjk_font,
    )
    _write_json(
        run_dir / "subtitle_layout_report.json",
        {
            "latin_font": environment["latin_font"],
            "cjk_font": environment["cjk_font"],
            "latin_font_size": layout["subtitle"]["latin_font_size"],
            "cjk_font_size": layout["subtitle"]["cjk_font_size"],
            "en_y_percent": layout["subtitle"]["en_y_percent"],
            "zh_y_percent": layout["subtitle"]["zh_y_percent"],
            "safe_rect": layout["subtitle"]["safe_rect"],
            "cue_count": subtitle_count,
            "bilingual_lines_per_cue": 2,
        },
    )
    scene_spec = {
        "scene_id": "scene_01_energy_competition",
        "font_family": font_family,
        "cjk_font_family": cjk_font,
        "layout": layout,
        "stage_scale_report": str(run_dir / "stage_scale_report.json"),
        "total_duration_ms": timeline["total_duration_ms"],
        "cue_checkpoints": [
            {
                "unit_id": cue["unit_id"],
                "start_ms": cue["start_ms"],
                "end_ms": cue["end_ms"],
                "duration_ms": cue["end_ms"] - cue["start_ms"],
                "visual_trigger_ids": cue["visual_trigger_ids"],
            }
            for cue in timeline["speech_units"]
        ],
    }

    logger.info("Rendering the single critical-nucleus Manim template.")
    scene_video = render_critical_nucleus_scene(project_root, run_dir, scene_spec)
    _write_json(
        run_dir / "scene_render_manifest.json",
        {
            "template": "critical_nucleus_free_energy_barrier",
            "scene_video": str(scene_video),
            "resolution": [1080, 1920],
            "fps": 30,
            "camera_mode": "static portrait camera for Slice A",
            "safe_zone_profile": layout["profile_id"],
        },
    )

    logger.info("Mixing narration with sparse local SFX and normalizing video.")
    final_mix = run_dir / "final_mix.wav"
    audio_master = audio_config(str(project_root))
    mix_report = mix_final_audio(
        narration_wav,
        timeline["sfx_events"],
        run_dir,
        final_mix,
        config=audio_master,
        timeline=timeline,
    )
    _write_json(run_dir / "audio_mix_report.json", mix_report)
    eq_ab_source = (
        project_root
        / "private"
        / "voice_profile"
        / "candidates"
        / "voice_eq_ab_report.json"
    )
    if eq_ab_source.is_file():
        shutil.copy2(eq_ab_source, run_dir / "voice_eq_ab_report.json")
    theme_master = theme_config(str(project_root))
    _write_json(run_dir / "theme_config_snapshot.json", theme_master)
    _write_json(run_dir / "audio_postprocess_snapshot.json", audio_master)
    expected_frames = round(
        int(timeline["total_sample_count"])
        * int(timeline["fps"])
        / int(timeline["audio_sample_rate"])
    )
    assembly = assemble_final_video(
        scene_video,
        final_mix,
        run_dir / "captions.ass",
        run_dir / "final.mp4",
        run_dir,
        expected_frames,
        config=audio_master,
    )
    _write_json(run_dir / "assembly_report.json", assembly)
    aac_noise = encoded_aac_noise_report(
        run_dir / "final.mp4", timeline, run_dir / "aac_noise_report.json"
    )
    candidate_quality = (
        project_root
        / "private"
        / "voice_profile"
        / "candidates"
        / "voice_quality_report.json"
    )
    if candidate_quality.is_file():
        shutil.copy2(candidate_quality, run_dir / "voice_quality_report.json")

    logger.info("Running media and synchronization QA.")
    qa = run_qa(
        run_dir / "final.mp4",
        narration_wav,
        timeline,
        subtitle_count,
        run_dir / "qa_report.json",
        context={
            "audio_manifest": json.loads((run_dir / "audio_manifest.json").read_text(encoding="utf-8")),
            "environment": environment,
            "motion_manifest": motion_manifest,
            "subtitle_layout": json.loads(
                (run_dir / "subtitle_layout_report.json").read_text(encoding="utf-8")
            ),
            "audio_master": audio_master,
            "theme_master": theme_master,
            "mix_report": mix_report,
            "aac_noise": aac_noise,
            "voice_eq_ab": json.loads((run_dir / "voice_eq_ab_report.json").read_text(encoding="utf-8"))
            if (run_dir / "voice_eq_ab_report.json").is_file()
            else None,
        },
    )
    if pending:
        approval_label = "NOT_FOR_PUBLICATION_PENDING_USER_FACT_CARD_REVIEW"
    elif qa.get("overall_status") == "PASS":
        approval_label = "QA_GATED_UNPUBLISHED_DRAFT_ELIGIBLE"
    else:
        approval_label = "NOT_UPLOAD_ELIGIBLE_QA_FAILED"

    _write_json(
        run_dir / "review_status.json",
        {
            "fact_card_approval_status": (
                "APPROVED_LOCAL_HASH_BOUND"
                if topic_approval and topic_approval.get("approval_type") == "local_hash_bound"
                else card["approval_status"]
            ),
            "topic_approval_record": (
                {
                    "approval_type": topic_approval.get("approval_type"),
                    "approved_by": topic_approval.get("approved_by"),
                    "approved_at": topic_approval.get("approved_at"),
                }
                if topic_approval
                else None
            ),
            "sample_status": approval_label,
            "user_video_acceptance": "NOT_REQUIRED_FOR_DRAFT; USER_REVIEW_BEFORE_PUBLISH",
            "automatic_upload": False,
            "automatic_publication": False,
        },
    )

    review = [
        "# Slice A review package",
        "",
        f"- Run: {run_id}",
        "- MP4: final.mp4",
        f"- Measured duration: {timeline['total_duration_seconds']:.2f}s",
        f"- QA: {qa['overall_status']}",
        f"- Fact Card status: {card['approval_status']}",
        f"- Review boundary: {approval_label}",
        "",
        "## Review notes before publication",
        "",
        "1. Compare private/voice_profile/candidates A/B WAVs and judge voice identity and cleanliness.",
        "2. Listen to audio/pronunciation_review.wav and every speech unit for US-English pronunciation.",
        "3. Inspect final.mp4 on a phone: English/Chinese subtitles, safe zones, motion and cue synchronization.",
        "4. Check motion_event_manifest.json against the rendered frames for real motion in every rhythm block.",
        "5. Confirm the sign convention and thermodynamic-vs-kinetic caveat in fact_card.json.",
        "6. Draft upload requires a valid one-time Fact Card approval and strict QA PASS.",
        "7. The user reviews the saved unpublished draft and manually publishes; no automatic publication occurs.",
        "",
        "This run does not connect to Edge, WeChat, Flow, OpenCode, or any upload endpoint.",
    ]
    (run_dir / "REVIEW.md").write_text("\n".join(review) + "\n", encoding="utf-8")
    logger.info("Slice A sample created: %s", run_dir / "final.mp4")
    return run_dir
