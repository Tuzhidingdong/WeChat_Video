# Slice A progress snapshot — 2026-11-21

Scope: Milestone 1 / Slice A of WeChat_Video. This snapshot records the state at
branch `feat/slice-a-english-visual-refinement`, local HEAD before this sync commit
`a4b27489a69b29250fc788b2a68ba544dba40350`, which was equal to the GitHub target
branch (0 ahead / 0 behind) at inventory time. Draft PR #2 remains open as a draft.

No new feature work, video regeneration, or functional change is part of this sync.

Frozen authority: `TASK_PLAN.md` (V5) is unchanged. This document does not authorize
Slice B, Milestone 2, or Milestone 3.

## 1. Implemented with real run evidence

- **Project-local toolchain**: `.venv` (Python 3.12.4), portable MiKTeX 25.12 with
  `latex`, `dvisvgm`, required LaTeX packages and `AutoInstall=0`; project FFmpeg 9.1
  with libass/loudnorm/libx264/AAC; `config/tools.local.json` is gitignored and used
  by the code/BAT launchers. Real preflight run: `all_preflight: PASS`.
- **Offline TTS adapters**: sherpa-onnx 1.13.8 with legacy MeloTTS zh_en and Piper
  en_US models (both retained on disk); real CPU inference was produced earlier for
  both, but these are no longer the daily voice.
- **Personal English voice enrollment**: isolated `.venv-voice` (Python 3.9.23,
  CPU torch 2.1.2). OpenVoice V2 converter loaded with watermark enabled;
  MeloTTS EN-US speaker `EN-US` (id 0) loaded. Real enrollment ran from the user's
  authorized local recording: VAD-based segmentation, real speaker embedding
  extraction, saved private `target_se.pth`, and A/B English samples. Fingerprint
  `33b0549a087fb6698bc8a5b651f8ca5de4fda387ba9c29a224de5d699da76745`.
- **Daily voice pipeline**: each English speech unit is generated as
  MeloTTS EN-US base WAV → OpenVoice V2 conversion with the saved profile → final
  WAV. The converted WAV is authoritative for the global timeline. The profile is
  not re-extracted on later runs.
- **English-only video content**: `content/sample_script.en.json` is the default;
  all visible text in the rendered MP4 is English. Verified captions contain no CJK.
- **Framing and visual stages**: symmetric 15% side margins, x=0 centered content,
  static portrait camera; 8 mutually exclusive visual stages with
  `visual_stage_manifest.json`. Earlier formula stacking and horizontal offset were
  re-rendered and checked against extracted MP4 frames.
- **Full local rendering**: real Manim + FFmpeg run produced a complete MP4. Latest
  run: 60.8 s, 1080×1920, 30 fps CFR, yuv420p, SAR 1:1, H.264/AAC; QA `PASS`.
- **Tests**: last full `pytest -q` run: **12 passed**.

## 2. Implemented but not fully verified by real execution

- **English pronunciation quality**: EN-US base speaker is selected and real WAVs
  exist, but intelligibility/naturalness of the converted voice has not been judged
  by listening. The user must compare A/B samples.
- **Personal voice similarity**: embedding extraction and conversion succeeded
  technically; similarity to the user's voice is not claimed without user listening.
- **Caption readability on a phone**: English captions are technically correct, no
  CJK, and whole-word wrapped; manual phone-screen review is still pending.
- **Scientific review**: the Fact Card remains `DRAFT_PENDING_USER_REVIEW`; the video
  is marked `NOT_FOR_PUBLICATION_PENDING_USER_FACT_CARD_REVIEW`.

## 3. Partially implemented

- **Audio cleanup / denoising**: there is no dedicated denoiser module. The source
  recording was converted locally to 16 kHz mono WAV, long silences were removed by
  VAD segmentation, and TTS/conversion ran offline. Source-level clipping/noise
  remains (see known issues).
- **Visual motion**: the template is static-camera by design. Stages transition via
  FadeIn/FadeOut. Between transitions, most frames are static holds; no camera pan,
  zoom, particle-level animation, or continuous motion was added.
- **Upstream tracking**: local branch pushes use explicit `origin HEAD:refs/heads/...`;
  a conventional remote-tracking upstream is not configured for this branch. This is
  cosmetic and did not block fetch/push.

## 4. Not implemented (out of this snapshot's scope)

