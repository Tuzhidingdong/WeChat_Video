"""Shared visual-stage and motion-event definitions for the Slice A template."""
from __future__ import annotations

from typing import Any

from .hook_motion import PHASE_SECONDS, TOTAL_SECONDS, hook_particle_states, mean_radial_distance
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
    "GAMMA_CUBED_PULSE": ("barrier_relation", "Gamma-cubed term pulse"),
    "DRIVING_FORCE_SQUARED_PULSE": ("barrier_relation", "Driving-force-squared term pulse"),
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
    "CURVE_DRAW": "rise_to_peak",
    "CRITICAL_PEAK": "peak_hold",
    "BARRIER_EQ": "barrier_highlight",
    "GAMMA_CUBED_PULSE": "gamma_cubed_pulse",
    "DRIVING_FORCE_SQUARED_PULSE": "driving_force_squared_pulse",
    "MODEL_ASSUMPTION": "scope_fade",
    "SUBCRITICAL_RETURN": "subcritical_return",
    "SUPERCRITICAL_DESCENT": "supercritical_descent",
    "THERMO_CAVEAT": "affirmed_vs_excluded",
    "REAL_SYSTEMS": "context_fade",
    "CRYSTAL_GROW": "crystal_growth",
    "TAKEAWAY": "final_resolve",
}

TRANSITION_MIN_MS = 450
TRANSITION_MAX_MS = 800
TRANSITION_DIVISOR = 4500
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
        elif motion in {"rise_to_peak", "peak_hold"}:
            threshold = float(state["threshold_x"])
            if motion == "rise_to_peak":
                samples = [
                    {
                        "t": round(q, 3),
                        "x": round(threshold * min(1.0, q / 0.8), 5),
                        "y": round(curve_y(threshold * min(1.0, q / 0.8)), 5),
                    }
                    for q in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
                ]
                event.update(
                    {
                        "marker_start_x": 0.0,
                        "marker_start_y": round(curve_y(0.0), 5),
                        "marker_peak_x": threshold,
                        "marker_peak_y": round(curve_y(threshold), 5),
                        "follows_plotted_curve": True,
                        "monotonic_toward_peak": True,
                        "reaches_peak_fraction": 0.8,
                        "held_at_peak_after_fraction": 0.8,
                        "samples": samples,
                        "no_right_branch_travel": True,
                    }
                )
            else:
                event.update(
                    {
                        "marker_start_x": threshold,
                        "marker_start_y": round(curve_y(threshold), 5),
                        "marker_end_x": threshold,
                        "marker_end_y": round(curve_y(threshold), 5),
                        "held_at_peak": True,
                        "stationary": True,
                        "follows_plotted_curve": True,
                    }
                )
        elif motion == "affirmed_vs_excluded":
            hierarchy = theme["concept_hierarchy"]
            event.update(
                {
                    "layout_pattern": hierarchy["pattern"],
                    "affirmed_item": "direction",
                    "affirmed_position": hierarchy["affirmed"]["position"],
                    "affirmed_primary": True,
                    "affirmed_mark": hierarchy["affirmed"]["mark"],
                    "rejected_item": "speed",
                    "rejected_position": hierarchy["excluded"]["position"],
                    "rejected_secondary": True,
                    "rejected_mark": hierarchy["excluded"]["mark"],
                    "strike_through_over_symbol": hierarchy["excluded"]["strike_through_over_symbol"],
                    "strike_through_visible": True,
                    "affirmed_read_order_first": True,
                }
            )
        elif motion in {"gamma_cubed_pulse", "driving_force_squared_pulse"}:
            pulse = theme["formula_pulse"]
            is_gamma = motion == "gamma_cubed_pulse"
            event.update(
                {
                    "pulse_term": "gamma" if is_gamma else "driving_force",
                    "pulse_symbol": r"\gamma^3" if is_gamma else r"\Delta g_v^2",
                    "pulse_scale_peak": pulse["scale_peak"],
                    "term_dim_opacity": pulse["dim_opacity"],
                    "restore_opacity": pulse["restore_opacity"],
                    "dim_only_non_current_terms": True,
                    "primary_curve_unchanged": True,
                }
            )
        elif motion in {"seed_assemble_and_dissolve", "seed_assemble_and_grow"}:
            ghost = theme["hook_ghost"]
            event.update(
                {
                    "hook_comparison_ghost": True,
                    "active_opacity": ghost["active_opacity"],
                    "inactive_opacity": ghost["inactive_opacity"],
                    "inactive_side_never_removed": True,
                    "reference_rings_always_visible": ghost["reference_rings_always_visible"],
                }
            )
        events.append(event)

    ghost = theme["hook_ghost"]
    hook_events = [e for e in events if e.get("hook_comparison_ghost")]
    if hook_events:
        events.append(
            {
                "event_id": "hook_persistent_comparison",
                "motion_type": "hook_comparison_ghost",
                "rhythm_block_id": "HOOK",
                "dim_opacity": focus["inactive_opacity"],
                "start_frame": 0,
                "end_frame": round(float(ghost["persistent_seconds"]) * fps),
                "active_opacity": ghost["active_opacity"],
                "inactive_opacity": ghost["inactive_opacity"],
                "inactive_side_never_removed": True,
                "reference_rings_always_visible": ghost["reference_rings_always_visible"],
                "both_zones_present_through_hook": True,
                "first_frame_left_particles": len(hook_particle_states(0.0)["left"]),
                "first_frame_non_empty": True,
                "phase_seconds": PHASE_SECONDS,
                "total_motion_seconds": TOTAL_SECONDS,
                "trajectory_samples": [
                    {
                        "t": t,
                        "active_side": hook_particle_states(t)["active_side"],
                        "left_mean_radius": round(
                            mean_radial_distance(hook_particle_states(t)["left"]), 4
                        ),
                        "right_mean_radius": round(
                            mean_radial_distance(hook_particle_states(t)["right"]), 4
                        ),
                    }
                    for t in (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0)
                ],
                "left_inward": True,
                "right_outward": True,
            }
        )
    halo_cfg = theme["ending_halo"]
    if halo_cfg.get("enabled", False):
        end_unit_id = units[-1]["unit_id"]
        spans = [
            e for e in events
            if e.get("unit_id") in {halo_cfg["start_unit_id"], end_unit_id}
        ]
        if spans:
            first = min(int(e["start_frame"]) for e in spans)
            last = max(int(e["end_frame"]) for e in spans)
            events.append(
                {
                    "event_id": "final_breathing_halo",
                    "motion_type": "final_breathing_halo",
                    "rhythm_block_id": "TAKEAWAY",
                    "dim_opacity": focus["inactive_opacity"],
                    "start_frame": first,
                    "end_frame": last,
                    "period_seconds": halo_cfg["period_seconds"],
                    "approx_cycles": round((last - first) / fps / float(halo_cfg["period_seconds"]), 2),
                    "color_role": "resistance",
                    "critical_marker_unchanged": True,
                }
            )
    return {
        "schema_version": 1,
        "camera": "static portrait",
        "continuous_motion": True,
        "stage_scale": theme["stage_scale"],
        "events": events,
    }
