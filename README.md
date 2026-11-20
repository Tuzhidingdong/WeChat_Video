# WeChat_Video — Milestone 1 / Slice A

This repository is an independent local science-animation project for the WeChat Channels account 「成核生长」. The existing Tuzhidingdong/WeChat_control repository and its browser profile are outside this project and must remain untouched.

## What Slice A contains

One local, Windows-first golden path for a critical-nucleus / free-energy-barrier video:

1. Project-local Python .venv bootstrap; global Python is not modified.
2. Manim Community Edition scene in portrait 1080×1920 / 30 fps.
3. Offline English Piper VITS voice (`vits-piper-en_US-lessac-medium`) as the default; the legacy Chinese MeloTTS model is retained for rollback only.
4. Separate raw_text, display_text, and spoken_text per speech unit.
5. One WAV per speech unit, plus a pronunciation-review WAV.
6. Measured WAV sample counts and per-chunk ffprobe records.
7. One global audio_timing.json with the explicit 0–1000 ms cover.
8. Cue-checkpoint-driven Manim visual stages with mutually exclusive VGroups and a `visual_stage_manifest.json`.
9. Symmetric portrait safe-zone profile (15% margins each side) and hard subtitles (ASS/SRT) with a Latin font.
10. FFmpeg normalization, two-pass loudness measurement/application, and final MP4 QA.

The current default production script is `content/sample_script.en.json`; all narration and visible video text are English. The original Chinese script and Fact Card are retained as evidence, not as the default voice path.

This is deliberately not the full daily production product. No topic-pool manager, OpenCode authoring, Google Flow, Edge session, WeChat uploader, upload state machine, or publishing action is included in Slice A.

## First-time setup (one time)

Prerequisites on Windows:

- 64-bit Python 3.11 or 3.12.
- Project-local FFmpeg and ffprobe under `tools/ffmpeg/bin` (libass/subtitles and loudnorm required); `config/tools.local.json` is read by the code and BAT launchers.
- Project-local portable MiKTeX under `tools/miktex-portable` with `latex`, `dvisvgm`, `standalone`, `amsmath`, `amssymb`, `graphicx`, `xcolor`, `preview` installed; automatic package installation is disabled.
- A Latin font from the configured list (Arial / Segoe UI / Aptos). The preflight checks that the font file exists; actual glyph appearance still requires user inspection.

Double-click Setup_Slice_A.bat. It reuses .venv and the project-local tools, downloads the official English Piper VITS voice only if missing, then runs preflight. Models are cached under `assets/models/` and ignored by Git. The runtime performs no model downloads and has no online TTS fallback.

The default voice is `vits-piper-en_US-lessac-medium` (English US, single speaker, 22,050 Hz), distributed by sherpa-onnx:
https://github.com/k2-fsa/sherpa-onnx/releases/tag/tts-models
The earlier `vits-melo-tts-zh_en` model remains on disk for rollback but is not selected by default.

## Generate the first local review sample

Double-click Run_Slice_A.bat.

The output is written to a new timestamped folder under outputs/, containing:

- final.mp4
- fact_card.json and source_record.json
- script.json and storyboard.json
- audio/*.wav and audio/pronunciation_review.wav
- audio_manifest.json and audio_timing.json
- narration.wav
- captions.srt and captions.ass
- visual_stage_manifest.json
- environment_report.json, scene_render_manifest.json, and assembly_report.json
- qa_report.json, review_status.json, REVIEW.md, and run.log

Run_Slice_A.bat uses --review-sample because the repository's initial Fact Card is a candidate pending your review. The resulting package is explicitly marked NOT_FOR_PUBLICATION_PENDING_USER_FACT_CARD_REVIEW. It is not a Verified Topic Pool entry and must not be uploaded or published. The normal CLI path rejects an unapproved card unless the review-sample flag is explicitly supplied.

## What this prototype explains

The sample is restricted to the spherical, homogeneous classical-nucleation approximation. It uses the sign convention:

- γ > 0 is the interfacial energy.
- Δg_v > 0 is the magnitude of the bulk free-energy driving force.
- ΔG(r) = 4πr²γ − (4/3)πr³Δg_v.
- r* = 2γ/Δg_v.
- ΔG* = 16πγ³/(3Δg_v²).

The Fact Card records assumptions and limitations. The equations are not presented as universal descriptions of all real nuclei. Sources and their access status are kept in fact_cards/sources.json.

## Local acceptance is still required

The repository implementation is not proof that every dependency/model works on your specific Windows machine. In particular, the following require the real local run and your playback:

- LaTeX / dvisvgm smoke test on the installed distribution.
- sherpa-onnx Windows wheel compatibility and actual CPU inference.
- English pronunciation of the scientific terms in `audio/pronunciation_review.wav`.
- Actual Latin font glyph rendering in Manim and FFmpeg/libass.
- Visual stage transitions: no previous formula or graph remains when the next stage appears.
- 55–65 s measured duration and visual/audio synchronization.
- Phone-screen safe-zone and readability review.

Do not mark the Slice A exit condition accepted until you have watched the complete MP4 and reviewed the Fact Card. STATUS.md distinguishes code implementation from local/manual verification.

## Commands for diagnosis

From the repository root, after setup:

- .venv\Scripts\python.exe -X utf8 -m wechat_video.cli preflight
- .venv\Scripts\python.exe -X utf8 -m wechat_video.cli run-slice-a --review-sample

These are diagnostic commands only; normal sample production uses the BAT launcher.

## Safety boundary

- No paid APIs, paid model fallback, online TTS, paid Flow credits, or new hardware.
- No browser automation, cookies, user credentials, or Edge profile.
- No upload, scheduling, final-send click, or automatic publication.
- TASK_PLAN.md remains the frozen V5 authority. Implementation progress is recorded in STATUS.md.
