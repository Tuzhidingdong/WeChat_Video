# Slice A quality upgrade — bilingual short-form storytelling, clean personal voice, and dynamic physics animation

**Status:** Authorized implementation specification for the next Slice A refinement.  
**Baseline branch:** feat/slice-a-english-visual-refinement  
**Baseline sync commit:** b70e4ca1d453376e8846cc4ce0e802015bef7312  
**Scope:** Milestone 1 / Slice A only — the existing critical-nucleus / free-energy-barrier sample.  
**Authority:** TASK_PLAN.md V5 remains frozen and authoritative. This document adds implementation detail for the user's latest quality requirements; it does not amend or replace V5, waive an AC, or authorize Slice B, Milestone 2, or Milestone 3.

## 1. Objective and acceptance outcome

Upgrade the existing Slice A production path so the next complete review sample is a genuinely engaging, approximately one-minute vertical science animation with:

1. A clean, intelligible, standard-US-English personal voice that preserves the user's timbre.
2. Synchronized English + Simplified Chinese subtitles with phone-readable typography and platform-safe placement.
3. A short-form narrative built around an immediate counter-intuitive hook, five rhythm blocks, and 10–15 second micro-climaxes.
4. Continuous, physically meaningful Manim animation rather than mostly static stage cards.
5. Subtle sound cues, object-scale/zoom accents, and deliberate 0.5–0.8 second comprehension pauses at selected scientific turning points.
6. A real-world relevance bridge and memorable final line without ending on model limitations.
7. The existing global sample/frame timing, scientific evidence chain, and strict no-publication boundary.

The deliverable is one newly rendered, complete local MP4 and its review package. Updating documentation or making a storyboard preview is not completion.

## 2. Frozen boundaries and privacy

- Do not edit, regenerate, reformat, or otherwise change TASK_PLAN.md.
- Work only on feat/slice-a-english-visual-refinement and its existing Draft PR #2. Do not modify main, merge the PR, force-push, or rewrite history.
- This remains Slice A. Do not build the other four templates, Flow integration, topic pool, Edge/CDP, WeChat upload, daily BAT, scheduling, or publication.
- The separate Tuzhidingdong/WeChat_control repository, its files, credentials, browser profile, and automation must remain completely untouched.
- Zero additional budget: no paid APIs, subscriptions, TTS, Flow credits, OpenCode extra usage, or hardware. No online TTS or cloud voice processing.
- Keep processing CPU/local/offline. Reuse the installed project-local Manim, FFmpeg, MiKTeX, MeloTTS, OpenVoice, and Python environments wherever possible. Do not download a large new model or install global software merely to avoid diagnosing the current pipeline.
- The authorized voice recording already exists at E:\Agent\WeChat\Video\my_voice\voice.m4a. Do not ask the user for its location again.
- Preserve the original recording and current production embedding. Never overwrite either silently. Any filtered reference, candidate embedding, or candidate output must be written to a separate ignored path under private/voice_profile/.
- Never commit, push, attach, or upload recordings, embeddings, cloned audio, generated WAVs, model weights, model caches, MP4s, extracted frames, screenshots containing private data, or machine-specific configs. Ensure .gitignore covers all candidate paths.
- Keep OpenVoice watermark/message behavior intact.
- No hidden workers, recursive agents, paid fallback, or network calls.
- The candidate Fact Card is still DRAFT_PENDING_USER_REVIEW. The rendered sample must remain NOT_FOR_PUBLICATION_PENDING_USER_FACT_CARD_REVIEW. Do not approve the Fact Card or imply scientific acceptance.
- The Agent may run automated tests and one controlled review-sample render through the Python CLI with --review-sample. It must not run Run_Slice_A.bat or any production BAT as a substitute for the user's own final acceptance. Never upload or publish.

## 3. Verified current baseline and concrete gaps

The latest GitHub progress snapshot records a real 60.8 s MP4 at 1080×1920 / 30 fps / yuv420p / SAR 1:1, with the existing QA status PASS and 12 previous pytest tests passing. It also records the following unfinished issues:

