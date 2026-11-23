from __future__ import annotations

import argparse
import asyncio
import base64
import importlib.metadata
import json
import os
import random
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

SEED_VOICE_ID = "multi_female_zhixingnv_v3_uranus_bigtts"
SEED_MODEL_ID = "doubao-seed-tts-3.0"
SEED_INSTRUCTION = (
    "使用自然、清晰、克制的普通话科研科普讲解语气；"
    "开场有适度好奇感，疑问句自然上扬，专业内容准确清楚，"
    "停顿自然，不要夸张播音腔，不要机械匀速朗读。"
)


class BenchmarkError(RuntimeError):
    pass


def load_benchmark() -> dict[str, Any]:
    path = Path(__file__).with_name("benchmark_text.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    clips = data.get("clips")
    if not isinstance(clips, list) or len(clips) < 4:
        raise BenchmarkError("benchmark_text.json must contain at least four clips.")
    ids = [str(item.get("id") or "") for item in clips]
    if any(not item for item in ids) or len(ids) != len(set(ids)):
        raise BenchmarkError("Clip IDs must be non-empty and unique.")
    if any(not str(item.get("text") or "").strip() for item in clips):
        raise BenchmarkError("Every benchmark clip requires non-empty text.")
    return data


def run_checked(args: list[str]) -> None:
    result = subprocess.run(
        args,
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        shell=False,
    )
    if result.returncode != 0:
        raise BenchmarkError(
            f"Command failed ({result.returncode}): {args[0]}\n{result.stdout[-3000:]}"
        )


def ffmpeg_path() -> str:
    from wechat_video.tooling import resolve_command
    return resolve_command("ffmpeg", ROOT)


def generate_melo(clips: list[dict[str, Any]], raw_dir: Path) -> dict[str, Any]:
    from wechat_video.tooling import legacy_model_root
    from wechat_video.tts import generate_chinese_speech_units

    units = [
        {"unit_id": str(item["id"]), "spoken_text": str(item["text"])}
        for item in clips
    ]
    results = generate_chinese_speech_units(
        legacy_model_root(ROOT), units, raw_dir
    )
    return {
        "engine": "sherpa-onnx / VITS MeloTTS zh_en",
        "version": importlib.metadata.version("sherpa-onnx"),
        "provider": "cpu",
        "files": {str(item["unit_id"]): str(item["audio_file"]) for item in results},
    }


def generate_edge(clips: list[dict[str, Any]], raw_dir: Path) -> dict[str, Any]:
    try:
        import edge_tts
    except ImportError as exc:
        raise BenchmarkError(
            "edge-tts is not installed in the project .venv; optional candidate skipped."
        ) from exc

    voice = "zh-CN-XiaoxiaoNeural"

    async def generate_all() -> dict[str, str]:
        files: dict[str, str] = {}
        for item in clips:
            clip_id = str(item["id"])
            target = raw_dir / f"{clip_id}.mp3"
            communicate = edge_tts.Communicate(
                str(item["text"]),
                voice=voice,
                rate="+0%",
                volume="+0%",
                pitch="+0Hz",
            )
            await communicate.save(str(target))
            if not target.is_file() or target.stat().st_size < 1024:
                raise BenchmarkError(f"Edge-TTS produced an empty/short file for {clip_id}.")
            files[clip_id] = str(target)
        return files

    files = asyncio.run(generate_all())
    try:
        version = importlib.metadata.version("edge-tts")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    return {
        "engine": "Edge-TTS / zh-CN-XiaoxiaoNeural",
        "version": version,
        "provider": "Microsoft online endpoint via edge-tts community client",
        "files": files,
    }


def generate_seed_tts(clips: list[dict[str, Any]], raw_dir: Path) -> dict[str, Any]:
    api_key = os.environ.get("VOLCENGINE_TTS_API_KEY", "").strip()
    if not api_key:
        raise BenchmarkError(
            "VOLCENGINE_TTS_API_KEY is not set; Seed-TTS 3.0 candidate skipped."
        )

    files: dict[str, str] = {}
    for item in clips:
        clip_id = str(item["id"])
        url = (
            "https://voice.cn-beijing.volces.com/api/v3/text-to-speech/"
            + SEED_VOICE_ID
            + "/streaming"
        )
        payload = {
            "text": str(item["text"]),
            "model_id": SEED_MODEL_ID,
            "language_code": "zh-CN",
            "output_format": {
                "format": "mp3",
                "sample_rate": 24000,
                "bit_rate": 64000,
            },
            "voice_settings": {
                "speed": 1.0,
                "volume": 1.0,
                "pitch": 0,
                "instructions": [SEED_INSTRUCTION],
            },
            "text_normalization": True,
            "enable_subtitle": False,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "X-Api-Key": api_key,
                "Content-Type": "application/json",
                "X-Request-Id": str(uuid.uuid4()),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                response_text = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read(2048).decode("utf-8", errors="replace")
            raise BenchmarkError(
                f"Seed-TTS HTTP {exc.code}; response={detail[:1000]}"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise BenchmarkError(f"Seed-TTS network error: {exc}") from exc

        audio_chunks: list[bytes] = []
        for line in response_text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") == "audio" and event.get("audio"):
                audio_chunks.append(base64.b64decode(event["audio"]))
            elif event.get("event") == "error":
                info = event.get("error") or {}
                raise BenchmarkError(
                    "Seed-TTS returned an error: "
                    + str(info.get("code") or info.get("message") or "unknown error")
                )
        if not audio_chunks:
            raise BenchmarkError(f"Seed-TTS returned no audio for {clip_id}.")
        target = raw_dir / f"{clip_id}.mp3"
        target.write_bytes(b"".join(audio_chunks))
        if target.stat().st_size < 1024:
            raise BenchmarkError(f"Seed-TTS output is unexpectedly small for {clip_id}.")
        files[clip_id] = str(target)

    return {
        "engine": "Volcengine Seed-TTS 3.0 / 知性女声 3.0",
        "version": SEED_MODEL_ID,
        "provider": "Volcengine cloud API",
        "files": files,
        "instructions": SEED_INSTRUCTION,
        "voice_id": SEED_VOICE_ID,
    }


def convert_to_pcm(source: Path, target: Path, ffmpeg: str) -> None:
    run_checked([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-map_metadata", "-1",
        "-vn", "-ac", "1", "-ar", "44100",
        "-c:a", "pcm_s16le", str(target),
    ])


def combine_segments(
    segment_paths: list[Path],
    destination: Path,
    pause_ms: int,
) -> None:
    if not segment_paths:
        raise BenchmarkError("No normalized segment WAVs to combine.")
    silence_frames = round(44100 * pause_ms / 1000)
    silence = b"\x00\x00" * silence_frames
    with wave.open(str(destination), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(44100)
        output.setcomptype("NONE", "not compressed")
        for index, path in enumerate(segment_paths):
            with wave.open(str(path), "rb") as segment:
                params = segment.getparams()
                if (
                    params.nchannels != 1
                    or params.sampwidth != 2
                    or params.framerate != 44100
                    or params.comptype != "NONE"
                ):
                    raise BenchmarkError(f"Unexpected PCM format in {path.name}: {params}")
                output.writeframes(segment.readframes(params.nframes))
            if index != len(segment_paths) - 1:
                output.writeframes(silence)


def normalize_combined(source: Path, target: Path, ffmpeg: str) -> None:
    run_checked([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source),
        "-af", "loudnorm=I=-20:TP=-2:LRA=7",
        "-map_metadata", "-1",
        "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le",
        str(target),
    ])


def duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        return audio.getnframes() / audio.getframerate()


def build_candidate(
    candidate_name: str,
    engine_info: dict[str, Any],
    clips: list[dict[str, Any]],
    output_dir: Path,
    ffmpeg: str,
    pause_ms: int,
) -> Path:
    raw_map = engine_info["files"]
    normalized_dir = output_dir / "_internal" / "normalized" / candidate_name
    normalized_dir.mkdir(parents=True, exist_ok=False)
    segment_paths: list[Path] = []
    for item in clips:
        clip_id = str(item["id"])
        source = Path(raw_map[clip_id])
        target = normalized_dir / f"{clip_id}.wav"
        convert_to_pcm(source, target, ffmpeg)
        segment_paths.append(target)

    joined = output_dir / "_internal" / f"{candidate_name}_joined.wav"
    combine_segments(segment_paths, joined, pause_ms)
    normalized = output_dir / "_internal" / f"{candidate_name}_normalized.wav"
    normalize_combined(joined, normalized, ffmpeg)
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate blinded Chinese scientific TTS samples."
    )
    parser.add_argument(
        "--output", required=True,
        help="New local output directory; must not exist."
    )
    args = parser.parse_args()

    output_dir = Path(args.output)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise BenchmarkError(
            f"Refusing to overwrite existing output directory: {output_dir}"
        )

    benchmark = load_benchmark()
    clips = benchmark["clips"]
    pause_ms = int(benchmark.get("pause_between_clips_ms", 550))
    output_dir.mkdir(parents=True, exist_ok=False)
    listen_dir = output_dir / "listen"
    internal_dir = output_dir / "_internal"
    raw_root = internal_dir / "raw"
    listen_dir.mkdir()
    raw_root.mkdir(parents=True)

    ffmpeg = ffmpeg_path()
    candidates: list[tuple[str, dict[str, Any]]] = []
    failures: dict[str, str] = {}

    try:
        melo_dir = raw_root / "melo"
        melo_dir.mkdir()
        melo_info = generate_melo(clips, melo_dir)
        candidates.append(("melo_baseline", melo_info))
    except Exception as exc:
        raise BenchmarkError(
            f"Current MeloTTS baseline failed: {type(exc).__name__}: {exc}"
        ) from exc

    try:
        edge_dir = raw_root / "edge"
        edge_dir.mkdir()
        edge_info = generate_edge(clips, edge_dir)
        candidates.append(("edge_tts", edge_info))
    except Exception as exc:
        failures["edge_tts"] = f"{type(exc).__name__}: {exc}"

    if os.environ.get("VOLCENGINE_TTS_API_KEY", "").strip():
        try:
            seed_dir = raw_root / "seed_tts"
            seed_dir.mkdir()
            seed_info = generate_seed_tts(clips, seed_dir)
            candidates.append(("seed_tts_3", seed_info))
        except Exception as exc:
            failures["seed_tts_3"] = f"{type(exc).__name__}: {exc}"
    else:
        failures["seed_tts_3"] = (
            "skipped: VOLCENGINE_TTS_API_KEY is not configured"
        )

    if len(candidates) < 2:
        report = {
            "status": "INSUFFICIENT_CANDIDATES",
            "candidate_count": len(candidates),
            "failures": failures,
            "note": "At least two complete candidates are required for blind listening.",
        }
        (internal_dir / "generation_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        raise BenchmarkError(
            "Only the baseline completed. Install optional edge-tts in the project .venv "
            "or configure VOLCENGINE_TTS_API_KEY; see the generation report."
        )

    built: list[tuple[str, str, Path]] = []
    details_by_name: dict[str, dict[str, Any]] = {}
    for internal_name, info in candidates:
        combined = build_candidate(
            internal_name, info, clips, output_dir, ffmpeg, pause_ms
        )
        built.append((internal_name, info["engine"], combined))
        details_by_name[internal_name] = {
            key: value for key, value in info.items() if key != "files"
        }

    random.SystemRandom().shuffle(built)
    public_rows: list[dict[str, Any]] = []
    answer_key: dict[str, Any] = {
        "warning": "Do not open until the user has completed blind listening and chosen a preferred sample.",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mapping": {},
        "engine_details": {},
    }
    for index, (internal_name, _engine_label, combined) in enumerate(built):
        blind_label = chr(ord("A") + index)
        target = listen_dir / f"{blind_label}.wav"
        shutil.copy2(combined, target)
        public_rows.append({
            "label": blind_label,
            "duration_seconds": round(duration_seconds(target), 3),
            "file": f"listen/{blind_label}.wav",
            "format": "WAV / PCM16 / mono / 44.1 kHz",
        })
        answer_key["mapping"][blind_label] = internal_name
        answer_key["engine_details"][internal_name] = details_by_name[internal_name]

    key_path = internal_dir / "answer_key.json"
    key_path.write_text(
        json.dumps(answer_key, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = {
        "status": "READY_FOR_BLIND_LISTENING",
        "candidate_count": len(built),
        "samples": public_rows,
        "skipped_or_failed": failures,
        "normalization": "One full-track loudnorm pass per candidate: -20 LUFS / -2 dBTP target",
        "music_or_sfx": False,
        "source_text_identical": True,
    }
    (output_dir / "blind_manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "LISTENING_SCORECARD.md").write_text(
        "# TTS 盲听评分卡\n\n"
        "请先听完全部样本，再填写分数。此时不要打开 _internal/answer_key.json。\n\n"
        "| 维度（1–5 分） | A | B | C |\n"
        "|---|---:|---:|---:|\n"
        "| 句首完整，没有吞掉第一个字 | | | |\n"
        "| 普通话发音和多音字正确 | | | |\n"
        "| 专业术语清楚 | | | |\n"
        "| 中英文混读自然 | | | |\n"
        "| 反问句、疑问句有自然语调 | | | |\n"
        "| 长句连读与停顿自然 | | | |\n"
        "| 整体不机械、不疲劳 | | | |\n"
        "| 综合偏好 | | | |\n\n"
        "请另外记录：最明显的错读词、最喜欢的片段、最不能接受的问题。\n"
        "若本次只有两个候选，只填写 A、B。\n",
        encoding="utf-8",
    )
    (output_dir / "TRANSCRIPT.txt").write_text(
        "\n\n".join(
            f"{index + 1:02d}. {item['text']}"
            for index, item in enumerate(clips)
        ) + "\n",
        encoding="utf-8",
    )
    (internal_dir / "generation_report.json").write_text(
        json.dumps({
            "status": "complete",
            "engines": [
                {
                    "internal_name": name,
                    "engine": info["engine"],
                    "version": info.get("version"),
                    "provider": info.get("provider"),
                }
                for name, info in candidates
            ],
            "failures": failures,
            "answer_key_path": str(key_path),
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Blind-listening assets ready: {listen_dir}")
    print(f"Candidate count: {len(built)}")
    for row in public_rows:
        print(f"{row['label']}: {row['duration_seconds']:.2f}s | {row['file']}")
    if failures:
        print("Optional candidates skipped/failed; details are in _internal/generation_report.json.")
    print("Do not open _internal/answer_key.json until the user has rated the samples.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BenchmarkError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
