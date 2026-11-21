# Slice A Final Refinement V3 — Caption, Motion Logic, and Natural Voice

**Status:** Authorized incremental correction after direct user review of the V2 review sample.  
**Repository:** Tuzhidingdong/WeChat_Video  
**Target branch:** feat/slice-a-english-visual-refinement  
**Verified starting head:** 571c20918717fae9e491eacf3bdb3d89d227ecbf  
**Scope:** Milestone 1 / Slice A critical-nucleus sample and reusable series-master rules only.  
**Authority:** TASK_PLAN.md V5 remains frozen and must not be edited.

This is a narrowly scoped V3 patch. Preserve the accepted Series Master and V2 work. Do not redesign the architecture or begin another milestone.

## 1. User-approved work — regression guard

The user considers the current sample close to finished and explicitly approves these elements. Preserve them exactly in meaning and quality:

- The isometric 3D cube at about 0:20 correctly represents volume.
- The barrier formula uses orange γ³ and cyan Δg_v², with yellow ΔG*.
- The spherical nucleus wireframe and radius concept around 0:44 are correct.
- The subcritical and supercritical markers move in opposite, scientifically correct directions around 0:46–0:51.
- The main CNT free-energy curve, 2D orange interface/annulus, 3D cyan volume geometry, bilingual captions, safe zones, formula pulse work, hook ghosts, and other V2 refinements must not regress.

Do not alter scientific claims or the pending status of the Fact Card.

## 2. Four visual/caption corrections

### 2.1 Hard caption typo at 0:19–0:22

The current English subtitle says:

**That gain scales with volume, r².**

This conflicts with the narration (“r cubed”), the Chinese subtitle (“收益随体积立方增长”), and the visible heading “r³ volume”.

Change only this subtitle/caption cue to the exact wording:

**That gain scales with volume, r³.**

Implementation requirements:
- Find and correct the source speech-unit/subtitle data, not merely the rendered pixels.
- Ensure the final rendered English subtitle displays the superscript ³ clearly.
- Add a focused regression test for this exact cue.
- Do not globally replace r². The separate “r² area” visual for a 2D interface is correct and must remain r².
- Verify the adjacent Chinese subtitle and narration remain unchanged.

### 2.2 Free-energy marker must rise before it rests at the critical peak (0:25–0:30)

The current marker/ball is visually descending toward the lower-right valley during the narration “Total free energy rises at first”, then jumps back to the peak for “Its peak marks the critical radius”.

Correct the temporal logic:
- At approximately 0:25, start the yellow marker at the origin of the plotted free-energy curve, corresponding to (r, ΔG) = (0, 0).
- During 0:25–0:28, move it continuously along the curve upward toward its maximum at r = r*.
- At approximately 0:29, stop and hold the marker exactly at the curve maximum/critical radius so the next spoken sentence lands on a stable visual.
- Do not let this marker roll down the right-hand branch or jump between positions during this explanation.
- Keep the actual curve, axes, and critical-point meaning intact. The marker must follow the plotted curve coordinates, not an approximate straight-line screen path.
- Use measured speech-unit/visual cue timing already available. Do not invent word-level timestamps.
- Keep the later, already-approved opposing subcritical-return and supercritical-descent motion at 0:46–0:51 unchanged. That later two-path comparison is a separate beat.

Add a focused test or motion-manifest assertion that the marker position is monotonic toward x = 1 / r* over the initial-rise interval and is held at the peak at the next cue. Inspect extracted frames at 0:25, 0:26, 0:27, 0:28, and 0:29.

### 2.3 Thermodynamic direction vs kinetic speed: correct hierarchy and explicit rejection mark (0:52–0:54)

The current visual gives “Speed / 快慢” the upper, dominant position while “Direction / 方向” is smaller and lower. The clock also does not have a sufficiently visible prohibition slash/cross.

Recompose this as a reusable positive-vs-excluded concept pattern.

**Primary, upper visual position — what the model does establish**
- Place a prominent check mark followed by “Direction / 方向”.
- Put it in the upper/main visual hierarchy, with the free-energy curve or directional energy arrow close to it.
- Keep the directional arrow visually clear and retain the actual free-energy curve.

**Secondary, lower or right position — what the model does not establish**
- Place a clear “✗ Speed / 速度” label.
- Show a clock icon with an unmistakable orange/red diagonal slash or cross drawn over the clock itself. A small separate X beside the clock is not sufficient.
- Keep this rejected item visually subordinate to the positive Direction conclusion.
- Animate the slash/cross drawing across the clock briefly and cleanly; avoid flashing.

The first visual scan must communicate “Direction, not Speed”. Keep both items readable on a phone and within the established science safe rectangle.

Generalize the rule in the series master as a reusable **affirmed concept vs excluded misconception** layout: affirmative item first and visually dominant; rejected item secondary and explicitly crossed out. Do not encode nucleation-specific text as a global template rule.

Add a focused validation of vertical/order hierarchy and the presence/visibility of the clock strike-through. Inspect actual frames around 0:52–0:54.

### 2.4 First-frame motion for the left “fades” hook (0:00–0:04)

