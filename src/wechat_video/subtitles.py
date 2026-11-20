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
        split_at = -1
        for punctuation in "，。；！？、":
            candidate = remaining.rfind(punctuation, 0, max_chars + 1)
            split_at = max(split_at, candidate)
        if split_at < max_chars // 2:
            split_at = max_chars
        lines.append(remaining[: split_at + 1].strip())
        remaining = remaining[split_at + 1 :].strip()
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


def write_subtitles(
    timeline: dict[str, Any],
    srt_path: Path,
    ass_path: Path,
    layout: dict[str, Any],
    font_family: str,
) -> int:
    cues = timeline["speech_units"]
    max_chars = int(layout["subtitle"]["max_line_chars"])
    srt_blocks: list[str] = []
    ass_events: list[str] = []

    for index, cue in enumerate(cues, start=1):
        display = _wrap_text(cue["display_text"], max_chars)
        srt_blocks.append(
            f"{index}\n"
            f"{_srt_timestamp(cue['start_ms'])} --> {_srt_timestamp(cue['end_ms'])}\n"
            f"{display}\n"
        )
        ass_text = display.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
        ass_text = ass_text.replace("\n", r"\N")
        ass_events.append(
            f"Dialogue: 0,{_ass_timestamp(cue['start_ms'])},"
            f"{_ass_timestamp(cue['end_ms'])},Default,,0,0,0,,{ass_text}"
        )

    subtitle_cfg = layout["subtitle"]
    ass = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "",
            "[V4+ Styles]",
            (
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
                "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                "Alignment, MarginL, MarginR, MarginV, Encoding"
            ),
            (
                "Style: Default,"
                f"{font_family},"
                f"{int(subtitle_cfg['font_size'])},"
                "&H00FFFFFF,&H0000FFFF,&H00101820,&H80000000,"
                "0,0,0,0,100,100,0,0,1,"
                f"{int(subtitle_cfg['outline'])},"
                f"{int(subtitle_cfg['shadow'])},"
                "2,"
                f"{int(subtitle_cfg['margin_left'])},"
                f"{int(subtitle_cfg['margin_right'])},"
                f"{int(subtitle_cfg['margin_vertical'])},1"
            ),
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
