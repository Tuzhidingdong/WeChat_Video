"""Strict, versioned planner intermediate output contract.

The planner is allowed to author scientific content only. Deterministic metadata
(article id, source SHA, image ids, paragraph indices) is owned by the program and
is validated here. One stable schema replaces the multiple ad-hoc shapes returned
by earlier models.
"""
from __future__ import annotations

import re
from typing import Any

from .article_source import ALLOWED_BEAT_KINDS

PLANNER_SCHEMA_VERSION = 1
_UID_RE = re.compile(r"[A-Za-z0-9_-]{1,24}")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_MIN_SPOKEN_HAN = 222
_MAX_SPOKEN_HAN = 235

_REQUIRED_TOP = {
    "schema_version", "summary_title", "channels_title", "core_thesis",
    "thesis_claim_ids", "claims", "speech_units", "beats",
}
# Deterministic metadata is owned by the program. Models may echo these values,
# but the echo is optional and must match the program value exactly when present.
_OPTIONAL_TOP = {"article_id", "source_article_sha256"}
_CLAIM_KEYS = {"claim_id", "statement", "source_ref"}
_SOURCE_REF_KEYS = {"paragraph_index"}
_UNIT_KEYS = {"unit_id", "spoken_text", "display_text", "claim_ids", "visual_beat_id", "pause_after_ms"}
_BEAT_BASE_KEYS = {"beat_id", "unit_id", "kind", "headline", "body", "claim_ids"}
_BEAT_EXTRA_KEYS: dict[str, set[str]] = {
    "hook": set(),
    "image": {"image_ids", "focus_regions", "display_crop_regions", "axis_labels_zh"},
    "stat": {"stat_value", "stat_label"},
    "compare": {"left", "right"},
    "mechanism": {"steps"},
    "quote": {"quote"},
    "takeaway": set(),
}


class PlannerContractError(ValueError):
    """Raised when planner output does not satisfy the single supported contract."""


def _fail(message: str) -> None:
    raise PlannerContractError(message)


def _require_text(value: Any, label: str, *, max_len: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{label} must be a non-empty string.")
    text = value.strip()
    if max_len is not None and len(text) > max_len:
        _fail(f"{label} exceeds {max_len} characters.")
    return text


def _require_uid(value: Any, label: str) -> str:
    text = _require_text(value, label)
    if not _UID_RE.fullmatch(text):
        _fail(f"{label} must match [A-Za-z0-9_-]{{1,24}}.")
    return text


def _require_string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item.strip() for item in value):
        _fail(f"{label} must be a non-empty list of strings.")
    items = [item.strip() for item in value]
    if len(set(items)) != len(items):
        _fail(f"{label} contains duplicate values.")
    return items


def _check_keys(obj: dict[str, Any], allowed: set[str], label: str) -> None:
    extra = set(obj) - allowed
    if extra:
        _fail(f"{label} contains unsupported fields: {sorted(extra)}")