The first frame currently shows the left “fades” circle empty; it stays nearly static until the right “grows” particles appear.

Correct the opening animation:
- At frame 0 / 0:00, show 3–4 distinct small orange particles clearly inside the left “fades” ring. They must already be visible in the first rendered frame, not introduced after a delay.
- From 0:00 to about 0:02, move these particles inward toward the centre while they shrink and fade smoothly to zero.
- From about 0:02 to 0:04, show 3–4 cyan particles emerging near the centre of the right “grows” ring and moving outward/growing.
- Retain a visible, balanced left/right comparison and both reference rings throughout the 0–5 s hook, in accordance with V2 ghost-persistence rules.
- Preserve the active/inactive opacity hierarchy and avoid fading out the whole comparison prematurely.
- Do not create a visually contradictory state in which the left particles grow while narration says “fades”.

The hook must show genuine motion from its first frame. Add focused checks for non-empty left particle geometry at t=0, inward radial progression over 0–2 s, and outward progression on the right over 2–4 s. Inspect frames at 0.00, 0.50, 1.00, 1.50, 2.00, 3.00, and 4.00 seconds.

## 3. Audio: remove processing artifacts without changing the voice architecture

### 3.1 Current code-grounded issue

At verified head 571c209:
- configs/audio_postprocess.json has denoise.enabled = true, filter afftdn, and nf_db = -25.
- src/wechat_video/master_config.py::denoise_filter_chain() constructs this configured filter.
- src/wechat_video/voice_worker.py applies the denoise chain after OpenVoice conversion when the clean-converted path is selected, before applying the configured clarity EQ.
- The clarity EQ currently uses 85 Hz high-pass, a -2.5 dB cut at 300 Hz, +3 dB at 4 kHz, and +2 dB air shelf at 9.5 kHz.
- The persistent synthetic ambient bed is already disabled in the default profile and must stay disabled.

The user's latest listening finds the low-frequency rumble much improved, but the remaining voice sounds slightly muffled and has a watery/electronic artifact. The active afftdn stage is therefore a concrete suspect. This is not proof that it is the sole cause: inspect the actual converted and processed voice stems.

### 3.2 Preserve the established local voice stack

Keep the current offline personal-voice architecture:

MeloTTS EN-US (CPU) → OpenVoice V2 tone-colour conversion (CPU) → justified minimal cleanup only → configurable clarity EQ → sparse SFX → one final programme loudnorm → AAC

Do NOT:
- replace this with Edge-TTS, ElevenLabs, Azure TTS, or another cloud/online TTS service;
- introduce a paid API, online voice demo, external upload, cloud account, or new model download;
- change or replace the active speaker embedding, active voice profile, or the user's reference recording;
- switch to UVR5/Demucs or Adobe Podcast Enhance as a speculative fix;
- add a -32 dB room-tone/ambient layer. The user specifically wants clean speech and silence; a new continuous bed would reintroduce the previous problem;
- add a noise gate, expander, AGC, dynamic compression, or pause-level pumping.

The generated speech is already a local TTS + timbre-conversion signal, not a noisy live field recording with music underneath. Source-separation software is not justified unless objective evidence later identifies a separable contaminant. Do not use it in this Slice A pass.

### 3.3 One controlled, same-text A/B before choosing the default

Use one short, identical speech unit and the same active voice profile to create local, gain-matched comparisons:

A. Raw OpenVoice-converted speech → current clarity EQ, without afftdn.  
B. Raw OpenVoice-converted speech → current afftdn (nf=-25) cleanup → same clarity EQ.

Keep the raw converted source and A/B outputs private/ignored. Never upload them.

Measure both versions:
- sample rate, channels, exact sample count and duration;
- active-speech RMS, peak, clipping ratio;
- spectrum / PSD and band energy, including 200–800 Hz, 4–8 kHz, and 8–10 kHz;
- any stable narrow-band hum, if present;
- noise floor during any genuine source-signal gaps (do not mistake unvoiced consonants for silence);
- whether the denoised result suppresses consonant/sibilant detail or adds watery/metallic modulation.

Do not use a single global spectral ratio as a proxy for voice quality. Compare the same phrase, at identical gain and playback level. The user makes the final subjective judgement.

**Default decision rule:** if the un-denoised converted signal is already clean enough and has more natural consonants/texture, disable post-conversion afftdn in the default profile (denoise.enabled = false, or an equivalent explicit no-denoise profile). Do not denoise merely because a denoise stage exists in the old pipeline. Keep the old filter available only as an explicit diagnostic/opt-in candidate if useful.

If measurable noise remains in the un-denoised speech, identify its actual spectral/time signature first. Apply only the least aggressive local cleanup that audibly improves the same-text A/B without making the voice watery or dull. Do not blindly set nr=18, nf=-35, or high-pass 110 Hz.

### 3.4 EQ: prioritize natural brightness, not aggressive treble