- The OpenVoice V2 + MeloTTS EN-US CPU enrollment and conversion path exists and has run, but voice cleanliness and naturalness have not been accepted by listening.
- There is no dedicated denoising stage. The reference M4A is converted to 16 kHz mono WAV without noise reduction; converted speech is copied to the production audio directory without cleanup.
- Subtitles are English-only, use one font, and have not passed phone readability review.
- The current scene has a static camera and mostly static holds with FadeIn/FadeOut transitions. It does not yet provide the requested continuous physical-motion explanation.
- The 280 ms inter-unit pause is fixed; there are no configurable 0.5–0.8 s comprehension pauses or synchronized SFX events.
- The video currently ends on model assumptions/limitations rather than a memorable practical takeaway.
- The code/reporting path is inconsistent: pipeline.py writes an audio_manifest engine label of sherpa-onnx even when tts.py has actually invoked the MeloTTS EN-US → OpenVoice V2 personal-voice worker. preflight.py and the README also continue to present Piper/sherpa as the default model path, while the documentation says personal OpenVoice is the daily voice.
- tts.generate_speech_units can fall through to the legacy sherpa model when the personal profile file is absent. That is inconsistent with the selected personal-voice default and must not silently produce an anonymous voice.

Relevant current modules include:
- src/wechat_video/voice_worker.py and tts.py — enrollment, conversion, speech output, and engine selection.
- src/wechat_video/pipeline.py — orchestration and manifests.
- src/wechat_video/timeline.py and media.py — sample-count timing, pauses, audio assembly, SFX mixing.
- src/wechat_video/subtitles.py and preflight.py — bilingual captions and font discovery.
- configs/layout.json — portrait safe zones, typography, palette.
- content/sample_script.en.json — script, speech-unit and claim links.
- src/wechat_video/scenes/critical_nucleus.py and visual_stages.py — animation and stage timing.
- src/wechat_video/qa.py — evidence-backed validation.
- README.md and STATUS.md — user-facing state and acceptance boundary.

Preserve working local tooling and compatibility fixes. Do not replace the project architecture wholesale.

## 4. Editorial and timing specification

### 4.1 Five rhythm blocks

Use five explicit narrative blocks, with measured timing guided by the target duration of 55–65 seconds:

| Block | Target time | Editorial purpose | Required visual event |
|---|---:|---|---|
| Hook | 0–5 s | Counter-intuitive observation and open question; no static title card | A tiny nucleus visibly forms and dissolves while a slightly larger one persists or grows |
| Conflict | 5–20 s | Introduce the opposing surface-energy cost and bulk free-energy gain | Two competing contributions animate simultaneously with distinct semantic colors |
| Mechanism / reversal | 20–40 s | Explain r² versus r³, then reveal the free-energy maximum and critical radius | Live contribution curves/bars change; total free-energy curve draws; critical marker appears |
| Real-world relevance | 40–55 s | Explain what the threshold means when controlling crystal formation; include the required thermodynamic caveat before the final takeaway | The nucleus marker crosses the threshold and follows the downhill branch; connect to controllable crystal growth |
| Takeaway | 55–60 s | One memorable, concise conclusion designed to be remembered/shared | A clean visual resolves to the central principle; no end-card lecture |

The 0–1000 ms cover is a frozen V5 timeline requirement, not permission for a static title page. Preserve the explicit cover segment and first narration at/after 1000 ms, but make the visual from frame one an active hook (particle/seed motion). Do not show a static title-only card during the first three seconds. The title may appear later as a small corner identifier or be integrated unobtrusively after the hook.

Suggested opening direction, subject to the current Fact Card:
“A tiny crystal seed can dissolve—while a slightly larger one grows. What changes?”
This is a hook, not a new scientific claim beyond the current CNT-04 scope. The opening should use a concrete visible seed/particle rather than a definition or “Today we will discuss…” introduction.

Suggested final-line direction:
“A crystal’s future can hinge on a radius too small to see.”
Use a natural, accurate Chinese translation in the second subtitle line. The Agent may polish the English and Chinese wording, but must not add unsupported claims.

### 4.2 Micro-climaxes and pacing

- Create clear attention resets or visual reversals at approximately 10–15 second intervals, not just at the eight old script checkpoints.
- At minimum, explicitly mark the hook, the surface-vs-bulk conflict, the r²/r³ crossover, the critical-radius peak, and the final practical takeaway in an editorial-beat manifest.
- Every block must end with either a short conclusion, a visual reversal, or a meaningful new state.
- Do not keep one static illustration on screen for a whole speech block.
- A deliberate 0.5–0.8 second visual/audio breathing pause is required after the principal equation or critical-radius conclusion and may be used after one other key result. During the pause, leave the result visible with only subtle motion. Do not fill every pause with narration.
- Other speech-unit gaps may remain short (about 180–280 ms) unless the measured narration requires adjustment.
- Do not stretch audio, alter speech rate to force duration, duplicate video frames, or add meaningless silence. The complete measured result must remain in the 55–65 s preferred range; otherwise revise useful narration and report the measured result honestly.

