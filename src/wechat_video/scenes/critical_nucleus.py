from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from manim import (
    Axes,
    Circle,
    DashedLine,
    Dot,
    FadeIn,
    FadeOut,
    MathTex,
    Scene,
    Square,
    Text,
    VGroup,
    DOWN,
)

from ..visual_stages import stage_for_unit, transition_ms


FRAME_WIDTH = 9.0
FRAME_HEIGHT = 16.0


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
    # Manim 0.22 removed get_bounding_box(); use boundary-defining anchors.
    boundary = mobject.get_points_defining_boundary()
    x_min = min(float(point[0]) for point in boundary)
    y_min = min(float(point[1]) for point in boundary)
    x_max = max(float(point[0]) for point in boundary)
    y_max = max(float(point[1]) for point in boundary)
    tol = 0.02
    if (
        x_min < box["left"] - tol
        or x_max > box["right"] + tol
        or y_min < box["bottom"] - tol
        or y_max > box["top"] + tol
    ):
        raise ValueError(
            f"Safe-zone overflow: {label}; "
            f"object=({x_min:.2f},{y_min:.2f})..({x_max:.2f},{y_max:.2f}), "
            f"safe=({box['left']:.2f},{box['bottom']:.2f})..({box['right']:.2f},{box['top']:.2f})"
        )


