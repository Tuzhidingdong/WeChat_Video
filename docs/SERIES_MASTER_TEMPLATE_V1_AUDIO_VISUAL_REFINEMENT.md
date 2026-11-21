# Series Master Template v1 — Audio Clarity, Dimensional Visuals, and Slice A Refinement

**Status:** Authorized implementation specification.  
**Repository:** Tuzhidingdong/WeChat_Video  
**Branch:** feat/slice-a-english-visual-refinement  
**Verified base:** 4240750284d2c9a4ffc64cb28121a48c01be4b6c  
**Scope:** Improve the existing Milestone 1 / Slice A critical-nucleus video and create domain-neutral series-level configuration contracts.  
**Authority:** TASK_PLAN.md V5 remains frozen. This document does not amend V5, waive an AC, authorize Slice B, or authorize Milestone 2/3.

## 1. Goal and current result

The latest recorded bilingual sample is 61.77 seconds, 1080×1920 at 30 fps, with five rhythm blocks, Manim motion, bilingual subtitles, personal OpenVoice voice, SFX, and technical QA PASS.

The user's playback review identifies the next quality gap: the narration still sounds somewhat muffled; the audio bed and SFX lack a polished balance; and the visual language needs stricter physical/dimensional logic and series-wide consistency.

The next sample must deliver:
1. Clearer, more open, intelligible personal voice while preserving the user's timbre and standard US-English pronunciation.
2. A very quiet, non-musical ambient bed through phrase gaps; SFX subtle and subordinate to speech.
3. Dimension-appropriate geometry and mathematically correct scaling; subcritical return and supercritical descent moving in opposite, physically consistent directions.
4. A reusable series master that separates shared visual/audio rules from topic-specific science data.

The deliverable is one new, complete local MP4 and its review package. Config files, mock frames, or tests alone are not completion.

## 2. Concrete implementation defects observed at the verified base

### Audio
- media.py mix_final_audio currently adds SFX to narration only. There is no ambient-bed input or mix stage.
- timeline.py inserts literal zero-valued PCM samples for inter-unit gaps, so the final programme falls into hard digital silence between phrases unless an SFX overlaps.
- The production chain does not implement the proposed high-pass / low-mid cut / presence lift / high-shelf EQ. Current cleanup uses afftdn and the final composite is loudness-normalized.
- SFX use a fixed peak target rather than a level relative to adjacent narration.
- mix_final_audio clips the sum using np.clip and merely reports clipped sample count instead of guaranteeing headroom and failing on unexpected clipping.
- Do not describe broadband compression as an existing filter unless code proves it. Avoid unnecessary heavy compression in this refinement.

### Motion and physics
- visual_stages.py maps SUBCRITICAL_RETURN and SUPERCRITICAL_DESCENT to the same threshold_dynamics stage.
- critical_nucleus.py uses x = 0.7 + 0.8p for both. The alleged subcritical path can therefore cross the critical point instead of returning to the origin.
- The entire shared graph is set to opacity 0.25 for critical-threshold/dynamics stages, dimming the main curve while it is the object being explained.
- area_scaling and volume_scaling both use the same 2D Rectangle. A flat square cannot represent both an area/interface and a volume without a depth representation.
- Formula stages do not consistently color individual symbols by their semantic roles.

Fix these defects in place. Do not redesign the project architecture.

## 3. Reusable, domain-neutral series master

Create and validate two standalone configuration files.

### 3.1 configs/theme_config.json

This is the shared visual master for the 「成核生长」 short-form science series. It must not contain topic-specific scientific claims, formula values, or hardcoded assumptions about one physical system.

Required sections:
- schema_version, theme_id, series_identity
- palette and semantic_roles
- portrait_grid and separate safe rectangles
- subtitle_rules
- dimension_visual_mapping
- hook_pattern
- state_curve_motion
- focus_rules
- motion_accent_rules
- formula_symbol_roles

#### Stable semantic palette

