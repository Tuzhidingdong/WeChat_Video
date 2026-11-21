# Final Refinement V3 progress snapshot — 2026-11-21

Implementation basis: `docs/SLICE_A_FINAL_REFINEMENT_V3.md`.
Branch `feat/slice-a-english-visual-refinement`, starting head
`571c20918717fae9e491eacf3bdb3d89d227ecbf`, synced by `git merge --ff-only` to
`ca865b7039c83893316672201fe754f3597f4e8b`. `TASK_PLAN.md` V5 unchanged.
PR #2 remains open/draft. This is a sanitized document: no media, WAV, stem,
frame, model, cache, embedding, recording, or machine-local config is committed.

## 1. Four corrections

- **R³ caption**: `content/sample_script.en.json` U07 source uses exactly
  `That gain scales with volume, r³.` (U+00B3); the separate 2D area cue U05
  remains `r²`. `tests/test_final_refinement_v3.py` locks the source wording,
  the spoken text ("r cubed"), the unchanged Chinese line, and the fact that
  SRT/ASS rendering preserves the superscript glyph. Extracted frame at 20.5 s
  shows `That gain scales with volume, r³.` above `r³ volume` and the cyan
  isometric cube.
- **Rise-to-peak marker**: `free_energy_landscape` now starts the yellow marker
  at the plotted origin (x=0), moves it monotonically along the curve to x=1 at
  80% of the cue, then holds. `critical_threshold` holds the marker at the peak.
  The motion manifest records `rise_to_peak` and `peak_hold` with sampled x/y and
  `follows_plotted_curve=True`; extracted frames at 27.0/28.0/29.0 s show the
  marker climbing along the curve and resting at r*. The accepted opposing
  0:46–0:51 motions (`subcritical_return`, `supercritical_descent`) are untouched.
- **Direction vs Speed hierarchy**: `thermo_caveat` now places a large check +
  `Direction / 方向` in the upper primary position next to the free-energy curve
  and downward arrow. `✗ Speed / 速度` is smaller, lower-right, and its clock has
  a thick orange diagonal slash drawn across the face during the cue. The generic
  rule `affirmed_concept_vs_excluded_misconception` (affirmed first/primary,
  rejected secondary/crossed out) lives in `configs/theme_config.json` without
  nucleation-specific wording. Frames at 53.5/54.6 s show the hierarchy and the
  fully drawn strike-through.
- **First-frame hook**: `wechat_video.hook_motion.py` is the pure, testable source
  of hook geometry. Frame 0 shows 4 distinct orange particles inside the left
  ring (active 1.0, right ghost 0.22); 0–2 s they contract inward and fade;
  2–4 s four cyan particles grow outward on the right. Both rings and both zones
  stay present. Manifest records `first_frame_left_particles=4` and sampled
  inward/outward radial progression. Frames at 0.0/0.5/1.5/3.0 s confirm it.

## 2. Audio A/B and decision

Same raw OpenVoice-converted speech, same active profile and same clarity EQ;
A = EQ only, B = configured afftdn (nf=-25) then EQ. Local report
`outputs/audio_ab_v3/afftdn_ab_report.json` (ignored):

| variant | sr | samples | active RMS | 4–8 kHz | 8–10 kHz | noise floor |
|---|---|---|---|---|---|---|
| A no-afftdn | 22050 | 84992 | -21.74 dBFS | 5.7e-5 | 2e-6 | 0.000207 |
| B afftdn | 22050 | 84992 | -21.43 dBFS | 4e-6 | 0.0 | 0.000061 |

B retained only 6.8% of 4–10 kHz consonant/air detail while lowering the floor —
the watery/metallic character the user reported. No continuous contaminant exists
in the personal-voice stem. Default profile is now `clean_voice_no_denoise_no_bed`
with `denoise.enabled=false`; afftdn remains an explicit diagnostic opt-in and was
removed from `required_ffmpeg_filters`. Preflight/QA/tests updated accordingly.
The MeloTTS EN-US → OpenVoice V2 CPU architecture and the active embedding are
unchanged; no cloud TTS, paid API, UVR/Demucs, new model, gate, AGC, or ambient bed
was introduced.

Final mix: voice peak -8.26 dBFS, no bed, zero clipped samples, 7 SFX at -13.5 dB
relative to local speech. Final AAC: -16.14 LUFS / -1.48 dBTP; active-speech RMS
-16.35 dBFS, comprehension-pause RMS -123.42 dBFS (separation 107 dB).

An FFmpeg 9.1 deadlock was found when two-pass linear loudnorm was combined with
the denoise-free stem; the final mux now uses a single-pass full-programme
loudnorm (still one normalization pass, measured values retained in the report).
The first full render failed with no usable MP4; after this concrete defect the
single justified re-render succeeded. No repetitive trial rendering was done.

## 3. Verification and final sample

- Focused tests: 6 passed. Full `pytest -q`: 41 passed. Preflight PASS with
  filters `highpass, equalizer, highshelf` and default denoise/bed both false.
- Local run `outputs/20261121_153013_critical_nucleus/` (gitignored).
- `final.mp4` SHA-256
  `a6f7f7e68d0887ab66ce68eae287a7a55ed43dae69d72c1ea056bfd27d6331cf`.
- 62.33 s; 1080×1920; 30/1 fps CFR; H.264 yuv420p; 1870 frames; AAC 44.1 kHz
  mono; QA `PASS`, no WARN/FAIL.
- Frame evidence under `outputs/qa_frames_v3/` and contact sheet
  `outputs/contact_sheet_v3.png` (local only).

## 4. Remaining human review

Listen to the no-afftdn/afftdn A/B and final narration; review phone-sized frames
for the hook, marker, caption and Direction/Speed layout; approve the Fact Card
later if desired. Fact Card remains `DRAFT_PENDING_USER_REVIEW` and the sample
remains `NOT_FOR_PUBLICATION_PENDING_USER_FACT_CARD_REVIEW`. No Slice B,
Milestone 2, BAT, upload or publication was executed.
