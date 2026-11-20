from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from manim import Axes, Create, DashedLine, Dot, FadeIn, MathTex, Scene, Text, VGroup, DOWN


def _fit(text: Text, max_width: float) -> Text:
    if text.width > max_width:
        text.scale_to_fit_width(max_width)
    return text


def _assert_safe_zone(mobject, label: str, profile: dict[str, Any]) -> None:
    frame_width, frame_height = 9.0, 16.0
    zones = profile["safe_zones"]
    left = -frame_width / 2 + frame_width * zones["left_margin_percent"] / 100
    right = frame_width / 2 - frame_width * zones["right_reserved_percent"] / 100
    top = frame_height / 2 - frame_height * zones["top_reserved_percent"] / 100
    bottom = frame_height / 2 - frame_height * zones["science_content_bottom_percent"] / 100
    box = mobject.get_bounding_box()
    x_min, y_min = float(box[0][0]), float(box[0][1])
    x_max, y_max = float(box[2][0]), float(box[2][1])
    tol = 0.025
    if x_min < left - tol or x_max > right + tol or y_min < bottom - tol or y_max > top + tol:
        raise ValueError(
            f"Safe-zone overflow: {label}; object=({x_min:.2f},{y_min:.2f})–"
            f"({x_max:.2f},{y_max:.2f}), safe=({left:.2f},{bottom:.2f})–({right:.2f},{top:.2f})"
        )


