from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .fact_card import load_fact_card, read_json, validate_script_claim_links
from .media import assemble_final_video, probe_media
from .preflight import run_preflight
from .qa import run_qa
from .render import render_critical_nucleus_scene
from .subtitles import write_subtitles
from .timeline import build_audio_timeline, write_timeline
from .tooling import model_root as configured_model_root
from .tts import generate_speech_units
from .visual_stages import build_stage_manifest


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_script_markdown(path: Path, script: dict[str, Any]) -> None:
    lines = [
        "# Slice A English Script",
        "",
        f"- Script ID: {script.get('script_id', '')}",
        f"- Title: {script.get('title', '')}",
        f"- Language: {script.get('language', '')}",
        "",
    ]
    for unit in script["speech_units"]:
        lines.extend(
            [
                f"## {unit['unit_id']}",
                "",
                f"- Spoken / displayed text: {unit['spoken_text']}",
                f"- Claim IDs: {', '.join(unit['claim_ids'])}",
                f"- Visual triggers: {', '.join(unit['visual_trigger_ids'])}",
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
                "time_source": "audio_timing.json measured speech-unit boundaries",
            }
            for unit in script["speech_units"]
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
        allow_pending_review=allow_pending_review,
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
    _write_json(
        run_dir / "audio_manifest.json",
        {"engine": "sherpa-onnx", "provider": "cpu", "speech_units": tts_results},
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
    logger.info("Visual stages: %s", ", ".join(s["stage_id"] for s in stage_manifest["stages"]))

    subtitle_count = write_subtitles(
        timeline,
        run_dir / "captions.srt",
        run_dir / "captions.ass",
        layout,
        font_family,
    )
    scene_spec = {
        "scene_id": "scene_01_energy_competition",
        "font_family": font_family,
        "layout": layout,
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

    logger.info("Normalizing video, assembling narration, and burning subtitles.")
    assembly = assemble_final_video(
        scene_video,
        narration_wav,
        run_dir / "captions.ass",
        run_dir / "final.mp4",
        run_dir,
    )
    _write_json(run_dir / "assembly_report.json", assembly)

    logger.info("Running media and synchronization QA.")
    qa = run_qa(
        run_dir / "final.mp4",
        narration_wav,
        timeline,
        subtitle_count,
        run_dir / "qa_report.json",
    )
    approval_label = (
        "NOT_FOR_PUBLICATION_PENDING_USER_FACT_CARD_REVIEW"
        if pending
        else "LOCAL_SAMPLE_PENDING_USER_VIDEO_ACCEPTANCE"
    )
    _write_json(
        run_dir / "review_status.json",
        {
            "fact_card_approval_status": card["approval_status"],
            "sample_status": approval_label,
            "user_video_acceptance": "PENDING",
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
        "## Manual review required",
        "",
        "1. Listen to audio/pronunciation_review.wav and every speech unit.",
        "2. Inspect final.mp4 on a phone-sized display.",
        "3. Check captions, formula labels, safe-zone margins, and cue synchronization.",
        "4. Confirm the sign convention and model assumptions in fact_card.json.",
        "5. Check visual_stage_manifest.json: each cue has one active stage and no previous formula remains on screen.",
        "6. Do not publish this candidate until the Fact Card and video are approved.",
        "",
        "This run does not connect to Edge, WeChat, Flow, OpenCode, or any upload endpoint.",
    ]
    (run_dir / "REVIEW.md").write_text("\n".join(review) + "\n", encoding="utf-8")
    logger.info("Slice A sample created: %s", run_dir / "final.mp4")
    return run_dir
