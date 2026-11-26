"""Deterministic paragraph index for source-grounded excerpt extraction."""
from __future__ import annotations

import re
from typing import Any

from .planner_output_schema import PlannerContractError


def build_paragraph_index(markdown: str) -> list[dict[str, Any]]:
    """Split exact article Markdown into stable, blank-line-delimited blocks.

    Empty blocks are skipped but their ordinal is preserved, so indices are stable
    across repeated runs on the same bytes. Headings, image links and all other
    non-empty blocks are included; no rewriting, trimming beyond outer whitespace
    or normalization is applied to the stored text.
    """
    blocks = re.split(r"\n\s*\n", markdown)
    index: list[dict[str, Any]] = []
    for ordinal, block in enumerate(blocks):
        text = block.strip()
        if not text:
            continue
        index.append({"paragraph_index": ordinal, "text": text})
    return index


def extract_source_excerpt(index: list[dict[str, Any]], paragraph_index: int) -> str:
    """Return the exact original block text for a validated paragraph index."""
    matches = [item for item in index if item["paragraph_index"] == paragraph_index]
    if len(matches) != 1:
        raise PlannerContractError(
            f"paragraph_index {paragraph_index} is missing or ambiguous in article.md."
        )
    return str(matches[0]["text"])