class CriticalNucleusScene(Scene):
    """One static-camera portrait scene driven by measured speech cue checkpoints."""

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

        # Explicit global 0–1000 ms cover. Narration starts after this segment.
        cover_title = Text("临界晶核", font=font, font_size=62, color=foreground)
        cover_subtitle = Text("自由能垒如何决定成核？", font=font, font_size=34, color=accent)
        cover = VGroup(cover_title, cover_subtitle).arrange(DOWN, buff=0.42)
        cover.move_to([-0.45, 1.25, 0])
        _assert_safe_zone(cover, "scene_00_cover", profile)
        self.play(FadeIn(cover), run_time=1.0)
        self.remove(cover)

        heading = _fit(
            Text("两种能量的竞争", font=font, font_size=38, color=foreground), 7.0
        ).move_to([-0.45, 5.55, 0])
        surface_formula = MathTex(
            r"\Delta G_{\mathrm{surface}}=4\pi r^2\gamma",
            font_size=42, color=secondary
        ).move_to([-0.45, 4.25, 0])
        volume_formula = MathTex(
            r"\Delta G_{\mathrm{bulk}}=-\frac{4}{3}\pi r^3\Delta g_v",
            font_size=42, color=accent
        ).move_to([-0.45, 3.35, 0])
        for mob in (surface_formula, volume_formula):
            if mob.width > 7.0:
                mob.scale_to_fit_width(7.0)

        surface_note = Text("界面代价 ∝ r²", font=font, font_size=29, color=secondary)
        surface_note.move_to([-1.95, 2.35, 0])
        bulk_note = Text("体相收益 ∝ −r³", font=font, font_size=29, color=accent)
        bulk_note.move_to([1.15, 2.35, 0])

        axes = Axes(
            x_range=[0, 2.05, 0.5],
            y_range=[-4.0, 1.2, 1.0],
            x_length=6.3,
            y_length=3.15,
            tips=False,
            axis_config={"color": foreground, "stroke_width": 2},
        ).move_to([-0.45, -0.25, 0])
        curve = axes.plot(
            lambda x: 3 * x**2 - 2 * x**3,
            x_range=[0, 2.0],
            color=accent,
            stroke_width=5,
        )
        curve_label = Text("总自由能 ΔG(r)", font=font, font_size=25, color=accent)
        curve_label.move_to([-0.55, 1.35, 0])
        x_label = MathTex(r"r/r^*", font_size=34, color=foreground)
        x_label.move_to([-0.45, -2.28, 0])

        critical_point = axes.c2p(1.0, 1.0)
        critical_line = DashedLine(
            axes.c2p(1.0, -4.0), axes.c2p(1.0, 1.0),
            dash_length=0.09, color=secondary, stroke_width=3
        )
        critical_dot = Dot(critical_point, radius=0.075, color=secondary)
        critical_label = MathTex(
            r"r^*=\frac{2\gamma}{\Delta g_v}", font_size=34, color=secondary
        ).move_to([-0.2, 1.9, 0])
        if critical_label.width > 6.8:
            critical_label.scale_to_fit_width(6.8)

        subcritical = Text("r < r*：倾向缩小", font=font, font_size=23, color=danger)
        subcritical.move_to([-2.05, -1.65, 0])
        supercritical = Text("r > r*：倾向长大", font=font, font_size=23, color=accent)
        supercritical.move_to([1.35, -1.65, 0])
        caveat = _fit(
            Text(
                "经典近似：球形 · 均匀成核 · 各向同性界面",
                font=font, font_size=21, color=foreground
            ), 7.0
        ).move_to([-0.45, -2.65, 0])

        objects = {
            "heading": heading,
            "surface_formula": surface_formula,
            "volume_formula": volume_formula,
            "surface_note": surface_note,
            "bulk_note": bulk_note,
            "axes": axes,
            "curve": curve,
            "curve_label": curve_label,
            "x_label": x_label,
            "critical_line": critical_line,
            "critical_dot": critical_dot,
            "critical_label": critical_label,
            "subcritical": subcritical,
            "supercritical": supercritical,
            "caveat": caveat,
        }
        for label, mob in objects.items():
            _assert_safe_zone(mob, label, profile)

        cursor_ms = 1000
        for checkpoint in spec["cue_checkpoints"]:
            start_ms = int(checkpoint["start_ms"])
            if start_ms < cursor_ms:
                raise ValueError(f"Cue checkpoint overlaps: {checkpoint['unit_id']}")
            if start_ms > cursor_ms:
                self.wait((start_ms - cursor_ms) / 1000.0)
            duration = min(0.62, max(0.28, int(checkpoint["duration_ms"]) / 6000))
            action_count = 0
            for trigger in checkpoint["visual_trigger_ids"]:
                action_count += 1
                if trigger == "INTRO_QUESTION":
                    self.play(FadeIn(heading), run_time=duration)
                elif trigger == "SHOW_TWO_TERMS":
                    self.play(FadeIn(surface_formula), FadeIn(volume_formula), run_time=duration)
                elif trigger == "SHOW_SCALING":
                    self.play(FadeIn(surface_note), FadeIn(bulk_note), run_time=duration)
                elif trigger == "SHOW_FREE_ENERGY_CURVE":
                    self.play(
                        Create(axes), Create(curve), FadeIn(curve_label), FadeIn(x_label),
                        run_time=duration
                    )
                elif trigger == "MARK_CRITICAL_RADIUS":
                    self.play(
                        Create(critical_line), FadeIn(critical_dot), FadeIn(critical_label),
                        run_time=duration
                    )
                elif trigger == "COMPARE_SUB_SUPERCRITICAL":
                    self.play(FadeIn(subcritical), FadeIn(supercritical), run_time=duration)
                elif trigger == "MODEL_LIMITS":
                    self.play(FadeIn(caveat), run_time=duration)
                else:
                    raise ValueError(f"Unregistered visual trigger: {trigger}")
            cursor_ms = start_ms + int(duration * 1000) * action_count

        total_ms = int(spec["total_duration_ms"])
        if total_ms < cursor_ms:
            raise ValueError(
                f"Scene cue actions exceed timeline: cursor={cursor_ms}, total={total_ms}."
            )
        if total_ms > cursor_ms:
            self.wait((total_ms - cursor_ms) / 1000.0)
