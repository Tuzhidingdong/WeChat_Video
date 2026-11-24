"""Configurable TTS providers for the Chinese article-summary production path.

The selected provider must complete successfully. Provider/network failures are
reported; this module never silently switches voices or retries a paid/online call.
All providers return the same measured mono PCM16 WAV contract to the audio clock.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import re
import time
import wave
from pathlib import Path
from typing import Any

from .process import run_checked
from .speech_alignment import normalize_word_boundary_coverage_text
from .tooling import legacy_model_root, tool_env


CONFIG_RELATIVE_PATH = Path("configs") / "article_summary_tts.json"
SUPPORTED_PROVIDERS = {"edge_tts", "melo_onnx"}


class ArticleSummaryTtsError(RuntimeError):
    """Raised when article-summary TTS cannot honor its configured contract."""


def load_article_summary_tts_config(project_root: Path) -> dict[str, Any]:
    path = project_root / CONFIG_RELATIVE_PATH
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ArticleSummaryTtsError(f"Article-summary TTS config is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ArticleSummaryTtsError(f"Invalid article-summary TTS JSON: {exc}") from exc
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise ArticleSummaryTtsError("Article-summary TTS config must be an object with schema_version=1.")

    provider = str(config.get("default_provider") or "").strip()
    if provider not in SUPPORTED_PROVIDERS:
        raise ArticleSummaryTtsError(
            f"Unsupported article-summary TTS provider {provider!r}; "
            f"supported={sorted(SUPPORTED_PROVIDERS)}."
        )
    if config.get("fallback_provider") is not None:
        raise ArticleSummaryTtsError(
            "fallback_provider must remain null; automatic voice/provider fallback is disabled."
        )
    if config.get("policy", {}).get("automatic_provider_fallback") is not False:
        raise ArticleSummaryTtsError("Automatic TTS provider fallback must be explicitly disabled.")

    output = config.get("audio_output") or {}
    expected_output = {
        "sample_rate": 44100,
        "channels": 1,
        "sample_width_bytes": 2,
        "subtype": "PCM_16",
    }
    for key, expected in expected_output.items():
        if output.get(key) != expected:
            raise ArticleSummaryTtsError(
                f"audio_output.{key} must be {expected!r}; got {output.get(key)!r}."
            )

    settings = config.get("providers", {}).get(provider)
    if not isinstance(settings, dict):
        raise ArticleSummaryTtsError(f"Missing settings for TTS provider {provider!r}.")
    if provider == "edge_tts":
        if not str(settings.get("voice") or "").strip():
            raise ArticleSummaryTtsError("Edge-TTS voice must be a non-empty voice name.")
        for key, pattern in (
            ("rate", r"^[+-]\d+%$"),
            ("volume", r"^[+-]\d+%$"),
            ("pitch", r"^[+-]\d+Hz$"),
        ):
            if not re.fullmatch(pattern, str(settings.get(key) or "")):
                raise ArticleSummaryTtsError(
                    f"Invalid Edge-TTS {key} value: {settings.get(key)!r}."
                )
        for key in ("request_timeout_seconds", "conversion_timeout_seconds"):
            value = settings.get(key)
            if not isinstance(value, int) or not 10 <= value <= 600:
                raise ArticleSummaryTtsError(f"Edge-TTS {key} must be an integer from 10 to 600.")
    elif provider == "melo_onnx":
        threads = settings.get("num_threads", 2)
        if not isinstance(threads, int) or not 1 <= threads <= 16:
            raise ArticleSummaryTtsError("MeloTTS num_threads must be an integer from 1 to 16.")

    return config


def validate_article_summary_tts_runtime(
    project_root: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    provider = str(config["default_provider"])
    settings = config["providers"][provider]
    if provider == "edge_tts":
        try:
            import edge_tts  # noqa: F401
        except ImportError as exc:
            raise ArticleSummaryTtsError(
                "The configured Edge-TTS provider is unavailable. Install the optional "
                "dependency with: python -m pip install -e '.[article-summary-tts]'. "
                "No fallback provider will be selected automatically."
            ) from exc
        try:
            version = importlib.metadata.version("edge-tts")
        except importlib.metadata.PackageNotFoundError as exc:
            raise ArticleSummaryTtsError("Cannot determine the installed edge-tts package version.") from exc
        minimum = str(settings.get("minimum_version", "7.3.1"))
        if _version_tuple(version) < _version_tuple(minimum):
            raise ArticleSummaryTtsError(
                f"edge-tts {version} is older than the configured minimum {minimum}."
            )
        return {
            "provider_id": "edge_tts",
            "engine": "Edge-TTS",
            "version": version,
            "provider": "Microsoft online endpoint via edge-tts community client",
            "voice": str(settings["voice"]),
            "rate": str(settings["rate"]),
            "volume": str(settings["volume"]),
            "pitch": str(settings["pitch"]),
            "network_required": True,
            "local_model_required": False,
            "automatic_fallback": False,
        }

    try:
        import sherpa_onnx
    except ImportError as exc:
        raise ArticleSummaryTtsError(
            "sherpa-onnx is required by the explicitly selected MeloTTS provider."
        ) from exc
    model_root = legacy_model_root(project_root)
    required = [model_root / "model.onnx", model_root / "lexicon.txt", model_root / "tokens.txt"]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ArticleSummaryTtsError(
            "The selected offline MeloTTS model is incomplete: " + ", ".join(missing)
        )
    return {
        "provider_id": "melo_onnx",
        "engine": "sherpa-onnx OfflineTts / VITS MeloTTS zh_en",
        "version": getattr(sherpa_onnx, "__version__", "unknown"),
        "provider": "cpu",
        "voice": None,
        "rate": 1.0,
        "volume": None,
        "pitch": None,
        "network_required": False,
        "local_model_required": True,
        "model_path": str(model_root),
        "automatic_fallback": False,
    }


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", value)
    return tuple(int(part) for part in parts) or (0,)


def _validate_unit_id(unit_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", unit_id):
        raise ArticleSummaryTtsError(f"Unsafe or empty speech unit id: {unit_id!r}")


def _inspect_pcm_wav(path: Path, unit_id: str) -> dict[str, Any]:
    try:
        with wave.open(str(path), "rb") as reader:
            info = {
                "channels": reader.getnchannels(),
                "sample_width_bytes": reader.getsampwidth(),
                "sample_rate": reader.getframerate(),
                "frames": reader.getnframes(),
                "compression": reader.getcomptype(),
            }
    except (OSError, wave.Error) as exc:
        raise ArticleSummaryTtsError(f"{unit_id} did not produce a readable PCM WAV: {path}") from exc
    if (
        info["channels"] != 1
        or info["sample_width_bytes"] != 2
        or info["sample_rate"] != 44100
        or info["compression"] != "NONE"
        or info["frames"] <= 0
    ):
        raise ArticleSummaryTtsError(
            f"{unit_id} WAV violates the normalized audio contract: {info}"
        )
    return {
        "unit_id": unit_id,
        "audio_file": str(path),
        "sample_rate": info["sample_rate"],
        "channels": info["channels"],
        "sample_width_bytes": info["sample_width_bytes"],
        "frames": info["frames"],
        "duration_seconds": info["frames"] / info["sample_rate"],
    }


def _read_word_boundary_metadata(
    metadata_path: Path,
    spoken_text: str,
    audio_duration_seconds: float,
) -> tuple[list[dict[str, Any]], str]:
    """Read Edge-TTS WordBoundary JSONL and verify lexical coverage. Edge omits punctuation."""
    if not metadata_path.is_file():
        return [], "metadata_missing"
    expected = normalize_word_boundary_coverage_text(spoken_text)
    boundaries: list[dict[str, Any]] = []
    emitted: list[str] = []
    duration_ms = max(0, round(audio_duration_seconds * 1000))
    try:
        for line in metadata_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("type") != "WordBoundary":
                continue
            text = str(item.get("text") or "")
            if not text:
                continue
            offset_ticks = int(item.get("offset", 0))
            duration_ticks = int(item.get("duration", 0))
            start_ms = max(0, round(offset_ticks / 10_000))
            end_ms = min(duration_ms, round((offset_ticks + duration_ticks) / 10_000))
            if end_ms <= start_ms:
                continue
            boundaries.append({"text": text, "start_ms": start_ms, "end_ms": end_ms})
            emitted.append(text)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return [], "metadata_invalid"
    if not boundaries:
        return [], "word_boundaries_missing"
    actual = normalize_word_boundary_coverage_text("".join(emitted))
    if not expected or actual != expected:
        return [], "text_coverage_mismatch"
    return boundaries, "word_boundaries_verified"


def _generate_edge_tts(
    project_root: Path,
    settings: dict[str, Any],
    units: list[dict[str, Any]],
    audio_dir: Path,
    ffmpeg: str,
    version: str,
) -> dict[str, Any]:
    try:
        import edge_tts
    except ImportError as exc:
        raise ArticleSummaryTtsError("edge-tts is not installed; no provider fallback is allowed.") from exc

    if not units:
        raise ArticleSummaryTtsError("Article-summary TTS received no speech units.")
    audio_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = audio_dir / "_raw_edge_tts"
    raw_dir.mkdir(exist_ok=True)
    rate = str(settings["rate"])
    volume = str(settings["volume"])
    pitch = str(settings["pitch"])
    voice = str(settings["voice"])
    timeout = int(settings["request_timeout_seconds"])
    results: list[dict[str, Any]] = []

    async def synthesize() -> None:
        for unit in units:
            unit_id = str(unit.get("unit_id") or "")
            spoken_text = str(unit.get("spoken_text") or "").strip()
            _validate_unit_id(unit_id)
            if not spoken_text:
                raise ArticleSummaryTtsError(f"{unit_id} has no spoken_text.")
            raw_mp3 = raw_dir / f"{unit_id}.mp3"
            raw_metadata = raw_dir / f"{unit_id}.jsonl"
            target_wav = audio_dir / f"{unit_id}.wav"
            started = time.monotonic()
            try:
                communicate = edge_tts.Communicate(
                    spoken_text,
                    voice=voice,
                    rate=rate,
                    volume=volume,
                    pitch=pitch,
                    boundary="WordBoundary",
                )
                await asyncio.wait_for(
                    communicate.save(str(raw_mp3), str(raw_metadata)),
                    timeout=timeout,
                )
            except asyncio.TimeoutError as exc:
                raise ArticleSummaryTtsError(
                    f"Edge-TTS timed out after {timeout}s for {unit_id}; no retry or fallback was attempted."
                ) from exc
            except Exception as exc:
                raise ArticleSummaryTtsError(
                    f"Edge-TTS request failed for {unit_id}: {type(exc).__name__}: {exc}. "
                    "No retry or fallback was attempted."
                ) from exc

            if not raw_mp3.is_file() or raw_mp3.stat().st_size < 1024:
                raise ArticleSummaryTtsError(f"Edge-TTS returned an empty or incomplete MP3 for {unit_id}.")
            try:
                run_checked(
                    [
                        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(raw_mp3), "-map_metadata", "-1", "-vn",
                        "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le",
                        str(target_wav),
                    ],
                    cwd=project_root,
                    timeout_seconds=int(settings["conversion_timeout_seconds"]),
                    env=tool_env(project_root),
                )
            except Exception as exc:
                raise ArticleSummaryTtsError(
                    f"Cannot convert Edge-TTS audio for {unit_id} to PCM16 WAV: {exc}"
                ) from exc

            measured = _inspect_pcm_wav(target_wav, unit_id)
            word_boundaries, boundary_status = _read_word_boundary_metadata(
                raw_metadata, spoken_text, float(measured["duration_seconds"])
            )
            measured.update({
                "word_boundaries": word_boundaries,
                "subtitle_alignment_method": (
                    "edge_word_boundary" if boundary_status == "word_boundaries_verified"
                    else "speech_unit_envelope"
                ),
                "word_boundary_status": boundary_status,
                "tts_engine": "Edge-TTS",
                "tts_engine_version": version,
                "provider": "Microsoft online endpoint via edge-tts community client",
                "voice": voice,
                "rate": rate,
                "volume": volume,
                "pitch": pitch,
                "generation_seconds": round(time.monotonic() - started, 3),
                "source_text_sha256": hashlib.sha256(spoken_text.encode("utf-8")).hexdigest(),
            })
            results.append(measured)

    try:
        asyncio.run(synthesize())
    except RuntimeError as exc:
        if "asyncio.run()" in str(exc):
            raise ArticleSummaryTtsError(
                "Edge-TTS synthesis requires a synchronous CLI context; an event loop is already running."
            ) from exc
        raise

    return {
        "engine": "Edge-TTS",
        "version": version,
        "provider": "Microsoft online endpoint via edge-tts community client",
        "provider_id": "edge_tts",
        "voice": voice,
        "rate": rate,
        "volume": volume,
        "pitch": pitch,
        "network_required": True,
        "automatic_fallback_used": False,
        "fallback_provider": None,
        "speech_units": results,
    }


def generate_article_summary_speech_units(
    project_root: Path,
    config: dict[str, Any],
    units: list[dict[str, Any]],
    audio_dir: Path,
    ffmpeg: str,
) -> dict[str, Any]:
    """Generate normalized speech-unit WAVs using exactly the configured provider."""
    runtime = validate_article_summary_tts_runtime(project_root, config)
    provider = str(config["default_provider"])
    if provider == "edge_tts":
        return _generate_edge_tts(
            project_root,
            config["providers"]["edge_tts"],
            units,
            audio_dir,
            ffmpeg,
            str(runtime["version"]),
        )

    from .tts import generate_chinese_speech_units

    model_root = legacy_model_root(project_root)
    results = generate_chinese_speech_units(model_root, units, audio_dir)
    return {
        **runtime,
        "automatic_fallback_used": False,
        "fallback_provider": None,
        "speech_units": results,
    }
