"""Structural-only Stage A validation and Stage B prompt compilation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wechat_video.micro_visual_theme import (
    THEME_AGENT, VisualThemeError, compile_visual_prompt, extract_visual_theme,
    validate_theme,
)

CONFIG = {
    "model": "Omni Flash 1.2", "duration_seconds": 15, "aspect_ratio": "9:16",
    "resolution": "720p", "output_count": 1,
}
CONTEXT: dict[str, Any] = {
    "article_id": "100000884_0",
    "source_article_sha256": "a" * 64,
    "run_id": "mv-test-theme",
    "summary": {"claims": [{"claim_id": "C1", "statement": "dense deposition"}]},
    "article_text": "# article\n",
}
HAN = __import__("re").compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def _field(text: str, **overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "text": text,
        "kind": "scientific",
        "supporting_claim_ids": ["C1"],
        "supporting_source_excerpts": ["excerpt"],
        "evidence_paraphrase": text,
    }
    value.update(overrides)
    return value


def _candidate(cid: str, subject: str, action: str, environment: str) -> dict[str, Any]:
    return {
        "candidate_id": cid,
        "subject": _field(subject),
        "action": _field(action),
        "environment": _field(environment),
        "selection_rationale": "one clean continuous shot",
        "relationship_to_core_finding": "core_phenomenon",
        "scientific_uncertainties": [],
        "unsupported_visual_details": [],
    }


def _theme(**kwargs: Any) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "article_id": CONTEXT["article_id"],
        "source_article_sha256": CONTEXT["source_article_sha256"],
        "run_id": CONTEXT["run_id"],
        "candidates": [
            _candidate("A", "translucent droplets", "drift and gather along a soft boundary",
                       "a clear liquid environment"),
            _candidate("B", "unrelated crystals", "grow", "vacuum"),
        ],
        "selected_candidate_id": "A",
        "selection_summary": "clearest single shot",
        **kwargs,
    }


def test_legacy_schema_is_rejected() -> None:
    legacy = {"candidates": [], "selected": {}}
    with pytest.raises(VisualThemeError, match="schema_version"):
        compile_visual_prompt(legacy, CONFIG)


def test_empty_or_chinese_text_is_rejected() -> None:
    theme = _theme()
    theme["candidates"][0]["subject"] = _field("  ")
    with pytest.raises(VisualThemeError, match="empty"):
        validate_theme(theme, **CONTEXT)
    theme = _theme()
    theme["candidates"][0]["subject"] = _field("中文主题")
    with pytest.raises(VisualThemeError, match="Chinese"):
        validate_theme(theme, **CONTEXT)


def test_field_must_be_object_and_evidence_fields_must_be_lists() -> None:
    theme = _theme()
    theme["candidates"][0]["action"] = "grow into a layer"
    with pytest.raises(VisualThemeError, match="must be an object"):
        validate_theme(theme, **CONTEXT)
    theme = _theme()
    theme["candidates"][0]["action"] = _field("grow into a layer", supporting_claim_ids="C1")
    with pytest.raises(VisualThemeError, match="must be a list"):
        validate_theme(theme, **CONTEXT)


def test_two_candidates_and_unique_ids_required() -> None:
    theme = _theme()
    theme["candidates"] = theme["candidates"][:1]
    with pytest.raises(VisualThemeError, match="at least two"):
        validate_theme(theme, **CONTEXT)
    theme = _theme()
    theme["candidates"][1]["candidate_id"] = "A"
    with pytest.raises(VisualThemeError, match="duplicate candidate_id"):
        validate_theme(theme, **CONTEXT)


def test_selected_id_must_resolve() -> None:
    theme = _theme(selected_candidate_id="missing")
    with pytest.raises(VisualThemeError, match="does not match"):
        validate_theme(theme, **CONTEXT)


def test_run_identity_mismatch_blocks() -> None:
    with pytest.raises(VisualThemeError, match="run_id mismatch"):
        validate_theme(_theme(), run_id="another")


def test_evidence_mismatch_no_longer_blocks() -> None:
    theme = _theme()
    theme["candidates"][0]["action"] = _field(
        "grow into a smooth, dense layer",
        supporting_claim_ids=["NOT_A_CLAIM"],
        supporting_source_excerpts=["not in this article"],
        evidence_paraphrase="unrelated wording",
    )
    theme["candidates"][0]["unsupported_visual_details"] = ["smooth"]
    prompt = compile_visual_prompt(theme, CONFIG, **CONTEXT)
    assert "grow into a smooth, dense layer" in prompt
    assert "grow into a smooth, layer" not in prompt


def test_scientific_claims_and_metadata_do_not_leak() -> None:
    theme = _theme(evidence_metadata={"claim_ids": ["C9"]}, claims=["ionic flux"])
    prompt = compile_visual_prompt(theme, CONFIG)
    for value in ("C9", "私密证据", "ionic flux"):
        assert value not in prompt


def test_prompt_has_no_chinese_or_extra_visible_text() -> None:
    prompt = compile_visual_prompt(_theme(), CONFIG)
    assert HAN.search(prompt) is None
    for rule in ("No visible text", "No captions or subtitles", "No title cards",
                 "No logos, watermarks", "No letters, words, numbers or symbols"):
        assert rule in prompt
    assert "Subtitle:" not in prompt


def test_capitalized_fields_are_compiled_as_grammatical_sentence() -> None:
    theme = _theme()
    theme["candidates"][0]["subject"] = _field("Composite single micelles")
    theme["candidates"][0]["action"] = _field("Spread laterally into a single monolayer")
    theme["candidates"][0]["environment"] = _field("Emulsion droplet interface")
    prompt = compile_visual_prompt(theme, CONFIG)
    assert (
        "One continuous microscopic shot: composite single micelles spread "
        "laterally into a single monolayer within an emulsion droplet interface."
    ) in prompt


def test_environment_preposition_is_not_duplicated() -> None:
    theme = _theme()
    theme["candidates"][0]["environment"] = _field("on a coated electrode surface")
    prompt = compile_visual_prompt(theme, CONFIG)
    assert " within on " not in prompt
    assert "on a coated electrode surface." in prompt


def test_flow_parameters_and_audio_are_preserved() -> None:
    prompt = compile_visual_prompt(_theme(), CONFIG)
    for value in ("15 second", "9:16", "720p", "Output count: 1", "Omni Flash 1.2",
                  "Instrumental music only", "no narration", "Do not extend"):
        assert value in prompt


def test_agent_rules_prioritize_filming_over_scientific_importance() -> None:
    rules = (Path(__file__).resolve().parents[1] / ".opencode/agents/micro-visual-theme-extractor.md").read_text(encoding="utf-8")
    assert rules.index("VISUAL EXPRESSIBILITY FIRST") < rules.index("VISUAL SIMPLICITY SECOND")
    assert rules.index("VISUAL SIMPLICITY SECOND") < rules.index("ARTICLE RELEVANCE THIRD")
    assert "headline contribution" in rules
    assert "fewer elements" in rules
    assert "Do NOT add colors" in rules
    assert "essential_acronyms" in rules


def test_extraction_uses_dedicated_agent_and_generic_input(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def fake_runner(root: Path, cfg: dict[str, Any], *, prompt: str, attachments: list[Path]):
        captured["agent"] = cfg["opencode"]["agent"]
        captured["prompt"] = prompt
        captured["attachments"] = attachments
        return _theme()

    summary = tmp_path / "summary.json"
    summary.write_text("{}", encoding="utf-8")
    article = tmp_path / "article.md"
    article.write_text("# article", encoding="utf-8")
    result = extract_visual_theme(
        tmp_path, summary_path=summary, article_dir=tmp_path,
        output_dir=tmp_path / "blind",
        deps={"run_agent": fake_runner, "load_daily_config": lambda _root: CONFIG | {"opencode": {}}},
    )
    assert result["selected_candidate_id"] == "A"
    assert captured["agent"] == THEME_AGENT
    assert captured["attachments"] == [summary, article]
