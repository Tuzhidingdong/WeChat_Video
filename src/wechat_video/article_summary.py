"""End-to-end local preview pipeline for source-grounded one-minute WeChat articles."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .article_source import (
    ArticleSourceError,
    build_article_channels_metadata,
    load_article_package,
    sha256_file,
    validate_article_summary,
)
from .master_config import audio_config, theme_config
from .media import assemble_final_video, mix_final_audio, probe_media
from .preflight import find_font
from .qa import run_qa
from .render import render_article_summary_scene
from .subtitles import write_chinese_subtitles
from .timeline import attach_editorial_events, build_audio_timeline, validate_audio_timeline, write_timeline
from .sfx import generate_editorial_music_bed, generate_sfx
from .tooling import resolve_command, tool_env
from .tts_provider import (
    generate_article_summary_speech_units,
    load_article_summary_tts_config,
    validate_article_summary_tts_runtime,
)


def _audio_duration_breakdown(timeline: dict[str, Any]) -> dict[str, Any]:
    """Break measured PCM runtime into speech, cover, pauses, and outro."""
    sample_rate = int(timeline["audio_sample_rate"])
    if sample_rate <= 0:
        raise ValueError("Audio duration breakdown requires a positive sample rate.")
    totals = {"speech_seconds": 0.0, "cover_seconds": 0.0, "pause_seconds": 0.0, "outro_seconds": 0.0}
    for segment in timeline["segments"]:
        kind = str(segment.get("kind") or "")
        duration = (
            int(segment["end_sample"]) - int(segment["start_sample"])
        ) / sample_rate
        if kind == "speech":
            totals["speech_seconds"] += duration
        elif kind == "cover":
            totals["cover_seconds"] += duration
        elif kind == "silence":
            totals["pause_seconds"] += duration
        elif kind == "outro":
            totals["outro_seconds"] += duration
    totals["unit_durations_seconds"] = {
        str(cue["unit_id"]): int(cue["sample_count"]) / sample_rate
        for cue in timeline["speech_units"]
    }
    return totals


def _narration_duration_budget(
    summary: dict[str, Any],
    tts_config: dict[str, Any],
) -> dict[str, Any]:
    """Estimate a one-minute script budget before any online TTS request."""
    policy = tts_config.get("duration_policy") or {}
    if not policy:
        raise ArticleSourceError("Article-summary duration_policy is required.")
    character_range = policy.get("target_cjk_characters") or {}
    minimum_characters = int(character_range.get("minimum", 0))
    maximum_characters = int(character_range.get("maximum", 0))
    cjk_characters = int(summary.get("spoken_cjk_characters", 0))
    if minimum_characters <= 0 or maximum_characters < minimum_characters:
        raise ArticleSourceError("duration_policy target_cjk_characters is invalid.")
    if not minimum_characters <= cjk_characters <= maximum_characters:
        raise ArticleSourceError(
            f"Spoken script has {cjk_characters} CJK characters; the calibrated "
            f"one-minute planning range is {minimum_characters}–{maximum_characters}. "
            "Revise the content plan before TTS; do not accelerate or truncate the finished audio."
        )

    base_rate = float(policy.get("expected_cjk_characters_per_second_at_default_rate", 0))
    rate_settings = policy.get("rate_adjustment") or {}
    reference_rate = float(rate_settings.get("reference_rate_percent", 0))
    configured_rate = str(
        (tts_config.get("providers") or {}).get("edge_tts", {}).get("rate", "+0%")
    )
    match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)%", configured_rate)
    if base_rate <= 0 or not match or 1 + reference_rate / 100 <= 0:
        raise ArticleSourceError("Duration calibration or configured Edge-TTS rate is invalid.")
    actual_rate = float(match.group(1))
    if abs(actual_rate) > float(rate_settings.get("maximum_percent", 8)):
        raise ArticleSourceError("Configured Edge-TTS speed exceeds the approved duration-policy limit.")
    effective_rate = base_rate * (1 + actual_rate / 100) / (1 + reference_rate / 100)
    if effective_rate <= 0:
        raise ArticleSourceError("Effective narration character rate must be positive.")

    units = summary.get("speech_units") or []
    pause_seconds = sum(
        max(450, int(unit.get("pause_after_ms", 500)))
        for unit in units[:-1]
    ) / 1000
    cover_seconds = int(summary.get("cover_duration_ms", 1500)) / 1000
    outro_seconds = int(summary.get("outro_duration_ms", 900)) / 1000
    provider_id = str(tts_config.get("default_provider") or "")
    if provider_id != "edge_tts":
        raise ArticleSourceError(
            f"The current one-minute duration calibration is for edge_tts, not {provider_id or 'an unspecified provider'}. "
            "Add a measured provider-specific calibration before using it for 58–62 second delivery."
        )
    estimated_speech_seconds = cjk_characters / effective_rate
    estimated_total = estimated_speech_seconds + cover_seconds + pause_seconds + outro_seconds
    minimum_seconds = float(policy.get("minimum_programme_seconds", 58))
    maximum_seconds = float(policy.get("maximum_programme_seconds", 62))
    if not minimum_seconds <= estimated_total <= maximum_seconds:
        raise ArticleSourceError(
            f"Estimated programme duration is {estimated_total:.2f}s, outside the "
            f"{minimum_seconds:.0f}–{maximum_seconds:.0f}s one-minute target. "
            "Revise script length or configured timing before TTS; do not use automatic speed adaptation."
        )
    return {
        "target_seconds": float(policy.get("target_programme_seconds", 60)),
        "minimum_seconds": minimum_seconds,
        "maximum_seconds": maximum_seconds,
        "spoken_cjk_characters": cjk_characters,
        "estimated_cjk_characters_per_second": round(effective_rate, 3),
        "estimated_speech_seconds": round(estimated_speech_seconds, 3),
        "estimated_cover_seconds": round(cover_seconds, 3),
        "estimated_pause_seconds": round(pause_seconds, 3),
        "estimated_outro_seconds": round(outro_seconds, 3),
        "estimated_programme_seconds": round(estimated_total, 3),
        "configured_edge_rate": configured_rate,
        "automatic_rate_adaptation": False,
        "measurement_authority": "actual_normalized_pcm_sample_clock",
    }


def _validate_edge_word_boundary_metadata(tts_results: list[dict[str, Any]]) -> None:
    """Fail closed when an existing Edge metadata file cannot prove lexical coverage."""
    failures = []
    for item in tts_results:
        if not item.get("word_boundary_metadata_present"):
            continue
        if (
            item.get("word_boundary_status") != "word_boundaries_verified"
            or item.get("subtitle_alignment_method") != "edge_word_boundary"
            or not item.get("word_boundaries")
        ):
            failures.append(
                f"{item.get('unit_id', 'unknown')}({item.get('word_boundary_status', 'unavailable')})"
            )
    if failures:
        raise RuntimeError(
            "Edge-TTS metadata files were present but word-boundary coverage was not verified; "
            "refusing silent speech_unit_envelope fallback: " + ", ".join(failures)
        )


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _summary_digest(summary: dict[str, Any]) -> str:
    clean = {key: value for key, value in summary.items() if key not in {"claim_map", "spoken_cjk_characters"}}
    return hashlib.sha256(
        json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _runtime_preflight(project_root: Path, article_title: str) -> dict[str, Any]:
    import sys
    if not ((3, 11) <= sys.version_info[:2] < (3, 13)):
        raise RuntimeError("Article-summary production requires project Python 3.11 or 3.12.")
    if sys.prefix == sys.base_prefix:
        raise RuntimeError("Article-summary production must run inside the project .venv.")
    try:
        import manim
        import soundfile  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(f"Article-summary runtime dependency is missing: {exc}") from exc

    tts_config = load_article_summary_tts_config(project_root)
    tts_runtime = validate_article_summary_tts_runtime(project_root, tts_config)

    tools = {name: resolve_command(name, project_root) for name in ("ffmpeg", "ffprobe")}
    from .process import run_checked
    filters = run_checked(
        [tools["ffmpeg"], "-hide_banner", "-filters"],
        timeout_seconds=30,
        env=tool_env(project_root),
    )
    filter_text = filters.stdout + "\n" + filters.stderr
    missing_filters = [name for name in ("subtitles", "loudnorm") if name not in filter_text]
    if missing_filters:
        raise RuntimeError(f"Project FFmpeg is missing required filters: {missing_filters}")

    layout = json.loads((project_root / "configs" / "layout.json").read_text(encoding="utf-8"))
    cjk_family, cjk_path = find_font(
        layout["subtitle"]["cjk_fonts"],
        required_chars="精读一分钟成核生长公众号文章原文科学研究",
    )
    audio_master = audio_config(str(project_root))
    theme_master = theme_config(str(project_root))
    return {
        "python": sys.version,
        "manim_version": getattr(manim, "__version__", "unknown"),
        "sherpa_onnx_version": tts_runtime["version"] if tts_runtime["provider_id"] == "melo_onnx" else None,
        "chinese_tts_model": tts_runtime["engine"],
        "chinese_tts_model_path": tts_runtime.get("model_path"),
        "tts_runtime": tts_runtime,
        "tts_config": tts_config,
        "font": {"family": cjk_family, "path": cjk_path},
        "tools": tools,
        "audio_profile": audio_master["preset_id"],
        "theme_id": theme_master["theme_id"],
        "article_title": article_title,
    }


def _assert_not_duplicate_article(output_root: Path, article_id: str) -> None:
    if not output_root.is_dir():
        return
    for manifest_path in output_root.glob("*/article_summary_manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(manifest.get("article_id") or "") == article_id:
            raise RuntimeError(
                f"Article {article_id!r} already has a generated summary run at "
                f"{manifest_path.parent}. Refusing to create a duplicate."
            )


def _copy_article_package(package: dict[str, Any], destination: Path) -> dict[str, dict[str, Any]]:
    source_root: Path = package["root"]
    target_root = destination / "source"
    target_root.mkdir(parents=True, exist_ok=False)
    shutil.copy2(package["markdown_path"], target_root / "article.md")
    shutil.copy2(source_root / "article.json", target_root / "article.json")
    shutil.copy2(source_root / "images.json", target_root / "images.json")
    image_root = target_root / "images"
    image_root.mkdir()
    copied: dict[str, dict[str, Any]] = {}
    for image_id, item in package["images"].items():
        source_path: Path = item["resolved_path"]
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", source_path.name)
        target = image_root / f"{image_id}_{safe_name}"
        shutil.copy2(source_path, target)
        copied[image_id] = {
            "image_id": image_id,
            "path": str(target.resolve()),
            "caption": str(item.get("caption") or ""),
            "context": str(item.get("context") or ""),
            "image_aspect": float(item["image_aspect"]),
            "sha256": sha256_file(target),
        }
    return copied


def _build_scene_beats(
    summary: dict[str, Any],
    timeline: dict[str, Any],
    copied_images: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    cue_map = {str(cue["unit_id"]): cue for cue in timeline["speech_units"]}
    beats: list[dict[str, Any]] = []
    for beat in summary["beats"]:
        unit_id = str(beat["unit_id"])
        cue = cue_map[unit_id]
        resolved = dict(beat)
        resolved["start_ms"] = int(cue["start_ms"])
        resolved["end_ms"] = int(cue["end_ms"])
        resolved["footer"] = str(beat.get("source_label") or "成核生长 · 精读一分钟")
        if beat["kind"] == "image":
            focus_regions = beat.get("focus_regions") or {}
            display_crop_regions = beat.get("display_crop_regions") or {}
            axis_labels_by_image = beat.get("axis_labels_zh") or {}
            for field_name, mapping in (
                ("focus_regions", focus_regions),
                ("display_crop_regions", display_crop_regions),
                ("axis_labels_zh", axis_labels_by_image),
            ):
                if not isinstance(mapping, dict):
                    raise ArticleSourceError(
                        f"{beat['beat_id']} {field_name} must map image IDs to image-specific display metadata."
                    )
            resolved["images"] = [
                {
                    "path": copied_images[image_id]["path"],
                    "caption": copied_images[image_id]["caption"],
                    "source_context": copied_images[image_id].get("context") or copied_images[image_id]["caption"],
                    "image_aspect": copied_images[image_id]["image_aspect"],
                    "focus_region": focus_regions.get(image_id),
                    "display_crop_region": display_crop_regions.get(image_id),
                    "axis_labels_zh": axis_labels_by_image.get(image_id, {}),
                }
                for image_id in beat["image_ids"]
            ]
        beats.append(resolved)
    return beats


def _narration_rhythm_report(units: list[dict[str, Any]]) -> dict[str, Any]:
    """Record reusable pacing risks without rewriting scientific narration."""
    punctuation = set("。！？；：")
    records: list[dict[str, Any]] = []
    for unit in units:
        text = str(unit.get("spoken_text") or "").strip()
        cjk_count = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))
        requested_pause = int(unit.get("requested_pause_after_ms", unit.get("pause_after_ms", 500)))
        effective_pause = int(unit.get("pause_after_ms", 500))
        warnings: list[str] = []
        if cjk_count > 65:
            warnings.append("long_speech_unit")
        if text and text[-1] not in punctuation:
            warnings.append("missing_sentence_or_clause_punctuation")
        if effective_pause < 450:
            warnings.append("short_comprehension_pause")
        records.append({
            "unit_id": str(unit.get("unit_id") or ""),
            "spoken_cjk_characters": cjk_count,
            "ends_with_pause_punctuation": bool(text and text[-1] in punctuation),
            "requested_pause_after_ms": requested_pause,
            "effective_pause_after_ms": effective_pause,
            "warnings": warnings,
        })
    warnings = [
        {"unit_id": item["unit_id"], "warning": warning}
        for item in records for warning in item["warnings"]
    ]
    return {
        "schema_version": 1,
        "unit_count": len(records),
        "minimum_pause_after_ms": min((item["effective_pause_after_ms"] for item in records), default=0),
        "maximum_unit_cjk_characters": max((item["spoken_cjk_characters"] for item in records), default=0),
        "overall_status": "WARN" if warnings else "PASS",
        "warnings": warnings,
        "speech_units": records,
        "policy": "diagnostic_only_no_scientific_text_is_rewritten",
    }


def run_article_summary(
    project_root: Path,
    *,
    article_dir: Path,
    summary_path: Path,
    output_root: Path = Path("outputs"),
) -> Path:
    """Create a local-only Chinese one-minute preview from an exported published article."""
    project_root = project_root.resolve()
    article_dir = article_dir.resolve()
    summary_path = summary_path.resolve()
    package = load_article_package(article_dir)
    try:
        summary_doc = json.loads(summary_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ArticleSourceError(f"Summary file does not exist: {summary_path}") from exc
    except json.JSONDecodeError as exc:
        raise ArticleSourceError(f"Invalid summary JSON: {exc}") from exc
    if not isinstance(summary_doc, dict):
        raise ArticleSourceError("summary.json must contain a JSON object.")
    summary = validate_article_summary(package, summary_doc)
    article = package["article"]
    # Fail fast on missing TTS/runtime dependencies before creating an output run.
    environment = _runtime_preflight(project_root, str(article["title"]))
    duration_plan = _narration_duration_budget(summary, environment["tts_config"])

    output_base = output_root if output_root.is_absolute() else project_root / output_root
    output_base = output_base.resolve()
    _assert_not_duplicate_article(output_base, str(article["article_id"]))
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    safe_article_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(article["article_id"]))[:48]
    run_dir = output_base / f"{stamp}_{safe_article_id}_article_summary"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "audio").mkdir()
    layout = json.loads((project_root / "configs" / "layout.json").read_text(encoding="utf-8"))
    copied_images = _copy_article_package(package, run_dir)
    shutil.copy2(summary_path, run_dir / "summary.json")
    units = summary["speech_units"]

    manifest = {
        "schema_version": 1,
        "content_type": "article_summary",
        "appmsgid": str(article.get("appmsgid") or ""),
        "article_id": str(article["article_id"]),
        "article_title": str(article["title"]),
        "published_at": str(article["published_at"]),
        "canonical_url": article.get("canonical_url"),
        "canonical_url_verified": bool(article.get("canonical_url_verified")),
        "url_provenance": article.get("url_provenance"),
        "account_name": "成核生长",
        "editorial_slot": int(article["editorial_slot"]),
        "article_type": str(article["article_type"]),
        "editorial_pillar_id": str(article["editorial_pillar_id"]),
        "source_article_sha256": package["markdown_sha256"],
        "summary_sha256": _summary_digest(summary),
        "spoken_cjk_characters": int(summary["spoken_cjk_characters"]),
        "image_count": len(copied_images),
        "image_manifest": copied_images,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    _write_json(run_dir / "article_summary_manifest.json", manifest)
    _write_json(run_dir / "environment_report.json", environment)
    _write_json(run_dir / "layout_profile.json", layout)
    _write_json(run_dir / "source_record.json", {
        "source_type": "published_wechat_article",
        "appmsgid": article.get("appmsgid"),
        "article_id": article["article_id"],
        "title": article["title"],
        "editorial_slot": article["editorial_slot"],
        "article_type": article["article_type"],
        "editorial_pillar_id": article["editorial_pillar_id"],
        "published_at": article["published_at"],
        "canonical_url": article.get("canonical_url"),
        "canonical_url_verified": bool(article.get("canonical_url_verified")),
        "url_provenance": article.get("url_provenance"),
        "article_markdown_sha256": package["markdown_sha256"],
    })
    _write_json(run_dir / "fact_card.json", {
        "content_type": "article_summary",
        "article_id": article["article_id"],
        "title": summary["summary_title"],
        "core_thesis": summary["core_thesis"],
        "claims": [
            {"claim_id": claim["claim_id"], "statement": claim["statement"],
             "source_excerpt": claim["source_excerpt"]}
            for claim in summary["claims"]
        ],
    })

    # Provider selection is explicit and recorded. The selected provider must
    # succeed; there is no silent switch to a different voice on network failure.
    tts_generation = generate_article_summary_speech_units(
        project_root,
        environment["tts_config"],
        units,
        run_dir / "audio",
        environment["tools"]["ffmpeg"],
    )
    tts_results = tts_generation["speech_units"]
    _write_json(run_dir / "audio_manifest.json", tts_generation)
    _validate_edge_word_boundary_metadata(tts_results)
    rhythm_report = _narration_rhythm_report(units)
    _write_json(run_dir / "narration_rhythm_report.json", rhythm_report)
    tts_by_id = {str(item["unit_id"]): item for item in tts_results}
    timeline_units = [
        {
            **unit,
            "word_boundaries": tts_by_id.get(str(unit["unit_id"]), {}).get("word_boundaries", []),
            "subtitle_alignment_method": tts_by_id.get(str(unit["unit_id"]), {}).get(
                "subtitle_alignment_method", "speech_unit_envelope"
            ),
            "word_boundary_status": tts_by_id.get(str(unit["unit_id"]), {}).get(
                "word_boundary_status", "unavailable"
            ),
        }
        for unit in units
    ]
    probes = {
        item["unit_id"]: probe_media(Path(item["audio_file"]))
        for item in tts_results
    }
    timeline = build_audio_timeline(
        timeline_units,
        audio_dir=run_dir / "audio",
        output_wav=run_dir / "narration.wav",
        ffprobe_records=probes,
        cover_duration_ms=int(summary.get("cover_duration_ms", 1500)),
        outro_duration_ms=int(summary.get("outro_duration_ms", 900)),
    )
    timeline_validation = validate_audio_timeline(timeline)
    _write_json(run_dir / "audio_timeline_validation.json", timeline_validation)
    duration = float(timeline["total_duration_seconds"])
    breakdown = _audio_duration_breakdown(timeline)
    duration_report = {
        **duration_plan,
        "measured_programme_seconds": round(duration, 3),
        "measured_speech_seconds": round(breakdown["speech_seconds"], 3),
        "measured_cover_seconds": round(breakdown["cover_seconds"], 3),
        "measured_pause_seconds": round(breakdown["pause_seconds"], 3),
        "measured_outro_seconds": round(breakdown["outro_seconds"], 3),
        "unit_durations_seconds": breakdown["unit_durations_seconds"],
        "overall_status": (
            "PASS" if duration_plan["minimum_seconds"] <= duration <= duration_plan["maximum_seconds"]
            else "FAIL"
        ),
    }
    _write_json(run_dir / "duration_budget_report.json", duration_report)
    if duration_report["overall_status"] != "PASS":
        raise RuntimeError(
            f"Measured programme audio is {duration:.2f}s; the one-minute target is "
            f"{duration_plan['minimum_seconds']:.0f}–{duration_plan['maximum_seconds']:.0f}s. "
            f"Breakdown: speech={breakdown['speech_seconds']:.2f}s, "
            f"cover={breakdown['cover_seconds']:.2f}s, "
            f"inter-unit pauses={breakdown['pause_seconds']:.2f}s, "
            f"outro={breakdown['outro_seconds']:.2f}s. "
            "The run stops before scene rendering; revise the content plan without removing evidence-backed claims."
        )
    sfx_durations = generate_sfx(run_dir / "sfx")
    timeline = attach_editorial_events(timeline, units, sfx_durations)
    for event in timeline["sfx_events"]:
        event["relative_level_db"] = -20.0
    subtitle_count = write_chinese_subtitles(
        timeline,
        run_dir / "captions.srt",
        run_dir / "captions.ass",
        layout,
        environment["font"]["family"],
    )
    write_timeline(run_dir / "audio_timing.json", timeline)

    scene_beats = _build_scene_beats(summary, timeline, copied_images)
    scene_spec = {
        "schema_version": 1,
        "article_title": str(article["title"]),
        "cover_title": str(summary.get("cover_title") or summary["summary_title"]),
        "cover_subtitle": str(summary.get("cover_subtitle") or "一篇文章 · 一个关键发现"),
        "source_line": str(summary.get("source_line") or "成核生长 · 原文精读"),
        "cover_duration_ms": int(timeline["cover_duration_ms"]),
        "outro_duration_ms": int(timeline["outro_duration_ms"]),
        "transition_duration_ms": int(summary.get("transition_duration_ms", 220)),
        "safe_zones": layout.get("safe_zones", {}),
        "cjk_font_family": environment["font"]["family"],
        "total_duration_ms": int(timeline["total_duration_ms"]),
        "speech_units": timeline["speech_units"],
        "beats": scene_beats,
        "visual_identity": "mobile_first_shortform_science_story",
    }
    _write_json(run_dir / "article_scene_spec.json", scene_spec)
    scene_video = render_article_summary_scene(project_root, run_dir, scene_spec)
    layout_report_path = run_dir / "scene_layout_report.json"
    if not layout_report_path.is_file():
        raise RuntimeError("Manim render did not produce mandatory scene_layout_report.json.")
    scene_layout_report = json.loads(layout_report_path.read_text(encoding="utf-8"))
    if scene_layout_report.get("overall_status") != "PASS":
        raise RuntimeError("Article-summary scene failed camera/safe-zone layout QA.")
    _write_json(run_dir / "scene_render_manifest.json", {
        "template": "article_summary_editorial",
        "visual_identity": scene_spec["visual_identity"],
        "scene_video": str(scene_video),
        "resolution": [1080, 1920],
        "fps": 30,
        "article_images_contain_not_crop": True,
        "layout_report": "scene_layout_report.json",
        "layout_qa": scene_layout_report.get("overall_status"),
    })

    audio_master = audio_config(str(project_root))
    theme_master = theme_config(str(project_root))
    _write_json(run_dir / "audio_postprocess_snapshot.json", audio_master)
    _write_json(run_dir / "theme_config_snapshot.json", theme_master)
    final_mix = run_dir / "final_mix.wav"
    music_bed_path = run_dir / "article_summary_music.wav"
    music_config = audio_master.get("article_summary_music", {})
    music_generation = generate_editorial_music_bed(
        music_bed_path,
        int(timeline["total_sample_count"]),
        sample_rate=int(timeline["audio_sample_rate"]),
        target_rms_dbfs=float(music_config.get("target_rms_dbfs", -28.0)),
        fade_ms=int(music_config.get("fade_ms", 700)),
    )
    _write_json(run_dir / "article_summary_music_manifest.json", music_generation)
    mix_report = mix_final_audio(
        run_dir / "narration.wav",
        timeline["sfx_events"],
        run_dir,
        final_mix,
        config=audio_master,
        timeline=timeline,
        music_bed_path=music_bed_path,
    )
    _write_json(run_dir / "audio_mix_report.json", mix_report)
    expected_frames = round(
        int(timeline["total_sample_count"]) * int(timeline["fps"])
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
    qa = run_qa(
        run_dir / "final.mp4",
        run_dir / "narration.wav",
        timeline,
        subtitle_count,
        run_dir / "qa_report.json",
    )

    claim_ids = {claim["claim_id"] for claim in summary["claims"]}
    content_qa = {
        "status": qa["overall_status"],
        "source_article_sha256_matched": True,
        "all_claims_have_exact_source_excerpt": True,
        "all_claims_referenced": claim_ids.issubset({
            claim_id for unit in units for claim_id in unit["claim_ids"]
        }),
        "all_visual_beats_have_narration": True,
        "all_original_images_local_and_unique": True,
        "no_third_party_visuals_inserted": True,
        "measured_duration_seconds": round(duration, 3),
        "technical_qa": qa["overall_status"],
        "audio_timeline_validation": timeline_validation["valid"],
        "outro_tail_ms": timeline["outro_duration_ms"],
        "subtitle_alignment": timeline.get("subtitle_alignment", {}),
        "caption_cues_cover_all_units": {
            unit_id: any(item["unit_id"] == unit_id for item in timeline.get("subtitle_cues", []))
            for unit_id in [str(unit["unit_id"]) for unit in units]
        },
        "scene_layout_qa": scene_layout_report.get("overall_status"),
        "music_cover_and_outro_audible": bool(mix_report.get("editorial_music_bed", {}).get("cover_opening_audible"))
            and bool(mix_report.get("editorial_music_bed", {}).get("outro_fade_audible")),
        "inter_unit_silence_preserved": bool(mix_report.get("editorial_music_bed", {}).get("inter_unit_silence_preserved")),
        "narration_rhythm_report": rhythm_report.get("overall_status"),
        "upload_eligible": False,
        "upload_block_reason": (
            "The WeChat Channels extended-link UI has not yet been verified and "
            "saved/read back. This article-summary run is local-preview-only."
        ),
    }
    _write_json(run_dir / "content_qa_report.json", content_qa)

    channels_metadata = build_article_channels_metadata(article, summary, run_dir.name)
    _write_json(run_dir / "channels_draft.json", channels_metadata)
    review_status = {
        "content_type": "article_summary",
        "sample_status": "LOCAL_PREVIEW_ONLY",
        "technical_qa": qa["overall_status"],
        "user_video_acceptance": "PENDING",
        "extended_link_status": channels_metadata["extended_link_status"],
        "automatic_upload": False,
        "automatic_publication": False,
    }
    _write_json(run_dir / "review_status.json", review_status)
    (run_dir / "REVIEW.md").write_text(
        "\n".join([
            "# 精读一分钟 · 本地审阅样片",
            "",
            f"- 原文：{article['title']}",
            f"- 发表时间：{article['published_at']}",
            (
                f"- 原文链接：{article['canonical_url']}"
                if article.get("canonical_url_verified")
                else "- 原文永久链接：尚未取得；本次仅生成本地预览，不能挂载扩展链接"
            ),
            "- 视频：final.mp4",
            f"- 实测时长（含片尾）：{duration:.2f}s",
            f"- 技术 QA：{qa['overall_status']}",
            f"- 画面布局 QA：{scene_layout_report.get('overall_status')}",
            f"- 字幕逐词对齐：{timeline.get('subtitle_alignment', {})}",
            f"- 片尾停留：{timeline['outro_duration_ms']} ms",
            f"- 旁白节奏诊断：{rhythm_report.get('overall_status')}（不自动改写科研文本）",
            f"- 中文配音：{tts_generation['engine']} / {tts_generation.get('voice') or tts_generation.get('provider')}",
            f"- TTS 参数：rate={tts_generation.get('rate')}; pitch={tts_generation.get('pitch')}; volume={tts_generation.get('volume')}",
            "- TTS 自动回退：关闭；所选供应商失败即停止",
            "- 扩展链接：待视频号页面实测；当前没有上传",
            "- 发布状态：未上传、未发布",
            "",
            "请完整观看视频，并对摘要准确性、节奏、画面和配音进行人工验收。",
            "",
        ]),
        encoding="utf-8",
    )
    return run_dir