### 4.3 Phrase-level narration units

The existing eight long speech units are too coarse for short-form captions and attention changes. Divide the English narration into phrase-sized units, targeting roughly 16–22 units if the measured speaking rhythm supports it.

Each unit still owns exactly one real audio chunk and one bilingual subtitle cue, preserving V5 AC-08/AC-09/AC-10 behavior. Do not fabricate word-level timings. Keep pauses and the global sample-count timeline authoritative.

For each speech unit, retain:
- unit_id
- raw_text (English source narration)
- display_text (English subtitle line)
- spoken_text (English TTS text)
- display_text_zh (Simplified Chinese subtitle line)
- claim_ids (only IDs that already exist in the Fact Card)
- visual_trigger_ids
- rhythm_block_id (HOOK / CONFLICT / MECHANISM / APPLICATION / TAKEAWAY)
- optional short visual_keyword
- optional pause_after_ms for selected comprehension pauses
- optional sfx_trigger_id or editorial event reference

Do not put explanatory paragraphs on the canvas. Manim scene labels should be short keywords, symbols, and formulas. Screen labels should not contain a sentence or exceed about 15 Chinese characters / a few concise English words. Subtitles are the explicit exception because they reproduce the spoken phrase.

## 5. Scientific integrity and narrative content

The current Fact Card and source record remain the only authority for scientific claims in this Slice A video. Preserve its scope and caveats:

- Classical homogeneous nucleation and a spherical nucleus.
- Positive interfacial-energy cost and negative bulk free-energy gain.
- ΔG(r) = 4πr²γ − (4/3)πr³Δg_v.
- γ > 0; Δg_v is the positive magnitude of the bulk free-energy driving force.
- Surface term scales as r²; bulk contribution magnitude scales as r³.
- r* = 2γ / Δg_v.
- ΔG* = 16πγ³ / (3Δg_v²).
- Below r*, shrinking is thermodynamically favored in this model; above r*, increasing radius lowers total free energy.
- This is a thermodynamic tendency, not a prediction of growth speed. Diffusion, transport, interface structure, kinetics, fluctuations, and model assumptions remain relevant.
- The classical expression assumes a spherical nucleus, homogeneous nucleation, a sharp interface, and isotropic curvature-independent interfacial energy.

Do not imply that crossing r* guarantees instantaneous growth or that the curve directly describes a real-time reaction rate. The moving dot/ball is a schematic marker on a free-energy landscape, not a literal mechanical ball or an atomistic trajectory.

Move the caveat “thermodynamic tendency, not a speed prediction” into the mechanism/application block before the final 5 seconds. Do not end the video with “model limitations,” assumptions, or caveats.

For the real-world bridge, explain the practical value of controlling the first stable nucleus in crystal formation/materials synthesis. Do not make specific claims about batteries, chips, industrial yields, or a named material unless that claim is already supported by the current Fact Card or is separately sourced and added for user review. Do not invent a new application fact merely to make the ending sound impressive.

Preserve the Fact Card status as DRAFT_PENDING_USER_REVIEW. Do not change its approval fields.

## 6. Personal voice: diagnose and clean without losing timbre

The goal is not a generic “noise-free” voice that loses the user's identity. The goal is the existing personal timbre with a clear, dry, stable, machine-generated sound and standard US-English pronunciation.

### 6.1 Locate the noise source before choosing a filter

Produce a local diagnostic report (no private audio uploaded) that compares these stages using the same test sentence:

1. Original authorized M4A recording.
2. Current 16 kHz mono reference WAV produced by FFmpeg.
3. A filtered reference candidate, if a measurable noise floor is present.
4. Existing personal-voice embedding + MeloTTS EN-US → OpenVoice V2 output.
5. MeloTTS EN-US base output before conversion.
6. Converted output with conservative post-cleanup, if useful.
7. Final assembled narration before AAC and encoded AAC.

For each available stage, record only non-sensitive technical metrics in the review package: sample rate, channels, frame count, duration, peak, clipping count/ratio, RMS/noise-floor estimate where measurable, and processing time. Do not include transcripts of the user's original recording or local absolute file paths.

