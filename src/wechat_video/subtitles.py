from __future__ import annotations

from pathlib import Path
from typing import Any

from .speech_alignment import restore_word_boundary_source_separators


def _wrap_text(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    lines: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        window = remaining[: max_chars + 1]
        cut = -1
        inclusive = False
        for punctuation in "，。；！？、":
            candidate = window.rfind(punctuation)
            if candidate > cut:
                cut, inclusive = candidate, True
        space = window.rfind(" ")
        if space > max_chars // 2 and (not inclusive or space > cut):
            cut, inclusive = space, False
        if cut < max_chars // 2:
            cut, inclusive = max_chars, False
        end = cut + 1 if inclusive else cut
        lines.append(remaining[:end].strip())
        remaining = remaining[end:].strip()
    if remaining:
        lines.append(remaining)
    return "\n".join(lines)


def _srt_timestamp(ms: int) -> str:
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _ass_timestamp(ms: int) -> str:
    centiseconds = max(0, ms // 10)
    hours, rem = divmod(centiseconds, 360_000)
    minutes, rem = divmod(rem, 6_000)
    seconds, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\n", r"\N")
    )


def write_subtitles(
    timeline: dict[str, Any],
    srt_path: Path,
    ass_path: Path,
    layout: dict[str, Any],
    font_family: str,
    cjk_font_family: str | None = None,
) -> int:
    """Write one bilingual cue per speech unit (English top, Chinese below)."""
    subtitle_config = layout["subtitle"]
    cues = timeline["speech_units"]
    en_limit = int(subtitle_config.get("max_line_chars_en", subtitle_config["max_line_chars"]))
    zh_limit = int(subtitle_config.get("max_line_chars_zh", 12))
    cjk_family = cjk_font_family or subtitle_config.get("cjk_fonts", [font_family])[0]
    canvas_width = int(layout["canvas"]["width"])
    canvas_height = int(layout["canvas"]["height"])
    en_y = round(canvas_height * float(subtitle_config.get("en_y_percent", 70.5)) / 100)
    zh_y = round(canvas_height * float(subtitle_config.get("zh_y_percent", 75.5)) / 100)
    center_x = canvas_width // 2

    srt_blocks: list[str] = []
    ass_events: list[str] = []
    for index, cue in enumerate(cues, start=1):
        english = _wrap_text(cue["display_text"], en_limit)
        chinese = _wrap_text(cue.get("display_text_zh", ""), zh_limit)
        srt_blocks.append(
            f"{index}\n"
            f"{_srt_timestamp(cue['start_ms'])} --> {_srt_timestamp(cue['end_ms'])}\n"
            f"{english}\n{chinese}\n"
        )
        start = _ass_timestamp(cue["start_ms"])
        end = _ass_timestamp(cue["end_ms"])
        ass_events.append(
            f"Dialogue: 0,{start},{end},EN,,0,0,0,,"
            rf"{{\an5\pos({center_x},{en_y})}}{_ass_escape(english)}"
        )
        if chinese:
            ass_events.append(
                f"Dialogue: 0,{start},{end},ZH,,0,0,0,,"
                rf"{{\an5\pos({center_x},{zh_y})}}{_ass_escape(chinese)}"
            )

    def style(name: str, family: str, size: int) -> str:
        return (
            f"Style: {name},{family},{size},"
            "&H00FFFFFF,&H0000FFFF,&H00101820,&H90000000,"
            "0,0,0,0,100,100,0,0,1,"
            f"{int(subtitle_config['outline'])},{int(subtitle_config['shadow'])},"
            "2,"
            f"{int(subtitle_config['margin_left'])},{int(subtitle_config['margin_right'])},0,1"
        )

    ass = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            f"PlayResX: {canvas_width}",
            f"PlayResY: {canvas_height}",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding",
            style("EN", font_family, int(subtitle_config.get("latin_font_size", 40))),
            style("ZH", cjk_family, int(subtitle_config.get("cjk_font_size", 46))),
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            *ass_events,
            "",
        ]
    )
    srt_path.write_text("\n".join(srt_blocks), encoding="utf-8-sig")
    ass_path.write_text(ass, encoding="utf-8-sig")
    return len(cues)