def validate_planner_output(
    raw: Any,
    *,
    article_id: str,
    article_sha256: str,
    image_ids: set[str],
) -> dict[str, Any]:
    """Validate one planner response against the versioned intermediate contract."""
    if not isinstance(raw, dict):
        _fail("Planner output must be a JSON object.")
    top_keys = set(raw)
    missing = _REQUIRED_TOP - top_keys
    if missing:
        _fail(f"Planner output is missing required fields: {sorted(missing)}")
    _check_keys(raw, _REQUIRED_TOP | _OPTIONAL_TOP, "planner output")
    if raw["schema_version"] != PLANNER_SCHEMA_VERSION:
        _fail("Planner schema_version must be 1.")
    if "article_id" in raw and str(raw["article_id"]) != article_id:
        _fail("Planner article_id echo conflicts with the selected article.")
    if "source_article_sha256" in raw:
        if str(raw["source_article_sha256"]).casefold() != article_sha256.casefold():
            _fail("Planner source_article_sha256 echo conflicts with article.md.")

    summary_title = _require_text(raw["summary_title"], "summary_title")
    channels_title = _require_text(raw["channels_title"], "channels_title")
    if not 6 <= len(channels_title) <= 16:
        _fail("channels_title must contain 6-16 characters.")
    core_thesis = _require_text(raw["core_thesis"], "core_thesis")
    thesis_claim_ids = _require_string_list(raw["thesis_claim_ids"], "thesis_claim_ids")

    claims_raw = raw["claims"]
    if not isinstance(claims_raw, list) or not 1 <= len(claims_raw) <= 12:
        _fail("claims must contain between 1 and 12 objects.")
    claims: list[dict[str, Any]] = []
    claim_ids: set[str] = set()
    for index, claim in enumerate(claims_raw):
        if not isinstance(claim, dict):
            _fail(f"claims[{index}] must be an object.")
        _check_keys(claim, _CLAIM_KEYS, f"claims[{index}]")
        claim_id = _require_uid(claim["claim_id"], f"claims[{index}].claim_id")
        if claim_id in claim_ids:
            _fail(f"Duplicate claim_id: {claim_id}")
        claim_ids.add(claim_id)
        statement = _require_text(claim["statement"], f"claims[{index}].statement")
        source_ref = claim["source_ref"]
        if not isinstance(source_ref, dict):
            _fail(f"claims[{index}].source_ref must be an object.")
        _check_keys(source_ref, _SOURCE_REF_KEYS, f"claims[{index}].source_ref")
        paragraph_index = source_ref["paragraph_index"]
        if isinstance(paragraph_index, bool) or not isinstance(paragraph_index, int) or paragraph_index < 0:
            _fail(f"claims[{index}].source_ref.paragraph_index must be a non-negative integer.")
        claims.append({
            "claim_id": claim_id,
            "statement": statement,
            "source_ref": {"paragraph_index": paragraph_index},
        })
    if not set(thesis_claim_ids).issubset(claim_ids):
        _fail("thesis_claim_ids references unknown claim IDs.")

    units_raw = raw["speech_units"]
    if not isinstance(units_raw, list) or not 5 <= len(units_raw) <= 8:
        _fail("speech_units must contain between 5 and 8 objects.")
    units: list[dict[str, Any]] = []
    unit_ids: set[str] = set()
    for index, unit in enumerate(units_raw):
        if not isinstance(unit, dict):
            _fail(f"speech_units[{index}] must be an object.")
        _check_keys(unit, _UNIT_KEYS, f"speech_units[{index}]")
        unit_id = _require_uid(unit["unit_id"], f"speech_units[{index}].unit_id")
        if unit_id in unit_ids:
            _fail(f"Duplicate unit_id: {unit_id}")
        unit_ids.add(unit_id)
        spoken = _require_text(unit["spoken_text"], f"speech_units[{index}].spoken_text")
        display = _require_text(unit["display_text"], f"speech_units[{index}].display_text")
        refs = _require_string_list(unit["claim_ids"], f"speech_units[{index}].claim_ids")
        if not set(refs).issubset(claim_ids):
            _fail(f"{unit_id} references unknown claim IDs.")
        beat_id = _require_uid(unit["visual_beat_id"], f"speech_units[{index}].visual_beat_id")
        pause = unit["pause_after_ms"]
        if isinstance(pause, bool) or not isinstance(pause, int) or not 0 <= pause <= 1000:
            _fail(f"{unit_id}.pause_after_ms must be an integer between 0 and 1000.")
        units.append({
            "unit_id": unit_id, "spoken_text": spoken, "display_text": display,
            "claim_ids": refs, "visual_beat_id": beat_id, "pause_after_ms": pause,
        })

    beats_raw = raw["beats"]
    if not isinstance(beats_raw, list) or len(beats_raw) != len(units):
        _fail("beats must contain exactly one object per speech unit.")
    beats: list[dict[str, Any]] = []
    beat_ids: set[str] = set()
    unit_to_beat: dict[str, str] = {}
    for index, beat in enumerate(beats_raw):
        if not isinstance(beat, dict):
            _fail(f"beats[{index}] must be an object.")
        beat_id = _require_uid(beat.get("beat_id"), f"beats[{index}].beat_id")
        if beat_id in beat_ids:
            _fail(f"Duplicate beat_id: {beat_id}")
        beat_ids.add(beat_id)
        unit_id = _require_uid(beat.get("unit_id"), f"beats[{index}].unit_id")
        unit = next((item for item in units if item["unit_id"] == unit_id), None)
        if unit is None:
            _fail(f"beats[{index}] references unknown unit_id.")
        if unit_id in unit_to_beat:
            _fail(f"{unit_id} has more than one visual beat.")
        unit_to_beat[unit_id] = beat_id
        if beat_id != unit["visual_beat_id"]:
            _fail(f"{unit_id}.visual_beat_id does not match its beat.")
        kind = _require_text(beat.get("kind"), f"beats[{index}].kind")
        if kind not in ALLOWED_BEAT_KINDS:
            _fail(f"beats[{index}] has unsupported kind {kind!r}.")
        allowed = _BEAT_BASE_KEYS | _BEAT_EXTRA_KEYS[kind]
        _check_keys(beat, allowed, f"beats[{index}]")
        headline = _require_text(beat.get("headline"), f"beats[{index}].headline")
        body = beat.get("body", "")
        if not isinstance(body, str):
            _fail(f"beats[{index}].body must be a string.")
        refs = _require_string_list(beat.get("claim_ids"), f"beats[{index}].claim_ids")
        if not set(refs).issubset(set(unit["claim_ids"])):
            _fail(f"{beat_id} references claims not used by its spoken unit.")
        normalized: dict[str, Any] = {
            "beat_id": beat_id, "unit_id": unit_id, "kind": kind,
            "headline": headline, "body": body, "claim_ids": refs,
        }
        if kind == "image":
            image_refs = _require_string_list(beat.get("image_ids"), f"{beat_id}.image_ids")
            if not 1 <= len(image_refs) <= 2:
                _fail(f"{beat_id}.image_ids must contain one or two image IDs.")
            if not set(image_refs).issubset(image_ids):
                _fail(f"{beat_id} references image IDs absent from the article package.")
            normalized["image_ids"] = image_refs
            for optional in ("focus_regions", "display_crop_regions", "axis_labels_zh"):
                if optional in beat:
                    if not isinstance(beat[optional], dict):
                        _fail(f"{beat_id}.{optional} must be an object.")
                    normalized[optional] = beat[optional]
        elif kind == "stat":
            normalized["stat_value"] = _require_text(beat.get("stat_value"), f"{beat_id}.stat_value")
            normalized["stat_label"] = _require_text(beat.get("stat_label"), f"{beat_id}.stat_label")
        elif kind == "compare":
            for field in ("left", "right"):
                if not isinstance(beat.get(field), dict):
                    _fail(f"{beat_id}.{field} must be an object.")
                normalized[field] = beat[field]
        elif kind == "mechanism":
            steps = beat.get("steps")
            if not isinstance(steps, list) or not 2 <= len(steps) <= 4 or any(not isinstance(s, str) or not s.strip() for s in steps):
                _fail(f"{beat_id}.steps must contain 2-4 non-empty strings.")
            normalized["steps"] = steps
        elif kind == "quote":
            normalized["quote"] = _require_text(beat.get("quote"), f"{beat_id}.quote")
        beats.append(normalized)
    if set(unit_to_beat) != unit_ids:
        _fail("Every speech unit must map to exactly one visual beat.")

    spoken = "".join(unit["spoken_text"] for unit in units)
    han = len(_CJK_RE.findall(spoken))
    if not _MIN_SPOKEN_HAN <= han <= _MAX_SPOKEN_HAN:
        _fail(f"Planner output has {han} Chinese Han characters; expected {_MIN_SPOKEN_HAN}-{_MAX_SPOKEN_HAN}.")

    return {
        "schema_version": PLANNER_SCHEMA_VERSION,
        "article_id": article_id,
        "summary_title": summary_title,
        "channels_title": channels_title,
        "core_thesis": core_thesis,
        "thesis_claim_ids": thesis_claim_ids,
        "claims": claims,
        "speech_units": units,
        "beats": beats,
    }
