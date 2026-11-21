from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Callable

from manim import (
    Axes,
    Circle,
    Create,
    DashedLine,
    Dot,
    FadeIn,
    FadeOut,
    MathTex,
    Polygon,
    Rectangle,
    Scene,
    Text,
    VGroup,
    DOWN,
    UP,
    ValueTracker,
    always_redraw,
    linear,
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


class CriticalNucleusScene(Scene):
    """Static portrait camera with continuous, physically meaningful motion."""

    def construct(self) -> None:
        spec_path = os.environ.get("WECHAT_VIDEO_SCENE_SPEC")
        if not spec_path:
            raise RuntimeError("WECHAT_VIDEO_SCENE_SPEC is not configured.")
        spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
        profile = spec["layout"]
        font = spec["font_family"]
        theme = theme_config()
        palette = theme["palette"]
        favorable = palette["driving_force"]
        resistance = palette["resistance"]
        critical = palette["critical"]
        neutral = palette["neutral"]
        grid = theme["portrait_grid"]
        focus = theme["focus_rules"]
        box = _bounds(profile)
        cx, cy = box["center_x"], box["center_y"]
        max_w = box["content_width"] - 0.3

        assert abs(float(self.camera.frame_width) - FRAME_WIDTH) < 0.01
        assert abs(float(self.camera.frame_height) - FRAME_HEIGHT) < 0.01

        badge_y = (
            FRAME_HEIGHT / 2
            - FRAME_HEIGHT
            * (grid["badge_top_percent"] + grid["badge_bottom_percent"])
            / 200
        )
        badge_font = spec.get("cjk_font_family", font)
        badge = (
            Text(theme["series_identity"]["badge_text"], font=badge_font, font_size=18,
                 color=neutral)
            .move_to([cx, badge_y, 0])
            .set_opacity(0.75)
        )
        self.add(badge)

        # Active 0–1000 ms binary contrast: a small seed fails, a larger one grows.
        hook_tracker = ValueTracker(0.0)
        left_x, right_x = cx - 1.45, cx + 1.45

        def side_particles(center_x: float, succeeds: bool) -> VGroup:
            p = hook_tracker.get_value()
            dots: list[Dot] = []
            for index, (dx, dy) in enumerate(
                [(-0.35, 0.25), (0.0, 0.4), (0.32, 0.2), (-0.25, -0.2),
                 (0.2, -0.15), (0.35, -0.4), (-0.05, -0.42)]
            ):
                appear = min(1.0, max(0.0, p * 2.0 - index * 0.06))
                if succeeds:
                    scale = 0.7 + 0.7 * p
                    radius = 0.07 * appear
                    color = favorable
                else:
                    scale = 0.7
                    shrink = 1.0 if p < 0.55 else max(0.0, 1 - (p - 0.55) / 0.45)
                    radius = 0.07 * appear * shrink
                    color = resistance
                if radius <= 0.001:
                    continue
                dots.append(
                    Dot([center_x + dx * scale, cy + dy * scale, 0], radius=radius, color=color)
                )
            return VGroup(*dots)

        left = always_redraw(lambda: side_particles(left_x, False))
        right = always_redraw(lambda: side_particles(right_x, True))
        reference = VGroup(
            Circle(radius=0.72, color=neutral, stroke_width=1, stroke_opacity=0.35).move_to(
                [left_x, cy, 0]
            ),
            Circle(radius=0.72, color=neutral, stroke_width=1, stroke_opacity=0.35).move_to(
                [right_x, cy, 0]
            ),
        )
        hook_hint = VGroup(
            Text("fades", font=font, font_size=22, color=resistance).move_to(
                [left_x, cy - 1.15, 0]
            ),
            Text("grows", font=font, font_size=22, color=favorable).move_to(
                [right_x, cy - 1.15, 0]
            ),
        )
        hook_group = VGroup(left, right, reference, hook_hint)
        _assert_safe_zone(hook_group, "binary_hook", box)
        self.play(FadeIn(hook_group), run_time=0.25)
        self.play(hook_tracker.animate.set_value(1.0), run_time=0.65, rate_func=linear)
        self.play(FadeOut(hook_group), run_time=0.10)

        graph: VGroup | None = None
        current: list[Any] = []
        current_stage: str | None = None
        cursor_ms = 1000

        for checkpoint in spec["cue_checkpoints"]:
            start_ms = int(checkpoint["start_ms"])
            end_ms = int(checkpoint["end_ms"])
            if start_ms < cursor_ms:
                raise ValueError(f"Cue overlap at {checkpoint['unit_id']}")
            if start_ms > cursor_ms:
                self.wait((start_ms - cursor_ms) / 1000.0)

            stage_key, _ = stage_for_unit(checkpoint)
            trans_ms = transition_ms(end_ms - start_ms)
            trans = trans_ms / 1000.0
            tracker = ValueTracker(0.0)

            # One transition play per cue keeps the scene locked to the global timeline.
            leaving_graph = (
                current_stage in GRAPH_STAGES and stage_key not in GRAPH_STAGES
            )
            outgoing: list[Any] = []
            if leaving_graph:
                outgoing = list(current) + ([graph] if graph is not None else [])
                graph = None
            elif stage_key in GRAPH_STAGES and graph is None:
                outgoing = list(current)
            else:
                outgoing = [item for item in current if item is not graph]

            create_graph = stage_key in GRAPH_STAGES and graph is None
            if create_graph:
                graph = self._build_graph(box, font, favorable, neutral)
                _assert_safe_zone(graph, "shared_graph", box)

            overlay, animated = self._build_overlay(
                stage_key, tracker, box, font, favorable, resistance, critical, neutral, graph
            )
            for item in overlay.submobjects:
                _assert_safe_zone(item, f"{stage_key}:{id(item) % 100}", box)
            if graph is not None:
                # Only helper context may dim; the primary curve stays fully opaque.
                context_opacity = (
                    focus["active_opacity"]
                    if stage_key == "free_energy_landscape"
                    else focus["inactive_opacity"]
                )
                for index in (0, 2, 3):  # axes, title, x-label
                    graph.submobjects[index].set_opacity(context_opacity)
                graph.submobjects[1].set_opacity(focus["primary_curve_opacity_during_motion"])

            transition_animations = [FadeOut(item) for item in outgoing]
            if create_graph and graph is not None:
                transition_animations.append(Create(graph))
            transition_animations.append(FadeIn(overlay))
            self.play(*transition_animations, run_time=trans)
            current = [overlay]
            current_stage = stage_key

            hold_ms = end_ms - start_ms - trans_ms
            if hold_ms > 0 and animated:
                self.play(
                    tracker.animate.set_value(1.0),
                    run_time=hold_ms / 1000.0,
                    rate_func=linear,
                )
            cursor_ms = start_ms + trans_ms + max(0, hold_ms)

        total_ms = int(spec["total_duration_ms"])
        if total_ms < cursor_ms:
            raise ValueError(f"Cue motion exceeds timeline: {cursor_ms} > {total_ms}")
        if total_ms > cursor_ms:
            self.wait((total_ms - cursor_ms) / 1000.0)

    def _build_graph(
        self, box: dict[str, float], font: str, favorable: str, neutral: str
    ) -> VGroup:
        cx, cy = box["center_x"], box["center_y"]
        axes = Axes(
            x_range=[0, 2.05, 0.5],
            y_range=[-4.0, 1.2, 1.0],
            x_length=6.0,
            y_length=3.0,
            tips=False,
            axis_config={"color": neutral, "stroke_width": 2},
        ).move_to([cx, cy - 0.2, 0])
        # Dimensionless x = r/r*, ΔG/ΔG* = 3x² − 2x³, maximum at x = 1.
        curve = axes.plot(
            lambda x: 3 * x**2 - 2 * x**3, x_range=[0, 2.0], color=favorable, stroke_width=5
        )
        label = _fit(
            Text("Total free energy  ΔG(r)", font=font, font_size=24, color=favorable),
            box["content_width"] - 0.3,
        ).move_to([cx, cy + 2.0, 0])
        x_label = MathTex(r"r/r^*", font_size=28, color=neutral).move_to([cx, cy - 2.05, 0])
        return VGroup(axes, curve, label, x_label)

    def _build_overlay(
        self,
        stage_key: str,
        tracker: ValueTracker,
        box: dict[str, float],
        font: str,
        favorable: str,
        resistance: str,
        critical: str,
        neutral: str,
        graph: VGroup | None,
    ) -> tuple[VGroup, bool]:
        cx, cy = box["center_x"], box["center_y"]
        max_w = box["content_width"] - 0.3
        theme = theme_config()
        state_motion = theme["state_curve_motion"]
        children: list[Any] = []
        animated = False

        def short_line(text: str, color: str, size: int = 26, y: float = cy - 2.4) -> Text:
            return _fit(Text(text, font=font, font_size=size, color=color), max_w).move_to(
                [cx, y, 0]
            )

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
                always_redraw(hook_seed),
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

            live = always_redraw(particles)
            ring = Circle(radius=0.95, color=critical, stroke_width=2).move_to([cx, cy, 0])
            children = [live, ring, short_line("Critical nucleus", critical)]
            animated = True

        elif stage_key in {"energy_competition", "competition", "surface_cost", "bulk_gain"}:
            def surface_bar() -> Rectangle:
                p = tracker.get_value()
                length = 0.5 + 4.2 * p
                return Rectangle(
                    width=length, height=0.28, color=resistance, fill_opacity=0.55,
                    stroke_width=1,
                ).move_to([cx - length / 2, cy + 0.5, 0])

            def bulk_bar() -> Rectangle:
                p = tracker.get_value()
                length = 0.5 + 4.8 * p**1.5
                return Rectangle(
                    width=length, height=0.28, color=favorable, fill_opacity=0.55,
                    stroke_width=1,
                ).move_to([cx - length / 2, cy - 0.5, 0])

            children = [
                always_redraw(surface_bar),
                always_redraw(bulk_bar),
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
                    return iso_cube(0.7 + 1.3 * p, cx + 1.0, cy + 0.1)
                return VGroup(
                    Circle(
                        radius=0.45 + 1.0 * p, color=resistance,
                        stroke_width=4, stroke_opacity=1.0,
                    ).move_to([cx - 1.0, cy + 0.1, 0])
                )

            children = [
                always_redraw(dim_shape),
                short_line(
                    "r² area" if not is_volume else "r³ volume",
                    resistance if not is_volume else favorable,
                ),
            ]
            animated = True

        elif stage_key in {
            "free_energy_landscape",
            "critical_threshold",
            "subcritical_return",
            "supercritical_descent",
        }:
            if graph is None:
                raise RuntimeError("Graph stage reached without a shared graph.")
            axes = graph[0]
            if stage_key == "critical_threshold":
                marker = Dot(color=critical, radius=0.09).move_to(axes.c2p(1.0, 1.0))
                line = DashedLine(
                    axes.c2p(1.0, -4.0), axes.c2p(1.0, 1.0),
                    dash_length=0.09, color=critical, stroke_width=3,
                )
                children = [line, marker, short_line("r*", critical, 28, cy - 1.6)]
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

                children = [always_redraw(moving_marker)]
            animated = True

        elif stage_key == "barrier_relation":
            roles = theme["formula_symbol_roles"]
            equation = MathTex(
                r"\Delta G^* = \frac{16\pi\gamma^3}{3\Delta g_v^2}",
                font_size=40,
                substrings_to_isolate=[r"\Delta G^*", r"\gamma^3", r"\Delta g_v^2"],
            )
            for token, role_key in (
                (r"\gamma^3", "gamma"),
                (r"\Delta g_v^2", "delta_g_v"),
                (r"\Delta G^*", "barrier"),
            ):
                try:
                    equation.get_part_by_tex(token).set_color(theme_color(roles[role_key]))
                except (ValueError, KeyError):
                    pass
            equation = _fit(equation, max_w).move_to([cx, cy + 0.2, 0])

            def pulsing_equation() -> Any:
                p = tracker.get_value()
                scale = 1.0 + 0.06 * math.sin(p * math.pi)
                return equation.copy().scale(scale)

            children = [always_redraw(pulsing_equation), short_line("Free-energy barrier", critical)]
            animated = True

        elif stage_key in {"model_scope", "thermo_caveat", "real_systems"}:
            lines = {
                "model_scope": ["Spherical nucleus", "Homogeneous model"],
                "thermo_caveat": ["Thermodynamic tendency", "not a speed prediction"],
                "real_systems": ["Interfaces and transport", "still matter"],
            }[stage_key]
            children = [
                short_line(lines[0], neutral, 28, cy + 0.4),
                short_line(lines[1], favorable, 26, cy - 0.4),
            ]
            animated = True

        else:
            children = [short_line(stage_key.replace("_", " "), neutral)]
            animated = False

        return VGroup(*children), animated
