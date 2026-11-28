"""Focused tests: article-specific visual theme really drives the Flow prompt."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from wechat_video import micro_visual_pipeline as pipeline
from wechat_video.micro_visual_content_summary import generate_content_only_summary
from wechat_video.micro_visual_article_source import find_fresh_summary_candidates
from wechat_video.micro_visual_plan import build_micro_visual_spec
from wechat_video.micro_visual_summary_source import select_sentence
from wechat_video.micro_visual_theme import (
    VisualThemeError, compile_visual_prompt, extract_visual_theme,
)
from wechat_video.article_source import load_article_package

ROOT = Path(__file__).resolve().parents[1]
ARTICLE_DIR = ROOT / "runtime/upstream_article_packages/100000884_0/20261124T145207-d1e7fee3"
PLANNER_SUMMARY = (
    ROOT / "runtime/micro_visual_article/"
    "20261128_100000884_0_micro_visual_identity_fix_20261128_161543/planner/summary.json"
)
RUN_ID = "mv-test-theme-integration"
CONFIG = {
    "model": "Omni Flash 1.2", "duration_seconds": 15, "aspect_ratio": "9:16",
    "resolution": "720p", "output_count": 1, "stop_before_flow_submit": True,
}


def _field(text: str) -> dict[str, Any]:
    return {
        "text": text, "kind": "scientific", "supporting_claim_ids": ["C2"],
        "supporting_source_excerpts": ["胶束在乳液界面的横向铺展"],
        "evidence_paraphrase": text,
    }


def _candidate(cid: str, subject: str, action: str, environment: str) -> dict[str, Any]:
    return {
        "candidate_id": cid,
        "subject": _field(subject),
        "action": _field(action),
        "environment": _field(environment),
        "selection_rationale": "one continuous shot grounded in the source",
        "relationship_to_core_finding": "core_phenomenon",
        "scientific_uncertainties": [],
        "unsupported_visual_details": [],
    }


def _theme_from_article(subject: str, action: str, environment: str) -> dict[str, Any]:
    selected = _candidate("A", subject, action, environment)
    if "micelle" not in subject:
        selected["action"]["evidence_paraphrase"] = action
        selected["subject"]["evidence_paraphrase"] = subject
        selected["environment"]["evidence_paraphrase"] = environment
    return {
        "schema_version": 2,
        "article_id": "100000884_0",
        "source_article_sha256": "0f3456a638798e44eef071d6710bd9644b727aab619dcb05cfe0ce5f9511b7f2",
        "run_id": RUN_ID,
        "candidates": [selected, _candidate("B", "unrelated crystals", "grow", "vacuum")],
        "selected_candidate_id": "A",
        "selection_summary": "clearest single shot",
    }


def _runner_from_article(subject: str, action: str, environment: str):
    observed: dict[str, Any] = {}

    def run(root: Path, cfg: dict[str, Any], *, prompt: str, attachments: list[Path]):
        observed["attachments"] = attachments
        observed["agent"] = cfg.get("opencode", {}).get("agent")
        observed["summary_text"] = Path(attachments[0]).read_text(encoding="utf-8")
        observed["article_text"] = Path(attachments[1]).read_text(encoding="utf-8")
        return _theme_from_article(subject, action, environment)

    return run, observed


def test_theme_extraction_reads_real_summary_and_article(tmp_path: Path) -> None:
    summary = tmp_path / "summary.json"
    shutil.copy2(PLANNER_SUMMARY, summary)
    runner, observed = _runner_from_article(
        "composite micelles", "spread laterally", "along an emulsion droplet interface"
    )
    theme = extract_visual_theme(
        ROOT, summary_path=summary, article_dir=ARTICLE_DIR, output_dir=tmp_path / "theme",
        deps={"run_agent": runner, "load_daily_config": lambda _root: {"opencode": {}}},
    )
    assert observed["agent"] == "micro-visual-theme-extractor"
    assert observed["attachments"] == [summary, ARTICLE_DIR / "article.md"]
    assert "cm⁻²" in observed["summary_text"]  # real scientific symbols preserved
    assert "复合胶束" in observed["article_text"] or "胶束" in observed["article_text"]
    assert theme["candidates"][0]["action"]["text"] == "spread laterally"
    assert (tmp_path / "theme" / "visual_theme.json").is_file()


def test_stage_a_failure_blocks_and_stage_b_requires_stage_a(tmp_path: Path) -> None:
    summary = tmp_path / "summary.json"
    shutil.copy2(PLANNER_SUMMARY, summary)

    def failing_runner(*_a: object, **_k: object) -> None:
        raise VisualThemeError("theme extraction failed")

    with pytest.raises(VisualThemeError):
        extract_visual_theme(
            ROOT, summary_path=summary, article_dir=ARTICLE_DIR, output_dir=tmp_path / "theme",
            deps={"run_agent": failing_runner, "load_daily_config": lambda _root: {"opencode": {}}},
        )
    with pytest.raises(VisualThemeError, match="schema_version"):
        compile_visual_prompt({}, CONFIG)


def test_prompt_changes_with_article_theme_but_keeps_fixed_constraints() -> None:
    first = compile_visual_prompt(_theme_from_article(
        "composite micelles", "spread laterally", "along an emulsion droplet interface"
    ), CONFIG)
    second = compile_visual_prompt(_theme_from_article(
        "tin electrodes", "accumulate deposits", "in a liquid electrolyte"
    ), CONFIG)
    assert first != second
    assert "composite micelles spread laterally" in first
    assert "tin electrodes accumulate deposits" in second
    for prompt in (first, second):
        assert "15 second 9:16" in prompt
        assert "Resolution: 720p. Output count: 1." in prompt
        assert "No visible text" in prompt
        assert "No captions or subtitles" in prompt
        assert "Instrumental music only" in prompt
        assert "no human voice" in prompt.lower()
        assert "Do not extend" in prompt
        assert "No Chinese" not in prompt


def test_final_flow_prompt_uses_stage_b_theme_not_fixed_template(tmp_path: Path) -> None:
    summary_path = tmp_path / "planner_summary.json"
    shutil.copy2(PLANNER_SUMMARY, summary_path)
    summary_root = tmp_path / "outputs" / "mv1"
    summary_run_dir = generate_content_only_summary(
        ROOT, article_dir=ARTICLE_DIR, summary_path=summary_path,
        output_root=summary_root, run_id=RUN_ID,
        source_metadata={"run_id": "20261124T145207-d1e7fee3",
                         "slot1_path": str(ARTICLE_DIR / "article.md"),
                         "slot1_sha256": __import__("hashlib").sha256(
                             (ARTICLE_DIR / "article.md").read_bytes()).hexdigest()},
    )
    runner, observed = _runner_from_article(
        "composite micelles", "spread laterally", "along an emulsion droplet interface"
    )

    def theme_dep(root: Path, **kwargs: Any) -> dict[str, Any]:
        return extract_visual_theme(
            root, deps={"run_agent": runner, "load_daily_config": lambda _r: {"opencode": {}}},
            **kwargs,
        )

    deps = {
        "load_config": lambda _root: dict(CONFIG),
        "prepare_article_source": lambda _root, _cfg, **_kw: {
            "state": "ARTICLE_SOURCE_READY",
            "job_id": "20261128_100000884_0_micro_visual_theme_test",
            "selected_article": {"article_id": "100000884_0", "run_id": "20261124T145207-d1e7fee3"},
            "summary_run_dir": str(summary_run_dir),
            "planner_summary_path": str(summary_path),
            "article_package_dir": str(ARTICLE_DIR),
            "summary_input_root": str(summary_root),
            "discovery": {},
        },
        "find_candidate_summaries": lambda root, *, input_root: find_fresh_summary_candidates(
            root, input_root=input_root
        ),
        "select_sentence": select_sentence,
        "extract_visual_theme": theme_dep,
        "compile_visual_prompt": compile_visual_prompt,
        "dedup_used_keys": lambda _root: {"sentence": set(), "visual_prompt": set(), "scene_recipe": set()},
        "record_dedup": lambda *_a, **_k: None,
    }
    result = pipeline.run_literature_micro_visual(
        tmp_path, deps=deps, run_id=RUN_ID
    )
    assert result["state"] == "STOPPED_BEFORE_FLOW_SUBMIT"
    prompt = result["flow_prompt"]
    assert "composite micelles spread laterally" in prompt
    assert "One continuous microscopic scene in a clear liquid environment" not in prompt
    assert observed["attachments"][0] == summary_run_dir / "summary.json"
    assert observed["attachments"][1] == ARTICLE_DIR / "article.md"
    binding = json.loads(
        (tmp_path / "outputs" / result["job_id"] / "visual_theme_binding.json").read_text(encoding="utf-8")
    )
    assert binding["run_id"] == RUN_ID
    assert binding["article_specific_theme"] is True
    assert binding["visual_theme_sha256"]
    # Article-specific evidence stays traceable to real claims.
    summary = json.loads((summary_run_dir / "summary.json").read_text(encoding="utf-8"))
    assert any("胶束" in item["statement"] for item in summary["claims"])