| Meaning | Token | Default colour |
|---|---|---|
| Resistance, loss, interface/activation cost, barrier contributions | resistance | Warm orange |
| Driving force, gain, favorable contribution, catalytic benefit | driving_force | Cool cyan |
| Critical point, threshold, state marker, decisive result | critical | Bright yellow |
| Axes, neutral context, secondary annotation | neutral | Soft white / gray |

Preserve the current project values when appropriate:
- resistance: #F08A5D
- driving_force: #61D6C8
- critical: #FFD166
- neutral: #F4F7FB

Formula symbol-to-role mapping must be topic data, not hardcoded assumptions in a generic renderer. For the current nucleation example:
- γ and positive surface/interface cost: orange.
- Δg_v as positive bulk-driving-force magnitude: cyan.
- r*, ΔG*, threshold marker, and decisive critical state: yellow.
- Formula terms and their corresponding animated objects must inherit the same semantic color tokens.
- Use separated MathTex parts or equivalent so an individual term can be highlighted without recoloring unrelated symbols.

#### Portrait grid

Define normalized percentage regions:
- Top series badge: 10%–16% of frame height. Example only: CLASSICAL NUCLEATION · 经典成核. This is a small identifier, never a full title card.
- Main science stage: 20%–66% of frame height. Target at least 45% of total frame height where composition permits; calculate bounds from the rendered frame.
- Bilingual subtitle block: 68%–78% of frame height, English above Chinese.
- Bottom 20% reserved for platform UI.
- Right 15% reserved for platform interaction controls.
- Preserve symmetric 15% left science margin where applicable.
- Keep the badge, science stage, and subtitle block in separate layout regions. Scale pulses, formula highlights, and subtitles must not collide.

Maintain separate safe rectangles for the main science visual and subtitles.

#### Subtitle rules
- English spoken narration and English caption on line one.
- Simplified Chinese translation on line two.
- Both lines use the same cue timestamps.
- Maximum six English words per displayed line and twelve Chinese characters per line.
- Exactly two intended language lines per cue; do not permit automatic wrapping into four or more lines.
- Keep phrase-level timing. Do not invent word-level karaoke timestamps.
- Validate Latin and CJK font files and glyph coverage independently.

#### Dynamic binary hook
The first three seconds show a dynamic binary contrast, never a static text/title slide:
- Failure / metastable / shrinking path: left side or first beat; visibly fails, contracts, or extinguishes.
- Stable / successful / growing path: right side or second beat; visibly persists, grows, or progresses.
- Use one matched comparison frame and common scale reference.
- Visible motion starts at frame zero. Preserve the V5 0–1000 ms cover segment, but it is active visual content, not a static title card.
- First spoken hook totals six to eight English words. When a mid-line pause is wanted, split the clauses into separate phrase units so each retains one audio chunk and one bilingual cue.
- Current sample suggestion: “Tiny seeds fade—” / “larger crystals grow.” Use two three-word units with a 300 ms pause between them.
- A small persistent series badge is acceptable. No long explanatory sentence on the hook screen.

### 3.2 configs/audio_postprocess.json

This is the reusable audio master. Separate voice cleanup, voice EQ, speech headroom, SFX, ambient bed, and final programme loudness.

#### Voice EQ preset: voice_clarity_v1

Use the user's proposed values as the initial testable preset:

1. High-pass: 85 Hz, gentle second-order response or equivalent verified slope.
2. Low-mid reduction: 300 Hz, Q=1.5, gain=-2.5 dB.
3. Presence / consonant clarity: 4000 Hz, Q=1.2, gain=+3.0 dB.
4. Air shelf: 9500 Hz, gain=+2.0 dB.

Equivalent FFmpeg filter chain:

highpass=f=85,equalizer=f=300:t=q:w=1.5:g=-2.5,equalizer=f=4000:t=q:w=1.2:g=3,highshelf=f=9500:g=2

