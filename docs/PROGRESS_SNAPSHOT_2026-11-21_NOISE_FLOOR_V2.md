# Noise Floor Removal V2 progress snapshot — 2026-11-21

Implementation basis: `docs/SLICE_A_NOISE_FLOOR_AND_VISUAL_POLISH_V2.md`.
Branch `feat/slice-a-english-visual-refinement`, base `df40862…`, synced by
`git merge --ff-only` to `de72205a5448658a218d738eb0dcbcb7afe27b55`.
`TASK_PLAN.md` V5 is unchanged. Draft PR #2 remains open and in draft state.
This is a sanitized progress document. No recording, embedding, WAV, MP4, stem,
frame, model, cache, virtual environment, or machine-local config is committed.

## 1. Noise diagnosis (the priority)

The continuous low-frequency hum / sandy hiss was traced to the synthetic
ambient bed, not to the personal voice. Local, gain-matched five-stem audition
files were built from the prior render with a single common linear gain from the
voice-only loudnorm measurement (`+9.71 dB`; relative stem levels preserved):

| stem | comprehension-pause RMS | pause spectral content |
|---|---|---|
| 01 voice only | -120 dBFS (true zeros) | no band energy, flatness 1.0 |
| 02 voice + SFX | -120 dBFS | no band energy |
| 03 voice + old ambient (diagnostic) | -19.72 dBFS | 50–200 Hz band 0.534, random/non-tonal |
| 04 existing final mix | -19.72 dBFS | same as 03 |
| 05 new default no-bed mix | -120 dBFS | true silence |

Voice-only active speech: RMS -18.4 dBFS, 50–200 Hz band 0.0195, spectral
flatness 0.000064 (tonal voice, not broadband noise). The diagnostic bed raised
the 50–200 Hz band to 0.232 and flatness to 0.006 in active speech. Conclusion:
the noise is a deterministic smoothed random-noise waveform across the whole
programme; voice gaps are exact digital silence.

Aggressive-filter A/B (`denoise-ab`, diagnostic only, not adopted):

| variant | noise floor | 80–150 Hz band | adopted |
|---|---|---|---|
| current afftdn=nf=-25 | 0.000351 | 0.000083 | baseline |
| nr=18:nf=-35:tn=1 | 0.001249 | 0.000417 | no — raises floor, adds artifacts |
| afftdn + highpass 85 | 0.000329 | 0.000056 | no material need |
| afftdn + highpass 110 | 0.000318 | 0.000038 | no — risks vocal body |

No gate, expander, AGC, or 110 Hz high-pass was adopted. Source sample counts
were preserved (84,992) in every variant.

## 2. Default audio profile

- `configs/audio_postprocess.json`: `preset_id` and `default_profile` are now
  `clean_voice_no_bed`; added explicit `noise_policy` (no continuous noise,
  gaps stay true zeros, no gate/expander/AGC, loudnorm must not fill gaps).
- `ambient_bed.enabled = false`, `opt_in_required = true`,
  `random_noise_voice_disabled = true`, `diagnostic_only = true`.
- `processing_order` no longer contains `ambient_bed_duck_and_mix`.
- `mix_final_audio` skips `generate_ambient()` entirely when disabled and emits
  `silence_diagnostics`. QA now treats bed-disabled as PASS and requires true
  silence in voice gaps plus near-digital silence in final-mix gaps.
- New `audio_diagnostics.py` produces the five stems, the denoise A/B and a
  post-AAC noise report. All outputs stay under ignored paths.

## 3. Visual polish

- Hook: both left/right zones, reference rings, "fades" and "grows" labels stay
  present for the full 0–5 s hook; the inactive side is a 0.22-opacity ghost and
  the active side is 1.0. No whole-group FadeOut during side switches; frames at
  0.3/1.5/2.5/3.5/4.5 s confirm the comparison stays balanced.
- Concept stages: `model_scope` now shows a spherical wireframe with equatorial
  and meridian ellipses plus a yellow radius arrow labelled r; `thermo_caveat`
  keeps a free-energy curve with a downward direction arrow / check mark and a
  clock icon crossed out by a drawn slash. No text-only hold exceeds 1.5 s.
- Formula pulses: U14 ("surface energy cubed") and U15 ("driving force squared")
  use separate triggers (`GAMMA_CUBED_PULSE`, `DRIVING_FORCE_SQUARED_PULSE`),
  scaling only γ³ / Δg_v² from 1.00× to 1.18× and back while dimming other
  terms to 0.65. Frames at 38.1 s and 41.5 s show γ³ and Δg_v² highlighted
  respectively, with unchanged semantic colors and an unchanged main curve.
- Stage scale: `theme_config.stage_scale` target 1.30× (range 1.25–1.35×).
  `stage_scale_report.json` records the applied factor per stage; safe-zone
  checks recompute bounds after scaling. Achieved 1.30× for most stages; the
  graph stages reached the largest safe factor 1.274× rather than overflowing.
  A mid-pass fill bug (curve drawn as a filled area) and an equation/label
  overlap were found in actual frames and corrected before the final render.
- Ending: ~6 s orange/resistance breathing halo with a 2.0 s period around the
  final nucleus; measured orange-ring pixel extent/opacity changes across
  56.6–61.6 s. Yellow critical marker is unchanged.

Accepted earlier visuals preserved: subcritical return vs supercritical descent
directions, 2D orange area / 3D cyan isometric cube, γ³ orange / Δg_v² cyan /
ΔG* yellow, bilingual captions, five rhythm blocks and claim links.

## 4. Final render and QA

- Local run: `outputs/20261121_133543_critical_nucleus/` (gitignored).
- `final.mp4`: SHA-256
  `3e67513295fd7d519e15eb906801ce007c29509e772510d129eff8bf834da6ee`.
- 62.43 s; 1080×1920; 30/1 fps CFR; H.264 yuv420p; SAR 1:1; 1873 frames;
  AAC 44.1 kHz mono; -16.02 LUFS; -1.49 dBTP.
- `qa_report.json` PASS, no WARN/FAIL, including new no-bed, true-silence and
  encoded-pause-quiet checks.
- Final mix: voice pre-mix peak -9.40 dBFS, 7 SFX all at -13.5 dB relative to
  local speech, zero clipped samples. Post-AAC speech RMS -16.77 dBFS,
  comprehension-pause RMS -120 dBFS, 103 dB separation; pause is truly quiet.
- `pytest -q`: 35 passed. Preflight PASS with all configured filters.

One prior render was rejected by a concrete frame-count QA failure (hook stages
did not consume their transition budget); it was fixed and re-rendered. A second
frame inspection found and fixed real composition defects, then the final render
was produced. No speculative repeated rendering was performed.

## 5. Human review still required

- Listen to the five gain-matched stems and the denoise A/B; confirm the bed was
  the noise and that the voice still sounds like the speaker.
- Watch phone-sized frames for subtitle comfort, hook balance, concept visuals,
  formula pulses, stage scale and the ending halo.
- Review scientific claims. Fact Card remains `DRAFT_PENDING_USER_REVIEW` and the
  sample remains `NOT_FOR_PUBLICATION_PENDING_USER_FACT_CARD_REVIEW`.

No Slice B, Milestone 2/3, production BAT, upload or publication was executed.