- First determine whether removing the unnecessary afftdn stage resolves the muffled character.
- Retain the current configurable EQ as the baseline comparison.
- Inspect the actual 4–8 kHz energy after conversion and processing. Current +3 dB at 4 kHz is already a presence boost; do not stack more gain without evidence.
- If the voice remains dark after the denoise A/B, test only one modest, same-text presence/air adjustment against the baseline and inspect sibilants and residual hiss. Keep the chosen values in audio_postprocess.json, not hardcoded in Python.
- Measure the actual voice sample rate and Nyquist limit before using a high shelf. Do not assume a 9–10 kHz boost has useful audible content just because the filter is configured.
- Do not high-pass at 110 Hz by default. Preserve the natural 200–800 Hz body; the existing 85 Hz baseline remains until measurements demonstrate a specific low-frequency contaminant.
- Preserve exact sample count/duration through post-processing so the global timeline remains correct.

If denoise.enabled = false, update required_ffmpeg_filters, preflight, tests and QA so afftdn is not incorrectly required for the default no-denoise profile. Keep checks for the other filters that are actually used.

### 3.5 Silence and final mix invariants

- Keep ambient_bed.enabled = false in the default profile.
- Keep actual programme gaps silent; do not fill them with room tone, noise, or a low-level synthesized layer.
- Do not use gates or AGC to create the perception of silence.
- Use sparse event-triggered SFX only at the existing restrained relative level.
- Keep one full-programme loudnorm pass after the final voice + SFX mix.
- Retain the current programme targets (-16 LUFS integrated / -1.5 dBTP ceiling) unless the final encoded-AAC measurement proves a specific issue.
- QA must separately inspect encoded-AAC speech gaps and speech-active sections; integrated LUFS/true peak passing alone is not proof of clean audio.

## 4. General template improvement boundary

Only generalize reusable presentation principles:
- positive/affirmed concept is visually primary;
- rejected misconception is secondary and has a clear crossed-out symbol;
- motion should begin on the first frame when the hook promises an active transformation;
- visual marker trajectory must match the narrated physical direction and plotted data;
- subtitle symbols/exponents must agree with narration, diagram and scientific dimension.

Keep all Slice A wording, formula strings, timestamps, nucleation physics and specific particle trajectories in the sample content/configuration, not as hard-coded global rules for unrelated topics.

No scientific test content, scientific claims, or this sample's transcript may become a universal template instruction.

## 5. Focused implementation and verification — no test loop

1. Sync the exact target branch and verify the starting commit is 571c20918717fae9e491eacf3bdb3d89d227ecbf or a fast-forward descendant. Do not reset or overwrite newer work.
2. Inspect the actual speech-unit/caption source for the r² typo; fix only the volume caption.
3. Correct the 0:25–0:29 rise-to-peak marker motion and add a focused regression check.
4. Correct the thermo-caveat layout hierarchy and visible strike-through.
5. Correct first-frame left hook particles and their inward/fading trajectory; preserve both hook rings and existing ghost logic.
6. Build and listen/measure the single controlled audio A/B. Select the least processed natural voice; no cloud services, new models or continuous bed.
7. Update only the relevant config, renderer, manifest, tests, and sanitized docs. Do not modify TASK_PLAN.md V5.
8. Run the narrow targeted tests once, then pytest -q once.
9. Run project preflight once.
10. Run exactly one complete local Python CLI review render with --review-sample. Do not run any production BAT or ask an Agent to execute it.
11. Inspect rendered frames at the specified timestamps, final AAC speech/gap measurements, subtitle cue, ffprobe metadata, and final QA. Do not create a second full render unless the first contains a concrete mandatory defect.
12. Keep all media, WAVs, MP4s, stems, frame captures, caches, models, speaker embeddings, recordings and machine-local config ignored and untracked.

## 6. Git and privacy boundaries

- Work only on feat/slice-a-english-visual-refinement.
- Keep PR #2 Open and Draft.
- Do not merge, force-push, rewrite history, or update main.
- Do not edit frozen TASK_PLAN.md V5.
- Do not access or modify Tuzhidingdong/WeChat_control.
- Do not start Slice B, Milestone 2 or any publication workflow.
- Do not upload recordings, embeddings, WAV, MP4, screenshots, models, caches, or local configuration.
- Do not run production BATs, schedule, submit, or publish.
- Commit and push only source code, tests, reusable config, and sanitized technical documentation using a normal fast-forward push.

## 7. Final report required

Report:
- starting and final commit SHAs and PR URL;
- exact changed files;
- exact corrected subtitle cue and regression test;
- extracted frame evidence for 0:00–0:04, 0:25–0:29, 0:52–0:54;
- marker trajectory values/timestamps and confirmation the later 0:46–0:51 opposing trajectories are unchanged;
- hook initial particle count and measured trajectory/opacity evidence;
- audio A/B stem paths (local only), sample rates, sample counts, spectral measurements, selected processing chain, and reason for disabling/retaining denoise;
- confirmation no continuous noise bed and no cloud/paid service/new model was used;
- final encoded AAC gap/speech measurements, LUFS and true peak;
- final MP4 path, SHA-256, duration, dimensions, FPS, codecs, tests, preflight and QA results;
- privacy scan and remaining human listening/viewing items.

Stop after one corrected Slice A review sample is ready for the user. The user performs final listening/viewing and final BAT acceptance. No automatic publication is authorized.
