"""Deterministic, evidence-grounded metadata for a WeChat Channels draft."""
from __future__ import annotations

import re
from typing import Any


DEFAULT_TAGS = ["#成核生长", "#科学动画", "#材料科学"]


def build_channels_metadata(
    fact_card: dict[str, Any],
    script: dict[str, Any],
    job_id: str,
    *,
    account_name: str = "成核生长",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Build draft copy only from the approved Fact Card and script metadata.

    This function does not invent additional scientific claims. A title may be
    explicitly supplied as channels_title on the Fact Card; otherwise the
    Fact Card title is used. Description sentences are copied from the card.
    """
    title = str(fact_card.get("channels_title") or fact_card.get("title") or "").strip()
    question = str(fact_card.get("scientific_question") or "").strip()
    scope = str(fact_card.get("scope") or "").strip()
    if not title or not question or not scope:
        raise ValueError("Fact Card must include title, scientific_question, and scope for Channels metadata.")

    selected_tags = tags if tags is not None else DEFAULT_TAGS
    normalized_tags = []
    for tag in selected_tags:
        value = str(tag).strip()
        if value and not value.startswith("#"):
            value = "#" + value
        if value and value not in normalized_tags:
            normalized_tags.append(value)

    description_parts = [question, scope]
    if normalized_tags:
        description_parts.append(" ".join(normalized_tags))
    description = "\n\n".join(description_parts)
    metadata = {
        "schema_version": 1,
        "job_id": str(job_id),
        "account_name": account_name,
        "title": title,
        "description": description,
        "tags": normalized_tags,
        "source_fact_card_id": str(fact_card.get("fact_card_id") or ""),
        "script_id": str(script.get("script_id") or ""),
        "source": "fact_card_and_script_metadata",
    }
    validate_channels_metadata(metadata)
    return metadata


def validate_channels_metadata(metadata: dict[str, Any]) -> None:
    title = str(metadata.get("title") or "").strip()
    description = str(metadata.get("description") or "").strip()
    if not title:
        raise ValueError("Channels draft title is empty.")
    if not 6 <= len(title) <= 50:
        raise ValueError(f"Channels short title must contain 6–50 characters; got {len(title)}.")
    if not description:
        raise ValueError("Channels draft description is empty.")
    if len(description) > 1000:
        raise ValueError(f"Channels description exceeds 1000 characters; got {len(description)}.")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", title + description):
        raise ValueError("Channels metadata contains control characters.")
    if not metadata.get("job_id"):
        raise ValueError("Channels metadata is missing job_id.")
