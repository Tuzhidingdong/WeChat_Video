from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any



class LocalTtsError(RuntimeError):
    pass


def _soundfile_module():
    """Load the audio I/O dependency only when a TTS job actually runs."""
    try:
        import soundfile
    except ImportError as exc:
        raise LocalTtsError(
            "The soundfile package is required for offline audio generation. "
            "Install the project's audio runtime dependencies."
        ) from exc
    return soundfile


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


def _voice_profile_paths():
    from .tooling import project_root

    root = project_root()
    return (
        root,
        root / "private" / "voice_profile",
        root / ".venv-voice" / "python.exe",
        root / "src" / "wechat_video" / "voice_worker.py",
    )


def _generate_with_personal_voice(
    units: list[dict[str, Any]],
    audio_dir: Path,
    pronunciation_text: str,
) -> list[dict[str, Any]]:
    sf = _soundfile_module()
    root, profile_dir, voice_python, worker = _voice_profile_paths()
    profile_json = profile_dir / "voice_profile.json"
    target_se = profile_dir / "target_se.pth"
    if not (profile_json.is_file() and target_se.is_file()):
        raise LocalTtsError(
            "Personal voice profile is missing; enrollment is required. "
            "No silent fallback to Piper or another voice is allowed."
        )
    if not voice_python.is_file() or not worker.is_file():
        raise LocalTtsError("Isolated voice runtime is missing (.venv-voice).")

    selection_path = profile_dir / "selection.json"
    selection = (
        json.loads(selection_path.read_text(encoding="utf-8"))
        if selection_path.is_file()
        else {"selected_profile": "active", "post_conversion_cleanup": "none"}
    )
    selected_profile = selection.get("selected_profile", "active")
    clean_converted = selection.get("post_conversion_cleanup", "none") != "none"
    if selected_profile == "candidate":
        candidate_files = (
            profile_dir / "candidates" / "voice_profile_candidate.json",
            profile_dir / "candidates" / "target_se_candidate.pth",
        )
        if not all(path.is_file() for path in candidate_files):
            raise LocalTtsError("Selected personal voice candidate is missing; refusing generic fallback.")
        profile = json.loads(candidate_files[0].read_text(encoding="utf-8"))
    else:
        profile = json.loads(profile_json.read_text(encoding="utf-8"))
    run_dir = audio_dir.parent
    script_path = run_dir / "voice_script.json"
    script_path.write_text(
        json.dumps(
            {"speech_units": units, "pronunciation_review_text": pronunciation_text},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    for key, value in (
        ("HF_HOME", root / ".cache" / "hf"),
        ("HF_HUB_CACHE", root / ".cache" / "hf" / "hub"),
        ("TORCH_HOME", root / ".cache" / "torch"),
        ("NLTK_DATA", root / ".cache" / "nltk_data"),
        ("TEMP", root / ".cache" / "temp"),
        ("TMP", root / ".cache" / "temp"),
    ):
        env[str(key)] = str(value)

    command = [
        str(voice_python), "-X", "utf8", str(worker), "generate",
        "--script", str(script_path), "--out", str(run_dir),
        "--profile", selected_profile,
    ]
    if clean_converted:
        command.append("--clean-converted")
    result = subprocess.run(
        command,
        cwd=str(root),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
        shell=False,
    )
    if result.returncode != 0:
        raise LocalTtsError(f"Personal voice generation failed:\n{result.stdout[-4000:]}")

    manifest = json.loads((run_dir / "voice_generation_manifest.json").read_text(encoding="utf-8"))
    converted_dir = run_dir / "converted_user_voice"
    audio_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for source in manifest["units"]:
        unit_id = source["unit_id"]
        final = audio_dir / f"{unit_id}.wav"
        shutil.copy2(converted_dir / f"{unit_id}.wav", final)
        info = sf.info(str(final))
        if info.frames <= 0 or info.samplerate <= 0 or info.channels != 1:
            raise LocalTtsError(f"{unit_id} converted audio is invalid: {info}")
        results.append(
            {
                "unit_id": unit_id,
                "audio_file": str(final),
                "sample_rate": int(info.samplerate),
                "channels": int(info.channels),
                "frames": int(info.frames),
                "duration_seconds": float(info.duration),
                "tts_engine": manifest["engine"],
                "tts_engine_version": profile["model_revision"],
                "base_speaker": source["base_speaker"],
                "voice_profile": selected_profile,
                "post_conversion_cleanup": source["post_conversion_cleanup"],
                "provider": manifest.get("provider", "cpu"),
                "speed": 1.0,
                "base_generation_seconds": source["base_generation_seconds"],
                "conversion_seconds": source["conversion_seconds"],
                "total_seconds": source["total_seconds"],
                "voice_profile_fingerprint": profile["fingerprint"],
            }
        )
    review_src = converted_dir / "pronunciation_review.wav"
    if review_src.is_file():
        shutil.copy2(review_src, audio_dir / "pronunciation_review.wav")
    return results


def generate_speech_units(
    model_root: Path,
    units: list[dict[str, Any]],
    audio_dir: Path,
    pronunciation_text: str,
) -> list[dict[str, Any]]:
    audio_dir.mkdir(parents=True, exist_ok=True)
    if not _voice_profile_paths()[1].joinpath("voice_profile.json").is_file():
        raise LocalTtsError(
            "Personal OpenVoice profile is required; generic/Piper fallback is disabled. "
            "Run enrollment before producing a Slice A sample."
        )
    return _generate_with_personal_voice(units, audio_dir, pronunciation_text)
    # Legacy sherpa path is intentionally unreachable in the daily production route.
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


def generate_chinese_speech_units(
    model_root: Path,
    units: list[dict[str, Any]],
    audio_dir: Path,
) -> list[dict[str, Any]]:
    """Generate local Chinese narration with the existing offline MeloTTS zh_en model.

    This intentionally does not use the English-trained personal voice profile and
    never falls back to a cloud provider or a different generic voice.
    """
    if not units:
        raise LocalTtsError("Article-summary TTS received no speech units.")
    sf = _soundfile_module()
    sherpa, engine = _create_engine(model_root)
    audio_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    try:
        for unit in units:
            unit_id = str(unit.get("unit_id") or "")
            spoken_text = str(unit.get("spoken_text") or "").strip()
            if not unit_id or not spoken_text:
                raise LocalTtsError("Every Chinese speech unit requires unit_id and spoken_text.")
            if any(char in unit_id for char in ("/", "\\", ":", "..")):
                raise LocalTtsError(f"Unsafe speech unit id: {unit_id!r}")
            output = audio_dir / f"{unit_id}.wav"
            generation = sherpa.GenerationConfig()
            generation.sid = 0
            generation.speed = 1.0
            generation.silence_scale = 0.2
            audio = engine.generate(spoken_text, generation)
            if audio.samples is None or len(audio.samples) == 0:
                raise LocalTtsError(f"{unit_id} produced no valid Chinese audio.")
            sf.write(
                str(output),
                audio.samples,
                samplerate=int(audio.sample_rate),
                subtype="PCM_16",
                format="WAV",
            )
            info = sf.info(str(output))
            if info.frames <= 0 or info.samplerate <= 0 or info.channels != 1:
                raise LocalTtsError(f"{unit_id} Chinese audio metadata is invalid: {info}")
            results.append({
                "unit_id": unit_id,
                "audio_file": str(output),
                "sample_rate": int(info.samplerate),
                "channels": int(info.channels),
                "frames": int(info.frames),
                "duration_seconds": float(info.duration),
                "tts_engine": "sherpa-onnx OfflineTts / VITS MeloTTS zh_en",
                "tts_engine_version": importlib.metadata.version("sherpa-onnx"),
                "provider": "cpu",
                "voice_profile": None,
                "speed": 1.0,
            })
    finally:
        del engine
    return results