Distinguish source-recording noise, voice-conversion artifacts, clipping, room reverberation, and encoding/mix problems. Do not assume that every audible artifact comes from the reference recording.

### 6.2 Local processing candidates

- Inspect the actual project FFmpeg filter list and existing Python dependencies before selecting a denoiser. Check whether local filters such as afftdn, anlmdn, or arnndn are actually present; do not assume availability.
- Prefer a gentle, deterministic, CPU/offline process using already-installed tools. Avoid downloading a large neural model unless there is no acceptable existing local solution and the Agent can justify the cost/storage/runtime.
- Create separate candidate files. Never change the original M4A or the currently active target_se.pth.
- If reference cleanup is beneficial, create a filtered-reference candidate and extract a candidate target embedding into a separate private candidate directory. Do not silently replace the active profile.
- Test a conservative post-conversion cleanup path as a separate candidate. Keep the unprocessed converted WAV so the user can A/B compare.
- Process voice chunks consistently; do not use aggressive gates that chop syllable tails, remove unvoiced consonants, create pumping, or change the perceived speaker.
- Any filter applied before timing must preserve the intended audio duration and sample boundaries, or the cleaned output must be remeasured and become the new timing authority.
- Do not add speed change, time stretching, automatic speech normalization that alters prosody, or fabricated pauses.
- Keep the official OpenVoice watermark/message behavior.

### 6.3 Voice-profile safety and engine selection

- Use the current personal profile by default. Keep a candidate profile separate until the A/B result is generated and can be reviewed.
- The user's recording is already authorized for this task; do not ask for another recording or ask where it is stored.
- Do not silently re-run enrollment into the active profile. If a candidate embedding is created, record its fingerprint privately and keep the old profile intact.
- The daily Slice A path must use MeloTTS EN-US → OpenVoice V2 with the selected personal target embedding. If the personal profile/runtime is absent or invalid, fail closed with a clear message. Do not silently fall back to Piper, sherpa-onnx, or a generic voice.
- Keep Piper and the legacy Chinese sherpa/MeloTTS model files for diagnostics/rollback only; do not delete them.
- Update preflight and documentation so the default voice, the model actually used, and the required runtime/profile are consistent.
- Fix pipeline.py's hard-coded audio_manifest engine label. The manifest must report the actual per-unit engine, CPU provider, base speaker, model revision, profile fingerprint, cleanup steps, and true duration/sample metadata. Never label an OpenVoice-generated WAV as sherpa-onnx.
- The normal production path must not require a generic Piper model merely because it was the former default. If a legacy diagnostic path is retained, it must require an explicit opt-in and must be clearly marked as non-default.

### 6.4 Voice listening deliverable

Provide local A/B assets for:
- Existing active profile, original conversion.
- Best candidate cleanup/profile path.
- Optional clean MeloTTS base reference solely as a diagnostic comparison.

Use the exact same short English text and matching levels. Record the variant processing chain in a private/local manifest. Do not call the candidate “better” or “accepted” without the user's listening judgment.

The complete MP4 must use the best conservative personal-voice path found by objective checks. If no candidate measurably improves cleanliness while preserving usable timbre, keep the active personal profile, report the unresolved limitation, and do not disguise it with a generic voice.

## 7. Bilingual subtitle and vertical layout specification

### 7.1 Content and timing

- English remains the spoken language and the top subtitle line.
- Simplified Chinese is a faithful, concise translation on the second line.
- Both lines appear and disappear together for each speech unit.
- The two lines share the exact same measured global start/end timestamps; do not create a second independent timeline.
- Split speech units at natural phrase/stress boundaries so captions appear with the voice rhythm. Do not split words or Chinese phrases unnaturally.
- Keep one phrase-level cue per speech unit, not word-by-word karaoke unless genuine word timestamps are available and validated.
- Chinese translation must preserve negation, qualifiers, thermodynamic-vs-kinetic distinctions, equations, and variable sign conventions. It must not add facts absent from the English narration.
- Establish a small bilingual glossary for key terms:
  - nucleation — 成核
  - nucleus — 晶核
  - critical radius — 临界半径
  - interfacial energy — 界面能
  - surface-energy cost — 表面能代价
  - bulk free-energy gain — 体相自由能收益
  - free-energy barrier — 自由能垒
  - homogeneous nucleation — 均匀成核
  - thermodynamic tendency — 热力学趋势
  - growth kinetics — 生长动力学