Safeguards:
- Verify that every filter and option exists in the installed project FFmpeg build.
- Keep all values in JSON, not buried in Python string literals.
- Generate a same-text A/B comparison: current flat/denoise-only voice versus voice_clarity_v1. Keep both WAVs locally.
- Use acoustic measurements and spectra to determine whether the issue is excess 250–350 Hz energy, weak 3.5–5 kHz presence, weak 9–10 kHz air, conversion noise, clipping, or another cause. Do not claim spectral diagnosis from listening notes alone.
- Treat these settings as a starting preset, not an unchangeable setting for every speaker or future TTS voice. Provide bounded per-band overrides.
- Check for harsh sibilants, brittle consonants, hiss, and metallic artifacts after the 4 kHz / 9.5 kHz boosts. If the candidate becomes harsh/noisy, make a documented small adjustment and preserve both variants.
- Never change the original M4A, active speaker embedding, or existing candidate embedding.
- Do not loudnorm each voice chunk and then loudnorm the final programme again. Cleanup/EQ occurs before timing; final full-programme loudness normalization occurs once after all tracks are mixed.

#### Voice headroom and dynamics
- Pre-mix voice sample-peak ceiling: approximately -3 dBFS. This is a ceiling, not a command to amplify every phrase to -3 dBFS.
- Prefer transparent static gain adjustment. Do not introduce aggressive compression, pumping, or over-limiting.
- Use a limiter only as a safety stage if the real combined mix needs it; report gain reduction and true peak.
- Preserve consonant attacks and speech-unit tails.
- Final AAC programme remains targeted at -16 LUFS integrated and -1.5 dBTP true-peak ceiling, measured after encoding.

#### SFX balance
- Replace fixed SFX peak scaling with a relative level control.
- Each SFX should be approximately 12–15 dB below the local active narration level; default target around -13.5 dB relative to local speech loudness/RMS.
- Measure the adjacent speech segment or a short local active-speech window. Do not compare SFX peak to the whole-video voice peak.
- Prefer soft, low-frequency pulse / subtle whoosh cues. Avoid sharp bright bubble/pop transients and excess high-frequency energy.
- Use only a few effects at meaningful visual changes, not every particle/subtitle/word.
- Record target level, measured level, gain, peak, and timing per SFX event.
- Reduce SFX when headroom is insufficient; do not clip or raise the voice.

#### Ambient bed
- Add a subtle, continuous, original, locally generated ambient bed. No copyrighted sound-pack assets, recognizable melody, distracting beat, or speech-like texture.
- Starting target: approximately -30 dBFS RMS as a standalone bed; configurable range -33 to -30 dBFS RMS.
- Use a soft low-hiss texture or restrained low-level technological pad. Avoid bright high-frequency noise.
- Keep it continuous through phrase gaps and comprehension pauses. The voice-only narration stem may retain exact zero-valued pause samples, but the final programme must not fall into hard digital silence while ambience is enabled.
- Duck gently under active narration (default about 3–4 dB), restore smoothly in gaps, and avoid audible pumping.
- Add short programme-boundary fade-in/out and use a seamless loop or deterministic full-length bed.
- Report measured RMS, duration, fade, and ducking.
- Provide an explicit config option to disable ambience for topics where it would interfere with science or deliberate silence.

#### Single audio processing order
1. MeloTTS EN-US synthesis.
2. OpenVoice V2 personal timbre conversion.
3. Existing conservative denoise path, only where measured benefit remains valid.
4. Configured clarity EQ.
5. Verify sample rate, channels, frame count, peak, clipping, and duration; enforce the voice peak ceiling.
6. Use cleaned/EQ'd WAV as timing authority.
7. Build global timeline with exact speech and intentional silence segments.
8. Mix local SFX relative to adjacent narration.
9. Mix/duck optional ambient bed.
10. Apply final full-programme loudness normalization once; encode AAC 192 kb/s; verify post-encode loudness/true peak.

If any filter changes sample count or duration, measure the processed file and use its samples as timing authority.

## 4. Dimensionally correct visual grammar

Create a generic mapping from physical dimensionality/scaling law to visual geometry. Topic data declares the appropriate mapping.

