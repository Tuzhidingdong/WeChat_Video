"""Premium editorial scene system for one-minute Chinese article summaries."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from manim import (
    Arrow,
    Circle,
    Create,
    FadeIn,
    FadeOut,
    ImageMobject,
    LEFT,
    Line,
    ORIGIN,
    Rectangle,
    RoundedRectangle,
    Scene,
    Text,
    VGroup,
    WHITE,
    RIGHT,
    UP,
    DOWN,
)


PAPER = "#F5F2EA"
INK = "#172A3A"
MUTED = "#64717A"
ACCENT = "#D76B4E"
PALE = "#E7E0D4"
CARD = "#FFFEFA"
TEAL = "#2B7775"


def _fit_width(mobject: Any, width: float) -> Any:
    if mobject.width > width:
        mobject.scale_to_fit_width(width)
    return mobject


def _fit_box(mobject: Any, width: float, height: float) -> Any:
    factor = min(width / max(mobject.width, 1e-6), height / max(mobject.height, 1e-6))
    if factor < 1:
        mobject.scale(factor)
    return mobject


class ArticleSummaryScene(Scene):
    """Render evidence-backed beats against measured speech-unit timestamps."""

    def construct(self) -> None:
        spec_path = Path(os.environ["WECHAT_VIDEO_ARTICLE_SCENE_SPEC"])
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        font = str(spec["cjk_font_family"])
        article_title = str(spec["article_title"])
        total_ms = int(spec["total_duration_ms"])
        beats = spec["beats"]
        if len(beats) != len(spec["speech_units"]):
            raise RuntimeError("Article scene beats do not match measured speech units.")

        self.camera.background_color = PAPER
        brand = Text("成核生长  /  精读一分钟", font=font, font_size=30, color=INK)
        brand.to_edge(UP, buff=0.82).to_edge(LEFT, buff=0.62)
        rule = Line(LEFT * 4.0, RIGHT * 4.0, color=PALE, stroke_width=3).next_to(
            brand, DOWN, buff=0.25
        )
        title = _fit_box(Text(article_title, font=font, font_size=64, color=INK, line_spacing=0.9), 7.5, 5.0)
        title.move_to(ORIGIN + UP * 0.5)
        strap = Text("一篇文章 · 一个关键发现 · 一分钟读懂", font=font, font_size=28, color=MUTED)
        strap.next_to(title, DOWN, buff=0.55)
        accent = Line(LEFT * 0.8, RIGHT * 0.8, color=ACCENT, stroke_width=8)
        accent.next_to(strap, DOWN, buff=0.55)
        cover = VGroup(brand, rule, title, strap, accent)
        self.play(FadeIn(cover, shift=UP * 0.12), run_time=0.35)
        self.wait(0.65)
        cursor = 1000
        current = cover

        for index, beat in enumerate(beats, start=1):
            start_ms = int(beat["start_ms"])
            end_ms = int(beat["end_ms"])
            if start_ms < cursor or end_ms <= start_ms:
                raise RuntimeError(f"Invalid or overlapping article beat timing: {beat.get('beat_id')}")
            gap = (start_ms - cursor) / 1000
            if gap > 0:
                self.wait(gap)
            group = self._build_beat(beat, index, len(beats), font)
            duration = max(0.12, min(0.32, (end_ms - start_ms) / 1000 * 0.18))
            self.play(FadeOut(current), FadeIn(group, shift=UP * 0.08), run_time=duration)
            cursor = start_ms + round(duration * 1000)
            remaining = end_ms - cursor
            if remaining > 0:
                self.wait(remaining / 1000)
            cursor = end_ms
            current = group

        if total_ms > cursor:
            self.wait((total_ms - cursor) / 1000)
        self.play(FadeOut(current), run_time=0.18)

    def _build_beat(
        self, beat: dict[str, Any], index: int, count: int, font: str
    ) -> VGroup:
        kind = str(beat["kind"])
        headline = _fit_box(
            Text(str(beat["headline"]), font=font, font_size=58, color=INK, line_spacing=0.9),
            7.5,
            2.2,
        )
        headline.move_to(UP * 4.4)
        top = Text("精读一分钟", font=font, font_size=25, color=ACCENT)
        top.to_corner(UP + LEFT, buff=0.65)
        counter = Text(f"{index:02d} / {count:02d}", font=font, font_size=24, color=MUTED)
        counter.to_corner(UP + RIGHT, buff=0.65)
        separator = Line(LEFT * 3.8, RIGHT * 3.8, color=PALE, stroke_width=2).move_to(UP * 3.6)
        parts: list[Any] = [top, counter, separator, headline]

        body = str(beat.get("body") or "").strip()
        if kind == "image":
            images = beat.get("images") or []
            if not images:
                raise RuntimeError(f"Image beat {beat.get('beat_id')} has no resolved image files.")
            rendered: list[Any] = []
            if len(images) == 1:
                picture = ImageMobject(str(images[0]["path"]))
                _fit_box(picture, 7.25, 7.5)
                picture.move_to(DOWN * 0.1)
                frame = RoundedRectangle(
                    width=picture.width + 0.12,
                    height=picture.height + 0.12,
                    corner_radius=0.10,
                    stroke_color=PALE,
                    stroke_width=2,
                    fill_color=CARD,
                    fill_opacity=1,
                ).move_to(picture)
                rendered.extend([frame, picture])
            else:
                for slot, item in enumerate(images):
                    picture = ImageMobject(str(item["path"]))
                    _fit_box(picture, 3.5, 6.1)
                    picture.move_to(LEFT * 1.9 + RIGHT * (3.8 * slot) + DOWN * 0.15)
                    frame = Rectangle(
                        width=picture.width + 0.1,
                        height=picture.height + 0.1,
                        stroke_color=PALE,
                        stroke_width=2,
                        fill_color=CARD,
                        fill_opacity=1,
                    ).move_to(picture)
                    rendered.extend([frame, picture])
            parts.extend(rendered)
            caption = Text(
                str(beat.get("caption") or body or "原文配图"),
                font=font,
                font_size=27,
                color=MUTED,
            )
            _fit_width(caption, 7.2)
            caption.move_to(DOWN * 4.45)
            parts.append(caption)

        elif kind == "stat":
            value = _fit_box(
                Text(str(beat["stat_value"]), font=font, font_size=132, color=ACCENT),
                7.0,
                2.4,
            ).move_to(UP * 1.0)
            label = _fit_box(
                Text(str(beat.get("stat_label") or body), font=font, font_size=38, color=INK),
                7.1,
                2.2,
            ).next_to(value, DOWN, buff=0.55)
            parts.extend([value, label])

        elif kind == "compare":
            left_data = beat["left"]
            right_data = beat["right"]
            cards = []
            for x, data, tone in (
                (-1.95, left_data, TEAL),
                (1.95, right_data, ACCENT),
            ):
                panel = RoundedRectangle(
                    width=3.55,
                    height=5.6,
                    corner_radius=0.16,
                    stroke_color=PALE,
                    stroke_width=2,
                    fill_color=CARD,
                    fill_opacity=1,
                ).move_to(RIGHT * x + DOWN * 0.45)
                label = _fit_box(
                    Text(str(data.get("label") or data.get("title") or ""), font=font, font_size=36, color=tone),
                    3.0,
                    1.4,
                ).move_to(panel.get_center() + UP * 1.35)
                detail = _fit_box(
                    Text(str(data.get("detail") or data.get("body") or ""), font=font, font_size=29, color=INK),
                    2.95,
                    3.1,
                ).move_to(panel.get_center() + DOWN * 0.5)
                cards.extend([panel, label, detail])
            parts.extend(cards)

        elif kind == "mechanism":
            steps = beat["steps"]
            nodes = []
            spacing = 6.8 / max(1, len(steps) - 1)
            start_x = -spacing * (len(steps) - 1) / 2
            for node_index, step in enumerate(steps):
                x = start_x + spacing * node_index
                circle = Circle(radius=0.55, stroke_color=ACCENT if node_index == 0 else TEAL, stroke_width=5)
                circle.move_to(RIGHT * x + UP * 0.65)
                number = Text(str(node_index + 1), font=font, font_size=34, color=INK).move_to(circle)
                label = _fit_box(
                    Text(str(step), font=font, font_size=28, color=INK),
                    max(1.6, spacing - 0.15),
                    2.0,
                ).move_to(RIGHT * x + DOWN * 1.0)
                nodes.extend([circle, number, label])
                if node_index < len(steps) - 1:
                    line = Arrow(
                        RIGHT * (x + 0.62) + UP * 0.65,
                        RIGHT * (x + spacing - 0.62) + UP * 0.65,
                        buff=0,
                        color=MUTED,
                        stroke_width=3,
                        max_tip_length_to_length_ratio=0.18,
                    )
                    nodes.append(line)
            parts.extend(nodes)
            if body:
                detail = _fit_box(Text(body, font=font, font_size=30, color=MUTED), 7.1, 1.7)
                detail.move_to(DOWN * 3.35)
                parts.append(detail)

        elif kind == "quote":
            quote = str(beat.get("quote") or body)
            quote_group = Text(
                f"“{quote}”",
                font=font,
                font_size=46,
                color=INK,
                line_spacing=0.95,
            )
            _fit_box(quote_group, 7.1, 6.1)
            quote_group.move_to(DOWN * 0.35)
            parts.append(quote_group)

        else:
            detail = _fit_box(
                Text(body, font=font, font_size=40, color=INK, line_spacing=0.95),
                7.2,
                5.3,
            )
            detail.move_to(DOWN * 0.55)
            parts.append(detail)

        footer_text = str(beat.get("footer") or "成核生长 · 精读一分钟")
        footer = _fit_width(Text(footer_text, font=font, font_size=22, color=MUTED), 7.2)
        footer.to_edge(DOWN, buff=0.62)
        parts.append(footer)
        return VGroup(*parts)
