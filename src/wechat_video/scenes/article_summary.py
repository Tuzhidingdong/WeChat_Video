"""Premium short-form editorial scene system for evidence-backed article summaries."""
from __future__ import annotations

import json
import os
import textwrap
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


def _axis_labels_object(item: dict[str, Any], *, width: float) -> Any | None:
    axis_labels = item.get("axis_labels_zh") or {}
    if not isinstance(axis_labels, dict):
        raise RuntimeError("axis_labels_zh must be an object with optional x and y labels.")
    axis_parts = []
    if str(axis_labels.get("x") or "").strip():
        axis_parts.append(f"横轴：{str(axis_labels['x']).strip()}")
    if str(axis_labels.get("y") or "").strip():
        axis_parts.append(f"纵轴：{str(axis_labels['y']).strip()}")
    if not axis_parts:
        return None
    label = Text(
        "  ·  ".join(axis_parts),
        font="Microsoft YaHei",
        font_size=18,
        color=INK,
    )
    return _fit_width(label, width)


def _image_objects(item: dict[str, Any]) -> list[Any]:
    """Render an evidence-preserving crop and optional focus zoom from local source imagery."""
    path = Path(str(item["path"]))
    axis_label = _axis_labels_object(item, width=2.75)
    with Image.open(path) as source:
        display_image = source.convert("RGB")
        display_region = item.get("display_crop_region")
        if display_region:
            x, y, width, height = _normalized_region(display_region)
            pixel_width, pixel_height = display_image.size
            left = max(0, min(pixel_width - 1, round(x * pixel_width)))
            top = max(0, min(pixel_height - 1, round(y * pixel_height)))
            right = max(left + 1, min(pixel_width, round((x + width) * pixel_width)))
            bottom = max(top + 1, min(pixel_height, round((y + height) * pixel_height)))
            display_image = display_image.crop((left, top, right, bottom))
        display_array = np.asarray(display_image).copy()
        picture = ImageMobject(display_array)
        region = item.get("focus_region")
        if region:
            x, y, width, height = _normalized_region(region)
            pixel_width, pixel_height = display_image.size
            left = max(0, min(pixel_width - 1, round(x * pixel_width)))
            top = max(0, min(pixel_height - 1, round(y * pixel_height)))
            right = max(left + 1, min(pixel_width, round((x + width) * pixel_width)))
            bottom = max(top + 1, min(pixel_height, round((y + height) * pixel_height)))
            crop = np.asarray(display_image.crop((left, top, right, bottom))).copy()

    region = item.get("focus_region")
    if not region:
        _fit_box(picture, 7.0, 4.85)
        picture.move_to(UP * 0.32)
        frame = RoundedRectangle(
            width=picture.width + 0.14,
            height=picture.height + 0.14,
            corner_radius=0.10,
            stroke_color=PALE,
            stroke_width=2,
            fill_color=CARD,
            fill_opacity=1,
        ).move_to(picture)
        objects = [frame, picture]
        if axis_label is not None:
            _fit_width(axis_label, 7.0)
            axis_label.next_to(picture, DOWN, buff=0.12)
            objects.append(axis_label)
        return objects

    x, y, width, height = _normalized_region(region)
    _fit_box(picture, 4.15, 4.7)
    picture.move_to(LEFT * 1.55 + UP * 0.25)
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
    _fit_box(zoom, 2.75, 3.4)
    zoom.move_to(RIGHT * 1.75 + UP * 0.25)
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
    parts: list[Any] = [frame, picture, focus_frame, zoom_frame, zoom, zoom_label]
    if axis_label is not None:
        axis_label.next_to(zoom, DOWN, buff=0.12)
        parts.append(axis_label)
    return parts


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
        cover = Group(brand, title_text, subtitle_text, accent, source_text)

        transition_ms = max(100, min(350, int(spec.get("transition_duration_ms", 220))))
        self.play(FadeIn(cover, shift=UP * 0.12), run_time=0.30)
        # The cover fade-in belongs to the measured cover duration. The first
        # visual transition occupies its final interval and ends at speech t=0.
        first_transition = min(transition_ms, max(0, cover_duration_ms - 300))
        cover_hold_ms = max(0, cover_duration_ms - 300 - first_transition)
        if cover_hold_ms:
            self.wait(cover_hold_ms / 1000)
        cursor = cover_duration_ms - first_transition
        current = cover
        layout_records: list[dict[str, Any]] = []
        self._record_layout(layout_records, "cover", "cover", cover, spec)

        for index, beat in enumerate(beats, start=1):
            start_ms = int(beat["start_ms"])
            end_ms = int(beat["end_ms"])
            if start_ms < cursor or end_ms <= start_ms:
                raise RuntimeError(
                    f"Invalid or overlapping article beat timing: {beat.get('beat_id')}"
                )
            gap = max(0, start_ms - cursor)
            if gap >= 100:
                transition = min(transition_ms, gap)
                transition_start = start_ms - transition
            else:
                transition_start = start_ms
                transition = max(80, min(transition_ms, end_ms - start_ms))
            if transition_start > cursor:
                self.wait((transition_start - cursor) / 1000)

            group, choreography, core_group = self._build_beat(
                beat, index, len(beats), font
            )
            self._record_layout(
                layout_records,
                str(beat.get("beat_id") or f"beat_{index}"),
                str(beat.get("kind") or ""),
                core_group,
                spec,
            )
            self.play(
                FadeOut(current),
                FadeIn(group, shift=UP * 0.08),
                run_time=transition / 1000,
            )
            cursor = transition_start + transition
            if cursor < start_ms:
                self.wait((start_ms - cursor) / 1000)
                cursor = start_ms

            choreography_budget_ms = max(0, end_ms - max(start_ms, cursor))
            choreography_time_ms = self._animate_choreography(
                choreography, choreography_budget_ms
            )
            cursor = max(cursor, start_ms + choreography_time_ms)
            if end_ms > cursor:
                self.wait((end_ms - cursor) / 1000)
            cursor = end_ms
            current = group

        if total_ms < cursor:
            raise RuntimeError(
                f"Manim scene exceeded measured audio timeline by {cursor - total_ms} ms."
            )
        tail_remaining = total_ms - cursor
        outro_fade_ms = min(260, tail_remaining)
        if tail_remaining > outro_fade_ms:
            self.wait((tail_remaining - outro_fade_ms) / 1000)
        if outro_fade_ms:
            self.play(FadeOut(current), run_time=outro_fade_ms / 1000)
        self._write_layout_report(spec_path, layout_records)

    def _build_beat(
        self, beat: dict[str, Any], index: int, count: int, font: str
    ) -> tuple[Group, dict[str, Any], Group]:
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
        choreography: dict[str, Any] = {"kind": kind}

        if kind == "image":
            images = beat.get("images") or []
            if not images:
                raise RuntimeError(
                    f"Image beat {beat.get('beat_id')} has no resolved image files."
                )
            image_parts: list[Any] = []
            for item in images:
                objects = _image_objects(item)
                image_parts.extend(objects)
                parts.extend(objects)
            if image_parts:
                choreography["image_focus_objects"] = image_parts[2:4] if len(image_parts) >= 6 else image_parts[:1]
            source_captions = [
                str(item.get("source_context") or item.get("caption") or "").strip()
                for item in images
                if str(item.get("source_context") or item.get("caption") or "").strip()
            ]
            if source_captions:
                caption_text = "图示：" + " / ".join(source_captions)
                caption_lines = "\n".join(textwrap.wrap(caption_text, width=30, break_long_words=True))
                figure_caption = _fit_box(
                    Text(caption_lines, font=font, font_size=24, color=MUTED, line_spacing=0.9),
                    7.1,
                    0.9,
                )
                figure_caption.move_to(DOWN * 2.55)
                parts.append(figure_caption)

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
            choreography["stat_values"] = [primary_value]
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
                choreography["stat_values"].append(secondary_value)
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
            compare_panels: list[Any] = []
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
                compare_panels.append(panel)
                cards.extend([panel, label, detail])
            choreography["compare_panels"] = compare_panels
            parts.extend(cards)

        elif kind == "mechanism":
            steps = beat["steps"]
            if not 2 <= len(steps) <= 4:
                raise RuntimeError("Mechanism scenes require two to four steps.")
            count_steps = len(steps)
            card_width = 3.42
            card_height = 3.45 if count_steps == 2 else 2.12
            column_gap = 0.22
            if count_steps == 2:
                centers = [(-1.82, 0.15), (1.82, 0.15)]
            elif count_steps == 3:
                centers = [(-1.82, 0.92), (1.82, 0.92), (0.0, -1.38)]
            else:
                # Four-step mechanisms use a phone-readable 2x2 grid.
                centers = [
                    (-1.82, 0.96), (1.82, 0.96),
                    (-1.82, -1.42), (1.82, -1.42),
                ]
            cards = []
            step_cards: list[Any] = []
            step_numbers: list[Any] = []
            for node_index, step in enumerate(steps):
                x, y = centers[node_index]
                card = RoundedRectangle(
                    width=card_width,
                    height=card_height,
                    corner_radius=0.16,
                    stroke_color=PALE,
                    stroke_width=2,
                    fill_color=CARD,
                    fill_opacity=1,
                ).move_to(RIGHT * x + UP * y)
                number = Text(
                    f"{node_index + 1:02d}",
                    font=font,
                    font_size=27,
                    color=MUTED,
                ).move_to(card.get_center() + UP * (card_height * 0.28))
                label = _fit_box(
                    Text(str(step), font=font, font_size=34, color=INK, line_spacing=0.92),
                    2.92,
                    card_height * 0.62,
                ).move_to(card.get_center() + DOWN * (card_height * 0.08))
                step_cards.append(card)
                step_numbers.append(number)
                cards.extend([card, number, label])
            choreography["step_cards"] = step_cards
            choreography["step_numbers"] = step_numbers
            parts.extend(cards)
            if body:
                detail = _fit_box(
                    Text(body, font=font, font_size=23, color=MUTED),
                    7.1,
                    0.36,
                )
                # Explanatory line stays above the portrait subtitle safe band.
                detail.move_to(DOWN * 2.82)
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

        elif kind in {"hook", "takeaway"}:
            role = "核心问题" if kind == "hook" else "一句话结论"
            statement_card = RoundedRectangle(
                width=7.15,
                height=4.75,
                corner_radius=0.20,
                stroke_color=PALE,
                stroke_width=2,
                fill_color=CARD,
                fill_opacity=1,
            ).move_to(DOWN * 0.10)
            statement_role = Text(role, font=font, font_size=28, color=ACCENT)
            statement_role.move_to(statement_card.get_top() + DOWN * 0.68)
            statement = _fit_box(
                Text(body, font=font, font_size=60, color=INK, line_spacing=1.08),
                6.25,
                3.25,
            ).move_to(statement_card.get_center() + DOWN * 0.30)
            parts.extend([statement_card, statement_role, statement])

        else:
            detail = _fit_box(
                Text(body, font=font, font_size=42, color=INK, line_spacing=0.95),
                7.2,
                4.4,
            )
            detail.move_to(DOWN * 0.05)
            parts.append(detail)

        core_group = Group(*parts)
        footer = _fit_width(
            Text("成核生长 · 精读一分钟", font=font, font_size=21, color=MUTED),
            7.2,
        )
        footer.to_edge(DOWN, buff=0.42)
        group = Group(core_group, footer)
        return group, choreography, core_group

    def _animate_choreography(
        self, choreography: dict[str, Any], budget_ms: int
    ) -> int:
        """Animate visual emphasis without extending the measured cue window."""
        budget = max(0, int(budget_ms))
        kind = choreography.get("kind")
        if kind == "mechanism":
            cards = choreography.get("step_cards", [])
            numbers = choreography.get("step_numbers", [])
            if not cards:
                return 0
            interval_ms = budget // len(cards)
            if interval_ms < 60:
                return 0
            animation_ms = min(180, interval_ms // 2)
            for index, _ in enumerate(cards):
                animations = [
                    card.animate.set_stroke(
                        color=ACCENT if card_index == index else PALE,
                        width=4 if card_index == index else 2,
                    )
                    for card_index, card in enumerate(cards)
                ]
                animations.extend([
                    number.animate.set_color(ACCENT if number_index == index else MUTED)
                    for number_index, number in enumerate(numbers)
                ])
                self.play(*animations, run_time=animation_ms / 1000)
                if interval_ms > animation_ms:
                    self.wait((interval_ms - animation_ms) / 1000)
            return interval_ms * len(cards)
        if kind == "compare":
            panels = choreography.get("compare_panels", [])
            if not panels or budget <= 0:
                return 0
            interval_ms = budget // len(panels)
            if interval_ms < 60:
                return 0
            animation_ms = min(180, interval_ms // 2)
            for index, panel in enumerate(panels):
                self.play(
                    panel.animate.set_stroke(color=TEAL if index == 0 else ACCENT, width=4),
                    run_time=animation_ms / 1000,
                )
                if interval_ms > animation_ms:
                    self.wait((interval_ms - animation_ms) / 1000)
            return interval_ms * len(panels)
        if kind == "stat":
            values = choreography.get("stat_values", [])
            if not values or budget <= 0:
                return 0
            animation_ms = min(180, budget // (2 * len(values)))
            if animation_ms < 60:
                return 0
            for value in values:
                self.play(value.animate.scale(1.06), run_time=animation_ms / 1000)
                self.play(value.animate.scale(1 / 1.06), run_time=animation_ms / 1000)
            return animation_ms * 2 * len(values)
        if kind == "image":
            focus = choreography.get("image_focus_objects", [])
            if not focus or budget < 120:
                return 0
            animation_ms = min(180, budget // 3)
            self.play(
                *[item.animate.set_stroke(color=ACCENT, width=4) for item in focus],
                run_time=animation_ms / 1000,
            )
            return animation_ms
        return 0

    def _record_layout(
        self,
        records: list[dict[str, Any]],
        beat_id: str,
        kind: str,
        group: Group,
        spec: dict[str, Any],
    ) -> None:
        left = float(group.get_left()[0])
        right = float(group.get_right()[0])
        top = float(group.get_top()[1])
        bottom = float(group.get_bottom()[1])
        safe = spec.get("safe_zones") or {}
        subtitle_top_percent = float(safe.get("subtitle_top_percent", 68))
        subtitle_top_y = 8.0 - 16.0 * subtitle_top_percent / 100.0
        within_frame = left >= -4.25 and right <= 4.25 and top <= 7.65 and bottom >= -7.65
        clear_of_subtitles = kind == "cover" or bottom >= subtitle_top_y - 0.20
        records.append({
            "beat_id": beat_id,
            "kind": kind,
            "bounds": {
                "left": round(left, 3), "right": round(right, 3),
                "top": round(top, 3), "bottom": round(bottom, 3),
            },
            "within_frame_safe_area": within_frame,
            "clear_of_subtitle_band": clear_of_subtitles,
            "status": "PASS" if within_frame and clear_of_subtitles else "FAIL",
        })

    def _write_layout_report(
        self, spec_path: Path, records: list[dict[str, Any]]
    ) -> None:
        failures = [item for item in records if item["status"] != "PASS"]
        report = {
            "schema_version": 1,
            "frame": {"width": 9, "height": 16, "resolution": [1080, 1920]},
            "checked_beats": len(records),
            "overall_status": "FAIL" if failures else "PASS",
            "checks": records,
            "failures": failures,
            "scope": "Manim core-scene bounds; rendered subtitle timing is checked separately",
        }
        (spec_path.parent / "scene_layout_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if failures:
            raise RuntimeError(
                "Article-summary scene violates portrait-frame or subtitle safe-area bounds: "
                + ", ".join(item["beat_id"] for item in failures)
            )