| Physical dimension / law | Required visual form |
|---|---|
| 1D / linear, ∝ L or t | Line segment, vector arrow, ruler, or one-dimensional progress indicator |
| 2D / area/interface, ∝ r² or A | Plane, polygon, annulus, ring, or highlighted surface layer |
| 3D / volume/bulk, ∝ r³ or V | Isometric cube, depth-shaded solid, or sphere/voxel with visible depth cues |

Requirements:
- Do not use the same flat 2D rectangle for area and volume.
- A 3D quantity needs visible depth cues, such as a three-face isometric solid, even if rendered in the existing 2D Cairo scene. Do not add an expensive 3D camera just to draw an isometric symbol.
- Geometric dimensions and exponent must match. If characteristic length doubles, a 1D line doubles, a 2D area grows by four, and a 3D volume grows by eight. Preserve the relationship in the visual data or label a normalized representation.
- For the current nucleation scene, use an orange surface/interface ring or membrane for the 2D surface term and a cyan isometric solid/sphere for the 3D bulk volume contribution, with the same radius parameter.
- Use the actual model expression. Under current dimensionless CNT normalization show ΔG/ΔG* = 3x² − 2x³, surface contribution +3x² in orange and bulk contribution −2x³ in cyan, with x = r/r*. Do not confuse equality of the two contribution magnitudes with the critical radius; the total free-energy maximum is at x=1.
- Keep signs visible: positive surface cost and negative bulk free-energy contribution must not both be drawn as positive costs.
- Add reusable mapping fields to topic data: quantity_id, symbol, physical_dimension, scaling_exponent, visual_geometry, semantic_role, sign_or_polarity, normalization.
- Keep the global theme domain-neutral. Future topics provide formulas and mapping data from their own approved Fact Cards.

## 5. State-curve animation: direction and focus contracts

### Main curve and focus
- The currently explained main curve/structure remains at 100% opacity.
- Keep the energy landscape curve at opacity 1.0 during landscape, critical-peak, subcritical, and supercritical stages.
- Axes may be softened if secondary, but never dim the curve itself.
- Only inactive helper labels, distant context, and unrelated background may be dimmed to about 0.25.
- The marker and currently explained point remain fully visible.
- A focus change must never push the primary structure into the background.

### Separate subcritical and supercritical paths

Do not map both triggers to the same undifferentiated marker path.

**Subcritical return**
- Dedicated SUBCRITICAL_RETURN stage/event.
- Marker begins left of the critical point (0 < x < 1), advances toward the peak but never crosses x=1, then reverses and returns toward the origin/small-radius side.
- During return, marker shrinks and disappears near the origin.
- y is always calculated from the same displayed curve ΔG/ΔG* = 3x² − 2x³.
- This is a thermodynamic tendency, not a guaranteed microscopic trajectory or time-resolved growth rate.

**Supercritical descent**
- Dedicated SUPERCRITICAL_DESCENT stage/event.
- Marker begins just right of the critical point (x > 1) and travels toward the large-radius endpoint.
- It must not pause/orbit at the peak; it moves downhill as x increases.
- Use monotonic accelerating easing (e.g. p²) so visual motion accelerates to the endpoint.
- y is always calculated from the same displayed curve.

Extend motion_event_manifest.json with start/end x/y, direction, threshold x=1, expected monotonic interval, easing profile, marker scale/fade endpoints, required graph/marker opacity, and exact global sample/frame boundaries.

Automated tests must prove the subcritical path does not cross x=1, reverses, reaches the origin side, shrinks, and fades; the supercritical path starts x>1, increases monotonically and accelerates; both stay on the same curve; main curve opacity remains 1; marker remains visible during motion. A manifest event name alone is not proof.

## 6. Formula-color linkage and focus

For every topic, formula symbols and corresponding geometric contributions share semantic tokens.

Current nucleation example:
- γ / surface-energy term: orange.
- Δg_v / bulk driving-force magnitude: cyan.
- r*, ΔG*, critical-radius marker: yellow.
- In ΔG* = 16πγ³ / (3Δg_v²), highlight γ³ orange and Δg_v² cyan while ΔG* remains yellow as the critical barrier quantity.

