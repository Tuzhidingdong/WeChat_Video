from __future__ import annotations

from pathlib import Path
from typing import Any


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


def write_chinese_subtitles(
    timeline: dict[str, Any],
    srt_path: Path,
    ass_path: Path,
    layout: dict[str, Any],
    cjk_font_family: str,
) -> int:
    """Write a spoken-text subtitle cue synchronized to each measured WAV unit."""
    subtitle_config = layout["subtitle"]
    limit = int(subtitle_config.get("max_line_chars_zh", 20))
    canvas_width = int(layout["canvas"]["width"])
    canvas_height = int(layout["canvas"]["height"])
    y = round(canvas_height * float(subtitle_config.get("zh_y_percent", 72.5)) / 100)
    center_x = canvas_width // 2
    srt_blocks: list[str] = []
    ass_events: list[str] = []
    for index, cue in enumerate(timeline["speech_units"], start=1):
        # The old article-summary renderer used display_text here, so the viewer
        # saw a fixed slide takeaway rather than the words being spoken. Prefer
        # the actual narrated sentence; display_text remains the scene headline.
        spoken = str(cue.get("subtitle_text") or cue.get("spoken_text") or cue.get("display_text") or "").strip()
        if not spoken:
            raise ValueError(f"Subtitle cue {cue.get('unit_id')} has no spoken text.")
        text = _wrap_text(spoken, limit)
        srt_blocks.append(
            f"{index}\n"
            f"{_srt_timestamp(cue['start_ms'])} --> {_srt_timestamp(cue['end_ms'])}\n"
            f"{text}\n"
        )
        ass_events.append(
            f"Dialogue: 2,{_ass_timestamp(cue['start_ms'])},{_ass_timestamp(cue['end_ms'])},ZH,,0,0,0,,"
            rf"{{\an5\fad(90,90)\pos({center_x},{y})}}{_ass_escape(text)}"
        )
    style = (
        f"Style: ZH,{cjk_font_family},{int(subtitle_config.get('cjk_font_size', 42))},"
        "&H00FFFFFF,&H000000FF,&H00101820,&H700B1C2C,"
        "0,0,0,0,100,100,0,0,3,"
        "8,0,2,"
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
    return len(ass_events)
