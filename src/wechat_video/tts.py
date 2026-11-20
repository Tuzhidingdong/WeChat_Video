from __future__ import annotations

import importlib.metadata
from pathlib import Path
from typing import Any

import soundfile as sf


class LocalTtsError(RuntimeError):
    pass


def _create_engine(model_root: Path, num_threads: int = 2):
    try:
        import sherpa_onnx
    except ImportError as exc:
        raise LocalTtsError(
            "未安装 sherpa-onnx；Slice A 不允许改用在线 TTS。"
        ) from exc

    model = model_root / "model.onnx"
    lexicon = model_root / "lexicon.txt"
    tokens = model_root / "tokens.txt"
    for path in (model, lexicon, tokens):
        if not path.is_file():
            raise LocalTtsError(f"离线 TTS 模型文件缺失：{path}")

    model_config = sherpa_onnx.OfflineTtsModelConfig(
        vits=sherpa_onnx.OfflineTtsVitsModelConfig(
            model=str(model),
            lexicon=str(lexicon),
            tokens=str(tokens),
            noise_scale=0.667,
            noise_scale_w=0.8,
            length_scale=1.0,
        ),
        num_threads=max(1, int(num_threads)),
        debug=False,
        provider="cpu",
    )
    config = sherpa_onnx.OfflineTtsConfig(
        model=model_config,
        rule_fsts=",".join(
            str(path)
            for path in (model_root / "date.fst", model_root / "number.fst")
            if path.is_file()
        ),
        max_num_sentences=1,
    )
    if not config.validate():
        raise LocalTtsError("sherpa-onnx 拒绝当前离线 TTS 配置。")
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
                raise LocalTtsError(f"{unit_id} 没有生成有效音频。")
            sf.write(
                str(output),
                audio.samples,
                samplerate=int(audio.sample_rate),
                subtype="PCM_16",
                format="WAV",
            )
            info = sf.info(str(output))
            if info.frames <= 0 or info.samplerate <= 0 or info.channels != 1:
                raise LocalTtsError(f"{unit_id} 音频元数据无效：{info}")
            results.append(
                {
                    "unit_id": unit_id,
                    "audio_file": str(output),
                    "sample_rate": int(info.samplerate),
                    "channels": int(info.channels),
                    "frames": int(info.frames),
                    "duration_seconds": float(info.duration),
                    "tts_engine": "sherpa-onnx OfflineTts / VITS MeloTTS zh_en",
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
            raise LocalTtsError("科学术语发音试听文件生成失败。")
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