- Use the same glossary consistently in captions and the review script.

### 7.2 Visual layout

- 1080×1920, 9:16, 30 fps remains unchanged.
- Preserve the 15% right-side interface reserve and symmetric side margins for the scientific content. Caption width must remain inside the safe horizontal content area.
- Reserve the bottom 20% for the platform interface. Center the bilingual subtitle block approximately 25% of frame height above the bottom edge (roughly 70–78% down from the top), and keep the entire block above the bottom UI reserve.
- Expand the existing narrow subtitle band enough to hold two readable lines without overlapping the science graphic. Use a clearly defined subtitle-safe rectangle in configs/layout.json and test its screen coordinates.
- English appears first/top; Chinese appears second/below. Use two explicit font families if needed: a Latin font with good English rendering and a CJK font that actually contains Simplified Chinese glyphs.
- Extend preflight to discover and validate Latin and CJK fonts separately. The current layout lists Arial/Segoe UI/Aptos but does not explicitly guarantee CJK glyph coverage. Do not mark the same Latin font as a valid Chinese font without verifying glyphs.
- Prefer an already installed local CJK font such as Microsoft YaHei or another font found on the machine. Do not install system-wide fonts or change PATH/registry.
- For 1080×1920 output, start with a legible two-line design around 38–44 px English and 42–48 px Chinese, then verify by actual rendered frame. Tune outline/shadow/background and line spacing conservatively; do not let subtitles dominate the entire screen.
- Aim for no more than 12 Chinese characters per subtitle line. Keep each English phrase to one short line where practical (approximately 30–36 Latin characters); split the speech unit if it cannot be read cleanly.
- A two-line English/Chinese cue must not wrap into four or more lines. If it does, shorten/resegment while preserving meaning.
- Make the subtitle background/outline sufficiently clear against both dark and bright animation elements. Avoid excessive opaque boxes.
- Subtitle position, size, and line count must be inspected on actual output frames and a phone-sized preview, not accepted from JSON geometry alone.

## 8. Dynamic physical-intuition animation

The scene must stop looking like a sequence of static PowerPoint cards. Use Manim vector objects, curves, trackers, and particles already available in the project. Keep the existing critical-nucleus template; do not introduce a new template family, stock imagery dependency, Flow footage, or unnecessary 3D scene.

### 8.1 Stable color semantics

Use one series-wide semantic palette and store it in configs/layout.json:

- Favorable bulk driving force / bulk gain: cyan-blue.
- Opposing surface-energy cost / resistance: orange-red.
- Critical radius, barrier peak, decisive conclusion: bright yellow.
- Neutral axes/context: low-contrast white/gray.

Use these meanings consistently for equations, labels, bars, particles, curves, markers, and subtitle emphasis. Do not let the same color mean opposing concepts in different stages.

### 8.2 Required physical-motion scenes

A. Hook — tiny versus stable seed
- Show a few particles assembling into a tiny embryo.
- The tiny embryo contracts/disappears; a slightly larger embryo persists or grows.
- Keep the scene schematic and explicitly within the classical nucleus model. Do not imply a specific atomistic pathway.
- No static title card.

B. Conflict — two competing contributions
- Show an expanding nucleus cross-section or equivalent geometry.
- Animate surface-related cost and bulk-related gain simultaneously.
- Show two synchronized, clearly distinguished visual quantities rather than just two static text labels.
- The orange-red surface contribution follows r² scaling; the cyan-blue magnitude of bulk gain follows r³ scaling.
- Show the competition so that the viewer can see which term dominates at small radius and how the bulk term overtakes it as radius increases.
- Label the signs and meaning clearly; do not accidentally plot the bulk term as a positive free-energy cost.

C. Mechanism — dynamic free-energy curve
- Draw the total free-energy curve progressively from the same physical expression:
  ΔG(r) = 4πr²γ − (4/3)πr³Δg_v.
- Prefer a dimensionless x = r/r* view when useful. For x = r/r*, the normalized curve ΔG/ΔG* = 3x² − 2x³ is consistent with the current formula and has its maximum at x = 1. Verify all axes/labels and scaling before use.
- Animate the marker for the instantaneous trial nucleus size along the curve. Show the maximum, then make the critical radius / peak unmistakable.
- Existing formulas and axes must be reused or removed deliberately; no stacked duplicate formula, graph, or stale label.
- When several elements exist, dim unrelated items to 20–30% opacity and keep the currently explained object/term highlighted.
- Keep scientific labels minimal: keywords, symbols, and necessary units only.

