# Slice A Refinement V2 — Eliminate Noise Floor and Polish Visual Continuity

**Status:** Authorized follow-up after the user's review of the latest Series Master sample.  
**Repository:** Tuzhidingdong/WeChat_Video  
**Branch:** feat/slice-a-english-visual-refinement  
**Verified base:** df4086277b0d1a774ba8c610ba295bd8147e725d  
**Scope:** Existing Milestone 1 / Slice A critical-nucleus sample only.  
**Authority:** TASK_PLAN.md V5 remains frozen. This supplement adds current user feedback and supersedes the previous ambient-bed preference where it conflicts with the explicit requirement for a clean, noise-free track.

## 1. User-reviewed outcome and priority

The user confirms that the latest rendered sample has a continuous low-frequency hum and broadband sandy/hissy noise throughout the video. The noise becomes especially prominent during speech gaps and comprehension pauses, making the voice sound muddy.

The user also confirms that these visual elements are now correct and must be preserved:
- At approximately 0:47–0:52, the state marker rolls in the correct opposing directions for subcritical return and supercritical descent.
- The approximately 0:20 isometric cube correctly communicates 3D volume.
- The approximately 0:34 barrier formula correctly distinguishes orange γ³ and cyan Δg_v² terms.

Do not regress these accepted visual improvements.

The next pass has four priorities, in order:
1. Remove the persistent noise floor and prove the voice-only signal is clean.
2. Preserve the accepted threshold motion, 3D geometry, and formula semantics.
3. Fix the paired-hook visual reference continuity and eliminate text-only PPT-like holds.
4. Add local formula-term pulses, a safe 1.25–1.35× stage-size improvement, and a breathing end state.

The deliverable remains one complete local Slice A review MP4 and report. No user playback or scientific approval is implied.

## 2. Important diagnosis: the synthetic ambient bed is the first suspect

The latest branch currently includes:
- configs/audio_postprocess.json: ambient bed enabled, target -30 dBFS RMS, 3.5 dB ducking, continuous through gaps.
- src/wechat_video/sfx.py / generate_ambient: creates a deterministic smoothed random-noise waveform (soft_low_hiss) across the entire programme.
- src/wechat_video/media.py / mix_final_audio: overlays that bed continuously; the ducking envelope reduces it only about 3.5 dB while narration is active and restores full bed level during gaps.
- The final full-programme loudnorm stage processes the whole mixture. It does not distinguish voice from the noise bed; any common gain applied to the programme also changes the absolute level of the bed.

This exact design can produce the reported symptoms: a continuous noise layer, more audible when the voice falls silent, and a lower/muddier perceived voice-to-noise contrast.

This is a strong code-grounded hypothesis, not yet an acoustic proof that no other source contributes. Diagnose and isolate the stems rather than guessing.

### 2.1 Immediate configuration change

**Turn the synthetic noise ambient bed OFF by default.**

In configs/audio_postprocess.json:
- Set ambient_bed.enabled to false.
- Add an explicit default profile such as clean_voice_no_bed.
- Do not invoke generate_ambient() for this profile.
- The final programme must not contain a random-noise bed, low-hiss bed, fan-like texture, or continuous synthesized noise.
- Preserve real intended silence between phrases and during 0.5–0.8 s comprehension pauses.
- Keep sparse, event-triggered SFX only where justified, at their configured low relative level.

The earlier preference for a very quiet ambient bed is superseded by the user's latest playback feedback. Do not retain ambient at -30 dBFS merely because the previous QA expects it to be enabled.

A future optional ambient mode may exist as an explicit opt-in, but it must not generate random white/pink/low-pass noise. It requires a separate human-approved non-noise tonal design and a much lower starting level (e.g. no higher than -42 dBFS RMS), with a clean A/B comparison. It remains OFF in the current default production profile.

### 2.2 Prove which stem creates the noise

Use the existing local output and private stems. Do not upload audio or ask the user to upload files.

Generate and compare these local audition files using identical sample alignment and overall programme gain:
1. Voice-only final EQ WAV (no SFX, no ambient).
2. Voice + SFX WAV (no ambient).
3. Voice + current ambient bed WAV (diagnostic only).
4. Existing final mix.
5. New default final mix with the ambient bed disabled.

Measure noise/spectral properties in:
- a speech-active section,
- a short natural speech-unit gap,
- a 0.5–0.8 s comprehension pause,
- the programme opening/closing fades if applicable.