When narration switches terms, briefly pulse/highlight the matching formula subobject and physical visual. Keep the active formula/curve/structure fully opaque; dim only non-focus context to about 25%. On-screen copy remains short; explanation belongs in narration and bilingual captions.

## 7. Specific Slice A hook and script update

Apply the dynamic binary hook to the current critical-nucleus sample:
- Frame zero shows matched comparison zones or two sequentially contrasted states, not a static title.
- Left/first: a subcritical seed assembles briefly, contracts, and disappears.
- Right/second: a larger seed assembles and continues growing.
- Use the same visual style and scale reference.
- Keep the series badge small and unobtrusive.
- First narrated hook totals six to eight English words, in two short clauses separated by about 300 ms. Suggested two-unit wording: “Tiny seeds fade—” / “larger crystals grow.”
- English and Chinese subtitle cues remain synchronized. Do not make one long subtitle while hiding a 300 ms audio gap inside it.
- Preserve the five rhythm blocks and existing Fact Card claim IDs. Split speech units so English subtitle lines contain at most six words and Chinese lines at most twelve characters.
- End with a memorable scientific takeaway, not a limitations slide.
- Put the thermodynamic-vs-kinetic caveat before the final takeaway.

## 8. Reusable topic-data contract

Keep global series master separate from topic-specific content.

A new topic should be expressible through data fields:
- approved Fact Card claim IDs and evidence links;
- bilingual phrase-level narration/subtitle lines;
- a hook object with failure/success states, visual actions, and timing;
- scaling_relations with symbol, expression, dimensionality, exponent, geometry, sign, and color role;
- optional state_transition with curve definition, threshold, below-threshold path, above-threshold path, and endpoint;
- rhythm block and visual trigger IDs.

This implementation applies these contracts only to the existing critical-nucleus template. Do not build a catalyst, battery, phase-transition, or any new scene template in this task. Do not add claims without supporting Fact Card claims. The reusable configuration remains domain-neutral.

## 9. QA requirements

Extend qa.py, focused tests, and run reports to validate configuration and actual output.

### Audio
- Effective EQ chain matches the selected audio_postprocess.json preset.
- Filter availability is verified in the installed FFmpeg build.
- Processed voice sample count/duration are measured; no unexplained timing change.
- Voice sample peak does not exceed configured -3 dBFS pre-mix ceiling.
- SFX level is measured relative to adjacent voice and stays in configured -12 to -15 dB range.
- Ambient bed remains continuous through intended gaps when enabled; measured RMS near -30 dBFS target.
- Final mix has zero clipped samples before encoding; unplanned clipping is a QA failure.
- Final AAC remains within -16 LUFS / -1.5 dBTP after encoding.
- Preserve flat-vs-EQ A/B and exact filter settings.
- Do not infer voice/SFX balance from one whole-track peak.

### Visual
- No static title-only card in first three seconds.
- Hook visibly contains failure and success paths.
- Central stage occupies at least 45% of frame height where composition permits and remains within 20%–66% band.
- Badge, subtitles, bottom 20%, and right 15% UI reserve are respected.
- Subtitle lines remain within six English words and twelve Chinese characters.
- Formula-symbol colors match semantic term roles.
- 1D/2D/3D geometry follows configured dimensional mapping.
- Main energy curve stays fully opaque during threshold motion.
- Subcritical marker returns left and fades; supercritical marker moves right and accelerates.
- Inspect actual rendered MP4 frames at hook, term competition, scaling, critical peak, both threshold paths, and ending.
- Frame-to-frame differences within each block must prove actual movement; transition fades alone do not count.

### Human review
Automated checks cannot decide whether the voice sounds open/natural/recognizable, EQ crisp rather than harsh, ambience perceptible but unobtrusive, SFX balanced, and subtitles comfortable on a real phone. Keep these checks explicitly pending in REVIEW.md.

## 10. Required code/configuration changes

