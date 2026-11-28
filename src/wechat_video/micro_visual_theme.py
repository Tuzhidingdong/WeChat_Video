"""Stage A theme -> Stage B Flow prompt compiler.

Stage A evidence checks are intentionally NOT applied: once the agent has
selected a theme it is passed directly to Stage B. Only data-structure
integrity (parseable JSON, required fields, non-empty English text) is checked.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import channels_uploader as cu, daily_pipelines
from .micro_visual_article_source import _single_line_prompt
from .micro_visual_plan import AUDIO, COMPOSITION, NO_TEXT_RULES, _CJK_RE

THEME_AGENT = "micro-visual-theme-extractor"
THEME_SCHEMA_VERSION = 2
SINGLE_GENERATION = (
    "Generate the video once in a single pass. Do not extend, loop, resume or "
    "generate additional clips."
)
_FIELD_NAMES = ("subject", "action", "environment")
_RELATIONSHIPS = {
    "core_phenomenon", "key_process", "experimental_observation", "downstream_result",
}


class VisualThemeError(RuntimeError):
    pass


def _validate_text(value: Any, name: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        raise VisualThemeError(f"visual theme {name} is empty")
    if _CJK_RE.search(text):
        raise VisualThemeError(f"visual theme {name} contains Chinese text")
    return text


def _validate_field(field: Any, name: str, context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Structural validation only -- no scientific evidence review."""
    if not isinstance(field, dict):
        raise VisualThemeError(f"{name} must be an object")
    text = _validate_text(field.get("text"), name)
    kind = str(field.get("kind") or "scientific").strip().lower()
    if kind not in {"scientific", "visual_constraint"}:
        raise VisualThemeError(f"{name}.kind is invalid: {kind}")
    evidence = {"text": text, "kind": kind, "claim_ids": [], "source_excerpts": [], "paraphrase": ""}
    for key in ("supporting_claim_ids", "supporting_source_excerpts"):
        value = field.get(key)
        if value is not None and not isinstance(value, list):
            raise VisualThemeError(f"{name}.{key} must be a list when present")
        if isinstance(value, list):
            evidence["claim_ids" if key == "supporting_claim_ids" else "source_excerpts"] = [
                str(item) for item in value
            ]
    paraphrase = field.get("evidence_paraphrase")
    if paraphrase is not None and not isinstance(paraphrase, str):
        raise VisualThemeError(f"{name}.evidence_paraphrase must be a string when present")
    evidence["paraphrase"] = str(paraphrase or "")
    return text, evidence


def validate_theme(theme: dict[str, Any], **context: Any) -> dict[str, Any]:
    """Check data structure only; return the selected fields for Stage B."""
    if not isinstance(theme, dict):
        raise VisualThemeError("visual theme must be a JSON object")
    if int(theme.get("schema_version") or 0) != THEME_SCHEMA_VERSION:
        raise VisualThemeError("unsupported Stage A schema_version")
    for key in ("article_id", "source_article_sha256", "run_id"):
        expected = context.get(key)
        actual = str(theme.get(key) or "")
        if expected is not None and actual != str(expected):
            raise VisualThemeError(f"visual theme {key} mismatch")
    candidates = theme.get("candidates")
    if not isinstance(candidates, list) or len(candidates) < 2:
        raise VisualThemeError("visual theme needs at least two candidates")
    by_id: dict[str, dict[str, Any]] = {}
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise VisualThemeError(f"candidate {index} must be an object")
        cid = str(candidate.get("candidate_id") or "").strip()
        if not cid or cid in by_id:
            raise VisualThemeError(f"candidate {index} has a missing or duplicate candidate_id")
        relation = str(candidate.get("relationship_to_core_finding") or "").strip().lower()
        if relation not in _RELATIONSHIPS:
            raise VisualThemeError(f"candidate {cid} has invalid relationship_to_core_finding")
        fields: dict[str, Any] = {}
        for name in _FIELD_NAMES:
            text, evidence = _validate_field(candidate.get(name), name, context)
            fields[name] = {"text": text, "evidence": evidence}
        by_id[cid] = {**candidate, "validated_fields": fields}
    selected_id = str(theme.get("selected_candidate_id") or "").strip()
    if selected_id not in by_id:
        raise VisualThemeError("selected_candidate_id does not match any candidate")
    selected = by_id[selected_id]
    fields = {name: selected["validated_fields"][name]["text"] for name in _FIELD_NAMES}
    evidence = {name: selected["validated_fields"][name]["evidence"] for name in _FIELD_NAMES}
    return {
        "candidate_id": selected_id,
        "fields": fields,
        "evidence": evidence,
        "relationship_to_core_finding": selected["relationship_to_core_finding"],
        "selection_rationale": str(selected.get("selection_rationale") or ""),
        "scientific_uncertainties": selected.get("scientific_uncertainties") or [],
        "unsupported_visual_details": selected.get("unsupported_visual_details") or [],
    }