D. Threshold — subcritical return and supercritical descent
- Put one small bright-yellow marker on the free-energy curve.
- First show a subcritical attempt: the marker moves toward the uphill side but returns toward smaller radius, illustrating the thermodynamic tendency for a subcritical nucleus to shrink.
- Then show a fluctuation/crossing beyond r*. After crossing the maximum, the marker travels down the free-energy curve as increasing radius lowers the model free energy.
- The marker is a schematic state marker on ΔG(r), not a literal ball that physically rolls over a mechanical hill. Narration/caption must make clear this is a thermodynamic landscape, not a real-time kinetic trajectory.
- Keep the r* marker, curve, and dot geometrically consistent and screen-safe.

E. Real-world relevance and close
- Show the crystal/nucleus growing beyond the threshold and resolving into an orderly larger crystal motif.
- Translate the theory into the practical principle of controlling the first stable nucleus in crystal formation/materials synthesis.
- Do not name a specific industry/application or promise a specific product outcome without evidence already present in the Fact Card.
- Place the caveat about thermodynamic tendency before the final line.
- End with the memorable takeaway and a clean visual resolve, not a limitations slide.

### 8.3 Motion, camera, and attention cues

- Use ValueTracker/always_redraw/Transform/MoveAlongPath/Create or equivalent tested Manim animations to make values and objects genuinely move. Do not replace one static image with another and call it animation.
- Keep the portrait camera stable for Slice A; achieve gentle “zoom-in” emphasis through a small, bounded object/group scale pulse or similarly safe animation. Avoid introducing an unneeded moving-camera framework.
- At key turning points, use a short zoom/pulse, curve highlight, marker pulse, or elastic scale. Do not apply a distracting effect to every spoken word.
- Keep the active composition centered in the usable content region and occupy approximately 55–65% of the main scientific visual area where the content permits. Avoid a tiny graph surrounded by empty space.
- Recalculate safe-zone bounds for the largest scale/pulse state; validate transformed object boundaries, not only their initial coordinates.
- Each visual stage must own its objects explicitly. Old objects must be removed or intentionally retained/shared. No stale formula or duplicate graph can persist by accident.
- Implement actual focus/dimming when several objects remain: inactive context at opacity 0.20–0.30; current focus at full opacity.
- Outside deliberate 0.5–0.8 s comprehension pauses, avoid static holds longer than about 2 s. Keep gentle purposeful motion; do not make the scene chaotic.
- At least one clear physical-motion event must occur in every rhythm block. The 10–15 s micro-climaxes must correspond to actual animation changes.

## 9. SFX and synchronized global timeline

- Create a small set of original, subtle, local sound cues (e.g. soft pop, short whoosh, light confirmation tone). Prefer programmatically synthesized or otherwise locally generated sounds. Do not download copyrighted sound packs.
- Use only a few purposeful cues at major events: seed transition, competing-term crossover, critical-radius/peak reveal, and final resolution. Do not add an SFX to every object or subtitle.
- Keep effects below narration and never obscure speech. Record per-event peak/RMS and verify clipping/headroom after mix.
- Extend the global timeline with explicit SFX event records using exact sample/frame positions. Do not shift speech, subtitle, or Manim cue times to fit sound effects.
- The voice chunks remain the authoritative speech timing source. Cleaned converted WAV sample counts are measured before building the timeline.
- Support per-unit pause_after_ms. Keep ordinary gaps short; set approximately 500–800 ms after the key equation/critical-radius conclusion and optionally another key result. These pauses are explicit silence segments in audio_timing.json.
- Add the final mix as a separate deterministic assembly stage: narration + deliberate silence + sparse SFX, then full-track loudness normalization. Preserve the 44.1 kHz mono output requirement unless the existing project has a validated reason to change it.
- Keep exact global sample-count/frame quantization, explicit 0–1000 ms cover, first speech at/after 1000 ms, CFR 30 fps, and exact final frame count. Never conceal a mismatch with frame duplication or time stretching.
- The QA report must record SFX events, pause segments, peak levels, final integrated loudness, and true peak. Preserve the existing -16 LUFS / -1.5 dBTP targets unless an evidence-based compatibility issue is found.

