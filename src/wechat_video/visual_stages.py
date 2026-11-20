"""Shared visual-stage definitions for the Slice A critical-nucleus template.

The Manim scene and the pipeline's visual_stage_manifest both use these
constants so that stage IDs and transition timing cannot drift apart.
"""
from __future__ import annotations

from typing import Any


TRIGGER_TO_STAGE: dict[str, tuple[str, str]] = {
    "INTRO_QUESTION": ("particle_embryo", "Particle embryo"),
    "SHOW_TOTAL_FREE_ENERGY": ("energy_competition", "Total free energy"),
    "SHOW_SCALING": ("area_vs_volume", "Area versus volume"),
    "SHOW_FREE_ENERGY_CURVE": ("free_energy_landscape", "Free-energy landscape"),
    "MARK_CRITICAL_RADIUS": ("critical_threshold", "Critical threshold"),
    "COMPARE_SUB_SUPERCRITICAL": ("critical_threshold", "Critical threshold"),
    "SHOW_CRITICAL_RADIUS_EQUATION": ("critical_radius_equation", "Critical radius relation"),
    "SHOW_BARRIER_EQUATION": ("barrier_equation", "Barrier relation"),
    "MODEL_LIMITS": ("model_assumptions", "Model assumptions and limits"),
}

TRANSITION_MIN_MS = 250
TRANSITION_MAX_MS = 600
TRANSITION_DIVISOR = 5000


def stage_for_unit(unit: dict[str, Any]) -> tuple[str, str]:
    """Resolve one unique stage for a speech unit from its visual triggers."""
    triggers = list(unit.get("visual_trigger_ids") or [])
    if not triggers:
        raise ValueError(f"{unit.get('unit_id')} has no visual_trigger_ids")
    stages = {TRIGGER_TO_STAGE.get(trigger, (None, None))[0] for trigger in triggers}
    if len(stages) != 1 or None in stages:
        raise ValueError(
            f"{unit.get('unit_id')} maps to ambiguous/unregistered stages: "
            f"{triggers} -> {sorted(str(s) for s in stages)}"
        )
    stage_id = next(iter(stages))
    label = next(label for sid, label in TRIGGER_TO_STAGE.values() if sid == stage_id)
    return stage_id, label


def transition_ms(duration_ms: int) -> int:
    """Bounded stage-transition duration derived from measured cue duration."""
    return max(TRANSITION_MIN_MS, min(TRANSITION_MAX_MS, int(duration_ms) // TRANSITION_DIVISOR))


def build_stage_manifest(
    cues: list[dict[str, Any]], units: list[dict[str, Any]], fps: int = 30
) -> dict[str, Any]:
    """Build the per-cue visual stage manifest from measured global timing."""
    if len(cues) != len(units):
        raise ValueError("cue/units length mismatch in visual stage manifest")
    stages: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for cue, unit in zip(cues, units):
        stage_id, label = stage_for_unit(unit)
        if stage_id in seen_ids:
            raise ValueError(f"duplicate visual stage id: {stage_id}")
        seen_ids.add(stage_id)
        start_ms = int(cue["start_ms"])
        end_ms = int(cue["end_ms"])
        trans_ms = transition_ms(end_ms - start_ms)
        record = {
            "stage_id": stage_id,
            "label": label,
            "unit_id": unit["unit_id"],
            "triggers": list(unit["visual_trigger_ids"]),
            "start_ms": start_ms,
            "end_ms": end_ms,
            "start_frame": round(start_ms * fps / 1000),
            "end_frame": round(end_ms * fps / 1000),
            "transition_start_frame": round(start_ms * fps / 1000),
            "transition_end_frame": round((start_ms + trans_ms) * fps / 1000),
            "transition_duration_ms": trans_ms,
            "active_stage": stage_id,
        }
        stages.append(record)
    return {
        "schema_version": 1,
        "template": "critical_nucleus_free_energy_barrier",
        "camera": "static portrait",
        "fps": fps,
        "time_origin": "final_mp4_first_frame",
        "one_active_stage_per_cue": True,
        "previous_stage_removed_before_next": True,
        "unique_stage_ids": True,
        "stages": stages,
    }
