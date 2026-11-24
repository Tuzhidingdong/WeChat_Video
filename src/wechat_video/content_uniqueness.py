"""Deterministic content-uniqueness gate for generated Slice A videos.

MP4 SHA-256 is NOT content evidence: re-rendering the same script produces a
different hash. This module fingerprints the editorial and visual identity of a
run (spoken text, Chinese display text, speech-unit order, visual-trigger
sequence, storyboard sequence and scene template/strategy) and blocks an upload
when a prior run has the same essential identity. The two 2026-11-22 runs whose
MP4 hashes differed but whose script.json was byte-identical are the negative
examples this gate is calibrated against.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_content_fingerprint(run_dir: Path) -> dict[str, Any]:
    """Build the saved content_fingerprint.json for one generated run."""
    run_dir = run_dir.resolve()
    script_path = run_dir / "script.json"
    if not script_path.is_file():
        raise ValueError(f"Missing script.json in {run_dir}")
    script = _read_json(script_path)
    units = script.get("speech_units", [])
    spoken = [str(unit.get("spoken_text") or "") for unit in units]
    display_zh = [str(unit.get("display_text_zh") or "") for unit in units]
    triggers = [
        [str(item) for item in unit.get("visual_trigger_ids", [])]
        for unit in units
    ]
    storyboard_path = run_dir / "storyboard.json"
    storyboard = _read_json(storyboard_path) if storyboard_path.is_file() else {}
    manifest_path = run_dir / "scene_render_manifest.json"
    manifest = _read_json(manifest_path) if manifest_path.is_file() else {}
    sequence = [
        {
            key: item.get(key)
            for key in ("scene_id", "template", "description")
        }
        for item in storyboard.get("sequence", [])
        if isinstance(item, dict)
    ]
    identity = {
        "spoken_text": spoken,
        "display_text_zh": display_zh,
        "visual_trigger_sequence": triggers,
        "storyboard_sequence": sequence,
        "scene_template": manifest.get("template") or storyboard.get("scene_template"),
        "visual_strategy": storyboard.get("visual_strategy"),
    }
    return {
        "schema_version": 1,
        "run_id": run_dir.name,
        "script_id": script.get("script_id"),
        "editorial_angle_id": script.get("editorial_angle_id"),
        "script_sha256": hashlib.sha256(script_path.read_bytes()).hexdigest(),
        "speech_unit_count": len(units),
        "spoken_text": spoken,
        "display_text_zh": display_zh,
        "visual_trigger_sequence": triggers,
        "rhythm_blocks": script.get("rhythm_blocks", []),
        "storyboard_sequence": sequence,
        "scene_template": identity["scene_template"],
        "visual_strategy": identity["visual_strategy"],
        "essential_identity_sha256": _digest(identity),
        "fingerprint_sha256": _digest({
            **identity,
            "script_id": script.get("script_id"),
            "editorial_angle_id": script.get("editorial_angle_id"),
        }),
    }


def compare_fingerprints(
    current: dict[str, Any], previous: list[dict[str, Any]]
) -> dict[str, Any]:
    """Return a deterministic comparison; identical essential identity fails."""
    comparisons = []
    for item in previous:
        reasons = []
        if item.get("essential_identity_sha256") == current.get("essential_identity_sha256"):
            reasons.append("identical_essential_identity")
        if item.get("script_sha256") == current.get("script_sha256"):
            reasons.append("identical_script_sha256")
        if item.get("spoken_text") == current.get("spoken_text"):
            reasons.append("identical_spoken_text")
        if item.get("visual_trigger_sequence") == current.get("visual_trigger_sequence"):
            reasons.append("identical_visual_trigger_sequence")
        if item.get("scene_template") == current.get("scene_template") and (
            item.get("visual_strategy") == current.get("visual_strategy")
        ):
            reasons.append("identical_scene_template_and_strategy")
        comparisons.append({
            "run_id": item.get("run_id"),
            "reasons": reasons,
            "similar": bool(reasons),
            "script_id": item.get("script_id"),
            "editorial_angle_id": item.get("editorial_angle_id"),
        })
    blocking = [
        item for item in comparisons
        if "identical_essential_identity" in item["reasons"]
    ]
    return {
        "passes": not blocking,
        "current_run_id": current.get("run_id"),
        "current_script_id": current.get("script_id"),
        "current_editorial_angle_id": current.get("editorial_angle_id"),
        "blocking_runs": [item["run_id"] for item in blocking],
        "comparisons": comparisons,
    }


def content_uniqueness_gate(
    run_dir: Path,
    outputs_root: Path,
    *,
    exclude_run_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Compare a run against all prior generated runs under outputs/."""
    run_dir = run_dir.resolve()
    outputs_root = outputs_root.resolve()
    current = build_content_fingerprint(run_dir)
    exclude = set(exclude_run_ids or ())
    exclude.add(run_dir.name)
    previous: list[dict[str, Any]] = []
    for child in sorted(outputs_root.iterdir()):
        if not child.is_dir() or child.name in exclude:
            continue
        path = child / "content_fingerprint.json"
        if path.is_file():
            previous.append(_read_json(path))
        elif (child / "script.json").is_file() and (child / "qa_report.json").is_file():
            try:
                previous.append(build_content_fingerprint(child))
            except Exception:
                continue
    report = compare_fingerprints(current, previous)
    report["compared_run_count"] = len(previous)
    (run_dir / "content_fingerprint.json").write_text(
        json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "content_difference_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report
