from __future__ import annotations

import importlib.metadata
from pathlib import Path
from typing import Any

import soundfile as sf


class LocalTtsError(RuntimeError):
    pass


def engine_label(model_root: Path) -> str:
    if (model_root / "espeak-ng-data").is_dir():
        return "sherpa-onnx Piper VITS / en_US-lessac-medium"
    return "sherpa-onnx OfflineTts / VITS MeloTTS zh_en"


def _create_engine(model_root: Path, num_threads: int = 2):
    try:
        import sherpa_onnx
    except ImportError as exc:
        raise LocalTtsError("sherpa-onnx is not installed; no online fallback is allowed.") from exc

    tokens = model_root / "tokens.txt"
    if not tokens.is_file():
        raise LocalTtsError(f"Offline TTS model file missing: {tokens}")

    espeak_dir = model_root / "espeak-ng-data"
    if espeak_dir.is_dir():
        # Piper VITS: tokens + espeak-ng-data are required; MeloTTS lexicon is not.
        candidates = sorted(
            (p for p in model_root.glob("*.onnx") if "int8" not in p.name),
            key=lambda p: p.stat().st_size,
            reverse=True,
        )
        if not candidates:
            raise LocalTtsError(f"Piper VITS ONNX model missing in {model_root}")
        model = candidates[0]
        vits_config = sherpa_onnx.OfflineTtsVitsModelConfig(
            model=str(model),
            tokens=str(tokens),
            data_dir=str(espeak_dir),
        )
        rule_fsts = ""
    else:
        model = model_root / "model.onnx"
        lexicon = model_root / "lexicon.txt"
        for path in (model, lexicon):
            if not path.is_file():
                raise LocalTtsError(f"Offline TTS model file missing: {path}")
        vits_config = sherpa_onnx.OfflineTtsVitsModelConfig(
            model=str(model),
            lexicon=str(lexicon),
            tokens=str(tokens),
            noise_scale=0.667,
            noise_scale_w=0.8,
            length_scale=1.0,
        )
        rule_fsts = ",".join(
            str(path)
            for path in (model_root / "date.fst", model_root / "number.fst")
            if path.is_file()
        )

    model_config = sherpa_onnx.OfflineTtsModelConfig(
        vits=vits_config,
        num_threads=max(1, int(num_threads)),
        debug=False,
        provider="cpu",
    )
    config = sherpa_onnx.OfflineTtsConfig(
        model=model_config,
        rule_fsts=rule_fsts,
        max_num_sentences=1,
    )
    if not config.validate():
        raise LocalTtsError("sherpa-onnx rejected the offline TTS configuration.")
    return sherpa_onnx, sherpa_onnx.OfflineTts(config)


def generate_speech_units(
    model_root: Path,
    units: list[dict[str, Any]],
    audio_dir: Path,
    pronunciation_text: str,
) -> list[dict[str, Any]]:
    audio_dir.mkdir(parents=True, exist_ok=True)
    sherpa, engine = _create_engine(model_root)
    results: list[dict[str, Any]] = []

    try:
        for unit in units:
            unit_id = str(unit["unit_id"])
            output = audio_dir / f"{unit_id}.wav"
            generation = sherpa.GenerationConfig()
            generation.sid = 0
            generation.speed = 1.0
            generation.silence_scale = 0.2
            audio = engine.generate(str(unit["spoken_text"]), generation)
            if audio.samples is None or len(audio.samples) == 0:
                raise LocalTtsError(f"{unit_id} produced no valid audio.")
            sf.write(
                str(output),
                audio.samples,
                samplerate=int(audio.sample_rate),
                subtype="PCM_16",
                format="WAV",
            )
            info = sf.info(str(output))
            if info.frames <= 0 or info.samplerate <= 0 or info.channels != 1:
                raise LocalTtsError(f"{unit_id} audio metadata is invalid: {info}")
            results.append(
                {
                    "unit_id": unit_id,
                    "audio_file": str(output),
                    "sample_rate": int(info.samplerate),
                    "channels": int(info.channels),
                    "frames": int(info.frames),
                    "duration_seconds": float(info.duration),
                    "tts_engine": engine_label(model_root),
                    "tts_engine_version": importlib.metadata.version("sherpa-onnx"),
                    "provider": "cpu",
                    "speed": 1.0,
                }
            )

        # A separate listening asset makes scientific pronunciation review explicit.
        review_path = audio_dir / "pronunciation_review.wav"
        review_config = sherpa.GenerationConfig()
        review_config.sid = 0
        review_config.speed = 1.0
        review_config.silence_scale = 0.2
        review_audio = engine.generate(pronunciation_text, review_config)
        if review_audio.samples is None or len(review_audio.samples) == 0:
            raise LocalTtsError("Pronunciation-review WAV generation failed.")
        sf.write(
            str(review_path),
            review_audio.samples,
            samplerate=int(review_audio.sample_rate),
            subtype="PCM_16",
            format="WAV",
        )
    finally:
        # The sherpa-onnx Python wrapper owns native resources; no network session is used.
        del engine

    return results
