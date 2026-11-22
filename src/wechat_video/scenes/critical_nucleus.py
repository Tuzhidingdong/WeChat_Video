from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Callable

import numpy as np
from manim import (
    Arrow,
    Axes,
    Circle,
    Create,
    DashedLine,
    Dot,
    Ellipse,
    FadeIn,
    FadeOut,
    LEFT,
    Line,
    MathTex,
    Polygon,
    Rectangle,
    RIGHT,
    Scene,
    Text,
    VGroup,
    DOWN,
    UP,
    ValueTracker,
    always_redraw,
    linear,
    smooth,
)

from ..hook_motion import (
    LEFT_X_OFFSET,
    RIGHT_X_OFFSET,
    TOTAL_SECONDS,
    hook_particle_states,
)
from ..master_config import theme_color, theme_config
from ..visual_stages import stage_for_unit, transition_ms


FRAME_WIDTH = 9.0
FRAME_HEIGHT = 16.0
GRAPH_STAGES = {
    "free_energy_landscape",
    "critical_threshold",
    "subcritical_return",
    "supercritical_descent",
}
HOOK_STAGES = {"seed_failure", "seed_success"}
HALO_STAGES = {"crystal_growth", "takeaway"}


def _bounds(profile: dict[str, Any]) -> dict[str, float]:
    zones = profile["safe_zones"]
    left = -FRAME_WIDTH / 2 + FRAME_WIDTH * zones["left_margin_percent"] / 100
    right = FRAME_WIDTH / 2 - FRAME_WIDTH * zones["right_reserved_percent"] / 100
    top = FRAME_HEIGHT / 2 - FRAME_HEIGHT * zones["top_reserved_percent"] / 100
    bottom = FRAME_HEIGHT / 2 - FRAME_HEIGHT * zones["science_content_bottom_percent"] / 100
    return {
        "left": left,
        "right": right,
        "top": top,
        "bottom": bottom,
        "center_x": (left + right) / 2,
        "center_y": (top + bottom) / 2,
        "content_width": right - left,
    }


def _fit(mobject: Any, max_width: float) -> Any:
    if mobject.width > max_width:
        mobject.scale_to_fit_width(max_width)
    return mobject


def _assert_safe_zone(mobject: Any, label: str, box: dict[str, float]) -> None:
    boundary = mobject.get_points_defining_boundary()
    if len(boundary) == 0:
        return
    x_min = min(float(p[0]) for p in boundary)
    y_min = min(float(p[1]) for p in boundary)
    x_max = max(float(p[0]) for p in boundary)
    y_max = max(float(p[1]) for p in boundary)
    tol = 0.03
    if (
        x_min < box["left"] - tol
        or x_max > box["right"] + tol
        or y_min < box["bottom"] - tol
        or y_max > box["top"] + tol
    ):
        raise ValueError(
            f"Safe-zone overflow: {label}; object=({x_min:.2f},{y_min:.2f}).."
            f"({x_max:.2f},{y_max:.2f}), safe=({box['left']:.2f},{box['bottom']:.2f}).."
            f"({box['right']:.2f},{box['top']:.2f})"
        )


