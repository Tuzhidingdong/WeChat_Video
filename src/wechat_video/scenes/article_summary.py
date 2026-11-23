"""Premium short-form editorial scene system for evidence-backed article summaries."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from manim import (
    Arrow,
    FadeIn,
    FadeOut,
    Group,
    ImageMobject,
    LEFT,
    Line,
    ORIGIN,
    Rectangle,
    RoundedRectangle,
    Scene,
    Text,
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


def _normalized_region(region: dict[str, Any]) -> tuple[float, float, float, float]:
    try:
        x = float(region["x"])
        y = float(region["y"])
        width = float(region["width"])
        height = float(region["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Image focus regions require numeric x, y, width and height.") from exc
    if (
        width <= 0 or height <= 0 or x < 0 or y < 0
        or x + width > 1 or y + height > 1
    ):
        raise RuntimeError(f"Image focus region is outside normalized image bounds: {region}")
    return x, y, width, height


def _image_objects(item: dict[str, Any]) -> list[Any]:
    """Show the whole source figure and, when specified, a true crop beside it."""
    path = Path(str(item["path"]))
    picture = ImageMobject(str(path))
    region = item.get("focus_region")
    if not region:
        _fit_box(picture, 7.0, 5.7)
        picture.move_to(UP * 0.05)
        frame = RoundedRectangle(
            width=picture.width + 0.14,
            height=picture.height + 0.14,
            corner_radius=0.10,
            stroke_color=PALE,
            stroke_width=2,
            fill_color=CARD,
            fill_opacity=1,
        ).move_to(picture)
        return [frame, picture]

    x, y, width, height = _normalized_region(region)
    with Image.open(path) as source:
        pixel_width, pixel_height = source.size
        left = max(0, min(pixel_width - 1, round(x * pixel_width)))
        top = max(0, min(pixel_height - 1, round(y * pixel_height)))
        right = max(left + 1, min(pixel_width, round((x + width) * pixel_width)))
        bottom = max(top + 1, min(pixel_height, round((y + height) * pixel_height)))
        crop = np.asarray(source.convert("RGB").crop((left, top, right, bottom)))

    _fit_box(picture, 4.15, 5.25)
    picture.move_to(LEFT * 1.55 + DOWN * 0.05)
    frame = RoundedRectangle(
        width=picture.width + 0.12,
        height=picture.height + 0.12,
        corner_radius=0.08,
        stroke_color=PALE,
        stroke_width=2,
        fill_color=CARD,
        fill_opacity=1,
    ).move_to(picture)

    focus_frame = Rectangle(
        width=picture.width * width,
        height=picture.height * height,
        stroke_color=ACCENT,
        stroke_width=5,
        fill_opacity=0,
    )
    focus_frame.move_to([
        picture.get_left()[0] + picture.width * (x + width / 2),
        picture.get_top()[1] - picture.height * (y + height / 2),
        0,
    ])

    zoom = ImageMobject(crop)
    _fit_box(zoom, 2.75, 4.0)
    zoom.move_to(RIGHT * 1.75 + DOWN * 0.05)
    zoom_frame = RoundedRectangle(
        width=zoom.width + 0.16,
        height=zoom.height + 0.16,
        corner_radius=0.08,
        stroke_color=ACCENT,
        stroke_width=3,
        fill_color=CARD,
        fill_opacity=1,
    ).move_to(zoom)
    zoom_label = Text(
        str(region.get("label") or "关键区域放大"),
        font="Microsoft YaHei",
        font_size=24,
        color=ACCENT,
    )
    _fit_width(zoom_label, 2.8)
    zoom_label.next_to(zoom, UP, buff=0.16)
    return [frame, picture, focus_frame, zoom_frame, zoom, zoom_label]


class ArticleSummaryScene(Scene):
    """Render short-form beats against measured speech-unit timestamps."""

    def construct(self) -> None:
        spec_path = Path(os.environ["WECHAT_VIDEO_ARTICLE_SCENE_SPEC"])
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        font = str(spec["cjk_font_family"])
        article_title = str(spec["article_title"])
        total_ms = int(spec["total_duration_ms"])
        cover_duration_ms = int(spec.get("cover_duration_ms", 1000))
        beats = spec["beats"]
        if len(beats) != len(spec["speech_units"]):
            raise RuntimeError("Article scene beats do not match measured speech units.")

        self.camera.background_color = PAPER
        brand = Text("成核生长  /  精读一分钟", font=font, font_size=28, color=INK)
        brand.to_edge(UP, buff=0.58).to_edge(LEFT, buff=0.62)
        paper_title = _fit_width(
            Text(article_title, font=font, font_size=27, color=MUTED),
            7.35,
        ).move_to(UP * 4.95)
        title_text = _fit_box(
            Text(
                str(spec.get("cover_title") or article_title),
                font=font,
                font_size=68,
                color=INK,
                line_spacing=0.88,
            ),
            7.45,
            3.25,
        ).move_to(UP * 1.65)
        subtitle_text = _fit_box(
            Text(
                str(spec.get("cover_subtitle") or "一篇文章 · 一个关键发现"),
                font=font,
                font_size=34,
                color=TEAL,
            ),
            7.25,
            1.0,
        ).move_to(DOWN * 0.85)
        accent = Line(LEFT * 0.9, RIGHT * 0.9, color=ACCENT, stroke_width=8)
        accent.move_to(DOWN * 1.65)
        source_text = _fit_box(
            Text(
                str(spec.get("source_line") or "成核生长 · 原文精读"),
                font=font,
                font_size=30,
                color=INK,
            ),
            7.25,
            0.95,
        ).move_to(DOWN * 2.65)
        cover = Group(brand, paper_title, title_text, subtitle_text, accent, source_text)
        self.play(FadeIn(cover, shift=UP * 0.12), run_time=0.30)
        self.wait(cover_duration_ms / 1000)
        cursor = cover_duration_ms
        current = cover

        for index, beat in enumerate(beats, start=1):
            start_ms = int(beat["start_ms"])
            end_ms = int(beat["end_ms"])
            if start_ms < cursor or end_ms <= start_ms:
                raise RuntimeError(
                    f"Invalid or overlapping article beat timing: {beat.get('beat_id')}"
                )
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
    ) -> Group:
        kind = str(beat["kind"])
        headline = _fit_box(
            Text(
                str(beat["headline"]),
                font=font,
                font_size=55,
                color=INK,
                line_spacing=0.9,
            ),
            7.35,
            1.65,
        )
        headline.move_to(UP * 4.55)
        top = Text("精读一分钟", font=font, font_size=25, color=ACCENT)
        top.to_corner(UP + LEFT, buff=0.62)
        counter = Text(f"{index:02d} / {count:02d}", font=font, font_size=24, color=MUTED)
        counter.to_corner(UP + RIGHT, buff=0.62)
        separator = Line(
            LEFT * 3.8, RIGHT * 3.8, color=PALE, stroke_width=2
        ).move_to(UP * 3.55)
        parts: list[Any] = [top, counter, separator, headline]
        body = str(beat.get("body") or "").strip()

        if kind == "image":
            images = beat.get("images") or []
            if not images:
                raise RuntimeError(
                    f"Image beat {beat.get('beat_id')} has no resolved image files."
                )
            for item in images:
                parts.extend(_image_objects(item))

        elif kind == "stat":
            primary_value = _fit_box(
                Text(str(beat["stat_value"]), font=font, font_size=112, color=ACCENT),
                3.1,
                1.8,
            )
            primary_label = _fit_box(
                Text(str(beat.get("stat_label") or body), font=font, font_size=29, color=INK),
                3.1,
                0.85,
            )
            if beat.get("stat_secondary_value"):
                secondary_value = _fit_box(
                    Text(str(beat["stat_secondary_value"]), font=font, font_size=92, color=TEAL),
                    3.1,
                    1.55,
                )
                secondary_label = _fit_box(
                    Text(
                        str(beat.get("stat_secondary_label") or ""),
                        font=font,
                        font_size=28,
                        color=INK,
                    ),
                    3.1,
                    0.8,
                )
                primary_card = RoundedRectangle(
                    width=3.35, height=4.2, corner_radius=0.16,
                    stroke_color=PALE, stroke_width=2,
                    fill_color=CARD, fill_opacity=1,
                ).move_to(LEFT * 1.82 + DOWN * 0.05)
                secondary_card = RoundedRectangle(
                    width=3.35, height=4.2, corner_radius=0.16,
                    stroke_color=PALE, stroke_width=2,
                    fill_color=CARD, fill_opacity=1,
                ).move_to(RIGHT * 1.82 + DOWN * 0.05)
                primary_value.move_to(primary_card.get_center() + UP * 0.55)
                primary_label.next_to(primary_value, DOWN, buff=0.38)
                secondary_value.move_to(secondary_card.get_center() + UP * 0.55)
                secondary_label.next_to(secondary_value, DOWN, buff=0.38)
                parts.extend([
                    primary_card, secondary_card,
                    primary_value, primary_label, secondary_value, secondary_label,
                ])
            else:
                primary_value.move_to(UP * 0.75)
                primary_label.next_to(primary_value, DOWN, buff=0.45)
                parts.extend([primary_value, primary_label])

        elif kind == "compare":
            left_data = beat["left"]
            right_data = beat["right"]
            cards = []
            for x, data, tone in (
                (-1.92, left_data, TEAL),
                (1.92, right_data, ACCENT),
            ):
                panel = RoundedRectangle(
                    width=3.55,
                    height=5.35,
                    corner_radius=0.16,
                    stroke_color=PALE,
                    stroke_width=2,
                    fill_color=CARD,
                    fill_opacity=1,
                ).move_to(RIGHT * x + DOWN * 0.05)
                label = _fit_box(
                    Text(
                        str(data.get("label") or data.get("title") or ""),
                        font=font,
                        font_size=36,
                        color=tone,
                    ),
                    3.0,
                    1.3,
                ).move_to(panel.get_center() + UP * 1.55)
                detail = _fit_box(
                    Text(str(data.get("detail") or data.get("body") or ""), font=font, font_size=30, color=INK),
                    2.95,
                    2.9,
                ).move_to(panel.get_center() + DOWN * 0.45)
                cards.extend([panel, label, detail])
            parts.extend(cards)

        elif kind == "mechanism":
            steps = beat["steps"]
            if not 2 <= len(steps) <= 4:
                raise RuntimeError("Mechanism scenes require two to four steps.")
            card_width = 1.72
            card_height = 4.0
            count_steps = len(steps)
            gap = 0.17
            total_width = count_steps * card_width + (count_steps - 1) * gap
            start_x = -total_width / 2 + card_width / 2
            cards = []
            for node_index, step in enumerate(steps):
                x = start_x + node_index * (card_width + gap)
                card = RoundedRectangle(
                    width=card_width,
                    height=card_height,
                    corner_radius=0.16,
                    stroke_color=ACCENT if node_index == 0 else PALE,
                    stroke_width=3,
                    fill_color=CARD,
                    fill_opacity=1,
                ).move_to(RIGHT * x + DOWN * 0.05)
                number = Text(
                    f"{node_index + 1:02d}",
                    font=font,
                    font_size=25,
                    color=ACCENT if node_index == 0 else TEAL,
                ).move_to(card.get_center() + UP * 1.15)
                label = _fit_box(
                    Text(str(step), font=font, font_size=25, color=INK, line_spacing=0.9),
                    1.43,
                    1.8,
                ).move_to(card.get_center() + DOWN * 0.2)
                cards.extend([card, number, label])
                if node_index < count_steps - 1:
                    start_x_arrow = x + card_width / 2 + 0.02
                    end_x_arrow = start_x_arrow + gap - 0.04
                    cards.append(
                        Arrow(
                            RIGHT * start_x_arrow + DOWN * 0.05,
                            RIGHT * end_x_arrow + DOWN * 0.05,
                            buff=0,
                            color=MUTED,
                            stroke_width=2,
                            max_tip_length_to_length_ratio=0.3,
                        )
                    )
            parts.extend(cards)
            if body:
                detail = _fit_box(
                    Text(body, font=font, font_size=25, color=MUTED),
                    7.1,
                    0.75,
                )
                detail.move_to(DOWN * 2.8)
                parts.append(detail)

        elif kind == "quote":
            quote = str(beat.get("quote") or body)
            quote_group = _fit_box(
                Text(
                    f"“{quote}”",
                    font=font,
                    font_size=43,
                    color=INK,
                    line_spacing=0.95,
                ),
                7.1,
                5.1,
            )
            quote_group.move_to(DOWN * 0.1)
            parts.append(quote_group)

        else:
            detail = _fit_box(
                Text(body, font=font, font_size=42, color=INK, line_spacing=0.95),
                7.2,
                4.4,
            )
            detail.move_to(DOWN * 0.05)
            parts.append(detail)

        footer = _fit_width(
            Text("成核生长 · 精读一分钟", font=font, font_size=21, color=MUTED),
            7.2,
        )
        footer.to_edge(DOWN, buff=0.42)
        parts.append(footer)
        return Group(*parts)