For each segment inspect:
- RMS and peak dBFS,
- frequency spectrum / PSD,
- spectral peaks in the 50–200 Hz region,
- broadband noise energy and spectral flatness,
- whether the bed is deterministic/random noise or a true narrow-band hum,
- encoded AAC result after final loudness normalization.

Do not label a 50/60 Hz fan/electrical hum unless the measured spectrum actually shows those peaks. Do not infer a precise spectral defect from listening notes.

The A/B files must be gain-matched for fair listening. Keep them under ignored outputs/ or private/ paths.

### 2.3 Voice-only denoising: no blind aggressive filter escalation

The user suggested afftdn=nr=18:nf=-35:tn=1 and high-pass 110 Hz. Treat these as diagnostic candidates, not universal mandatory values.

Do not blindly impose them:
- nr=18 can create watery/metallic artifacts, suppress consonants, and damage converted voice if the actual noise is in the ambient stem rather than the voice stem.
- A 110 Hz high-pass can remove useful vocal body/fundamental content. The source is a personal-voice conversion, not a guaranteed female voice with a known F0 range.
- A +3.5 dB presence lift and +2 dB high shelf can make residual hiss more obvious, particularly when the sample rate is 22.05 kHz and 9 kHz is near Nyquist.

Required process:
1. Establish the noise floor on the voice-only stem first.
2. If voice-only speech is clean and gaps are exactly zero, do not add stronger denoising. Remove the ambient noise source.
3. If voice-only speech contains measurable hum, identify its actual fundamental/harmonics before choosing a notch or high-pass. Only apply a notch where the measured peak is stable and not part of the voice.
4. If voice-only speech contains broadband noise, test the existing afftdn and the candidate nr=18:nf=-35:tn=1 as separate same-text variants. Inspect consonants, sibilants, and artifacts; choose the least aggressive variant that materially reduces noise.
5. Test high-pass 85 Hz versus 110 Hz as separate A/B candidates. Do not select 110 Hz if it weakens the speaker's vocal body.
6. Make the presence and air boosts conditional on the voice-only spectrum and listening. Do not boost hiss.
7. Re-measure the processed WAV sample counts and durations. The exact post-processed samples become the timing authority.

Do not use dynamic compression, gate, expander, or automatic gain control to raise/lower gaps. The voice stem should retain its intended sample-level silence; final audio loudnorm is applied once after mixing only.

### 2.4 Final audio assembly

New default order:
1. MeloTTS EN-US synthesis.
2. OpenVoice V2 user timbre conversion.
3. Conservative voice cleanup only if voice-only diagnostics justify it.
4. Configured clarity EQ, with any noise-aggravating band disabled or calibrated as required.
5. Measure the processed chunks: sample rate, channels, sample count, duration, peak, clipping, spectrum.
6. Build the exact global timeline. Silence segments remain true zeros in the voice-only track.
7. Add only sparse SFX aligned to real animation events, at -12 to -15 dB relative to adjacent speech. Use approximately -13.5 dB as a configurable starting point.
8. Do not add continuous noise ambience in the default profile.
9. Apply one full-programme loudnorm pass to the voice + SFX final mix, then AAC encode.
10. Inspect the post-AAC audio in both active-speech and pause windows.

Keep the final programme target at -16 LUFS integrated / -1.5 dBTP ceiling unless an evidence-backed issue requires a change. Measure post-encode values.

Important: loudnorm must never be used to fill gaps or raise the noise floor. Do not put noise into the intentional silence segments. If the post-normalized speech gaps are non-zero in the default no-bed mode, identify the source rather than hiding it with a gate.

### 2.5 QA changes

- Ambient bed disabled is a valid PASS state for the default clean voice profile.
- QA must not require ambient.enabled == true.
- QA checks no ambient bed is mixed when enabled == false.
- Check the voice-only pause samples are exact zeros.
- Check final mix silence intervals are at digital silence except explicitly overlapping SFX or an explicitly enabled optional ambience profile.
- Include stem-specific noise metrics and a diagnostic note in the mix report.
- Do not classify low-level intended SFX as background noise.
- Do not pass the audio check solely because integrated loudness/true peak pass. Noise during speech gaps must be measured separately.

## 3. Hook: persistent non-active comparison ghost