Implement focused updates:
- configs/theme_config.json — reusable series theme.
- configs/audio_postprocess.json — configurable audio master.
- configs/layout.json — align Slice A to theme grid; retain explicit safe zones.
- content/sample_script.en.json — hook split, subtitle length, bilingual wording, rhythm/claim links.
- voice_worker.py and tts.py — configurable clarity EQ after conversion/cleanup; preserve active/candidate profiles; create flat-vs-EQ A/B; record actual filter chain.
- timeline.py — preserve exact zero-valued voice-pause segments as timing data while exposing ambience regions and unchanged global origin.
- sfx.py — softer event tones/transients and configured level behavior.
- media.py — mix narration, relative-level SFX, optional continuous ambient bed; smooth bed ducking; report gain/headroom/clipping; never silently clip.
- critical_nucleus.py and visual_stages.py — binary hook, dimensional forms, formula colors, distinct marker paths, correct focus opacity, motion manifests with expected paths.
- qa.py — validate config, audio balance, ambience, marker paths, geometry, safe zones, and actual render evidence.
- README.md, STATUS.md, and sanitized progress snapshot — document the reusable master and actual result.

Do not rewrite the project or add template families. Preserve local toolchain, OpenVoice V2 CPU runtime, bilingual subtitles, exact sample-count timeline, and Windows compatibility fixes.

## 11. Focused validation and one complete render

Avoid endless loops:
1. Inspect current final MP4 and existing voice A/B locally; do not upload.
2. Run one targeted audio analysis and one same-text flat-vs-EQ A/B render.
3. Run focused tests for config, voice DSP, sample count, SFX-relative level, ambient continuity, and marker direction.
4. Run pytest -q once after implementation.
5. Run project preflight and verify every configured FFmpeg filter.
6. Render exactly one complete Slice A review sample through the Python CLI with --review-sample. Do not run Run_Slice_A.bat or other production BAT.
7. Run ffprobe and full QA on the real MP4.
8. Extract actual frames at hook, dimensional comparison, formula highlight, free-energy peak, subcritical return, supercritical descent, subtitle blocks, and ending.
9. Create a phone-sized preview/contact sheet, local and ignored.
10. Re-render only for a concrete mandatory failure. Do not repeat successful tests without reason.

## 12. Scope, privacy, GitHub sync, and handoff

- Work only on feat/slice-a-english-visual-refinement.
- Do not change TASK_PLAN.md, main, PR base, or PR merge state.
- Do not enter Slice B, Milestone 2, or Milestone 3.
- Do not modify WeChat_control or its browser profile.
- Zero new budget; no online TTS, cloud voice processing, paid APIs, extra Flow credits, or new hardware.
- Keep recordings, embeddings, A/B WAVs, rendered WAV/MP4, extracted frames, model weights, caches, .venv, portable tools, and local config ignored and untracked.
- Preserve the active voice profile/fingerprint; do not replace without approval.
- Keep the Fact Card DRAFT_PENDING_USER_REVIEW; result remains NOT_FOR_PUBLICATION_PENDING_USER_FACT_CARD_REVIEW.
- Do not run production BATs, upload, schedule, or publish.

After implementation:
- Commit only source code, tests, reusable JSON configuration, and sanitized documentation.
- Inspect staged diff and commit for private/media/model artifacts.
- Push to feat/slice-a-english-visual-refinement without force-push.
- Leave PR #2 open and draft.

Final report:
1. Base and final commit SHA / GitHub URL.
2. Changed files and concise implementation result.
3. pytest -q, preflight, focused audio test results.
4. Flat-vs-EQ A/B paths and exact EQ parameters.
5. Ambient-bed level, SFX-relative level, voice peak ceiling, final LUFS and true peak.
6. Actual final MP4 path, SHA-256, duration, frame count, resolution, FPS, codecs.
7. Proof from actual frames of binary hook, dimensional mapping, main-curve opacity, opposite marker paths.
8. QA report and pending human checks.
9. Privacy scan proving no voice/media/model/cache/local-only files committed.
10. Explicit statement that user playback, voice-quality acceptance, phone review, and Fact Card approval remain pending.

Stop after the Slice A review candidate. No upload, publication, new template, or later milestone is authorized.