## 10. Implementation details and code consistency

Implement focused changes in the existing modules; do not rewrite the architecture:

1. voice_worker.py: local audio inspection, candidate reference cleanup, optional candidate embedding extraction, A/B generation, and consistent manifest. Preserve the original recording and active profile.
2. tts.py: explicit engine selection; personal MeloTTS/OpenVoice profile is the default and required production route. Missing/invalid profile must fail closed. A generic legacy engine can only be invoked by an explicit diagnostic option.
3. pipeline.py: truthful engine manifest, bilingual script artifact, editorial-beat manifest, SFX event data, final review status, and correct audio assembly.
4. timeline.py: configurable per-unit pause_after_ms, explicit pause segments, and SFX events aligned on the same global sample origin.
5. media.py: mix narration and SFX in a deterministic manner and preserve existing loudness/frame constraints. Keep relative ASS path handling.
6. subtitles.py: English + Simplified Chinese lines in one cue; correct CJK font style; safe wrapping; identical global cue times.
7. preflight.py: independently validate Latin and CJK fonts/glyph coverage; check the personal voice runtime/model/profile when that mode is active; inspect actual FFmpeg filter availability.
8. configs/layout.json: update subtitle-safe rectangle, bilingual font and typography settings, bottom/right platform reserves, and semantic color tokens.
9. content/sample_script.en.json: rebuild the short-form English script and add the Chinese subtitle field and rhythm metadata while retaining supported claim IDs.
10. visual_stages.py and scenes/critical_nucleus.py: add rhythm-block / motion event definitions, live physical animations, focus/dimming, marker movement, zoom pulses, and manifest data. Preserve one-active-stage ownership.
11. qa.py: add bilingual subtitle, glyph, phrase-length, motion-event, safe-zone, voice-cleanup, SFX/headroom, and manifest-consistency checks without weakening current media QA.
12. README.md, STATUS.md, and a new run progress summary: document the actual default pipeline, new sample artifacts, remaining human review, and fact-card publication block.

Correct known inconsistencies:
- Do not hard-code audio_manifest["engine"] as sherpa-onnx when the manifest says OpenVoice.
- Do not report Piper as the daily default when the code is expected to use the user's OpenVoice personal profile.
- Do not silently fall back to Piper/sherpa if the personal profile is missing.
- Do not let QA call a run PASS if the voice engine/profile path differs from the configured personal-voice production mode.
- Do not mark a CJK font check PASS merely because some Latin font file exists.
- Do not claim dynamic animation based only on stage transitions; prove continuous object/curve motion in rendered frames.

## 11. Required review package

The new local outputs/<run_id>_critical_nucleus/ directory must contain at least:

- final.mp4
- fact_card.json and source_record.json
- script.json and a readable bilingual script Markdown file
- storyboard.json with the five rhythm blocks and editorial beats
- audio/ phrase WAV chunks and pronunciation_review.wav
- audio_manifest.json with actual engine/profile/cleanup detail
- audio_timing.json with speech, silence, SFX, sample, and frame boundaries
- narration.wav and final_mix.wav (or clearly documented equivalent)
- captions.srt and captions.ass containing both languages
- visual_stage_manifest.json
- motion_event_manifest.json
- subtitle_layout_report.json with font and safe-zone measurements
- voice_quality_report.json with non-sensitive acoustic metrics and A/B file references local to the machine
- environment_report.json
- scene_render_manifest.json
- assembly_report.json
- qa_report.json
- review_status.json
- REVIEW.md
- run.log

Do not copy private voice-profile artifacts or original/candidate raw recordings into the review package. Do not include local absolute paths in the public report.

## 12. Focused verification and completion gates

Do not enter an endless test/render loop. Perform targeted tests once after each relevant change, then one complete review-sample render. Re-render only when a concrete failed gate requires a correction.

### Automated tests