The user reports that the comparison reference disappears while the opposite side is being animated, making the left/right composition lose balance and removing the size reference.

Modify the first 0–5 seconds:
- Keep both left and right comparison zones present for the entire hook.
- Keep both reference rings / outlines visible at all times.
- When animating the left failure path, the right state remains as a 20%–25% opacity ghost.
- When animating the right success path, the left failed state remains at 20%–25% opacity in its final contracted state.
- Never remove the inactive counterpart completely.
- Keep the active path at 100% opacity and the inactive counterpart at 20%–25%.
- Maintain the same size reference, scale, and relative placement so the eye can compare states.
- Avoid calling FadeOut on the entire hook comparison group at the moment that only one side should become inactive.
- The comparison should remain balanced through all 0–5 second hook beats. After the hook resolves, it may transition smoothly to the next scene rather than disappearing abruptly.
- Inspect actual extracted frames across 0.0–5.0 seconds, not only the first/last frames.

## 4. Eliminate text-only PPT holds

The current model_scope and thermo_caveat stages use two lines of text without a meaningful physical visual. This creates static text-only holds.

Generic rule:
- No pure-text-only visual stage may remain for more than 1.5 seconds.
- Any scientific caveat/concept must have a minimal physical diagram, symbol, or meaningful visual object alongside short labels.
- Continue using narration and bilingual subtitles for explanatory text; do not add long canvas sentences.

Specific Slice A visuals:

### Spherical nucleus / model scope (~0:44)
- Draw a clean circular/spherical wireframe or circle with subtle depth cues.
- Add a radius arrow from the center to the interface, labelled r.
- Optionally show a very subtle rotation/lighting sweep; do not imply an atomistic pathway.
- Keep the labels concise: Spherical nucleus / 球形晶核.
- Preserve the homogeneous model caveat in narration/subtitles, not as a second static paragraph.

### Thermodynamic tendency vs speed prediction (~0:53)
- Keep the actual free-energy curve or a simplified directional energy arrow visible.
- Show a clear downward free-energy direction arrow and a concise check mark labelled Direction / 方向.
- Show a clock/speed icon with a slash/cross labelled Speed / 快慢.
- Use motion: the energy arrow draws or pulses; the crossed-out clock appears with a short restrained strike-through animation.
- Do not show only two static text lines.
- Preserve the scientific statement that the curve represents thermodynamic preference, not a real-time growth-rate prediction.

The graphics must stay inside the science safe rectangle and maintain the established color semantics.

## 5. Local formula pulse/highlight

At approximately 0:34–0:42, the displayed barrier formula is already clearly color-coded and should remain that way.

Improve phrase-level reading cues:
- When narration says “surface energy cubed”, pulse only γ³.
- When narration says “driving force squared”, pulse only Δg_v².
- Pulse sequence: 1.00× → 1.18× → 1.00×, smoothly within the associated spoken cue, with a subtle glow/brightness increase.
- Dim only non-current formula terms slightly (e.g. 60%–75% opacity), not the whole equation and not the primary curve.
- Restore all formula terms to full opacity at the end of each cue.
- Preserve semantic colors: γ³ orange, Δg_v² cyan, ΔG* yellow.
- Use separate visual triggers/manifest entries for the two formula terms; do not map both spoken units to an identical generic BARRIER_EQ pulse.
- Use actual measured cue timestamps. No word-level timing should be invented.

Automated validation must check the two separate highlight events and their cue alignment. Inspect actual frames at each pulse peak.

## 6. Main visual stage size

The user reports that the main graphic/axes appear relatively small, roughly 55% of the screen width, with excessive dark-blue empty space.

Create a configurable target main-stage scale factor defaulting to approximately 1.30× (bounded range 1.25–1.35×):
- Scale the active visual group (graph, particle system, dimensional geometry, formula) around the science-stage centre, not the whole 1080×1920 frame.
- Recompose/re-layout individual objects when a simple global scale would push them outside the safe region.
- Maintain the top badge, subtitle rectangle, bottom 20% platform reserve, and right 15% UI reserve.
- Use existing safe-zone geometry after scale, and validate all maximum transformed bounds.
- The scale factor is a target, not permission to crop/overflow.
- If a specific graph cannot safely reach 1.30×, compute the largest safe factor and report it. Do not fake a 1.30× setting while leaving geometry unchanged.
- Target the main science-stage height at approximately 45% or more of the full frame where the scene permits, within the 20%–66% region.
- Check phone-sized rendered frames rather than only trusting scene units.