class CriticalNucleusScene(Scene):
    """Static portrait scene driven by measured global cue checkpoints."""

    def construct(self) -> None:
        spec_path = os.environ.get("WECHAT_VIDEO_SCENE_SPEC")
        if not spec_path:
            raise RuntimeError("WECHAT_VIDEO_SCENE_SPEC is not configured.")
        spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
        profile = spec["layout"]
        font = spec["font_family"]
        colors = profile["manim"]
        foreground = colors["foreground_color"]
        accent = colors["accent_color"]
        secondary = colors["secondary_color"]
        danger = colors["danger_color"]
        box = _bounds(profile)
        cx, cy = box["center_x"], box["center_y"]
        max_w = box["content_width"] - 0.3

        # Explicit global 0-1000 ms cover (no narration).
        cover_title = _fit(
            Text("Critical Nucleus", font=font, font_size=58, color=foreground), max_w
        )
        cover_subtitle = _fit(
            Text("Free Energy and the Critical Radius", font=font, font_size=32, color=accent),
            max_w,
        )
        cover = VGroup(cover_title, cover_subtitle).arrange(DOWN, buff=0.35)
        cover.move_to([cx, cy, 0])
        _assert_safe_zone(cover, "scene_00_cover", box)
        self.play(FadeIn(cover), run_time=1.0)
        self.remove(cover)

        # Stage 1: small particle embryo (illustration, not an atomistic claim).
        dots = VGroup(
            *[
                Dot([cx + dx, cy + dy, 0], radius=0.075, color=foreground)
                for dx, dy in (
                    (-0.55, 0.35), (0.0, 0.55), (0.55, 0.3),
                    (-0.5, -0.2), (0.1, -0.05), (0.6, -0.25), (0.0, -0.6),
                )
            ]
        )
        embryo_ring = Circle(radius=0.95, color=secondary, stroke_width=2)
        embryo_ring.move_to([cx, cy, 0])
        embryo_label = _fit(
            Text("A tiny embryo can dissolve", font=font, font_size=28, color=foreground),
            max_w,
        ).move_to([cx, cy - 1.5, 0])
        particle_stage = [dots, embryo_ring, embryo_label]

        # Stage 2: one total free-energy equation with distinguished terms.
        total_equation = MathTex(
            r"\Delta G(r) = ",
            r"4\pi r^2\gamma",
            r"\;-\;",
            r"\frac{4}{3}\pi r^3 \Delta g_v",
            substrings_to_isolate=[r"4\pi r^2\gamma", r"\frac{4}{3}\pi r^3 \Delta g_v"],
            font_size=40,
        )
        total_equation[1].set_color(secondary)
        total_equation[3].set_color(accent)
        _fit(total_equation, max_w).move_to([cx, cy + 0.2, 0])
        energy_label = _fit(
            Text("surface cost (+)   vs   bulk gain (-)", font=font, font_size=27,
                 color=foreground),
            max_w,
        ).move_to([cx, cy - 1.3, 0])
        energy_stage = [total_equation, energy_label]

        # Stage 3: area versus volume scaling.
        area_square = Square(side_length=0.85, color=secondary, stroke_width=3)
        area_square.move_to([cx - 1.55, cy + 0.3, 0])
        volume_square = Square(side_length=1.25, color=accent, stroke_width=3)
        volume_square.move_to([cx + 1.55, cy + 0.2, 0])
        area_text = _fit(
            Text("Area grows as r²", font=font, font_size=28, color=secondary), max_w / 2
        ).move_to([cx - 1.55, cy - 0.9, 0])
        volume_text = _fit(
            Text("Volume grows as r³", font=font, font_size=28, color=accent), max_w / 2
        ).move_to([cx + 1.55, cy - 0.9, 0])
        scaling_stage = [area_square, volume_square, area_text, volume_text]

        # Shared graph: created once and retained by both graph-based stages.
        axes = Axes(
            x_range=[0, 2.05, 0.5],
            y_range=[-4.0, 1.2, 1.0],
            x_length=6.0,
            y_length=3.0,
            tips=False,
            axis_config={"color": foreground, "stroke_width": 2},
        )
        axes.move_to([cx, cy - 0.3, 0])
        curve = axes.plot(
            lambda x: 3 * x**2 - 2 * x**3, x_range=[0, 2.0], color=accent, stroke_width=5
        )
        graph_label = _fit(
            Text("Total free energy  ΔG(r)", font=font, font_size=26, color=accent), max_w
        ).move_to([cx, cy + 2.0, 0])
        x_label = MathTex(r"r/r^*", font_size=30, color=foreground).move_to(
            [cx, cy - 2.1, 0]
        )
        graph_core = [axes, curve, graph_label, x_label]

        landscape_hint = _fit(
            Text("One maximum separates two regimes", font=font, font_size=24,
                 color=foreground),
            max_w,
        ).move_to([cx, cy - 2.65, 0])
        landscape_stage = graph_core + [landscape_hint]

        # Stage 5 reuses the same graph; only the threshold overlay changes.
        critical_line = DashedLine(
            axes.c2p(1.0, -4.0), axes.c2p(1.0, 1.0),
            dash_length=0.09, color=secondary, stroke_width=3,
        )
        critical_dot = Dot(axes.c2p(1.0, 1.0), radius=0.075, color=secondary)
        r_star_mark = MathTex(r"r^*", font_size=30, color=secondary).move_to(
            [cx + 0.3, cy + 0.85, 0]
        )
        subcritical = _fit(
            Text("r < r*: shrink", font=font, font_size=25, color=danger), max_w / 2
        ).move_to([cx - 1.6, cy - 1.65, 0])
        supercritical = _fit(
            Text("r > r*: grow", font=font, font_size=25, color=accent), max_w / 2
        ).move_to([cx + 1.6, cy - 1.65, 0])
        threshold_overlay = [critical_line, critical_dot, r_star_mark,
                             subcritical, supercritical]
        threshold_stage = graph_core + threshold_overlay

        # Stages 6 and 7: one equation at a time.
        critical_eq = _fit(
            MathTex(r"r^* = \frac{2\gamma}{\Delta g_v}", font_size=44, color=secondary),
            max_w,
        ).move_to([cx, cy + 0.2, 0])
        critical_eq_label = _fit(
            Text("Critical radius", font=font, font_size=27, color=foreground), max_w
        ).move_to([cx, cy - 1.3, 0])
        critical_eq_stage = [critical_eq, critical_eq_label]

        barrier_eq = _fit(
            MathTex(
                r"\Delta G^* = \frac{16\pi\gamma^3}{3\Delta g_v^2}",
                font_size=42, color=accent,
            ),
            max_w,
        ).move_to([cx, cy + 0.2, 0])
        barrier_eq_label = _fit(
            Text("Nucleation barrier", font=font, font_size=27, color=foreground), max_w
        ).move_to([cx, cy - 1.3, 0])
        barrier_eq_stage = [barrier_eq, barrier_eq_label]

        # Stage 8: model caveats only.
        caveat_a = _fit(
            Text("Assumptions: spherical nucleus, homogeneous nucleation,", font=font,
                 font_size=25, color=foreground),
            max_w,
        ).move_to([cx, cy + 0.5, 0])
        caveat_b = _fit(
            Text("isotropic interface", font=font, font_size=25, color=foreground), max_w
        ).move_to([cx, cy - 0.1, 0])
        caveat_c = _fit(
            Text("Real systems: interface structure, anisotropy, transport, kinetics",
                 font=font, font_size=23, color=accent),
            max_w,
        ).move_to([cx, cy - 1.1, 0])
        limits_stage = [caveat_a, caveat_b, caveat_c]

        stage_visuals: dict[str, list[Any]] = {
            "particle_embryo": particle_stage,
            "energy_competition": energy_stage,
            "area_vs_volume": scaling_stage,
            "free_energy_landscape": landscape_stage,
            "critical_threshold": threshold_stage,
            "critical_radius_equation": critical_eq_stage,
            "barrier_equation": barrier_eq_stage,
            "model_assumptions": limits_stage,
        }
        for stage_id, visuals in stage_visuals.items():
            for index, mobject in enumerate(visuals):
                _assert_safe_zone(mobject, f"{stage_id}[{index}]", box)

        # The graph is intentionally shared only by the two consecutive graph stages.
        shared_graph_stages = {"free_energy_landscape", "critical_threshold"}

        cursor_ms = 1000
        current_visuals: list[Any] = []
        current_stage_id: str | None = None
        for checkpoint in spec["cue_checkpoints"]:
            start_ms = int(checkpoint["start_ms"])
            if start_ms < cursor_ms:
                raise ValueError(f"Cue checkpoint overlap: {checkpoint['unit_id']}")
            if start_ms > cursor_ms:
                self.wait((start_ms - cursor_ms) / 1000.0)
            stage_id, _ = stage_for_unit(checkpoint)
            next_visuals = stage_visuals[stage_id]
            trans_seconds = transition_ms(int(checkpoint["duration_ms"])) / 1000.0

            keep_graph = (
                current_stage_id in shared_graph_stages
                and stage_id in shared_graph_stages
            )
            retained = graph_core if keep_graph else []
            outgoing = [m for m in current_visuals if m not in retained]
            incoming = [m for m in next_visuals if m not in retained]
            animations = [FadeOut(m) for m in outgoing] + [FadeIn(m) for m in incoming]
            if animations:
                self.play(*animations, run_time=trans_seconds)
            current_visuals = list(next_visuals)
            current_stage_id = stage_id
            cursor_ms = start_ms + int(trans_seconds * 1000)

        total_ms = int(spec["total_duration_ms"])
        if total_ms < cursor_ms:
            raise ValueError(
                f"Scene cue actions exceed timeline: cursor={cursor_ms}, total={total_ms}."
            )
        if total_ms > cursor_ms:
            self.wait((total_ms - cursor_ms) / 1000.0)