def _caption_groups(cue: dict[str, Any], max_chars: int) -> list[dict[str, Any]]:
    """Group verified TTS word boundaries into short, readable phrase cues."""
    cue_start = int(cue["start_ms"])
    cue_end = int(cue["end_ms"])
    boundaries = cue.get("word_boundaries") or []
    alignment = str(cue.get("subtitle_alignment_method") or "speech_unit_envelope")
    if alignment == "edge_word_boundary" and boundaries:
        boundaries = restore_word_boundary_source_separators(
            boundaries, str(cue.get("spoken_text") or "")
        )
    if alignment != "edge_word_boundary" or not boundaries:
        text = str(cue.get("spoken_text") or cue.get("display_text") or "").strip()
        return [{
            "unit_id": str(cue["unit_id"]), "text": text,
            "start_ms": cue_start, "end_ms": cue_end,
            "alignment_method": "speech_unit_envelope",
        }] if text else []

    groups: list[dict[str, Any]] = []
    current_text: list[str] = []
    current_start: int | None = None
    current_end = cue_start
    current_chars = 0

    def flush() -> None:
        nonlocal current_text, current_start, current_end, current_chars
        text = "".join(current_text).strip()
        if text and current_start is not None:
            start = max(cue_start, current_start - 25)
            end = min(cue_end, max(current_end + 70, start + 120))
            if end > start:
                groups.append({
                    "unit_id": str(cue["unit_id"]), "text": text,
                    "start_ms": start, "end_ms": end,
                    "alignment_method": "edge_word_boundary",
                })
        current_text = []
        current_start = None
        current_end = cue_start
        current_chars = 0

    for boundary in boundaries:
        text = str(boundary.get("text") or "")
        if not text:
            continue
        try:
            start_rel = max(0, int(boundary["start_ms"]))
            end_rel = max(start_rel, int(boundary["end_ms"]))
        except (KeyError, TypeError, ValueError):
            continue
        start = min(cue_end, cue_start + start_rel)
        end = min(cue_end, cue_start + end_rel)
        count = len(text.strip())
        elapsed = max(0, end - (current_start if current_start is not None else start))
        if current_text and (current_chars + count > max_chars or elapsed >= 2200):
            flush()
        if current_start is None:
            current_start = start
        current_text.append(text)
        current_end = max(current_end, end)
        current_chars += count
        if text.rstrip().endswith(tuple("，。；！？、：")):
            flush()
    flush()

    if not groups:
        return [{
            "unit_id": str(cue["unit_id"]),
            "text": str(cue.get("spoken_text") or cue.get("display_text") or "").strip(),
            "start_ms": cue_start, "end_ms": cue_end,
            "alignment_method": "speech_unit_envelope",
        }]
    return groups


def _han_character_count(text: str) -> int:
    return sum(1 for char in text if "\u3400" <= char <= "\u4dbf" or "\u4e00" <= char <= "\u9fff")


def _merge_short_caption_groups(
    groups: list[dict[str, Any]],
    *,
    minimum_han_characters: int = 5,
) -> list[dict[str, Any]]:
    """Merge orphan CJK fragments into an adjacent cue within the same speech unit."""
    merged = [dict(item) for item in groups]
    index = 0
    while index < len(merged):
        current = merged[index]
        if _han_character_count(str(current.get("text") or "")) >= minimum_han_characters:
            index += 1
            continue

        previous_ok = index > 0 and merged[index - 1].get("unit_id") == current.get("unit_id")
        next_ok = index + 1 < len(merged) and merged[index + 1].get("unit_id") == current.get("unit_id")
        if not previous_ok and not next_ok:
            index += 1
            continue

        # Prefer the temporally closer neighbour; ties merge backwards so
        # leading short fragments naturally merge forwards.
        previous_gap = (
            max(0, int(current["start_ms"]) - int(merged[index - 1]["end_ms"]))
            if previous_ok else 10**9
        )
        next_gap = (
            max(0, int(merged[index + 1]["start_ms"]) - int(current["end_ms"]))
            if next_ok else 10**9
        )
        merge_previous = previous_ok and (not next_ok or previous_gap <= next_gap)
        neighbour_index = index - 1 if merge_previous else index + 1
        neighbour = merged[neighbour_index]
        if merge_previous:
            neighbour["text"] = str(neighbour.get("text") or "") + str(current.get("text") or "")
        else:
            neighbour["text"] = str(current.get("text") or "") + str(neighbour.get("text") or "")
        neighbour["start_ms"] = min(int(neighbour["start_ms"]), int(current["start_ms"]))
        neighbour["end_ms"] = max(int(neighbour["end_ms"]), int(current["end_ms"]))
        neighbour["merged_short_fragment_count"] = int(
            neighbour.get("merged_short_fragment_count", 0)
        ) + int(current.get("merged_short_fragment_count", 0)) + 1
        merged.pop(index)
        if merge_previous:
            index = max(0, index - 1)
    return merged


def _strip_trailing_caption_punctuation(text: str) -> str:
    """Remove only visual end punctuation; authored narration remains untouched."""
    return text.rstrip().rstrip("，。,.").rstrip()


