# Implementation status — Milestone 1 / Slice A

> Authority: TASK_PLAN.md (V5, FROZEN). This file records progress only; it does not amend requirements.

## Current state

- **Milestone:** 1 — Local video-production proof
- **Slice:** A — One critical-nucleus / free-energy-barrier sample
- **Implementation state:** Final refinement v3 implemented: r³ volume caption locked by regression test, free-energy marker rises to r* then holds, Direction/Speed affirmed-vs-excluded hierarchy with visible clock strike-through, first-frame left hook particles with verified inward/outward trajectories, and a controlled no-afftdn A/B that led to disabling afftdn in the default profile. Single-pass loudnorm avoids an FFmpeg mux deadlock. A new real bilingual MP4 was rendered and passes full QA.
- **Slice A exit condition:** NOT MET — the user must listen to the A/B voice samples and play the bilingual MP4 before accepting it.
- **Next authorized work:** user review of voice identity/cleanliness, US-English pronunciation, bilingual subtitle legibility, motion timing, and scientific claims; do not begin Slice B.

## Implemented in this branch

- Project-local Python environment bootstrap (Setup_Slice_A.bat).
- Local-only runtime entry (Run_Slice_A.bat); no runtime package installation or network fallback.
- Windows preflight for Python venv, Manim, project-local FFmpeg/ffprobe, libass/loudnorm plus local denoise filters, portable MiKTeX LaTeX/dvisvgm, independently validated Latin and CJK fonts, and the personal OpenVoice runtime/profile.
- Default personal English narration: one-time OpenVoice V2 target embedding from `my_voice/voice.m4a`, reused for all speech units; isolated `.venv-voice` (Python 3.9, CPU PyTorch), MeloTTS EN-US base voice; legacy Chinese and Piper voices retained for rollback only.
- Phrase-level bilingual script schema with raw/display/spoken/zh forms, claim links, rhythm blocks, configurable pauses, and SFX triggers.
- Per-unit converted WAV output, independent pronunciation-review WAV, and separate private A/B cleanup candidates without overwriting the active embedding.
- Measured sample counts, per-unit ffprobe metadata, explicit cover, configurable silence, sparse SFX events, and one global audio timeline.
- One registered Manim critical-nucleus template with continuous value-driven motion, mutually exclusive visual stages, focus dimming, and `visual_stage_manifest.json` / `motion_event_manifest.json`.
- Static-camera portrait safe-zone profile with symmetric 15% side margins and x=0 centered content.
- Bilingual SRT/ASS subtitles with separate Latin/CJK styles, explicit safe-zone placement, and relative-path FFmpeg burn-in.
- Video/audio assembly and mandatory media QA.
- Candidate Fact Card plus source records and a clear not-for-publication review status.
- Core unit tests and GitHub Actions test workflow.

## AC-01 to AC-25 tracking

| AC | Code implementation | Windows / user evidence |
|---|---|---|
| AC-01 | Project-local .venv bootstrap | Pending user setup run |
| AC-02 | Manim / FFmpeg / ffprobe preflight | Pending user preflight |
| AC-03 | Noninteractive LaTeX + dvisvgm smoke test | Pending installed TeX distribution |
| AC-04 | Runtime path contains no package installer | Implemented; verify BAT behavior locally |
| AC-05 | External command timeouts and captured diagnostics | Implemented; exercise on local machine |
| AC-06 | sherpa-onnx VITS MeloTTS offline CPU adapter/model bootstrap | Pending Windows inference |
| AC-07 | Dedicated Mandarin/scientific-term listening asset | Pending actual listening and user approval |
| AC-08 | raw/display/spoken fields | Implemented |
| AC-09 | One WAV + one cue per speech unit | Implemented; verify generated files |
| AC-10 | Per-chunk ffprobe metadata + sample-count timing | Implemented; pending run |
| AC-11 | Explicit cover segment 0–1000 ms in global timeline | Implemented; pending run |
| AC-12 | First voice starts at/after 1000 ms | Implemented and asserted; pending run |
| AC-13 | Subtitle cue timestamps use final-MP4 time origin | Implemented; pending visual sync check |
| AC-14 | Scene-relative cue checkpoints derived from measured audio | Implemented; pending render |
| AC-15 | Registered Manim visual events at cue checkpoints | Implemented; pending render/timing review |
| AC-16 | 9:16 1080×1920 scene configuration | Implemented; pending render |
| AC-17 | Manim content and subtitle area are separate in the layout profile | Implemented; pending phone review |
| AC-18 | Final FFmpeg normalization to 1080×1920/30fps/yuv420p/setsar=1 | Implemented; pending ffprobe |
| AC-19 | Preflight selects an installed Chinese font; subtitles use ASS | Pending local font/glyph inspection |
| AC-20 | Relative ASS path avoids absolute Windows drive-colon parsing | Implemented; pending path-with-spaces/Chinese run |
| AC-21 | Runtime measures actual length and warns outside 55–65 s | Pending real TTS duration; no speech-rate stretching |
| AC-22 | Media, subtitle count, audio, duration and frame checks | Implemented; pending generated MP4 |
| AC-23 | Flow is not required or referenced | Implemented |
| AC-24 | Pipeline emits the complete review-package structure | Pending generated artifacts |
| AC-25 | Final MP4 is playable for user review | Pending local generation and manual playback |

## Scientific review gate

fact_cards/critical_nucleus_free_energy_candidate.json is intentionally DRAFT_PENDING_USER_REVIEW. The primary source is a NIST-hosted 2019 workshop presentation containing the classical spherical CNT assumptions and equations. An ACS Chemical Reviews DOI is recorded as corroboration with publisher-preview-only access status. The code allows this card only through explicit --review-sample; the output is labelled NOT_FOR_PUBLICATION_PENDING_USER_FACT_CARD_REVIEW.

Do not change the card to APPROVED on the user's behalf.

## Known verification boundary

The source was authored and committed through GitHub. This environment cannot execute the user's Windows machine, verify installed fonts/TeX/FFmpeg builds, run the 347 MB TTS model on the user's CPU, or perform the required human listening/mobile review. Do not mark local-only AC items complete until the local evidence exists.

## Next step

The user syncs this branch, runs Setup_Slice_A.bat once, then Run_Slice_A.bat. Use the resulting outputs/<run>/run.log, environment_report.json, qa_report.json, and REVIEW.md to fix only observed Slice A defects. Slice B remains unauthorized until Slice A has been reviewed and accepted.
