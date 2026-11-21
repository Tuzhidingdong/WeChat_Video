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

from ..visual_stages import DIM_OPACITY, stage_for_unit, transition_ms


FRAME_WIDTH = 9.0
FRAME_HEIGHT = 16.0
GRAPH_STAGES = {"free_energy_landscape", "critical_threshold", "threshold_dynamics"}


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
        semantics = profile["manim"]["semantic"]
        favorable = semantics["favorable_color"]
        resistance = semantics["resistance_color"]
        critical = semantics["critical_color"]
        neutral = semantics["neutral_color"]
        box = _bounds(profile)
        cx, cy = box["center_x"], box["center_y"]
        max_w = box["content_width"] - 0.3

        assert abs(float(self.camera.frame_width) - FRAME_WIDTH) < 0.01
        assert abs(float(self.camera.frame_height) - FRAME_HEIGHT) < 0.01

        # Active 0–1000 ms hook: particles assemble, the tiny embryo dissolves.
        hook_tracker = ValueTracker(0.0)

        def seed_points() -> VGroup:
            progress = hook_tracker.get_value()
            dots: list[Dot] = []
            for index, (dx, dy) in enumerate(
                [(-0.5, 0.25), (0.0, 0.45), (0.45, 0.2), (-0.35, -0.3),
                 (0.25, -0.25), (0.6, -0.5), (-0.1, -0.55)]
            ):
                appear = min(1.0, max(0.0, progress * 1.6 - index * 0.08))
                tiny_shrink = 1.0 if progress < 0.65 else max(0.25, 1 - (progress - 0.65) * 2.0)
                radius = 0.075 * appear * tiny_shrink
                if radius <= 0.001:
                    continue
                dots.append(
                    Dot([cx + dx * (0.6 + 0.4 * progress), cy + dy, 0], radius=radius, color=neutral)
                )
            return VGroup(*dots)

        seed = always_redraw(seed_points)
        hook_ring = always_redraw(
            lambda: Circle(
                radius=max(0.05, 0.95 * (0.35 + 0.65 * hook_tracker.get_value())),
                color=critical, stroke_width=2,
            ).move_to([cx, cy, 0])
        )
        hook_hint = _fit(
            Text("Stability depends on size", font=font, font_size=24, color=neutral), max_w
        ).move_to([cx, cy - 1.45, 0])
        hook_group = VGroup(seed, hook_ring, hook_hint)
        _assert_safe_zone(hook_group, "hook", box)
        self.play(FadeIn(hook_group), run_time=0.35)
        self.play(hook_tracker.animate.set_value(1.0), run_time=0.65, rate_func=linear)
        self.play(FadeOut(hook_group), run_time=0.15)

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
                graph.set_opacity(1.0 if stage_key == "free_energy_landscape" else DIM_OPACITY)

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
        children: list[Any] = []
        animated = False

        def short_line(text: str, color: str, size: int = 26, y: float = cy - 2.4) -> Text:
            return _fit(Text(text, font=font, font_size=size, color=color), max_w).move_to(
                [cx, y, 0]
            )

        if stage_key in {"particle_embryo", "crystal_growth", "takeaway"}:
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
            def growth_shape() -> VGroup:
                p = tracker.get_value()
                side = 0.6 + 1.6 * p if stage_key == "volume_scaling" else 0.6 + 1.3 * p
                return VGroup(
                    Rectangle(width=side, height=side,
                              color=favorable if stage_key == "volume_scaling" else resistance,
                              stroke_width=3)
                    .move_to([cx + (0.9 if stage_key == "volume_scaling" else -0.9), cy + 0.3, 0])
                )

            children = [
                always_redraw(growth_shape),
                short_line("r² area" if stage_key == "area_scaling" else "r³ volume",
                           resistance if stage_key == "area_scaling" else favorable),
            ]
            animated = True

        elif stage_key in {"free_energy_landscape", "critical_threshold", "threshold_dynamics"}:
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
                def moving_marker() -> Dot:
                    p = tracker.get_value()
                    if stage_key == "threshold_dynamics":
                        x = 0.7 + 0.8 * p
                    else:
                        x = 0.2 + 1.3 * p
                    y = 3 * x**2 - 2 * x**3
                    return Dot(axes.c2p(x, y), color=critical, radius=0.09)

                children = [always_redraw(moving_marker)]
            animated = True

        elif stage_key == "barrier_relation":
            equation = _fit(
                MathTex(r"\Delta G^* = \frac{16\pi\gamma^3}{3\Delta g_v^2}",
                        font_size=40, color=critical),
                max_w,
            ).move_to([cx, cy + 0.2, 0])

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
