"""Loaders for the reusable series master configuration files."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .tooling import project_root


def _load(root: Path, relative: str, expected_sections: tuple[str, ...]) -> dict[str, Any]:
    path = root / relative
    if not path.is_file():
        raise RuntimeError(f"Missing series master config: {relative}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid series master config {relative}: {exc}") from exc
    missing = [key for key in expected_sections if key not in data]
    if missing:
        raise RuntimeError(f"Series master config {relative} is missing sections: {missing}")
    return data


@lru_cache(maxsize=8)
def theme_config(root: str | None = None) -> dict[str, Any]:
    root_path = Path(root) if root else project_root()
    return _load(
        root_path,
        "configs/theme_config.json",
        (
            "schema_version", "theme_id", "series_identity", "palette",
            "semantic_roles", "portrait_grid", "subtitle_rules",
            "dimension_visual_mapping", "hook_pattern", "state_curve_motion",
            "focus_rules", "stage_scale", "hook_ghost", "formula_pulse",
            "concept_visuals", "ending_halo", "motion_accent_rules",
            "formula_symbol_roles",
        ),
    )


@lru_cache(maxsize=8)
def audio_config(root: str | None = None) -> dict[str, Any]:
    root_path = Path(root) if root else project_root()
    return _load(
        root_path,
        "configs/audio_postprocess.json",
        (
            "schema_version", "preset_id", "default_profile", "noise_policy",
            "required_ffmpeg_filters", "denoise", "voice_eq", "voice_headroom",
            "sfx", "ambient_bed", "final_programme", "processing_order",
        ),
    )


def voice_eq_filter_chain(config: dict[str, Any] | None = None) -> str:
    """Build the configured clarity EQ chain; no band values live in Python."""
    cfg = config or audio_config()
    eq = cfg["voice_eq"]
    return (
        f"highpass=f={eq['highpass_hz']},"
        f"equalizer=f={eq['low_mid_hz']}:t=q:w={eq['low_mid_q']}:g={eq['low_mid_gain_db']},"
        f"equalizer=f={eq['presence_hz']}:t=q:w={eq['presence_q']}:g={eq['presence_gain_db']},"
        f"highshelf=f={eq['air_hz']}:g={eq['air_gain_db']}"
    )


def denoise_filter_chain(config: dict[str, Any] | None = None) -> str:
    cfg = config or audio_config()
    denoise = cfg["denoise"]
    if not denoise.get("enabled", False):
        return "anull"
    return f"{denoise['filter']}=nf={denoise['nf_db']}"


def theme_color(role: str, config: dict[str, Any] | None = None) -> str:
    cfg = config or theme_config()
    try:
        return cfg["palette"][role]
    except KeyError as exc:
        raise RuntimeError(f"Unknown theme semantic role: {role}") from exc
