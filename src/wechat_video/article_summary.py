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
from .timeline import build_audio_timeline, write_timeline
from .tooling import legacy_model_root, resolve_command, tool_env


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
        import sherpa_onnx
        import soundfile  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(f"Article-summary runtime dependency is missing: {exc}") from exc

    model_root = legacy_model_root(project_root)
    required_model = [model_root / "model.onnx", model_root / "lexicon.txt", model_root / "tokens.txt"]
    missing = [str(path.relative_to(project_root)) for path in required_model if not path.is_file()]
    if missing:
        raise RuntimeError(
            "The local Chinese MeloTTS model is not ready: "
            + ", ".join(missing)
            + ". Run the existing download-model-zh command once; no automatic download is performed."
        )

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
        "sherpa_onnx_version": getattr(sherpa_onnx, "__version__", "unknown"),
        "chinese_tts_model": "sherpa-onnx OfflineTts / VITS MeloTTS zh_en",
        "chinese_tts_model_path": str(model_root),
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
            if not isinstance(focus_regions, dict):
                raise ArticleSourceError(
                    f"{beat['beat_id']} focus_regions must map image IDs to normalized rectangles."
                )
            resolved["images"] = [
                {
                    "path": copied_images[image_id]["path"],
                    "caption": copied_images[image_id]["caption"],
                    "image_aspect": copied_images[image_id]["image_aspect"],
                    "focus_region": focus_regions.get(image_id),
                }
                for image_id in beat["image_ids"]
            ]
        beats.append(resolved)
    return beats


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

    output_base = output_root if output_root.is_absolute() else project_root / output_root
    output_base = output_base.resolve()
    _assert_not_duplicate_article(output_base, str(article["article_id"]))
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    safe_article_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(article["article_id"]))[:48]
    run_dir = output_base / f"{stamp}_{safe_article_id}_article_summary"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "audio").mkdir()

    environment = _runtime_preflight(project_root, str(article["title"]))
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

    # Keep CLI/parser imports lightweight: the offline audio stack is runtime-only.
    from .tts import generate_chinese_speech_units

    tts_results = generate_chinese_speech_units(
        legacy_model_root(project_root),
        units,
        run_dir / "audio",
    )
    _write_json(run_dir / "audio_manifest.json", {
        "engine": "sherpa-onnx OfflineTts / VITS MeloTTS zh_en",
        "provider": "cpu",
        "voice_profile": None,
        "speech_units": tts_results,
        "online_fallback": False,
    })
    probes = {
        item["unit_id"]: probe_media(Path(item["audio_file"]))
        for item in tts_results
    }
    timeline = build_audio_timeline(
        units,
        audio_dir=run_dir / "audio",
        output_wav=run_dir / "narration.wav",
        ffprobe_records=probes,
        cover_duration_ms=int(summary.get("cover_duration_ms", 1500)),
    )
    duration = float(timeline["total_duration_seconds"])
    if not 45.0 <= duration <= 75.0:
        raise RuntimeError(
            f"Measured Chinese narration is {duration:.2f}s; expected 45–75s. "
            "Rewrite the script; playback speed will not be altered."
        )
    write_timeline(run_dir / "audio_timing.json", timeline)
    subtitle_count = write_chinese_subtitles(
        timeline,
        run_dir / "captions.srt",
        run_dir / "captions.ass",
        layout,
        environment["font"]["family"],
    )

    scene_beats = _build_scene_beats(summary, timeline, copied_images)
    scene_spec = {
        "schema_version": 1,
        "article_title": str(article["title"]),
        "cover_title": str(summary.get("cover_title") or summary["summary_title"]),
        "cover_subtitle": str(summary.get("cover_subtitle") or "一篇文章 · 一个关键发现"),
        "source_line": str(summary.get("source_line") or "成核生长 · 原文精读"),
        "cover_duration_ms": int(timeline["cover_duration_ms"]),
        "cjk_font_family": environment["font"]["family"],
        "total_duration_ms": int(timeline["total_duration_ms"]),
        "speech_units": timeline["speech_units"],
        "beats": scene_beats,
        "visual_identity": "mobile_first_shortform_science_story",
    }
    _write_json(run_dir / "article_scene_spec.json", scene_spec)
    scene_video = render_article_summary_scene(project_root, run_dir, scene_spec)
    _write_json(run_dir / "scene_render_manifest.json", {
        "template": "article_summary_editorial",
        "visual_identity": scene_spec["visual_identity"],
        "scene_video": str(scene_video),
        "resolution": [1080, 1920],
        "fps": 30,
        "article_images_contain_not_crop": True,
    })

    audio_master = audio_config(str(project_root))
    theme_master = theme_config(str(project_root))
    _write_json(run_dir / "audio_postprocess_snapshot.json", audio_master)
    _write_json(run_dir / "theme_config_snapshot.json", theme_master)
    final_mix = run_dir / "final_mix.wav"
    mix_report = mix_final_audio(
        run_dir / "narration.wav",
        [],
        run_dir,
        final_mix,
        config=audio_master,
        timeline=timeline,
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
            f"- 实测时长：{duration:.2f}s",
            f"- 技术 QA：{qa['overall_status']}",
            "- 中文离线配音：MeloTTS zh_en / CPU",
            "- 扩展链接：待视频号页面实测；当前没有上传",
            "- 发布状态：未上传、未发布",
            "",
            "请完整观看视频，并对摘要准确性、节奏、画面和配音进行人工验收。",
            "",
        ]),
        encoding="utf-8",
    )
    return run_dir
