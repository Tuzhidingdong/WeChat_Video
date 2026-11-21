from __future__ import annotations

import json
import subprocess
import threading
import wave
from pathlib import Path

import numpy as np
import pytest

from wechat_video import media as media_module
from wechat_video.fact_card import FactCardError, load_fact_card
from wechat_video.timeline import build_audio_timeline


def _write_wav(path: Path, sample_rate: int, frames: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(b"\x00\x01" * frames)


def test_pending_fact_card_is_blocked_without_review_override(tmp_path: Path) -> None:
    card = {
        "approval_status": "DRAFT_PENDING_USER_REVIEW",
        "claims": [
            {
                "claim_id": "C1",
                "statement": "A test claim.",
                "source_ids": ["S1"],
                "evidence_status": "FULL_TEXT_LOCATED",
                "caveats": [],
            }
        ],
    }
    source_doc = {"sources": [{"source_id": "S1"}]}
    card_path = tmp_path / "card.json"
    source_path = tmp_path / "sources.json"
    card_path.write_text(json.dumps(card), encoding="utf-8")
    source_path.write_text(json.dumps(source_doc), encoding="utf-8")

    with pytest.raises(FactCardError, match="尚未获人工批准"):
        load_fact_card(card_path, source_path, allow_pending_review=False)

    loaded, _, pending = load_fact_card(
        card_path, source_path, allow_pending_review=True
    )
    assert loaded["approval_status"] == "DRAFT_PENDING_USER_REVIEW"
    assert pending is True


def test_global_timeline_has_explicit_cover_and_measured_audio(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    _write_wav(audio_dir / "U01.wav", sample_rate=44_100, frames=44_100)
    _write_wav(audio_dir / "U02.wav", sample_rate=44_100, frames=88_200)
    units = [
        {
            "unit_id": "U01",
            "raw_text": "一",
            "display_text": "一",
            "spoken_text": "一",
            "claim_ids": ["C1"],
            "visual_trigger_ids": ["A"],
        },
        {
            "unit_id": "U02",
            "raw_text": "二",
            "display_text": "二",
            "spoken_text": "二",
            "claim_ids": ["C1"],
            "visual_trigger_ids": ["B"],
        },
    ]
    timeline = build_audio_timeline(
        units,
        audio_dir=audio_dir,
        output_wav=tmp_path / "narration.wav",
        ffprobe_records={"U01": {"streams": []}, "U02": {"streams": []}},
    )

    assert timeline["cover"]["start_ms"] == 0
    assert timeline["cover"]["end_ms"] == 1000
    assert timeline["speech_units"][0]["start_sample"] == 44_100
    assert timeline["speech_units"][0]["start_ms"] == 1000
    assert timeline["speech_units"][0]["end_ms"] == 2000
    assert timeline["speech_units"][1]["start_ms"] == 2200
    assert timeline["speech_units"][1]["sample_count"] == 88_200
    assert timeline["total_duration_ms"] == 4200
    assert timeline["audio_boundary_transition"] == {
        "inter_unit_pause_ms": 200,
        "speech_edge_fade_ms": 12,
        "fade_curve": "equal_power_sine_squared",
    }
    with wave.open(str(tmp_path / "narration.wav"), "rb") as reader:
        mixed_pcm = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2")
    first_start = timeline["speech_units"][0]["start_sample"]
    first_end = timeline["speech_units"][0]["end_sample"]
    second_start = timeline["speech_units"][1]["start_sample"]
    assert mixed_pcm[first_start] == 0
    assert mixed_pcm[first_end - 1] == 0
    assert np.any(mixed_pcm[first_start + 100:first_end - 100] != 0)
    assert np.all(mixed_pcm[first_end:second_start] == 0)
    assert mixed_pcm[second_start] == 0


def test_timeline_rejects_mixed_sample_rates(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    _write_wav(audio_dir / "U01.wav", sample_rate=44_100, frames=44_100)
    _write_wav(audio_dir / "U02.wav", sample_rate=22_050, frames=22_050)
    units = [
        {
            "unit_id": "U01", "raw_text": "1", "display_text": "1",
            "spoken_text": "1", "claim_ids": ["C1"], "visual_trigger_ids": ["A"],
        },
        {
            "unit_id": "U02", "raw_text": "2", "display_text": "2",
            "spoken_text": "2", "claim_ids": ["C1"], "visual_trigger_ids": ["B"],
        },
    ]
    with pytest.raises(ValueError, match="采样率不一致"):
        build_audio_timeline(
            units,
            audio_dir=audio_dir,
            output_wav=tmp_path / "narration.wav",
            ffprobe_records={"U01": {}, "U02": {}},
        )


def test_final_video_assembly_runs_video_audio_and_mux_as_separate_stages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    scene = run_dir / "scene.mp4"
    audio = run_dir / "final_mix.wav"
    captions = run_dir / "captions.ass"
    final = run_dir / "final.mp4"
    for path in (scene, audio, captions):
        path.write_bytes(b"input")

    calls: list[tuple[str, list[str]]] = []

    def fake_stage(args, *, cwd, stage_name, progress_path, **kwargs):
        command = [str(item) for item in args]
        calls.append((stage_name, command))
        output = Path(command[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"x" * 2048)
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text("frame=10\nout_time_us=1000000\nprogress=end\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "progress=end\n", "")

    monkeypatch.setattr(media_module, "_run_ffmpeg_stage", fake_stage)
    monkeypatch.setattr(
        media_module,
        "_loudnorm_measurement",
        lambda *_args: {
            "measured_I": "-20.0",
            "measured_TP": "-3.0",
            "measured_LRA": "4.0",
            "measured_thresh": "-30.0",
            "offset": "0.0",
        },
    )
    monkeypatch.setattr(media_module, "resolve_command", lambda name: f"fake-{name}")
    monkeypatch.setattr(media_module, "_cfr_flag", lambda _exe: ["-fps_mode", "cfr"])

    config = {
        "preset_id": "test-preset",
        "final_programme": {
            "integrated_lufs": -16.0,
            "true_peak_dbtp": -1.5,
            "codec": "aac",
            "bitrate_kbps": 192,
            "sample_rate": 44100,
            "channels": 1,
        },
    }
    report = media_module.assemble_final_video(
        scene,
        audio,
        captions,
        final,
        run_dir,
        expected_frames=1800,
        config=config,
    )

    assert [name for name, _ in calls] == [
        "video_encode",
        "audio_normalize",
        "final_mux",
    ]
    video_command = calls[0][1]
    audio_command = calls[1][1]
    mux_command = calls[2][1]

    assert "-vf" in video_command and "-af" not in video_command
    assert "libx264" in video_command
    assert video_command[video_command.index("-preset") + 1] == "medium"
    assert video_command[video_command.index("-crf") + 1] == "19"
    assert video_command[video_command.index("-frames:v") + 1] == "1800"

    assert "-af" in audio_command and "loudnorm=I=-16.0:TP=-1.5:LRA=11:print_format=summary" in audio_command
    assert "-vf" not in audio_command and "-vn" in audio_command
    assert audio_command[audio_command.index("-c:a") + 1] == "aac"

    assert "-c" in mux_command and mux_command[mux_command.index("-c") + 1] == "copy"
    assert "-shortest" in mux_command
    assert "-vf" not in mux_command and "-af" not in mux_command
    assert final.is_file() and final.stat().st_size == 2048
    assert report["assembly_mode"] == (
        "separate_video_encode_audio_normalize_then_stream_copy_mux"
    )
    assert report["loudnorm_pass"] == "single_pass_full_programme_audio_only_stage"
    assert [stage["stage"] for stage in report["stages"]] == [
        "video_encode",
        "audio_normalize",
        "final_mux",
    ]


def test_ffmpeg_stage_watchdog_terminates_process_without_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BlockingStdout:
        def __init__(self):
            self.closed = threading.Event()

        def __iter__(self):
            return self

        def __next__(self):
            self.closed.wait()
            raise StopIteration

        def close(self):
            self.closed.set()

    class StalledProcess:
        def __init__(self):
            self.stdout = BlockingStdout()
            self.returncode = None
            self.terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15
            self.stdout.close()

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9
            self.stdout.close()

    fake_process = StalledProcess()
    monkeypatch.setattr(
        media_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: fake_process,
    )
    progress = tmp_path / "video.progress.txt"

    with pytest.raises(
        media_module.ExternalProcessError,
        match="no FFmpeg progress",
    ):
        media_module._run_ffmpeg_stage(
            ["fake-ffmpeg", "-y", str(tmp_path / "video.mp4")],
            cwd=tmp_path,
            stage_name="video_encode",
            progress_path=progress,
            timeout_seconds=1,
            stall_timeout_seconds=0.01,
        )

    assert fake_process.terminated is True
    assert progress.is_file()
    assert progress.read_text(encoding="utf-8") == ""



def test_sfx_edge_fade_reaches_zero_without_changing_clip_duration() -> None:
    source = np.ones(100, dtype=np.float64)
    faded = media_module._fade_audio_edges(source, sample_rate=1000, fade_ms=15)
    assert len(faded) == len(source)
    assert faded[0] == pytest.approx(0.0)
    assert faded[-1] == pytest.approx(0.0)
    assert faded[15] == pytest.approx(1.0)
    assert faded[-16] == pytest.approx(1.0)
