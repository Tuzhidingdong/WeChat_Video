"""Shared visual-stage and motion-event definitions for the Slice A template."""
from __future__ import annotations

from typing import Any

from .master_config import theme_config


TRIGGER_TO_STAGE: dict[str, tuple[str, str]] = {
    "SEED_FORM_DISSOLVE": ("seed_failure", "Subcritical seed fades"),
    "SEED_GROW": ("seed_success", "Supercritical seed grows"),
    "SEED_QUESTION": ("particle_embryo", "Critical-size question"),
    "TWO_TERMS": ("energy_competition", "Two opposing terms"),
    "SURFACE_COST": ("surface_cost", "Surface-energy cost"),
    "AREA_SCALING": ("area_scaling", "Area scales as r squared"),
    "BULK_GAIN": ("bulk_gain", "Bulk free-energy gain"),
    "VOLUME_SCALING": ("volume_scaling", "Volume scales as r cubed"),
    "COMPETITION": ("competition", "Live term competition"),
    "SMALL_R_SURFACE": ("competition", "Small-r surface dominance"),
    "CURVE_DRAW": ("free_energy_landscape", "Free-energy curve drawing"),
    "CRITICAL_PEAK": ("critical_threshold", "Critical-radius peak"),
    "BARRIER_EQ": ("barrier_relation", "Barrier relation"),
    "MODEL_ASSUMPTION": ("model_scope", "Model assumptions"),
    "SUBCRITICAL_RETURN": ("subcritical_return", "Subcritical return"),
    "SUPERCRITICAL_DESCENT": ("supercritical_descent", "Supercritical descent"),
    "THERMO_CAVEAT": ("thermo_caveat", "Thermodynamic tendency"),
    "REAL_SYSTEMS": ("real_systems", "Real-system factors"),
    "CRYSTAL_GROW": ("crystal_growth", "Crystal growth beyond threshold"),
    "TAKEAWAY": ("takeaway", "Memorable principle"),
}

TRIGGER_TO_MOTION: dict[str, str] = {
    "SEED_FORM_DISSOLVE": "seed_assemble_and_dissolve",
    "SEED_GROW": "seed_assemble_and_grow",
    "SEED_QUESTION": "marker_pulse",
    "TWO_TERMS": "term_split",
    "SURFACE_COST": "surface_growth",
    "AREA_SCALING": "r_squared_rise",
    "BULK_GAIN": "bulk_release",
    "VOLUME_SCALING": "r_cubed_rise",
    "COMPETITION": "term_crossover",
    "SMALL_R_SURFACE": "surface_dominance",
    "CURVE_DRAW": "curve_draw",
    "CRITICAL_PEAK": "peak_reveal",
    "BARRIER_EQ": "barrier_highlight",
    "MODEL_ASSUMPTION": "scope_fade",
    "SUBCRITICAL_RETURN": "subcritical_return",
    "SUPERCRITICAL_DESCENT": "supercritical_descent",
    "THERMO_CAVEAT": "caveat_fade",
    "REAL_SYSTEMS": "context_fade",
    "CRYSTAL_GROW": "crystal_growth",
    "TAKEAWAY": "final_resolve",
}

TRANSITION_MIN_MS = 250
TRANSITION_MAX_MS = 600
TRANSITION_DIVISOR = 5000
DIM_OPACITY = 0.25

EDITORIAL_BEATS = {
    "HOOK": "counter-intuitive hook",
    "CONFLICT": "surface vs bulk conflict",
    "r_squared_rise": "r² vs r³ crossover",
    "CRITICAL_PEAK": "critical-radius peak",
    "TAKEAWAY": "final practical takeaway",
}


def stage_for_unit(unit: dict[str, Any]) -> tuple[str, str]:
    triggers = list(unit.get("visual_trigger_ids") or [])
    if not triggers:
        raise ValueError(f"{unit.get('unit_id')} has no visual_trigger_ids")
    stages = {TRIGGER_TO_STAGE.get(trigger, (None, None))[0] for trigger in triggers}
    if len(stages) != 1 or None in stages:
        raise ValueError(
            f"{unit.get('unit_id')} maps to ambiguous/unregistered stages: {triggers}"
        )
    stage_key = next(iter(stages))
    label = next(label for key, label in TRIGGER_TO_STAGE.values() if key == stage_key)
    return stage_key, label


