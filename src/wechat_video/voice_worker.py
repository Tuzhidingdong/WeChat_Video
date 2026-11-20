"""Isolated OpenVoice V2 + MeloTTS EN-US worker (run with .venv-voice Python).

This module is intentionally independent of the Manim .venv. It performs:
  - CPU feasibility preflight
  - one-time personal voice enrollment from the user's local recording
  - per-speech-unit MeloTTS EN-US base synthesis + OpenVoice tone conversion

No online TTS, no CUDA, no upload. All model/cache paths stay under the project.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache"
for _key, _value in (
    ("HF_HOME", CACHE / "hf"),
    ("HUGGINGFACE_HUB_CACHE", CACHE / "hf" / "hub"),
    ("TORCH_HOME", CACHE / "torch"),
    ("NLTK_DATA", CACHE / "nltk_data"),
    ("TEMP", CACHE / "temp"),
    ("TMP", CACHE / "temp"),
):
    os.environ.setdefault(_key, str(_value))
for _dir in (CACHE / "temp", CACHE / "hf" / "hub", CACHE / "nltk_data"):
    _dir.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "tools" / "voice_shims"))

OV_ROOT = ROOT / "tools" / "openvoice" / "checkpoints_v2"
CONVERTER_DIR = OV_ROOT / "converter"
SRC_SE_PATH = OV_ROOT / "base_speakers" / "ses" / "en-us.pth"
MELO_DIR = ROOT / "assets" / "models" / "melo-en-us"
PROFILE_DIR = ROOT / "private" / "voice_profile"
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
DEFAULT_REFERENCE = ROOT / "my_voice" / "voice.m4a"
AB_TEXT = "The critical radius separates growth from dissolution."

ENROLLMENT_SCHEMA = "slice-a-voice-profile-v1"
MODEL_REVISION = "OpenVoiceV2-myshell-ai/converter-9652c27e+MeloEN-acd27804"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _wav_info(path: Path) -> dict[str, Any]:
    import soundfile as sf

    info = sf.info(str(path))
    return {
        "path": str(path.relative_to(ROOT)),
        "sample_rate": int(info.samplerate),
        "channels": int(info.channels),
        "frames": int(info.frames),
        "duration_seconds": round(float(info.duration), 4),
    }


def _load_converter():
    import torch
    from openvoice.api import ToneColorConverter

    converter = ToneColorConverter(str(CONVERTER_DIR / "config.json"), device="cpu")
    converter.load_ckpt(str(CONVERTER_DIR / "checkpoint.pth"))
    return converter


def _load_melo():
    from melo.api import TTS

    model = TTS(
        language="EN",
        device="cpu",
        config_path=str(MELO_DIR / "config.json"),
        ckpt_path=str(MELO_DIR / "checkpoint.pth"),
    )
    return model


def _base_speaker_choice(model) -> tuple[str, int]:
    ids = dict(model.hps.data.spk2id)
    for key in ("EN-US", "en-US", "EN_US", "EN"):
        if key in ids:
            return key, int(ids[key])
    for key, value in ids.items():
        if "EN" in str(key).upper():
            return str(key), int(value)
    raise RuntimeError(f"No EN-US speaker found in MeloTTS spk2id: {ids}")


def _fingerprint(reference: Path) -> str:
    payload = "|".join(
        [
            ENROLLMENT_SCHEMA,
            MODEL_REVISION,
            _sha256(reference),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cmd_preflight(args: argparse.Namespace) -> int:
    import torch

    print("python", sys.version.split()[0])
    print("torch", torch.__version__)
    import torchaudio

    print("torchaudio", torchaudio.__version__)
    import librosa, soundfile

    print("librosa", librosa.__version__, "soundfile", soundfile.__version__)
    import openvoice

    print("openvoice", Path(openvoice.__file__).parent)
    import melo

    print("melo", Path(melo.__file__).parent)
    for path in (
        CONVERTER_DIR / "config.json",
        CONVERTER_DIR / "checkpoint.pth",
        SRC_SE_PATH,
        MELO_DIR / "config.json",
        MELO_DIR / "checkpoint.pth",
    ):
        if not path.is_file():
            raise RuntimeError(f"Missing model file: {path}")
        print("model", path.relative_to(ROOT), path.stat().st_size)
    converter = _load_converter()
    print("converter loaded; version", converter.version, "watermark", converter.watermark_model is not None)
    model = _load_melo()
    print("melo spk2id", dict(model.hps.data.spk2id))
    print("PREFLIGHT_OK")
    return 0


def _convert_reference(reference: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not reference.is_file():
        raise RuntimeError(f"Reference recording not found: {reference}")
    subprocess.run(
        [
            str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(reference),
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            str(target),
        ],
        check=True,
    )
    info = _wav_info(target)
    if info["duration_seconds"] < 20:
        raise RuntimeError(f"Reference audio too short: {info['duration_seconds']}s")
    print("reference_wav", json.dumps(info, ensure_ascii=False))


def _vad_segments_local(audio, sample_rate=16000, output_sample=True, **kwargs):
    """Offline energy-based VAD used instead of whisper-timestamped's VAD.

    The installed whisper-timestamped 1.14.2 hardcodes ``~/.cache/torch`` and a
    POSIX symlink trick that fails on Windows. This replacement keeps the
    ``se_extractor.get_se(vad=True)`` call path while remaining fully local and
    CPU-only. It returns speech intervals in samples, as expected by OpenVoice.
    """
    import numpy as np
    import torch

    values = audio.detach().cpu().numpy() if torch.is_tensor(audio) else np.asarray(audio)
    values = np.asarray(values, dtype=np.float32).reshape(-1)
    frame = max(1, int(0.02 * sample_rate))
    count = len(values) // frame
    if count == 0:
        return [{"start": 0, "end": len(values)}]
    frames = values[: count * frame].reshape(count, frame)
    rms = np.sqrt(np.mean(frames**2, axis=1))
    threshold = max(0.004, 0.08 * float(rms.max()))
    speech = rms > threshold
    min_silence_frames = int(0.5 / 0.02)
    start = None
    segments: list[dict[str, int]] = []
    for index, active in enumerate(speech):
        if active and start is None:
            start = index
        elif not active and start is not None:
            if index - start < min_silence_frames:
                continue
            segments.append({"start": start * frame, "end": index * frame})
            start = None
    if start is not None:
        segments.append({"start": start * frame, "end": count * frame})
    if not segments:
        segments = [{"start": 0, "end": count * frame}]
    return segments


def cmd_enroll(args: argparse.Namespace) -> int:
    reference = Path(args.reference)
    fingerprint = _fingerprint(reference)
    profile_json = PROFILE_DIR / "voice_profile.json"
    target_se = PROFILE_DIR / "target_se.pth"

    if profile_json.is_file() and target_se.is_file():
        existing = json.loads(profile_json.read_text(encoding="utf-8"))
        if existing.get("fingerprint") == fingerprint and not args.force:
            print("REUSING_EXISTING_PROFILE", existing.get("fingerprint"))
            return 0

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    ref_wav = PROFILE_DIR / "reference_input.wav"
    _convert_reference(reference, ref_wav)

    converter = _load_converter()
    import torch
    import importlib

    wt_module = importlib.import_module("whisper_timestamped.transcribe")
    wt_module.get_vad_segments = _vad_segments_local
    from openvoice import se_extractor

    started = time.time()
    target_embedding, audio_name = se_extractor.get_se(
        str(ref_wav), converter, vad=True, target_dir=str(PROFILE_DIR / "processed")
    )
    torch.save(target_embedding.cpu(), str(target_se))
    extraction_seconds = round(time.time() - started, 3)

    source_se = torch.load(str(SRC_SE_PATH), map_location="cpu")
    model = _load_melo()
    speaker_key, speaker_id = _base_speaker_choice(model)
    base_path = PROFILE_DIR / "ab_base_en_us.wav"
    cloned_path = PROFILE_DIR / "ab_user_voice_en.wav"
    model.tts_to_file(AB_TEXT, speaker_id, str(base_path), speed=1.0)
    converter.convert(
        audio_src_path=str(base_path),
        src_se=source_se,
        tgt_se=target_embedding,
        output_path=str(cloned_path),
        message="@MyShell",
    )

    metadata = {
        "schema": ENROLLMENT_SCHEMA,
        "fingerprint": fingerprint,
        "model_revision": MODEL_REVISION,
        "embedding_file": target_se.name,
        "base_speaker": speaker_key,
        "reference_wav": _wav_info(ref_wav),
        "ab_base": _wav_info(base_path),
        "ab_cloned": _wav_info(cloned_path),
        "extraction_seconds": extraction_seconds,
        "se_audio_name": audio_name,
        "watermark_preserved": True,
    }
    profile_json.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (PROFILE_DIR / "enrollment.log").write_text(
        f"enrollment fingerprint={fingerprint} seconds={extraction_seconds} status=PASS\n",
        encoding="utf-8",
    )
    print("ENROLLMENT_OK", json.dumps(metadata, ensure_ascii=False))
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    import torch

    profile_json = PROFILE_DIR / "voice_profile.json"
    target_se_path = PROFILE_DIR / "target_se.pth"
    if not profile_json.is_file() or not target_se_path.is_file():
        raise RuntimeError("Voice profile missing; run enrollment first.")
    profile = json.loads(profile_json.read_text(encoding="utf-8"))

    script_path = Path(args.script)
    out_dir = Path(args.out)
    base_dir = out_dir / "base_melotts"
    converted_dir = out_dir / "converted_user_voice"
    base_dir.mkdir(parents=True, exist_ok=True)
    converted_dir.mkdir(parents=True, exist_ok=True)

    converter = _load_converter()
    source_se = torch.load(str(SRC_SE_PATH), map_location="cpu")
    target_se = torch.load(str(target_se_path), map_location="cpu")
    model = _load_melo()
    speaker_key, speaker_id = _base_speaker_choice(model)

    script = json.loads(script_path.read_text(encoding="utf-8"))
    if not script.get("speech_units"):
        raise RuntimeError("No speech units in the script; refusing to generate an empty voice track.")
    results: list[dict[str, Any]] = []
    for unit in script["speech_units"]:
        unit_id = unit["unit_id"]
        text = unit["spoken_text"]
        base_path = base_dir / f"{unit_id}.wav"
        final_path = converted_dir / f"{unit_id}.wav"
        t0 = time.time()
        model.tts_to_file(text, speaker_id, str(base_path), speed=1.0)
        t1 = time.time()
        converter.convert(
            audio_src_path=str(base_path),
            src_se=source_se,
            tgt_se=target_se,
            output_path=str(final_path),
            message="@MyShell",
        )
        t2 = time.time()
        info = _wav_info(final_path)
        results.append(
            {
                "unit_id": unit_id,
                "spoken_text": text,
                "base_wav": str(base_path.relative_to(ROOT)),
                "final_wav": str(final_path.relative_to(ROOT)),
                **info,
                "base_generation_seconds": round(t1 - t0, 3),
                "conversion_seconds": round(t2 - t1, 3),
                "total_seconds": round(t2 - t0, 3),
                "voice_profile_fingerprint": profile["fingerprint"],
                "base_speaker": speaker_key,
            }
        )
        print("UNIT_DONE", unit_id, info["duration_seconds"])

    review_text = script["pronunciation_review_text"]
    base_review = base_dir / "pronunciation_review.wav"
    final_review = converted_dir / "pronunciation_review.wav"
    model.tts_to_file(review_text, speaker_id, str(base_review), speed=1.0)
    converter.convert(
        audio_src_path=str(base_review),
        src_se=source_se,
        tgt_se=target_se,
        output_path=str(final_review),
        message="@MyShell",
    )

    manifest = {
        "schema_version": 1,
        "engine": "MeloTTS EN-US -> OpenVoice V2 ToneColorConverter (CPU)",
        "voice_profile_fingerprint": profile["fingerprint"],
        "base_speaker": speaker_key,
        "watermark_preserved": True,
        "units": results,
        "pronunciation_review": _wav_info(final_review),
    }
    (out_dir / "voice_generation_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("VOICE_GENERATION_OK", out_dir)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wechat-video-voice-worker")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight")
    enroll = sub.add_parser("enroll")
    enroll.add_argument("--reference", default=str(DEFAULT_REFERENCE))
    enroll.add_argument("--force", action="store_true")
    generate = sub.add_parser("generate")
    generate.add_argument("--script", default=str(ROOT / "content" / "sample_script.en.json"))
    generate.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "preflight":
        return cmd_preflight(args)
    if args.command == "enroll":
        return cmd_enroll(args)
    if args.command == "generate":
        return cmd_generate(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
