"""Deterministic adapter from validated planner output to article_summary schema 1."""
from __future__ import annotations

import re
from typing import Any

from .article_source import validate_article_summary
from .planner_output_schema import PlannerContractError, _CJK_RE
from .source_paragraphs import extract_source_excerpt


def adapt_planner_output(
    validated: dict[str, Any],
    *,
    package: dict[str, Any],
    paragraphs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Convert a contract-valid planner response into the legacy summary object.

    Every deterministic field comes from the verified article package. Scientific
    content comes only from the planner. No content is invented or repaired.
    """
    article = package["article"]
    article_id = str(article["article_id"])
    if validated["article_id"] != article_id:
        raise PlannerContractError("Planner article_id does not match the article package.")

    claims: list[dict[str, str]] = []
    statement_by_id: dict[str, str] = {}
    for item in validated["claims"]:
        excerpt = extract_source_excerpt(paragraphs, item["source_ref"]["paragraph_index"])
        if excerpt not in package["markdown"]:
            raise PlannerContractError(
                f"{item['claim_id']} paragraph excerpt is not an exact substring of article.md."
            )
        claim_id = str(item["claim_id"])
        claims.append({
            "claim_id": claim_id,
            "statement": str(item["statement"]),
            "source_excerpt": excerpt,
        })
        statement_by_id[claim_id] = str(item["statement"])

    beat_by_id = {item["beat_id"]: item for item in validated["beats"]}
    units: list[dict[str, Any]] = []
    beats: list[dict[str, Any]] = []
    for item in validated["speech_units"]:
        beat = beat_by_id[item["visual_beat_id"]]
        if beat["unit_id"] != item["unit_id"]:
            raise PlannerContractError(f"{item['unit_id']} is mapped to a beat for another unit.")
        units.append({
            "unit_id": item["unit_id"],
            "spoken_text": item["spoken_text"],
            "display_text": item["display_text"],
            "claim_ids": list(item["claim_ids"]),
            "visual_trigger_ids": [item["visual_beat_id"]],
            "pause_after_ms": item["pause_after_ms"],
        })
        beats.append({key: value for key, value in beat.items() if key != "visual_beat_id"})

    spoken = "".join(unit["spoken_text"] for unit in units)
    summary: dict[str, Any] = {
        "schema_version": 1,
        "article_id": article_id,
        "source_article_sha256": package["markdown_sha256"],
        "summary_title": validated["summary_title"],
        "channels_title": validated["channels_title"],
        "core_thesis": validated["core_thesis"],
        "thesis_claim_ids": list(validated["thesis_claim_ids"]),
        "claims": claims,
        "speech_units": units,
        "beats": beats,
        "cover_title": validated["summary_title"],
        "cover_subtitle": "一篇文章 · 一个关键发现",
        "source_line": "成核生长 · 文献精读",
        "cover_duration_ms": 1500,
        "outro_duration_ms": 1800,
        "spoken_cjk_characters": len(_CJK_RE.findall(spoken)),
    }
    return validate_article_summary(package, summary)