def _cap(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _scale_about(mobject: Any, factor: float, centre: np.ndarray) -> Any:
    if abs(factor - 1.0) > 1e-9:
        mobject.scale(factor, about_point=centre)
    return mobject


def _max_safe_factor(
    mobject: Any, box: dict[str, float], centre: np.ndarray, target: float, tol: float = 0.03
) -> float:
    """Largest uniform scale about the science centre that keeps all points inside the box."""
    boundary = mobject.get_points_defining_boundary()
    if len(boundary) == 0:
        return target
    cx, cy = float(centre[0]), float(centre[1])
    factor = target
    for point in boundary:
        dx, dy = float(point[0]) - cx, float(point[1]) - cy
        if dx > 1e-6:
            factor = min(factor, (box["right"] - tol - cx) / dx)
        elif dx < -1e-6:
            factor = min(factor, (box["left"] + tol - cx) / dx)
        if dy > 1e-6:
            factor = min(factor, (box["top"] - tol - cy) / dy)
        elif dy < -1e-6:
            factor = min(factor, (box["bottom"] + tol - cy) / dy)
    return max(1.0, min(target, factor))


def _barrier_curve_hook(
    tracker: Any,
    scale: list[float],
    box: dict[str, float],
    centre: Any,
    font: str,
    cjk_font: str,
    favorable: Any,
    resistance: Any,
    critical: Any,
    neutral: Any,
) -> VGroup:
    """Curve-first opening used only by the barrier-peak-anatomy strategy.

    This is a genuinely different composition from the binary particle hook:
    the full ΔG(r) curve is present from frame zero and a marker climbs to the
    peak while the two peak coordinates are labelled separately.
    """
    axes = Axes(
        x_range=[0, 2.05, 0.5],
        y_range=[-0.6, 1.4, 0.5],
        x_length=4.6,
        y_length=3.4,
        tips=False,
        axis_config={"color": neutral, "stroke_width": 2},
    ).move_to([box["center_x"], box["center_y"] - 0.2, 0])
    curve = axes.plot(
        lambda x: 3 * x**2 - 2 * x**3, x_range=[0, 2.0],
        color=favorable, stroke_width=5,
    )
    curve.set_fill(opacity=0)
    title = Text(
        "Free energy along the pathway", font=font, font_size=22, color=favorable,
    ).move_to([box["center_x"], box["top"] - 0.5, 0])

    def peak_annotation() -> VGroup:
        p = min(1.0, max(0.0, tracker.get_value() / max(TOTAL_SECONDS, 0.001)))
        x = p
        y = 3 * x**2 - 2 * x**3
        marker = Dot(axes.c2p(x, y), color=critical, radius=0.09)
        vertical = DashedLine(
            axes.c2p(1.0, -0.6), axes.c2p(1.0, 1.0),
            color=critical, stroke_width=2, dash_length=0.08,
        )
        horizontal = DashedLine(
            axes.c2p(0, 1.0), axes.c2p(1.0, 1.0),
            color=resistance, stroke_width=2, dash_length=0.08,
        )
        x_label = MathTex(r"r^*", font_size=26, color=critical).move_to(
            axes.c2p(1.0, -0.38)
        )
        y_label = MathTex(r"\Delta G^*", font_size=24, color=resistance).move_to(
            axes.c2p(0.22, 1.0)
        )
        return VGroup(marker, vertical, horizontal, x_label, y_label)

    hook = VGroup(
        axes, curve, title, always_redraw(peak_annotation),
    )
    return VGroup(always_redraw(lambda: _scale_about(hook, scale[0], centre)))


class CriticalNucleusScene(Scene):
    """Static portrait camera with continuous, physically meaningful motion."""

    def construct(self) -> None:
        spec_path = os.environ.get("WECHAT_VIDEO_SCENE_SPEC")
        if not spec_path:
            raise RuntimeError("WECHAT_VIDEO_SCENE_SPEC is not configured.")
        spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
        profile = spec["layout"]
        font = spec["font_family"]
        cjk_font = spec.get("cjk_font_family", font)
        theme = theme_config()
        palette = theme["palette"]
        favorable = palette["driving_force"]
        resistance = palette["resistance"]
        critical = palette["critical"]
        neutral = palette["neutral"]
        grid = theme["portrait_grid"]
        focus = theme["focus_rules"]
        scale_cfg = theme["stage_scale"]
        ghost_cfg = theme["hook_ghost"]
        halo_cfg = theme["ending_halo"]
        box = _bounds(profile)
        cx, cy = box["center_x"], box["center_y"]
        centre = np.array([cx, cy, 0.0])
        max_w = box["content_width"] - 0.3

        target_scale = float(scale_cfg["target"])
        if scale_cfg.get("enabled", True):
            target_scale = _cap(
                target_scale, float(scale_cfg["min"]), float(scale_cfg["max"])
            )
        else:
            target_scale = 1.0

        scale_report: dict[str, Any] = {
            "schema_version": 1,
            "theme_id": theme["theme_id"],
            "enabled": scale_cfg.get("enabled", True),
            "target": target_scale,
            "bounded_range": [scale_cfg["min"], scale_cfg["max"]],
            "safe_box": box,
            "per_stage": [],
        }

        assert abs(float(self.camera.frame_width) - FRAME_WIDTH) < 0.01
        assert abs(float(self.camera.frame_height) - FRAME_HEIGHT) < 0.01

        badge_y = (
            FRAME_HEIGHT / 2
            - FRAME_HEIGHT
            * (grid["badge_top_percent"] + grid["badge_bottom_percent"])
            / 200
        )
        badge = (
            Text(theme["series_identity"]["badge_text"], font=cjk_font, font_size=18,
                 color=neutral)
            .move_to([cx, badge_y, 0])
            .set_opacity(0.75)
        )
        self.add(badge)

        # ------------------------------------------------------------------ hook
        # Driven by the pure hook_motion states: left orange particles are already
        # visible at frame 0, contract inward and fade over 0-2 s; right cyan
        # particles emerge near the centre and grow outward over 2-4 s. Both rings
        # and both zones stay present, with the inactive side as a 0.22 ghost.
        hook_t = ValueTracker(0.0)
        hook_scale = [1.0]
        left_x, right_x = cx + LEFT_X_OFFSET, cx + RIGHT_X_OFFSET

        def hook_particles_for(side: str) -> VGroup:
            states = hook_particle_states(hook_t.get_value())[side]
            center_x = left_x if side == "left" else right_x
            color = resistance if side == "left" else favorable
            dots: list[Dot] = []
            for state in states:
                if state["opacity"] <= 0.001 or state["radius"] <= 0.0005:
                    continue
                dots.append(
                    Dot(
                        [center_x + state["dx"], cy + state["dy"], 0],
                        radius=state["radius"],
                        color=color,
                    ).set_opacity(state["opacity"])
                )
            return VGroup(*dots)

        def hook_ring_for(side: str) -> Circle:
            is_active = hook_particle_states(hook_t.get_value())["active_side"] == side
            stroke_opacity = 0.45 if is_active else float(ghost_cfg["inactive_opacity"])
            center_x = left_x if side == "left" else right_x
            return Circle(
                radius=0.72, color=neutral, stroke_width=1,
                stroke_opacity=stroke_opacity,
            ).move_to([center_x, cy, 0])

        def hook_label_for(side: str) -> Text:
            is_active = hook_particle_states(hook_t.get_value())["active_side"] == side
            opacity = ghost_cfg["active_opacity"] if is_active else ghost_cfg["inactive_opacity"]
            center_x = left_x if side == "left" else right_x
            return Text(
                "grows" if side == "right" else "fades", font=font, font_size=22,
                color=favorable if side == "right" else resistance,
            ).set_opacity(opacity).move_to([center_x, cy - 1.15, 0])

        left_dots = always_redraw(lambda: _scale_about(hook_particles_for("left"), hook_scale[0], centre))
        right_dots = always_redraw(lambda: _scale_about(hook_particles_for("right"), hook_scale[0], centre))
        left_ring = always_redraw(lambda: _scale_about(hook_ring_for("left"), hook_scale[0], centre))
        right_ring = always_redraw(lambda: _scale_about(hook_ring_for("right"), hook_scale[0], centre))
        left_label = always_redraw(lambda: _scale_about(hook_label_for("left"), hook_scale[0], centre))
        right_label = always_redraw(lambda: _scale_about(hook_label_for("right"), hook_scale[0], centre))
        hook_group = VGroup(left_dots, right_dots, left_ring, right_ring, left_label, right_label)
        if spec.get("visual_strategy") == "barrier_peak_anatomy":
            # Replace the particle-comparison opening entirely with the curve
            # anatomy opening; the particle mobjects above are never added.
            hook_group = _barrier_curve_hook(
                hook_t, hook_scale, box, centre, font, cjk_font,
                favorable, resistance, critical, neutral,
            )

        # Find the largest safe stage factor at the widest geometry (t = 4 s).
        hook_t.set_value(TOTAL_SECONDS)
        for item in hook_group.get_family():
            if getattr(item, "updaters", None):
                item.update()
        hook_factor = _max_safe_factor(hook_group, box, centre, target_scale)
        hook_scale[0] = hook_factor
        scale_report["per_stage"].append(
            {"stage": "binary_hook", "applied": round(hook_factor, 4), "target": target_scale}
        )
        _assert_safe_zone(hook_group, "binary_hook", box)
        # Rewind to frame 0 and add directly (no FadeIn) so the left particles are
        # already visible in the very first rendered frame.
        hook_t.set_value(0.0)
        for item in hook_group.get_family():
            if getattr(item, "updaters", None):
                item.update()
        self.add(hook_group)
        self.play(
            hook_t.animate.set_value(TOTAL_SECONDS),
            run_time=TOTAL_SECONDS,
            rate_func=linear,
        )
        hook_visible = True
        cursor_ms = round(TOTAL_SECONDS * 1000)

        # ------------------------------------------------------------ breathing halo
        halo_scale = [1.0]
        halo_tracker = ValueTracker(0.0)

        def halo_shape() -> VGroup:
            cycles = halo_tracker.get_value()
            phase = 2 * math.pi * cycles
            radius = halo_cfg["base_radius"] + halo_cfg["radius_amplitude"] * math.sin(phase)
            stroke = halo_cfg["stroke_width_base"] + halo_cfg["stroke_width_amplitude"] * math.sin(phase)
            opacity = (
                (float(halo_cfg["opacity_min"]) + float(halo_cfg["opacity_max"])) / 2
                + (float(halo_cfg["opacity_max"]) - float(halo_cfg["opacity_min"])) / 2 * math.sin(phase)
            )
            ring = Circle(radius=radius, color=resistance, stroke_width=stroke).move_to([cx, cy, 0])
            ring.set_stroke(opacity=opacity)
            return _scale_about(VGroup(ring), halo_scale[0], centre)

        halo = always_redraw(halo_shape)
        halo_visible = False

        current: list[Any] = []
        current_stage: str | None = None

        for checkpoint in spec["cue_checkpoints"]:
            stage_key, _ = stage_for_unit(checkpoint)
            if stage_key in HOOK_STAGES:
                # The whole 0-4 s hook animation was already played above.
                continue
            start_ms = int(checkpoint["start_ms"])
            end_ms = int(checkpoint["end_ms"])
            if start_ms < cursor_ms:
                raise ValueError(f"Cue overlap at {checkpoint['unit_id']}")
            if start_ms > cursor_ms:
                self.wait((start_ms - cursor_ms) / 1000.0)

            trans_ms = transition_ms(end_ms - start_ms)
            trans = trans_ms / 1000.0
            hold_ms = end_ms - start_ms - trans_ms
            hold_s = max(0.0, hold_ms / 1000.0)
            tracker = ValueTracker(0.0)

            transition_animations: list[Any] = [FadeOut(item) for item in current]
            if hook_visible:
                transition_animations.append(FadeOut(hook_group))
                hook_visible = False

            pulse_term = None
            triggers = list(checkpoint.get("visual_trigger_ids") or [])
            if "GAMMA_CUBED_PULSE" in triggers:
                pulse_term = "gamma"
            elif "DRIVING_FORCE_SQUARED_PULSE" in triggers:
                pulse_term = "driving_force"
            elif "BARRIER_EQ" in triggers:
                pulse_term = "barrier"

            overlay, animated, factor = self._build_overlay(
                stage_key, tracker, box, font, cjk_font, favorable, resistance,
                critical, neutral, pulse_term, target_scale, centre,
            )
            scale_report["per_stage"].append(
                {
                    "stage": checkpoint["unit_id"],
                    "stage_key": stage_key,
                    "applied": round(factor, 4),
                    "target": target_scale,
                }
            )
            for item in overlay.submobjects:
                _assert_safe_zone(item, f"{stage_key}:{id(item) % 100}", box)

            transition_animations.append(FadeIn(overlay))
            if stage_key in HALO_STAGES and halo_cfg.get("enabled", False):
                if not halo_visible:
                    transition_animations.append(FadeIn(halo))
                    halo_visible = True
            self.play(*transition_animations, run_time=trans, rate_func=smooth)

            hold_animations: list[Any] = []
            if hold_s > 0 and animated:
                hold_animations.append(tracker.animate.set_value(1.0))
            if stage_key in HALO_STAGES and halo_visible and hold_s > 0:
                cycles = hold_s / float(halo_cfg["period_seconds"])
                hold_animations.append(
                    halo_tracker.animate.set_value(halo_tracker.get_value() + cycles)
                )
            if hold_animations:
                self.play(*hold_animations, run_time=hold_s, rate_func=linear)

            current = [overlay]
            current_stage = stage_key
            cursor_ms = start_ms + trans_ms + max(0, hold_ms)

        total_ms = int(spec["total_duration_ms"])
        if total_ms < cursor_ms:
            raise ValueError(f"Cue motion exceeds timeline: {cursor_ms} > {total_ms}")
        if total_ms > cursor_ms:
            self.wait((total_ms - cursor_ms) / 1000.0)

        report_path = spec.get("stage_scale_report")
        if report_path:
            Path(report_path).parent.mkdir(parents=True, exist_ok=True)
            Path(report_path).write_text(
                json.dumps(scale_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

    def _build_overlay(
        self,
        stage_key: str,
        tracker: ValueTracker,
        box: dict[str, float],
        font: str,
        cjk_font: str,
        favorable: str,
        resistance: str,
        critical: str,
        neutral: str,
        pulse_term: str | None,
        target_scale: float,
        centre: np.ndarray,
    ) -> tuple[VGroup, bool, float]:
        cx, cy = box["center_x"], box["center_y"]
        max_w = box["content_width"] - 0.3
        theme = theme_config()
        state_motion = theme["state_curve_motion"]
        focus = theme["focus_rules"]
        pulse_cfg = theme["formula_pulse"]
        concept_cfg = theme["concept_visuals"]
        children: list[Any] = []
        animated = False
        scale_ref = [1.0]

        def scaled_redraw(func: Callable[[], Any]) -> Any:
            return always_redraw(lambda: _scale_about(func(), scale_ref[0], centre))

        def short_line(text: str, color: str, size: int = 26, y: float = cy - 2.4,
                       use_cjk: bool = False) -> Text:
            chosen_font = cjk_font if use_cjk else font
            return _fit(
                Text(text, font=chosen_font, font_size=size, color=color), max_w
            ).move_to([cx, y, 0])

        if stage_key in {"seed_failure", "seed_success"}:
            succeeds = stage_key == "seed_success"
            side_x = cx + 1.45 if succeeds else cx - 1.45
            color = favorable if succeeds else resistance

            def hook_seed() -> VGroup:
                p = tracker.get_value()
                dots: list[Dot] = []
                for index, (dx, dy) in enumerate(
                    [(-0.32, 0.22), (0.0, 0.38), (0.3, 0.18), (-0.22, -0.18),
                     (0.18, -0.12), (0.3, -0.38), (-0.04, -0.4)]
                ):
                    appear = min(1.0, max(0.0, p * 2.2 - index * 0.05))
                    scale = 0.7 + 0.7 * p if succeeds else 0.7
                    fade = max(0.0, 1 - max(0.0, p - 0.55) / 0.45) if not succeeds else 1.0
                    radius = 0.07 * appear * fade
                    if radius <= 0.001:
                        continue
                    dots.append(
                        Dot([side_x + dx * scale, cy + dy * scale, 0], radius=radius, color=color)
                    )
                return VGroup(*dots)

            children = [
                scaled_redraw(hook_seed),
                Circle(radius=0.72, color=neutral, stroke_width=1, stroke_opacity=0.35).move_to(
                    [side_x, cy, 0]
                ),
                short_line("grows" if succeeds else "fades", color, 22, cy - 1.15),
            ]
            animated = True

        elif stage_key in {"particle_embryo", "crystal_growth", "takeaway"}:
            def particles() -> VGroup:
                p = tracker.get_value()
                scale = 0.6 + 0.7 * p if stage_key != "particle_embryo" else 0.5 + 0.5 * p
                dots = []
                for dx, dy in (
                    (-0.45, 0.3), (0.0, 0.5), (0.45, 0.25),
                    (-0.4, -0.25), (0.15, -0.1), (0.55, -0.4), (0.0, -0.55),
                ):
                    dots.append(
                        Dot([cx + dx * scale, cy + dy * scale, 0], radius=0.075, color=neutral)
                    )
                return VGroup(*dots)

            children = [
                scaled_redraw(particles),
                Circle(radius=0.95, color=critical, stroke_width=2).move_to([cx, cy, 0]),
                short_line("Critical nucleus", critical),
            ]
            animated = True

        elif stage_key in {"energy_competition", "competition", "surface_cost", "bulk_gain"}:
            def surface_bar() -> Rectangle:
                p = tracker.get_value()
                length = 0.3 + 2.0 * p
                return Rectangle(
                    width=length, height=0.24, color=resistance, fill_opacity=0.55,
                    stroke_width=1,
                ).move_to([cx - length / 2, cy + 0.5, 0])

            def bulk_bar() -> Rectangle:
                p = tracker.get_value()
                length = 0.3 + 2.3 * p**1.5
                return Rectangle(
                    width=length, height=0.24, color=favorable, fill_opacity=0.55,
                    stroke_width=1,
                ).move_to([cx - length / 2, cy - 0.5, 0])

            children = [
                scaled_redraw(surface_bar),
                scaled_redraw(bulk_bar),
                short_line("Surface cost (+)", resistance, 24, cy + 1.1),
                short_line("Bulk gain (-)", favorable, 24, cy - 1.1),
            ]
            animated = True

        elif stage_key in {"area_scaling", "volume_scaling"}:
            is_volume = stage_key == "volume_scaling"
            dimension_key = "3D" if is_volume else "2D"
            geometry = theme["dimension_visual_mapping"][dimension_key]["geometry"]

            def iso_cube(size: float, center_x: float, center_y: float) -> VGroup:
                s = size
                depth = 0.35 * s
                front = Polygon(
                    [center_x, center_y - s / 2, 0],
                    [center_x + s / 2, center_y, 0],
                    [center_x, center_y + s / 2, 0],
                    [center_x - s / 2, center_y, 0],
                    color=favorable, stroke_width=2, fill_opacity=0.25,
                )
                top = Polygon(
                    [center_x - s / 2, center_y, 0],
                    [center_x, center_y + s / 2, 0],
                    [center_x, center_y + s / 2 + depth, 0],
                    [center_x - s / 2, center_y + depth, 0],
                    color=favorable, stroke_width=2, fill_opacity=0.12,
                )
                side = Polygon(
                    [center_x + s / 2, center_y, 0],
                    [center_x + s / 2, center_y + depth, 0],
                    [center_x, center_y + s / 2 + depth, 0],
                    [center_x, center_y + s / 2, 0],
                    color=favorable, stroke_width=2, fill_opacity=0.18,
                )
                return VGroup(front, top, side)

            def dim_shape() -> VGroup:
                p = tracker.get_value()
                if is_volume:
                    return iso_cube(0.7 + 1.1 * p, cx + 1.0, cy + 0.1)
                return VGroup(
                    Circle(
                        radius=0.45 + 0.8 * p, color=resistance,
                        stroke_width=4, stroke_opacity=1.0,
                    ).move_to([cx - 0.9, cy + 0.1, 0])
                )

            children = [
                scaled_redraw(dim_shape),
                short_line(
                    "r² area" if not is_volume else "r³ volume",
                    resistance if not is_volume else favorable,
                ),
            ]
            animated = True

        elif stage_key in GRAPH_STAGES:
            axes = Axes(
                x_range=[0, 2.05, 0.5],
                y_range=[-4.0, 1.2, 1.0],
                x_length=4.8,
                y_length=3.6,
                tips=False,
                axis_config={"color": neutral, "stroke_width": 2},
            ).move_to([cx, cy - 0.4, 0])
            curve = axes.plot(
                lambda x: 3 * x**2 - 2 * x**3, x_range=[0, 2.0],
                color=favorable, stroke_width=5,
            )
            label = _fit(
                Text("Total free energy  ΔG(r)", font=font, font_size=24, color=favorable),
                max_w,
            ).move_to([cx, cy + 2.4, 0])
            x_label = MathTex(r"r/r^*", font_size=28, color=neutral).move_to([cx, cy - 2.6, 0])
            context_opacity = (
                focus["active_opacity"]
                if stage_key == "free_energy_landscape"
                else focus["inactive_opacity"]
            )
            axes.set_opacity(context_opacity)
            label.set_opacity(context_opacity)
            x_label.set_opacity(context_opacity)
            # Keep the main curve an open stroke; set_opacity() would also turn on
            # fill and draw a misleading cyan area under the free-energy landscape.
            curve.set_fill(opacity=0)
            curve.set_stroke(opacity=focus["primary_curve_opacity_during_motion"])
            children.extend([axes, curve, label, x_label])

            if spec.get("visual_strategy") == "barrier_peak_anatomy":
                # Explicitly separate the peak's horizontal position (r*) from
                # its vertical height (delta G*) - the central point of this
                # editorial angle, and absent from the growth-perspective video.
                vertical = DashedLine(
                    axes.c2p(1.0, -4.0), axes.c2p(1.0, 1.0),
                    color=critical, stroke_width=3, dash_length=0.09,
                )
                horizontal = DashedLine(
                    axes.c2p(0, 1.0), axes.c2p(1.3, 1.0),
                    color=resistance, stroke_width=3, dash_length=0.09,
                )
                x_mark = MathTex(r"r^*", font_size=30, color=critical).move_to(
                    axes.c2p(1.0, -3.5)
                )
                y_mark = MathTex(r"\Delta G^*", font_size=28, color=resistance).move_to(
                    axes.c2p(0.32, 1.0)
                )
                children.extend([vertical, horizontal, x_mark, y_mark])

            if stage_key == "critical_threshold":
                marker = Dot(color=critical, radius=0.09).move_to(axes.c2p(1.0, 1.0))
                line = DashedLine(
                    axes.c2p(1.0, -4.0), axes.c2p(1.0, 1.0),
                    dash_length=0.09, color=critical, stroke_width=3,
                )
                children.extend([line, marker, short_line("r*", critical, 28, cy - 2.9)])
            elif stage_key == "free_energy_landscape":
                # Narration says free energy "rises at first": start at the curve
                # origin (0,0), climb along the plotted curve to r* = 1, then hold.
                # Never travel down the right-hand branch during this beat.
                reach_fraction = 0.8

                def rising_marker() -> VGroup:
                    p = tracker.get_value()
                    x = min(1.0, p / reach_fraction)
                    y = 3 * x**2 - 2 * x**3
                    return VGroup(Dot(axes.c2p(x, y), color=critical, radius=0.09))

                children.append(scaled_redraw(rising_marker))
            else:
                subcritical = stage_key == "subcritical_return"
                path = state_motion["subcritical" if subcritical else "supercritical"]

                def moving_marker() -> VGroup:
                    p = tracker.get_value()
                    if subcritical:
                        approach_end = 0.5
                        if p <= approach_end:
                            q = p / approach_end
                            x = path["start_x"] + (path["approach_x"] - path["start_x"]) * q
                            scale = 1.0
                            opacity = 1.0
                        else:
                            q = (p - approach_end) / (1 - approach_end)
                            x = path["approach_x"] + (path["return_x"] - path["approach_x"]) * q
                            scale = 1.0 + (path["marker_scale_end"] - 1.0) * q
                            opacity = 1.0 + (path["marker_fade_end"] - 1.0) * q
                    else:
                        q = p**2
                        x = path["start_x"] + (path["end_x"] - path["start_x"]) * q
                        scale = path["marker_scale_end"]
                        opacity = path["marker_fade_end"]
                    y = 3 * x**2 - 2 * x**3
                    return VGroup(
                        Dot(axes.c2p(x, y), color=critical, radius=0.09)
                        .scale(scale)
                        .set_opacity(opacity)
                    )

                children.append(scaled_redraw(moving_marker))
            animated = True

        elif stage_key == "barrier_relation":
            roles = theme["formula_symbol_roles"]
            equation = MathTex(
                r"\Delta G^* = \frac{16\pi\gamma^3}{3\Delta g_v^2}",
                font_size=40,
                substrings_to_isolate=[r"\Delta G^*", r"\gamma^3", r"\Delta g_v^2"],
            )
            token_roles = (
                (r"\gamma^3", "gamma"),
                (r"\Delta g_v^2", "delta_g_v"),
                (r"\Delta G^*", "barrier"),
            )
            for token, role_key in token_roles:
                try:
                    equation.get_part_by_tex(token).set_color(theme_color(roles[role_key]))
                except (ValueError, KeyError):
                    pass
            equation = _fit(equation, max_w).move_to([cx, cy + 0.2, 0])

            pulse_token = {
                "gamma": r"\gamma^3",
                "driving_force": r"\Delta g_v^2",
                "barrier": r"\Delta G^*",
            }.get(str(pulse_term))

            def pulsing_equation() -> Any:
                p = tracker.get_value()
                scale = 1.0 + (float(pulse_cfg["scale_peak"]) - 1.0) * math.sin(math.pi * p)
                result = equation.copy()
                for token, _ in token_roles:
                    try:
                        part = result.get_part_by_tex(token)
                    except ValueError:
                        continue
                    if token == pulse_token:
                        part.set_opacity(float(pulse_cfg["restore_opacity"]))
                        part.scale(scale, about_point=part.get_center())
                    elif pulse_token is not None:
                        part.set_opacity(float(pulse_cfg["dim_opacity"]))
                return result

            children = [
                scaled_redraw(pulsing_equation),
                short_line("Free-energy barrier", critical),
            ]
            animated = pulse_token is not None

        elif stage_key == "model_scope":
            # Spherical nucleus: wireframe, depth cue and labelled radius arrow.
            def nucleus() -> VGroup:
                p = tracker.get_value()
                radius = 0.7 + 0.25 * p
                outer = Circle(radius=radius, color=favorable, stroke_width=3).move_to(
                    [cx, cy, 0]
                )
                equator = Ellipse(
                    width=2 * radius, height=0.45 * radius, color=favorable,
                    stroke_width=1, stroke_opacity=0.55,
                ).move_to([cx, cy, 0])
                meridian = Ellipse(
                    width=0.45 * radius, height=2 * radius, color=favorable,
                    stroke_width=1, stroke_opacity=0.4,
                ).move_to([cx, cy, 0])
                arrow = Arrow(
                    [cx, cy, 0], [cx + radius, cy, 0],
                    color=critical, stroke_width=2, buff=0,
                )
                r_label = MathTex("r", font_size=26, color=critical).next_to(
                    arrow.get_end(), RIGHT, buff=0.1
                )
                return VGroup(outer, equator, meridian, arrow, r_label)

            children = [
                scaled_redraw(nucleus),
                short_line("Spherical nucleus", neutral, 26, cy + 1.7),
                short_line(concept_cfg["sphere_label_zh"], favorable, 26, cy - 1.7, use_cjk=True),
            ]
            animated = True

        elif stage_key == "thermo_caveat":
            # Affirmed-vs-excluded hierarchy: the established Direction conclusion
            # is primary and upper; the excluded Speed claim is secondary, lower
            # right, and its clock carries a drawn, unmistakable strike-through.
            mini_axes = Axes(
                x_range=[0, 2.0, 0.5], y_range=[-0.2, 1.2, 0.5],
                x_length=3.0, y_length=1.5, tips=False,
                axis_config={"color": neutral, "stroke_width": 1},
            ).move_to([cx, cy + 0.25, 0])
            mini_curve = mini_axes.plot(
                lambda x: 3 * x**2 - 2 * x**3, x_range=[0, 1.5],
                color=favorable, stroke_width=3,
            )

            def direction_arrow() -> VGroup:
                p = tracker.get_value()
                end_x = 1.12 + 0.32 * p
                arrow = Arrow(
                    mini_axes.c2p(1.1, 3 * 1.1**2 - 2 * 1.1**3),
                    mini_axes.c2p(end_x, 3 * end_x**2 - 2 * end_x**3),
                    color=favorable, stroke_width=4, buff=0,
                )
                return VGroup(arrow)

            check = VGroup(
                Line([0, 0, 0], [0.18, -0.18, 0], color=favorable, stroke_width=5),
                Line([0.18, -0.18, 0], [0.5, 0.28, 0], color=favorable, stroke_width=5),
            ).move_to([cx - 1.7, cy + 1.55, 0])

            def crossed_clock() -> VGroup:
                p = tracker.get_value()
                centre_clock = np.array([cx + 1.5, cy - 1.15, 0.0])
                clock = Circle(radius=0.36, color=resistance, stroke_width=3).move_to(centre_clock)
                hands = VGroup(
                    Line(centre_clock, centre_clock + np.array([0, 0.22, 0]), color=resistance, stroke_width=2),
                    Line(centre_clock, centre_clock + np.array([0.17, 0.04, 0]), color=resistance, stroke_width=2),
                )
                # Diagonal slash is drawn across the clock face itself, not next to it.
                slash_progress = max(0.0, min(1.0, (p - 0.2) / 0.35))
                slash_start = centre_clock + np.array([-0.34, -0.34, 0.0])
                slash_end = slash_start + np.array(
                    [0.68 * slash_progress, 0.68 * slash_progress, 0.0]
                )
                slash = Line(slash_start, slash_end, color=resistance, stroke_width=6)
                return VGroup(clock, hands, slash)

            # A small cross precedes the excluded "Speed" label.
            speed_cross = VGroup(
                Line([-0.11, -0.11, 0], [0.11, 0.11, 0], color=resistance, stroke_width=4),
                Line([-0.11, 0.11, 0], [0.11, -0.11, 0], color=resistance, stroke_width=4),
            ).move_to([cx + 0.45, cy - 1.95, 0])

            children = [
                mini_axes,
                mini_curve,
                scaled_redraw(direction_arrow),
                check,
                short_line("Direction", favorable, 28, cy + 1.75),
                short_line(concept_cfg["direction_label_zh"], favorable, 24, cy + 1.4, use_cjk=True),
                scaled_redraw(crossed_clock),
                speed_cross,
                short_line("Speed", resistance, 20, cy - 1.95),
                short_line(concept_cfg["speed_label_zh"], resistance, 18, cy - 2.25, use_cjk=True),
            ]
            animated = True

        elif stage_key in {"model_assumption", "real_systems"}:
            lines = {
                "model_assumption": ["Homogeneous model", "球形近似"],
                "real_systems": ["Interfaces still matter", "界面仍重要"],
            }[stage_key]
            children = [
                short_line(lines[0], neutral, 26, cy + 0.4),
                short_line(lines[1], favorable, 24, cy - 0.4, use_cjk=True),
                Circle(radius=0.7, color=favorable, stroke_width=2).move_to([cx, cy, 0]),
            ]
            animated = True

        else:
            children = [short_line(stage_key.replace("_", " "), neutral)]
            animated = False

        base_group = VGroup(*children)
        tracker.set_value(1.0)
        for item in base_group.get_family():
            if getattr(item, "updaters", None):
                item.update()
        factor = _max_safe_factor(base_group, box, centre, target_scale)
        scale_ref[0] = factor
        tracker.set_value(0.0)
        for item in children:
            if not getattr(item, "updaters", None):
                _scale_about(item, factor, centre)
        return VGroup(*children), animated, factor