def transition_ms(duration_ms: int) -> int:
    return max(TRANSITION_MIN_MS, min(TRANSITION_MAX_MS, int(duration_ms) // TRANSITION_DIVISOR))


def build_stage_manifest(
    cues: list[dict[str, Any]], units: list[dict[str, Any]], fps: int = 30
) -> dict[str, Any]:
    if len(cues) != len(units):
        raise ValueError("cue/units length mismatch in visual stage manifest")
    stages: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for cue, unit in zip(cues, units):
        stage_key, label = stage_for_unit(unit)
        stage_id = f"{stage_key}_{unit['unit_id']}"
        if stage_id in seen_ids:
            raise ValueError(f"duplicate visual stage id: {stage_id}")
        seen_ids.add(stage_id)
        start_ms = int(cue["start_ms"])
        end_ms = int(cue["end_ms"])
        trans_ms = transition_ms(end_ms - start_ms)
        stages.append(
            {
                "stage_id": stage_id,
                "stage_key": stage_key,
                "label": label,
                "unit_id": unit["unit_id"],
                "rhythm_block_id": unit.get("rhythm_block_id"),
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
        )
    return {
        "schema_version": 2,
        "template": "critical_nucleus_free_energy_barrier",
        "camera": "static portrait",
        "fps": fps,
        "time_origin": "final_mp4_first_frame",
        "one_active_stage_per_cue": True,
        "previous_stage_removed_before_next": True,
        "unique_stage_ids": True,
        "dim_opacity_for_inactive_objects": DIM_OPACITY,
        "stages": stages,
    }


def build_motion_manifest(
    cues: list[dict[str, Any]], units: list[dict[str, Any]], fps: int = 30
) -> dict[str, Any]:
    theme = theme_config()
    state = theme["state_curve_motion"]
    focus = theme["focus_rules"]

    def curve_y(x: float) -> float:
        return 3.0 * x**2 - 2.0 * x**3

    events: list[dict[str, Any]] = []
    for cue, unit in zip(cues, units):
        trigger = unit["visual_trigger_ids"][0]
        motion = TRIGGER_TO_MOTION.get(trigger)
        if not motion:
            raise ValueError(f"No motion event registered for trigger {trigger}")
        start_ms = int(cue["start_ms"])
        trans_ms = transition_ms(int(cue["end_ms"]) - start_ms)
        event: dict[str, Any] = {
            "event_id": f"{motion}_{unit['unit_id']}",
            "motion_type": motion,
            "unit_id": unit["unit_id"],
            "rhythm_block_id": unit.get("rhythm_block_id"),
            "trigger_id": trigger,
            "start_ms": start_ms + trans_ms,
            "end_ms": int(cue["end_ms"]),
            "start_frame": round((start_ms + trans_ms) * fps / 1000),
            "end_frame": round(int(cue["end_ms"]) * fps / 1000),
            "dim_opacity": focus["inactive_opacity"],
            "graph_opacity_during_motion": focus["primary_curve_opacity_during_motion"],
            "marker_opacity_during_motion": focus["marker_opacity_during_motion"],
            "schematic_marker": state["schematic_marker"],
        }
        if motion == "subcritical_return":
            path = state["subcritical"]
            event.update(
                {
                    "path_start_x": path["start_x"],
                    "path_approach_x": path["approach_x"],
                    "path_end_x": path["return_x"],
                    "path_start_y": round(curve_y(path["start_x"]), 5),
                    "path_end_y": round(curve_y(path["return_x"]), 5),
                    "direction": "approach_then_return_left",
                    "crosses_threshold": path["crosses_threshold"],
                    "threshold_x": state["threshold_x"],
                    "monotonic": False,
                    "easing": path["easing"],
                    "marker_scale_end": path["marker_scale_end"],
                    "marker_fade_end": path["marker_fade_end"],
                }
            )
        elif motion == "supercritical_descent":
            path = state["supercritical"]
            event.update(
                {
                    "path_start_x": path["start_x"],
                    "path_end_x": path["end_x"],
                    "path_start_y": round(curve_y(path["start_x"]), 5),
                    "path_end_y": round(curve_y(path["end_x"]), 5),
                    "direction": "downhill_right",
                    "crosses_threshold": False,
                    "threshold_x": state["threshold_x"],
                    "monotonic": path["monotonic"],
                    "easing": path["easing"],
                    "marker_scale_end": path["marker_scale_end"],
                    "marker_fade_end": path["marker_fade_end"],
                }
            )
        events.append(event)
    return {
        "schema_version": 1,
        "camera": "static portrait",
        "continuous_motion": True,
        "events": events,
    }
