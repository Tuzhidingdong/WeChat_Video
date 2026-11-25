"""Offline tests for the strict planner contract and deterministic adapter."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from wechat_video.article_source import load_article_package
from wechat_video.planner_output_schema import PlannerContractError, validate_planner_output
from wechat_video.planner_summary_adapter import adapt_planner_output
from wechat_video.source_paragraphs import build_paragraph_index

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "outputs/article_inputs/100000764_0"
ORIGINAL_SUMMARY = ROOT / "content/article_summaries/100000764_0/summary_v2.json"
PRODUCTION_SUMMARY = (
    ROOT / "outputs/article_summary_production_20261124_01/20261124_141611_100000764_0_article_summary/summary.json"
)


def _article_id() -> str:
    return json.loads((PACKAGE_DIR / "article.json").read_text(encoding="utf-8"))["article_id"]


def _legal_output() -> dict:
    original = json.loads(ORIGINAL_SUMMARY.read_text(encoding="utf-8"))
    production = json.loads(PRODUCTION_SUMMARY.read_text(encoding="utf-8"))
    markdown = (PACKAGE_DIR / "article.md").read_text(encoding="utf-8")
    blocks = build_paragraph_index(markdown)
    norm = lambda value: re.sub(r"\s+", "", value)

    claims = []
    for claim in original["claims"]:
        excerpt = claim["source_excerpt"]
        matches = [b["paragraph_index"] for b in blocks if norm(excerpt) in norm(b["text"])]
        assert len(matches) == 1, (claim["claim_id"], matches)
        claims.append({
            "claim_id": claim["claim_id"], "statement": claim["statement"],
            "source_ref": {"paragraph_index": matches[0]},
        })

    beat_by_unit = {beat["unit_id"]: beat for beat in original["beats"]}
    image_ids = [image["image_id"] for image in json.loads(
        (PACKAGE_DIR / "images.json").read_text(encoding="utf-8")
    )["images"]]
    beats = []
    units = []
    for unit in production["speech_units"]:
        old_beat = beat_by_unit[unit["unit_id"]]
        kind = old_beat["kind"]
        beat = {
            "beat_id": old_beat["beat_id"], "unit_id": unit["unit_id"], "kind": kind,
            "headline": old_beat["headline"], "claim_ids": old_beat["claim_ids"],
        }
        if kind == "image":
            old_images = old_beat.get("image_ids") or []
            beat["image_ids"] = [image_ids[int(name.split("_")[1]) - 1] for name in old_images]
        elif kind == "stat":
            beat["stat_value"] = old_beat["stat_value"]
            beat["stat_label"] = old_beat["stat_label"]
        elif kind == "compare":
            beat["left"] = old_beat["left"]
            beat["right"] = old_beat["right"]
        elif kind == "mechanism":
            beat["steps"] = old_beat["steps"]
        beats.append(beat)
        units.append({
            "unit_id": unit["unit_id"], "spoken_text": unit["spoken_text"],
            "display_text": unit["display_text"], "claim_ids": unit["claim_ids"],
            "visual_beat_id": old_beat["beat_id"], "pause_after_ms": unit.get("pause_after_ms", 500),
        })

    return {
        "schema_version": 1,
        "article_id": _article_id(),
        "summary_title": original["summary_title"],
        "channels_title": original["channels_title"],
        "core_thesis": original["core_thesis"],
        "thesis_claim_ids": original["thesis_claim_ids"],
        "claims": claims,
        "speech_units": units,
        "beats": beats,
    }


def _package():
    return load_article_package(PACKAGE_DIR)


def test_legal_planner_output_passes_contract_and_adapter() -> None:
    package = _package()
    validated = validate_planner_output(
        _legal_output(),
        article_id=_article_id(),
        article_sha256=package["markdown_sha256"],
        image_ids=set(package["images"]),
    )
    summary = adapt_planner_output(validated, package=package, paragraphs=build_paragraph_index(package["markdown"]))
    assert summary["source_article_sha256"] == package["markdown_sha256"]
    assert len(summary["claims"]) == 7
    assert all(len(item["source_excerpt"]) >= 8 for item in summary["claims"])


def test_optional_sha_echo_is_checked_when_present() -> None:
    package = _package()
    output = _legal_output()
    output["source_article_sha256"] = package["markdown_sha256"]
    validate_planner_output(output, article_id=_article_id(), article_sha256=package["markdown_sha256"], image_ids=set(package["images"]))
    output["source_article_sha256"] = "0" * 64
    with pytest.raises(PlannerContractError, match="echo conflicts"):
        validate_planner_output(output, article_id=_article_id(), article_sha256=package["markdown_sha256"], image_ids=set(package["images"]))


@pytest.mark.parametrize("mutate", [
    lambda o: o.pop("summary_title"),
    lambda o: o.update({"unexpected": True}),
    lambda o: o.update({"article_id": "wrong_0"}),
    lambda o: o["claims"][0].update({"statement": ""}),
    lambda o: o["speech_units"][0].update({"claim_ids": ["NOPE"]}),
    lambda o: o["speech_units"][0].update({"visual_beat_id": "NOPE"}),
    lambda o: o["beats"][0].update({"kind": "unknown"}),
    lambda o: o["beats"][1].update({"image_ids": ["NOPE"]}),
    lambda o: o["beats"][3].update({"stat_value": ""}),
    lambda o: o["beats"][5].update({"steps": ["only one"]}),
    lambda o: o["speech_units"][0].update({"spoken_text": "短"}),
])
def test_invalid_planner_outputs_fail(mutate) -> None:
    package = _package()
    output = _legal_output()
    mutate(output)
    with pytest.raises(PlannerContractError):
        validate_planner_output(output, article_id=_article_id(), article_sha256=package["markdown_sha256"], image_ids=set(package["images"]))


def test_missing_paragraph_index_fails_in_adapter() -> None:
    package = _package()
    output = _legal_output()
    output["claims"][0]["source_ref"]["paragraph_index"] = 99999
    validated = validate_planner_output(
        output, article_id=_article_id(), article_sha256=package["markdown_sha256"], image_ids=set(package["images"])
    )
    with pytest.raises(PlannerContractError, match="paragraph_index"):
        adapt_planner_output(validated, package=package, paragraphs=build_paragraph_index(package["markdown"]))


def test_failed_model_shapes_are_rejected() -> None:
    package = _package()
    # Observed shape from hy4-flash-free and hungerg-free: custom keys, no legacy contract.
    hy4_shape = {
        "account_name": "成核生长", "article_id": _article_id(), "source_title": "标题",
        "spoken_text": "长旁白", "speech_units": [{"unit_id": "SU1", "spoken_text": "旁白", "claims": [], "visual_beat": {}}],
        "constraints_check": {},
    }
    hungerg_shape = {
        "account_name": "成核生长", "article_id": _article_id(), "source_files": [],
        "speech_units": [{"unit_id": 1, "spoken_text": "旁白", "source_excerpt": "摘录", "visual_beat": {"image_id": "IMG01"}}],
    }
    for output in (hy4_shape, hungerg_shape):
        with pytest.raises(PlannerContractError):
            validate_planner_output(output, article_id=_article_id(), article_sha256=package["markdown_sha256"], image_ids=set(package["images"]))


def test_paragraph_index_is_deterministic_and_excerpt_is_exact() -> None:
    markdown = (PACKAGE_DIR / "article.md").read_text(encoding="utf-8")
    first = build_paragraph_index(markdown)
    assert build_paragraph_index(markdown) == first
    assert len({item["paragraph_index"] for item in first}) == len(first)
    assert all(item["text"] in markdown for item in first)