The stage target belongs in configs/theme_config.json. The renderer must actually consume it.

## 7. Ending: slow two-second breathing halo

The current sample ends with a circular critical-nucleus ring held nearly static for about five seconds. Keep the final takeaway but make the final visual feel alive.

- Add a subtle outer orange/resistance halo or ring around the final nucleus.
- Animate a slow breathing pulse with an approximately 2.0-second period (roughly 2–3 cycles over a five-second ending).
- Use restrained changes to radius, stroke width, and/or opacity; keep the central nucleus and critical meaning clear.
- Do not flicker, flash, or use a fast repeated pop.
- Keep the central object and ring within safe bounds at the largest pulse size.
- Preserve the bright-yellow critical marker/meaning; the orange ring is a secondary resistance/interface visual, not a new critical-state color.
- Record the pulse event in the motion manifest and verify frame-to-frame motion throughout the final hold.
- The final line remains the concise memorable takeaway, not model limitations.

## 8. Keep accepted visual work intact

Do not regress:
- correct subcritical return and supercritical descent directions;
- main energy curve opacity 1.0 during threshold explanation;
- orange 2D area/interface representation;
- cyan isometric 3D volume representation;
- formula symbols γ³ orange and Δg_v² cyan, ΔG* yellow;
- bilingual captions and phone-safe region;
- five rhythm blocks and existing claim links.

Do not change scientific claims or the pending Fact Card status.

## 9. Focused test and render plan

Do not make repeated speculative changes. Use one diagnosis-first pass:

1. Inspect latest local render and all available stems. Record sample counts, RMS, peak, and frequency spectra for voice-only, SFX, ambient, and final mix.
2. Build the five gain-matched audio A/B stems described in section 2.2.
3. Disable the default random ambient bed and run focused audio tests.
4. If the voice-only stem is still noisy, diagnose the frequency/time source and run only one justified cleanup A/B. Do not blindly set nr=18 and highpass=110.
5. Implement hook ghost persistence, icon-supported concept stages, term-specific formula pulses, adaptive stage scale, and end halo.
6. Run focused tests for each behavior and pytest -q once.
7. Run project preflight and check configured filters.
8. Render exactly one complete review sample using the Python CLI with --review-sample. Do not run Run_Slice_A.bat or any production BAT.
9. Run ffprobe, full QA, extract actual frames at 0–5 s, 0:20, 0:34–0:42, 0:44–0:56, 0:47–0:52, and 0:57–end.
10. Inspect speech gaps and final MP4 AAC noise spectrum. Verify that no continuous random-noise bed remains.
11. Create gain-matched audio comparison files and a contact sheet, all local and ignored.

Only re-render again if a concrete mandatory QA issue is found. No endless test/render loop.

## 10. GitHub sync and safety boundaries

- Work only on feat/slice-a-english-visual-refinement.
- Keep TASK_PLAN.md unchanged and frozen.
- Keep PR #2 open and in draft state.
- Do not merge, force-push, rewrite history, or update main.
- Do not touch Tuzhidingdong/WeChat_control.
- Keep all recordings, embeddings, WAVs, MP4s, stems, screenshots/frames, caches, models, virtual environments, and local machine configuration ignored and untracked.
- Never upload private voice data or rendered media.
- Preserve active and candidate speaker embeddings.
- Keep Fact Card DRAFT_PENDING_USER_REVIEW and sample status NOT_FOR_PUBLICATION_PENDING_USER_FACT_CARD_REVIEW.
- Do not run production BATs, upload, schedule, or publish.

After implementation, commit only code/tests/config/sanitized documentation and push the target branch without force-push.

Final report must include:
- base/final commit SHAs and GitHub URL;
- changed files;
- stem noise diagnostics and A/B paths;
- confirmation that default ambient bed is disabled;
- final encoded-AAC noise measurements in speech gaps and active speech;
- final LUFS and true peak;
- actual MP4 path, SHA-256, duration, frame count, dimensions, FPS, and codecs;
- tests and QA results;
- actual hook frames, text-free concept visuals, formula-pulse frames, scale measurements, and final halo motion evidence;
- privacy scan and remaining human review items.

Stop after the Slice A sample is ready for the user's listening and viewing. No later milestone or publishing action is authorized.