def write_chinese_subtitles(
    timeline: dict[str, Any],
    srt_path: Path,
    ass_path: Path,
    layout: dict[str, Any],
    cjk_font_family: str,
) -> int:
    """Write phrase-level Chinese captions synchronized to verified TTS word boundaries."""
    subtitle_config = layout["subtitle"]
    limit = max(6, int(subtitle_config.get("max_line_chars_zh", 12)))
    canvas_width = int(layout["canvas"]["width"])
    canvas_height = int(layout["canvas"]["height"])
    y = round(canvas_height * float(subtitle_config.get("zh_y_percent", 72.5)) / 100)
    center_x = canvas_width // 2
    caption_cues: list[dict[str, Any]] = []
    for cue in timeline["speech_units"]:
        caption_cues.extend(_caption_groups(cue, limit))
    caption_cues.sort(key=lambda item: (item["start_ms"], item["end_ms"]))
    caption_cues = _merge_short_caption_groups(
        caption_cues,
        minimum_han_characters=max(1, int(subtitle_config.get("minimum_han_characters_per_caption", 5))),
    )
    for index, cue in enumerate(caption_cues):
        original_text = str(cue.get("text") or "").strip()
        cue["source_text"] = original_text
        if subtitle_config.get("strip_trailing_caption_punctuation", True):
            cue["text"] = _strip_trailing_caption_punctuation(original_text)
        if index + 1 < len(caption_cues) and cue["unit_id"] == caption_cues[index + 1]["unit_id"]:
            cue["end_ms"] = min(cue["end_ms"], caption_cues[index + 1]["start_ms"])
        cue["caption_id"] = f"{cue['unit_id']}_C{index + 1:02d}"

    srt_blocks: list[str] = []
    ass_events: list[str] = []
    for index, cue in enumerate(caption_cues, start=1):
        text = _wrap_text(str(cue["text"]), limit)
        srt_blocks.append(
            f"{index}\n"
            f"{_srt_timestamp(cue['start_ms'])} --> {_srt_timestamp(cue['end_ms'])}\n"
            f"{text}\n"
        )
        ass_events.append(
            f"Dialogue: 2,{_ass_timestamp(cue['start_ms'])},{_ass_timestamp(cue['end_ms'])},ZH,,0,0,0,,"
            rf"{{\an5\fad(50,60)\pos({center_x},{y})}}{_ass_escape(text)}"
        )

    base_font_size = int(subtitle_config.get("cjk_font_size", 42))
    font_scale = float(subtitle_config.get("caption_font_scale", 1.18))
    if not 1.0 <= font_scale <= 1.3:
        raise ValueError("caption_font_scale must remain between 1.0 and 1.3.")
    font_size = round(base_font_size * font_scale)
    text_color = str(subtitle_config.get("caption_color", "#222222")).lstrip("#").upper()
    if len(text_color) != 6 or any(char not in "0123456789ABCDEF" for char in text_color):
        raise ValueError("caption_color must be a six-digit RGB hex value.")
    red, green, blue = text_color[0:2], text_color[2:4], text_color[4:6]
    ass_color = f"&H00{blue}{green}{red}"
    outline = int(subtitle_config.get("caption_outline", 0))
    shadow = int(subtitle_config.get("caption_shadow", 0))
    style = (
        f"Style: ZH,{cjk_font_family},{font_size},"
        f"{ass_color},{ass_color},{ass_color},&H00000000,"
        "0,0,0,0,100,100,0,0,1,"
        f"{outline},{shadow},2,"
        f"{int(subtitle_config.get('margin_left', 75))},{int(subtitle_config.get('margin_right', 75))},0,1"
    )
    ass = "\n".join([
        "[Script Info]", "ScriptType: v4.00+", "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        f"PlayResX: {canvas_width}", f"PlayResY: {canvas_height}", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        style, "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        *ass_events, "",
    ])
    srt_path.write_text("\n".join(srt_blocks), encoding="utf-8-sig")
    ass_path.write_text(ass, encoding="utf-8-sig")
    timeline["subtitle_cues"] = caption_cues
    timeline["subtitle_alignment"] = {
        "caption_count": len(caption_cues),
        "word_boundary_caption_count": sum(
            1 for item in caption_cues if item["alignment_method"] == "edge_word_boundary"
        ),
        "speech_unit_envelope_fallback_count": sum(
            1 for item in caption_cues if item["alignment_method"] == "speech_unit_envelope"
        ),
        "max_chars_per_caption": limit,
        "minimum_han_characters_per_caption": int(subtitle_config.get("minimum_han_characters_per_caption", 5)),
        "font_size": font_size,
        "font_scale": font_scale,
        "caption_color": f"#{text_color}",
        "outline": outline,
        "shadow": shadow,
        "style": "transparent_background_charcoal_text_no_outline",
    }
    return len(caption_cues)
