# Slice A bilingual short-form upgrade — progress snapshot (2026-11-21)

Implementation basis: `docs/SLICE_A_BILINGUAL_SHORTFORM_ANIMATION_UPGRADE.md`.
Base branch `feat/slice-a-english-visual-refinement`, synced base commit
`3525bb4e42b4fb77fb7c04448b19ee44611446b7` by fast-forward from
`b70e4ca1d453376e8846cc4ce0e802015bef7312`. `TASK_PLAN.md` V5 is unchanged.
Draft PR #2 remains open and in draft state.

No raw recording, voice embedding, generated WAV/MP4, frame, model, cache, or
machine-local config is included in this document or committed with it. Relative
paths below point to ignored local artifacts only.

## 1. What is implemented and has real run evidence

- **Personal voice cleanup**: local FFmpeg `afftdn`/`anlmdn` availability was checked;
  a filtered reference and candidate embedding were created under ignored private
  paths. The active recording and active `target_se.pth` were not overwritten.
  Same-text A/B WAVs and a post-conversion cleaned sample were generated. Objective
  metrics showed the cleaned candidate noise floor 0.000351 versus 0.002648 for the
  original conversion, identical duration, and no additional clipping. The candidate
  profile and `afftdn=nf=-25` post-conversion cleanup were selected for this render.
  User listening is still required before calling it better.
- **Bilingual narration pipeline**: 18 phrase-level English speech units, each with a
  Simplified Chinese subtitle line, claim IDs, rhythm block, pause, and visual trigger.
  Every unit was generated with MeloTTS EN-US → OpenVoice V2 using the saved candidate
  profile; the produced WAVs are the timing authority.
- **Five-block rhythm**: HOOK / CONFLICT / MECHANISM / APPLICATION / TAKEAWAY with an
  editorial-beat manifest. Two 650 ms comprehension pauses follow the critical-radius
  and barrier conclusions; other gaps are 280 ms.
- **Dynamic animation**: value-tracker-driven particle assembly/dissolution, competing
  surface/bulk bars, r²/r³ growth shapes, progressive free-energy curve, moving marker,
  critical-radius line, and final crystal/takeaway resolution. Inactive graph context is
  dimmed to 0.25 opacity. `visual_stage_manifest.json` and `motion_event_manifest.json`
  record one active stage per cue and one motion event in every rhythm block.
- **SFX**: locally synthesized pop/tone/whoosh cues at major turning points, mixed over
  the narration on the same global sample origin without shifting speech or subtitles.
  Final mix peak and post-AAC loudness were measured.
- **Bilingual subtitles**: explicit EN and ZH ASS styles (Arial 40 px above,
  Microsoft YaHei 46 px below, centered at 70.5% / 75.5% frame height), inside the
  15%–85% horizontal safe area and above the 22% bottom UI reserve. CJK glyph coverage
  was verified with fontTools; Arial does not satisfy the CJK check.
- **Full render and QA**: one final controlled `run-slice-a --review-sample` render
  completed after targeted fixes. Earlier renders during this pass failed on concrete
  defects (scene API naming, FFmpeg filter flag, SFX sample rate, and stage handoff);
  each was fixed from the exact error or rendered frame before the final render.

## 2. Implemented but still requiring human judgement

- Voice similarity, cleanliness, and naturalness: A/B and final WAVs exist; the user
  must listen and decide.
- Phone-screen legibility of the two-line subtitles and perceived pacing of the
  visual reversals: automated layout/manifest checks passed, but human review is pending.
- Scientific acceptance: the Fact Card remains `DRAFT_PENDING_USER_REVIEW`; the video
  remains `NOT_FOR_PUBLICATION_PENDING_USER_FACT_CARD_REVIEW`.

## 3. Partially implemented

- Motion richness: the scene has continuous vector/particle/curve motion and bounded
  scale pulses, but no moving-camera zoom/pan by design; the camera is static.
- Denoising: conservative FFmpeg FFT denoise is applied to reference and converted
  audio; no neural denoiser or additional model was introduced.

## 4. Not implemented in this pass

- Slice B templates, Flow, topic pool, Edge/CDP, WeChat upload, daily BAT, scheduling,
  publication, or any external upload path.
- No online TTS, paid API, cloud voice demo, or new large model was used.

## 5. Known limitations

- The selected cleaned candidate is based on objective acoustic metrics; perceived
  identity may still need a different reference recording in a future authorized pass.
- Some science stages are intentionally text-and-curve focused rather than cinematic.
- OpenVoice V2 watermark behavior was preserved; no attempt was made to remove it.

## 6. Reproducible local environment

- Manim runtime: Python 3.12.4, manim 0.22.1, sherpa-onnx 1.13.8, fonttools 4.68.0.
- Voice runtime: Python 3.9.23, torch/torchaudio 2.1.2+cpu, numpy 1.26.4,
  librosa 0.9.1, whisper-timestamped 1.14.2, transformers 4.27.4.
- Tools: FFmpeg/ffprobe 9.1 (libass, loudnorm, afftdn, anlmdn); MiKTeX 25.12 Portable
  with pdfTeX 4.23 and dvisvgm 3.4.3. Version pins are in `requirements-voice.txt`.

## 7. Latest sample and QA (metadata only)

- Local run directory: `outputs/20261121_112026_critical_nucleus/` (gitignored).
- `final.mp4`: 2,547,180 bytes, SHA-256
  `732e45bb57eb5c8bd08581ba55e72e5d0f4f0d0ef8688f36eb6c17f56a3b05bb`.
- Duration 61.77 s; 1853 frames; 1080×1920; 30/1 fps CFR; H.264 yuv420p; SAR 1:1;
  AAC 44.1 kHz mono.
- Encoded audio: integrated loudness -16.06 LUFS, true peak -1.47 dBTP.
- `qa_report.json`: `overall_status: PASS` with no WARN/FAIL; all media, exact-frame,
  loudness, bilingual-subtitle, font, pause, SFX, and motion-manifest checks passed.
- Additional local artifacts: `script_en.md`, `captions.srt`, `captions.ass`,
  `audio_timing.json`, `visual_stage_manifest.json`, `motion_event_manifest.json`,
  `subtitle_layout_report.json`, `voice_quality_report.json`, `final_mix.wav`,
  `audio_manifest.json`, `environment_report.json`, `assembly_report.json`.
- Voice A/B samples remain only under ignored `private/voice_profile/candidates/`.

## 8. Next steps (not executed here)

1. User listens to the A/B WAVs and the final MP4 narration; decide whether the cleaned
   candidate preserves their identity and whether US-English pronunciation is acceptable.
2. User reviews the bilingual subtitles on a phone-sized screen and checks that visual
   reversals land near the intended beats.
3. User reviews the scientific claims and decides whether to approve the Fact Card.
   No publication or upload is implied.