- Slice B template library, camera-aware moving-camera safe zones, Flow integration,
  WeChat Channels upload, Edge/CDP session reuse, daily integrated BAT, kernel mutex,
  topic pool, or any publication/scheduling path.
- No automatic YouTube/online TTS fallback exists by design; the pipeline fails if
  the private voice profile is absent.

## 5. Known issues, failures, and blockers

- Source M4A analysis showed peak level near 0 dBFS (possible light clipping) and a
  low mean level. Conversion succeeded; no perceptual denoise step was applied.
  Whether cloned speech sounds noisy must be judged by listening.
- Personal voice similarity and standard-American-English naturalness are targets,
  not verified outcomes. User listening approval is required.
- The first personal-voice render measured 70.39 s (outside 55–65 s). English wording
  was tightened without dropping claims/caveats; the final render measured 60.8 s.
  No speed change, time stretch, silence padding, or frame duplication was used.
- `faster-whisper==0.9.0` could not be installed on Python 3.9 Windows because
  `av==10` failed to build. The CUDA Whisper path is disabled; a local shim satisfies
  the import. `whisper-timestamped==1.14.2` hardcodes a user-profile Torch cache and
  a POSIX symlink hack, so an offline energy-based VAD function is monkeypatched into
  `se_extractor.get_se(..., vad=True)`. All caches stay inside the project.
- NumPy 2 was initially pulled in by `openai-whisper` and broke Torch 2.1.2; pinned
  back to NumPy 1.26.4. Python 3.9 produces upstream end-of-life warnings.
- FACT Card scientific approval, final playback acceptance, and the user's own
  `Run_Slice_A.bat` run are still pending.

## 6. Reproducible local environment and tool versions

| Component | Version |
|---|---|
| Manim runtime Python | 3.12.4 (`.venv`) |
| Manim / sherpa-onnx | 0.22.1 / 1.13.8 |
| Voice runtime Python | 3.9.23 (`.venv-voice`, project-local conda env) |
| torch / torchaudio | 2.1.2+cpu / 2.1.2+cpu |
| numpy / scipy / librosa | 1.26.4 / 1.13.1 / 0.9.1 |
| transformers / whisper-timestamped | 4.27.4 / 1.14.2 |
| FFmpeg / ffprobe | 9.1-essentials_build-www.gyan.dev |
| MiKTeX / pdfTeX / dvisvgm | 25.12 Portable / 4.23 / 3.4.3 |
| OpenVoice / MeloTTS | myshell-ai OpenVoice V2 / MeloTTS EN-US |
| Pinned voice dependencies | `requirements-voice.txt` |
| Model provenance | `docs/VOICE_RUNTIME_RECORD.md` |

## 7. Latest sample and QA result (metadata only; artifacts not committed)

Latest run directory: `outputs/20261121_001026_critical_nucleus/` (gitignored).

- `final.mp4`: 2,022,445 bytes; SHA-256
  `cf16faa1ad659383a9463619c764aa6edb21e44f07bc0f028c7c0ce23c43ff3f`.
- Duration 60.8 s; 1824 frames; 1080×1920; 30/1 fps; yuv420p; SAR 1:1.
- Audio: AAC, 44.1 kHz, mono, 60.719 s.
- `qa_report.json`: `overall_status: PASS`; no WARN or FAIL items.
- `visual_stage_manifest.json`: 8 stages, unique active stage per cue.
- `voice_generation_manifest.json`: 8 units, MeloTTS EN-US → OpenVoice V2.
- Also present locally: `audio_timing.json`, `script_en.md`, `captions.srt`,
  `captions.ass`, `review_status.json`, `REVIEW.md`, `environment_report.json`,
  `assembly_report.json`, per-unit WAVs.

No MP4, WAV, image, embedding, model, or private recording is committed.

## 8. Suggested next steps (not executed here)

1. User listens to A/B WAVs and plays the MP4; judge voice similarity, English
   pronunciation, noise, subtitle timing, and visual pacing.
2. Decide whether to keep the personal OpenVoice voice or revise the enrolled
   reference recording (new enrollment requires explicit user approval).
3. If the user accepts the sample, review the Fact Card and decide whether to
   approve it for any future publication path. No publication is implied here.
4. Keep Slice B, upload, and integrated BAT out of scope until Slice A is accepted.