1. Script schema validates all fields and every claim ID exists in the current Fact Card.
2. English narration contains no CJK; Chinese subtitle translations exist for every cue.
3. Chinese translations preserve negation, key qualifiers, symbols, sign convention, and thermodynamic-versus-kinetic meaning.
4. Speech-unit IDs are unique; one WAV and one bilingual subtitle cue exist for each unit.
5. Cue start/end times are identical for English and Chinese subtitle lines.
6. Chinese and English wrapping obey the layout limits and do not exceed the two-line bilingual block.
7. Latin and CJK font discovery verifies actual glyph support.
8. Personal voice engine is MeloTTS EN-US → OpenVoice V2; invalid/missing profile fails rather than falling back.
9. All candidate voice paths remain inside ignored private/ directories; no candidate can overwrite the active embedding without an explicit operator choice.
10. Audio cleanup preserves sample rate, channel count, and sample count unless a measured resample is explicitly recorded before timeline construction.
11. Configured 0.5–0.8 s pauses are present as explicit silence segments after the designated units.
12. SFX events are finite, within the global timeline, aligned with their visual event, and do not clip the final mix.
13. Manim stage ownership remains exclusive; old formulas disappear; shared graph reuse is intentional and tested.
14. Physical animation events exist in each rhythm block and are recorded in motion_event_manifest.json.
15. Focus opacity values for inactive content are 0.20–0.30.
16. Subtitle block and all maximum animation bounds remain inside the screen-safe rectangle.
17. Canvas labels obey the short-keyword rule; no explanatory paragraph appears in the science canvas.
18. The final engine/profile manifests agree with the actual files and runtime.
19. Existing media QA remains intact: 1080×1920, 30 fps CFR, yuv420p, SAR 1:1, audio/video duration match, exact global frame count, -16 LUFS target and -1.5 dBTP ceiling.
20. The rendered duration remains 55–65 seconds without speed changes, frame duplication, or filler silence.

### Real local evidence

- Run pytest -q in the existing project environment.
- Run focused voice preflight and one same-text A/B test using the current and best candidate path.
- Confirm no private recording, embedding, or candidate audio leaves the PC.
- Run the standard project preflight after updating its personal-voice and bilingual-font checks.
- Render exactly one complete review-sample MP4 through the Python CLI with --review-sample. Do not run Run_Slice_A.bat or any production BAT.
- Run ffprobe and QA on the actual final.mp4, not on synthetic fixtures only.
- Extract a small set of real frames at hook, each micro-climax, subtitle positions, equations, and ending; inspect them for motion, center, legibility, safe zones, correct color semantics, and no stale elements.
- Check frame-to-frame visual differences across every rhythm block to confirm that motion is real and not just a static slide with fades.
- Generate a phone-sized preview or contact sheet for user review. Keep all preview assets local and ignored.
- Report any failed gate honestly. No test pass or user acceptance may be fabricated.

### Completion and user hand-off

The work is complete only when:
- A new full MP4 exists locally and its SHA-256/metadata are reported.
- The final MP4 has both synchronized subtitle languages.
- The personal-voice path is still used and the best verified cleanup candidate is applied without overwriting the original profile.
- The animation contains the physical-motion events and timing beats described above.
- QA passes all machine-checkable requirements, with any human-only judgement clearly marked PENDING.
- The candidate Fact Card remains pending and the sample remains not-for-publication.
- The branch has been safely committed and pushed, with no private media or model assets uploaded.

The user personally watches/listens to the sample and later runs the BAT for final local acceptance. Do not claim that step is complete.

## 13. GitHub synchronization and final report

After implementation and local review-sample testing:

- Commit only source code, tests, configuration examples, and sanitized documentation.
- Recheck .gitignore and staged files before commit.
- Never upload my_voice, private/voice_profile, WAV, MP4, image/frame, model, cache, .venv, tools, or local-only config files.
- Push only to feat/slice-a-english-visual-refinement. No force push, no merge, no main update.
- Update README.md and STATUS.md. Add a new sanitized progress snapshot documenting exact implementation state, real tests, local MP4 metadata/SHA-256 (metadata only), known limitations, and pending user review.
- Leave Draft PR #2 open and in draft state.

Final report must include:
1. Base and final commit SHAs plus GitHub commit link.
2. Changed files and concise implementation summary.
3. pytest result and focused voice/preflight results.
4. Actual review-sample path, duration, dimensions, FPS, codecs, exact frame count, QA status, and MP4 SHA-256.
5. Local A/B sample paths and what each variant changes (no private files uploaded).
6. Confirmation of bilingual subtitle font/position checks and motion-event checks.
7. Security check confirming no recording, embedding, audio/video output, model, cache, or machine-specific config was committed.
8. Explicit outstanding human checks: voice identity/cleanliness, subtitle phone readability, scientific Fact Card approval, and user playback acceptance.

Stop after this Slice A refinement. Do not proceed to Slice B or any upload/publication feature.
