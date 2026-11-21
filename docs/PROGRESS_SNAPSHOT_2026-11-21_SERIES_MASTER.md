# Series Master v1 progress snapshot — 2026-11-21

Implementation basis: `docs/SERIES_MASTER_TEMPLATE_V1_AUDIO_VISUAL_REFINEMENT.md`.
Base branch `feat/slice-a-english-visual-refinement`, synced base commit
`989f1456f5a1bc43e2cc8faf60ec73e4bafd4fbc` by fast-forward from `4240750…`.
`TASK_PLAN.md` V5 is unchanged. Draft PR #2 remains open and in draft state.

This is a sanitized progress document. No recording, embedding, WAV, MP4, frame,
model, cache, virtual environment, or machine-local config is committed.

## 1. Implemented with real run evidence

- **Reusable master configs**: `configs/theme_config.json` (domain-neutral palette,
  semantic roles, portrait grid, subtitle rules, 1D/2D/3D geometry mapping, binary
  hook pattern, state-curve motion, focus and accent rules, formula symbol roles)
  and `configs/audio_postprocess.json` (voice EQ preset, denoise, headroom, relative
  SFX, ambient bed, final programme targets, processing order). Both are loaded and
  validated by `master_config.py`, preflight, the voice worker, the mixer and QA;
  numeric values are not buried in Python literals.
- **Voice EQ**: `voice_clarity_v1` chain built from config:
  `highpass=f=85,equalizer=f=300:t=q:w=1.5:g=-2.5,equalizer=f=4000:t=q:w=1.2:g=3.0,highshelf=f=9500:g=2.0`.
  Same-text A/B kept locally: flat denoised
  `private/voice_profile/candidates/ab_candidate_converted_cleaned.wav` and EQ
  `private/voice_profile/candidates/ab_voice_clarity_eq.wav`. Measured low-mid band
  energy 0.1548 → 0.1213; presence band 0.000003 → 0.000008; sample count preserved
  (84,992); no clipping. Listening is still required before calling it clearer.
- **Audio mix**: deterministic ambient bed at measured -30.08 dBFS RMS with 800 ms
  boundary fades and 3.5 dB ducking; relative SFX at -13.5 dB below local active
  narration; voice pre-mix peak -8.39 dBFS under the -3 dBFS ceiling; zero clipped
  samples; final AAC measured -16.1 LUFS / -1.48 dBTP. Voice pause samples remain
  zero in `narration.wav`, but the final programme has continuous ambience in gaps.
- **Visual master**: binary hook (left failure / right growth with matched reference
  and CJK badge), 2D orange annulus for r² surface, 3D cyan isometric cube for r³
  bulk, full-opacity energy curve during threshold motion with dimmed helper labels,
  separate subcritical return (x 0.35 → 0.92 → 0.12, shrink/fade, no threshold
  crossing) and supercritical descent (x 1.08 → 2.0, monotonic p²), and semantic
  formula colors (γ³ orange, Δg_v² cyan, ΔG* yellow).
- **QA**: `pytest -q` 34 passed; preflight PASS including theme/audio config and all
  configured FFmpeg filters. Final QA `PASS` with no WARN/FAIL, including new config,
  audio-balance, ambient, marker-path and focus checks.
- Actual rendered frames were inspected at hook, 2D/3D scaling, formula, both
  threshold paths and ending. Frame-to-frame differences confirm motion in each block.

## 2. Implemented but still requiring human judgement

- Whether the EQ sounds open rather than harsh; whether the ambient bed is
  perceptible but unobtrusive; whether SFX are balanced; voice identity/cleanliness;
  phone-sized subtitle comfort. These remain explicit human review items.

## 3. Partially implemented

- The “air shelf” at 9.5 kHz shows near-zero band energy because converted speech is
  22.05 kHz (Nyquist 11.025 kHz); the filter is applied and recorded but its audible
  effect is limited for this voice. Kept as a configurable preset for future voices.
- Motion remains within a static portrait camera; no moving-camera system was added.

## 4. Not implemented (out of scope)

- Slice B templates, Flow, topic pool, Edge/CDP, uploader, scheduling, publication.
- No cloud TTS, online voice demo, paid API, new model download, or new template family.

## 5. Known limitations

- Personal voice similarity and scientific-claim approval are unverified; Fact Card
  remains `DRAFT_PENDING_USER_REVIEW` and sample remains
  `NOT_FOR_PUBLICATION_PENDING_USER_FACT_CARD_REVIEW`.
- The hook is a short two-clause contrast; it is not a long cinematic sequence.

## 6. Reproducible environment

- Manim runtime: Python 3.12.4, manim 0.22.1, sherpa-onnx 1.13.8, fonttools 4.68.0.
- Voice runtime: Python 3.9.23, torch/torchaudio 2.1.2+cpu, numpy 1.26.4,
  librosa 0.9.1, whisper-timestamped 1.14.2, transformers 4.27.4.
- Tools: FFmpeg/ffprobe 9.1 (libass, loudnorm, afftdn, anlmdn); MiKTeX 25.12 Portable.

## 7. Latest sample and QA (metadata only)

- Local run: `outputs/20261121_124420_critical_nucleus/` (gitignored).
- `final.mp4`: SHA-256
  `8828b27d1269ae627c0a11de709ff8cd518785c56d1ac87dc9ec4a6549ed4164`.
- 62.60 s; 1080×1920; 30/1 fps CFR; H.264 yuv420p; SAR 1:1; 1878 frames;
  AAC 44.1 kHz mono; -16.1 LUFS; -1.48 dBTP.
- `qa_report.json`: `PASS`, no WARN/FAIL.

## 8. Next steps (not executed)

1. User listens to flat/EQ A/B and final narration; judge clarity, harshness, identity.
2. User reviews phone-sized preview and framing/legibility.
3. User reviews scientific claims and decides whether to approve the Fact Card.
   No publication or upload is implied.