def extract_visual_theme(
    project_root: Path,
    *,
    summary_path: Path,
    article_dir: Path,
    output_dir: Path,
    config: dict[str, Any] | None = None,
    deps: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stage A: ask the production agent to select a visual theme."""
    root = project_root.resolve()
    deps = dict(deps or {})
    ctx = dict(context or {})
    daily_cfg = deps.get("load_daily_config", daily_pipelines._load_config)(root)
    runner = deps.get("run_agent", daily_pipelines._run_content_planner)
    agent_cfg = dict(daily_cfg)
    opencode_cfg = dict(daily_cfg.get("opencode") or {})
    opencode_cfg["agent"] = THEME_AGENT
    agent_cfg["opencode"] = opencode_cfg
    identity = (
        " Context: article_id=" + str(ctx.get("article_id") or "")
        + "; source_article_sha256=" + str(ctx.get("source_article_sha256") or "")
        + "; run_id=" + str(ctx.get("run_id") or "")
        + ". Include these three values verbatim in your JSON."
    )
    prompt = (
        "Read the attached summary.json and article.md. Identify at least two "
        "candidate phenomena directly observable in one microscopic shot. For "
        "EACH candidate give candidate_id and evidence-bearing objects for "
        "subject, action and environment, each with text, kind, "
        "supporting_claim_ids, supporting_source_excerpts (verbatim from the "
        "article) and an English evidence_paraphrase using the same key terms "
        "as the text. Also give selection_rationale, "
        "relationship_to_core_finding, scientific_uncertainties and "
        "unsupported_visual_details. Finish with selected_candidate_id and "
        "selection_summary. Do not explain the science or write a video prompt."
        + identity
    )
    raw = runner(
        root, agent_cfg,
        prompt=_single_line_prompt(prompt),
        attachments=[Path(summary_path), Path(article_dir) / "article.md"],
    )
    # Persist the real model response at the moment it is received, before any
    # normalization, so acceptance can recover it without a second LLM call.
    metadata = dict(raw.get("_planner_run_metadata") or {})
    output_dir.mkdir(parents=True, exist_ok=True)
    cu._write_json_atomic(output_dir / "visual_theme_raw.json", raw)
    (output_dir / "visual_theme_raw.txt").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    cu._write_json_atomic(output_dir / "stage_a_session.json", {
        "agent": metadata.get("agent") or THEME_AGENT,
        "model": metadata.get("model"),
        "session_ids": (metadata.get("usage") or {}).get("session_ids") or [],
        "attachments": [str(Path(summary_path).resolve()),
                        str((Path(article_dir) / "article.md").resolve())],
        "article_id": ctx.get("article_id"),
        "source_article_sha256": ctx.get("source_article_sha256"),
        "run_id": ctx.get("run_id"),
    })
    raw.pop("_planner_run_metadata", None)
    validate_theme(raw, **ctx)
    cu._write_json_atomic(output_dir / "visual_theme.json", raw)
    return raw


def compile_visual_prompt(
    theme: dict[str, Any],
    config: dict[str, Any],
    **context: Any,
) -> str:
    """Stage B: compile the selected theme into an English Flow prompt."""
    validated = validate_theme(theme, **context)
    fields = validated["fields"]
    model = str(config.get("model") or "").strip()
    duration = str(config.get("duration_seconds") or "").strip()
    aspect = str(config.get("aspect_ratio") or "").strip()
    resolution = str(config.get("resolution") or "").strip()
    count = str(config.get("output_count") or "").strip()
    if not all((model, duration, aspect, resolution, count)):
        raise VisualThemeError("Flow model, duration, aspect, resolution and count are required")

    def mid_sentence(text: str) -> str:
        return text[:1].lower() + text[1:] if text[:1].isupper() else text

    subject = mid_sentence(fields["subject"])
    action = mid_sentence(fields["action"])
    environment = mid_sentence(fields["environment"])
    prepositions = ("on ", "in ", "above ", "along ", "across ", "inside ", "under ", "over ", "at ")
    if environment.lower().startswith(prepositions):
        environment_phrase = environment
    elif environment.lower().startswith(("a ", "an ", "the ")):
        environment_phrase = f"within {environment}"
    else:
        article = "an " if environment[:1].lower() in "aeiou" else "a "
        environment_phrase = f"within {article}{environment}"
    lines = [
        f"Create one {duration} second {aspect} video with {model}.",
        f"One continuous microscopic shot: {subject} {action} {environment_phrase}.",
        COMPOSITION,
        NO_TEXT_RULES,
        f"Resolution: {resolution}. Output count: {count}.",
        SINGLE_GENERATION,
        AUDIO,
    ]
    prompt = "\n".join(lines)
    if _CJK_RE.search(prompt):
        raise VisualThemeError("compiled Flow prompt contains Chinese text")
    return prompt
